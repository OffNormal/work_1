#!/usr/bin/env python3
"""
AI 小说转剧本 - 增强版流水线
修复场景重复、角色缺失、情绪混用、空字段等问题
用法: python pipeline.py <小说文件路径> [--output 输出YAML路径] [--model 模型名称]
"""

import argparse
import os
import re
import json
import sys
from typing import List, Optional
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

load_dotenv()

# ============================================================
# 数据模型 (增强校验与序列化)
# ============================================================
class Character(BaseModel):
    id: str = Field(description="角色 ID，如 CHAR_LIN")
    name: str
    aliases: List[str] = []
    type: str = "supporting"          # protagonist / antagonist / supporting
    description: str = ""
    traits: List[str] = []
    voice_tone: str = ""

class Location(BaseModel):
    id: str = Field(description="地点 ID，如 LOC_CAFE")
    name: str
    type: str = "INT"                 # INT / EXT
    description: str = ""

class AssetBox(BaseModel):
    characters: List[Character] = []
    locations: List[Location] = []
    props: List[str] = []

class Beat(BaseModel):
    type: str = Field(description="action 或 dialogue")
    character_ref: Optional[str] = None
    emotion: Optional[str] = None
    description: Optional[str] = None   # action
    line: Optional[str] = None          # dialogue
    parenthetical: Optional[str] = None
    subtext: Optional[str] = None
    to: Optional[str] = None

    def dict(self, *args, **kwargs):
        # 排除空值，避免输出 null 或空字符串
        kwargs["exclude_none"] = True
        result = super().dict(*args, **kwargs)
        # 进一步排除空字符串
        return {k: v for k, v in result.items() if v != "" and v is not None}

class Scene(BaseModel):
    scene_id: str = Field(description="场次编号，如 S01")
    slug: str = Field(description="场标，如 INT. 咖啡馆 - 黄昏")
    location_ref: Optional[str] = None
    time_of_day: str = "day"
    summary: str = ""
    intention: str = ""
    beats: List[Beat] = []
    source_text: Optional[str] = None  # 原文片段，供生成 beats 使用

class Script(BaseModel):
    title: str = "未命名剧本"
    author: str = "AI 辅助改编"
    assets: AssetBox = AssetBox()
    scenes: List[Scene] = []

# ============================================================
# LLM 交互（兼容 DeepSeek，带 fallback）
# ============================================================
def structured_completion(system_prompt: str, user_prompt: str, model: str = "deepseek-chat") -> dict:
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    )

    json_notice = "\n请输出一个严格的 JSON 对象，不要包含任何额外解释或 markdown 标记。"
    system_prompt_json = system_prompt + json_notice
    user_prompt_json = user_prompt + "\n注意：只输出 JSON 对象，且确保字符串正确转义。"

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt_json},
                    {"role": "user", "content": user_prompt_json}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                top_p=0.95,
                reasoning_effort="high",
                stream=False
            )
            raw = response.choices[0].message.content
            if not raw or raw.strip() == "":
                print(f"  ⚠️ 第 {attempt+1} 次尝试返回空内容，重试...")
                continue

            json_str = raw.strip()
            if json_str.startswith("```"):
                json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
                json_str = re.sub(r"\s*```$", "", json_str)

            return json.loads(json_str)

        except (json.JSONDecodeError, ValueError) as e:
            print(f"  ⚠️ 第 {attempt+1} 次 JSON 解析失败: {e}")
            if 'raw' in locals():
                print(f"  📄 原始返回 (前500字符):\n{raw[:500]}")
            if attempt == 2:
                print("  🔄 JSON Output 模式失败，降级为普通模式（手动清洗）...")
                return _fallback_completion(system_prompt, user_prompt, model, client)
            print("  🔄 正在重试...")
    raise RuntimeError("结构化调用完全失败")

def _fallback_completion(system_prompt: str, user_prompt: str, model: str, client) -> dict:
    strict_system = (
        system_prompt +
        "\n\n【重要】你必须只输出一个合法的 JSON 对象，不要包含任何 markdown 标记，确保所有字符串正确转义。"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": strict_system},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,
        top_p=0.95,
        reasoning_effort="high",
        stream=False
    )
    raw = response.choices[0].message.content
    json_str = raw.strip()
    if json_str.startswith("```"):
        json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
        json_str = re.sub(r"\s*```$", "", json_str)
    return json.loads(json_str)

# ============================================================
# 核心流水线函数
# ============================================================
def run_agent(agent_file: str, user_prompt: str, model: str = "deepseek-chat", 
            skills: list = None, assets: AssetBox = None, scene: Scene = None) -> dict:
    """
    通用 Agent 执行器：加载 Agent 定义 → 调用 LLM → 返回结果。
    **不再承担审核职责**，审核由上层调用专门的 apply_*_review 完成。
    """
    agent_content = load_markdown(f"agents/{agent_file}.md")
    system = agent_content

    # 如果指定了 skills，将它们作为【写作规范】注入，但不作为审核
    # （与审核 Skill 分开，这里的 skill 是指导生成的，不是审核的）
    if skills:
        skill_texts = []
        for sk in skills:
            sk_content = load_markdown(f"skills/{sk}.md")
            if sk_content:
                skill_texts.append(sk_content)
        if skill_texts:
            system += "\n\n【写作规范】\n" + "\n".join(skill_texts)

    system += "\n\n请输出一个严格的 JSON 对象，不要包含 markdown 标记或额外解释。"
    return structured_completion(system, user_prompt, model)

def apply_asset_review(asset_data: dict, skill_content: str, model: str) -> dict:
    """资产审核"""
    review_prompt = f"""请根据以下审核规则审核提取的资产，并给出审核结果。

## 审核规则
{skill_content}

## 资产数据
{json.dumps(asset_data, ensure_ascii=False, indent=2)}

返回 JSON: {{ "pass": true/false, "issues": ["问题"] }}
"""
    try:
        res = structured_completion("你是严格的资产审核员。只输出 JSON。", review_prompt, model)
        return {"pass": res.get("pass", False), "issues": res.get("issues", [])}
    except:
        return {"pass": False, "issues": ["资产审核执行失败"]}

def apply_scene_review(scenes_data: dict, skill_content: str, model: str) -> dict:
    """场景切分审核"""
    review_prompt = f"""请根据以下审核规则审核场景切分，并给出审核结果。

## 审核规则
{skill_content}

## 场景数据
{json.dumps(scenes_data, ensure_ascii=False, indent=2)}

返回 JSON: {{ "pass": true/false, "issues": ["问题"] }}
"""
    try:
        res = structured_completion("你是严格的场景审核员。只输出 JSON。", review_prompt, model)
        return {"pass": res.get("pass", False), "issues": res.get("issues", [])}
    except:
        return {"pass": False, "issues": ["场景审核执行失败"]}


def extract_assets(novel_text: str, model: str = "deepseek-chat") -> AssetBox:
    user_prompt = f"小说内容：\n{novel_text}\n\n请提取资产。"
    review_skill = load_markdown("skills/asset-review.md")

    max_retries = 2
    for retry in range(max_retries + 1):
        result = run_agent("asset-extractor", user_prompt, model)
        # 独立审核
        review = apply_asset_review(result, review_skill, model)
        if review["pass"]:
            break
        elif retry < max_retries:
            print(f"  🔄 资产审核未通过，重试 {retry+1}/{max_retries}")
            user_prompt += f"\n\n【上一版问题】\n" + "\n".join(review["issues"])
        else:
            print(f"  ⚠️ 资产审核未通过，保留当前版本")

    return AssetBox(
        characters=[Character(**c) for c in result.get("characters", [])],
        locations=[Location(**l) for l in result.get("locations", [])],
        props=result.get("props", [])
    )

def segment_scenes_with_text(novel_text: str, assets: AssetBox, model: str = "deepseek-chat") -> List[Scene]:
    """第二步：切分场景，带审核，补录地点和临时角色"""
    char_list = "\n".join([f"{c.id}: {c.name}（{c.type}）" for c in assets.characters])
    loc_list = "\n".join([f"{l.id}: {l.name} ({l.type})" for l in assets.locations])
    user_prompt = f"角色列表：\n{char_list}\n\n地点列表：\n{loc_list}\n\n小说内容：\n{novel_text}"
    review_skill = load_markdown("skills/scene-segmentation-review.md")

    max_retries = 2
    for retry in range(max_retries + 1):
        result = run_agent("scene-segmenter", user_prompt, model)
        review = apply_scene_review(result, review_skill, model)
        if review["pass"]:
            break
        elif retry < max_retries:
            print(f"  🔄 场景切分审核未通过，重试 {retry+1}/{max_retries}")
            user_prompt += f"\n\n【上一版问题】\n" + "\n".join(review["issues"])
        else:
            print(f"  ⚠️ 场景切分审核未通过，保留当前版本")

    scenes = [Scene(**s) for s in result.get("scenes", [])]

    # 动态补录地点和临时角色（与之前相同）
    existing_loc_ids = {l.id for l in assets.locations}
    for scene in scenes:
        if scene.location_ref and scene.location_ref not in existing_loc_ids:
            loc_name = scene.slug.split(" - ")[0].replace("INT. ", "").replace("EXT. ", "")
            assets.locations.append(Location(id=scene.location_ref, name=loc_name,
                                            type="INT" if "INT." in scene.slug else "EXT", description="自动补录"))
            existing_loc_ids.add(scene.location_ref)
    # 临时角色注册（与之前相同）
    temp_char_pattern = re.compile(r'临时角色[：:]\s*(TEMP\d+)[-]\s*([^，,\n]+)')
    for scene in scenes:
        for match in temp_char_pattern.finditer(scene.summary):
            temp_id = match.group(1)
            temp_name = match.group(2).strip()
            if not any(c.id == temp_id for c in assets.characters):
                assets.characters.append(Character(id=temp_id, name=temp_name, type="supporting", description="临时群演"))
    
    # 地点一致性硬校验：如果 source_text 中出现其他地点名称，强制报警
    for scene in scenes:
        if not scene.source_text or not scene.location_ref:
            continue
        current_loc = next((loc for loc in assets.locations if loc.id == scene.location_ref), None)
        if not current_loc:
            continue
        other_names = [loc.name for loc in assets.locations if loc.id != scene.location_ref]
        found_others = [name for name in other_names if name and name in scene.source_text]
        if found_others:
            print(f"  ⚠️ 场景 {scene.scene_id} ({current_loc.name}) 的 source_text 包含其他地点: {found_others}")
            # 简单拆分策略：将 source_text 中首次出现其他地点的位置作为切割点
            # （注：精确拆分需复杂 NLP，此处仅警告，由审核 Skill 兜底）

    return scenes



def load_markdown(filepath: str) -> str:
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def load_skills(skill_names: list) -> dict:
    skills = {}
    for name in skill_names:
        path = f"skills/{name}.md"
        if os.path.exists(path):
            skills[name] = load_markdown(path)
        else:
            print(f"  ⚠️ Skill {name} 文件未找到，跳过")
    return skills

def apply_review_skill(scene: Scene, assets: AssetBox, skill_content: str, model: str = "deepseek-chat") -> dict:
    """将审核规则（Skill Markdown）交给 LLM 执行，返回 {'pass': bool, 'issues': [str]}"""
    valid_ids = {c.id for c in assets.characters}
    beats_json = json.dumps(
        [beat.dict(exclude_none=True) for beat in scene.beats],
        ensure_ascii=False,
        indent=2
    )
    review_prompt = f"""请根据以下审核规则审核剧本节拍列表，并给出审核结果。

## 审核规则
{skill_content}

## 可用角色 ID
{', '.join(valid_ids) if valid_ids else '无'}

## 节拍数据
{beats_json}

请返回一个 JSON 对象：
{{ "pass": true/false, "issues": ["问题描述1", "问题描述2"] }}
如果所有节拍都符合规则，pass 为 true；否则为 false，并在 issues 中列出所有问题（每个问题需指出具体 beat 序号和违规项）。
如果遇到英文情绪，请直接按映射表自动修正，并在 issues 中注明已修正，同时 pass 仍为 true（除非有其他问题）。
"""
    try:
        result = structured_completion(
            system_prompt="你是一个严格的剧本审核员。请只输出 JSON。",
            user_prompt=review_prompt,
            model=model
        )
        return {"pass": result.get("pass", False), "issues": result.get("issues", [])}
    except Exception as e:
        print(f"  ❌ 审核 Skill 执行失败: {e}")
        return {"pass": False, "issues": [f"审核异常: {str(e)}"]}

def beat_generator_agent(scene: Scene, assets: AssetBox, model: str = "deepseek-chat") -> Scene:
    """使用 Agent + Skill 生成节拍，带审核与自动回改，支持临时角色"""
    if not scene.source_text:
        scene.beats = []
        return scene

    # 加载 Agent 定义、写作标准、审核 Skill
    agent_prompt = load_markdown("agents/beat-generator.md")
    beat_standard = load_markdown("references/01-beat-writing-standard.md")
    review_skill = load_markdown("skills/review-beats.md")

    # 构建角色列表（包含临时角色）
    char_list = "\n".join([f"{c.id}: {c.name}" for c in assets.characters])
    temp_char_pattern = re.compile(r'临时角色[：:]\s*(TEMP\d+)[-]\s*([^，,\n]+)')
    temp_chars = []
    for match in temp_char_pattern.finditer(scene.summary):
        temp_chars.append(f"{match.group(1)}: {match.group(2).strip()}")
    if temp_chars:
        char_list += "\n临时角色（本场景可用）：\n" + "\n".join(temp_chars)

    # 获取当前场景的地点名称
    scene_location = scene.slug  # 默认使用 slug 作为地点描述
    for loc in assets.locations:
        if loc.id == scene.location_ref:
            scene_location = f"{loc.name}（{loc.type}）"
            break

    # 准备系统提示词（注入标准）
    system = agent_prompt.format(
        scene_summary=scene.summary,
        scene_intention=scene.intention,
        scene_source_text=scene.source_text,
        character_list=char_list,
        beat_writing_standard=beat_standard,
        scene_location=scene_location  # 新增：当前场景地点
    )
    system += "\n\n所有输出必须使用中文。请输出仅包含 beats 数组的 JSON 对象。"

    # 初始用户提示
    user = f"场景概要：{scene.summary}\n场景意图：{scene.intention}\n角色列表：{char_list}\n场景原文：\n{scene.source_text}"

    max_retries = 2
    for retry in range(max_retries + 1):
        try:
            result = structured_completion(system, user, model)
            beats_data = result.get("beats", [])
            beats = []
            for b in beats_data:
                # 基本过滤
                if b.get("type") == "dialogue" and not b.get("line", "").strip():
                    continue
                if b.get("type") == "action" and not b.get("description", "").strip():
                    continue
                beats.append(Beat(**b))
            scene.beats = beats
        
            # 使用 Skill 审核
            review_result = apply_review_skill(scene, assets, review_skill, model)
            if review_result["pass"]:
                break
            else:
                if retry < max_retries:
                    print(f"  🔄 场景 {scene.scene_id} 审核未通过，根据 Skill 修正指引重试 {retry+1}/{max_retries}")
                    user += f"\n\n【上一版问题与修正指引】\n" + "\n".join(review_result["issues"])
                    user += "\n请严格按修正指引重写节拍，确保通过审核。"
                else:
                    print(f"  ⚠️ 场景 {scene.scene_id} 审核未通过，已达最大重试次数，保留当前版本")
                    for issue in review_result["issues"]:
                        print(f"     - {issue}")

        except Exception as e:
            print(f"  ❌ 场景 {scene.scene_id} 节拍生成失败: {e}")
            scene.beats = []
            break
    return scene


def novel_to_script(novel_file: str, model: str = "deepseek-chat") -> Script:
    with open(novel_file, 'r', encoding='utf-8') as f:
        text = f.read()

    print("📖 正在提取角色与场景资产...")
    assets = extract_assets(text, model)
    print(f"   发现 {len(assets.characters)} 个角色，{len(assets.locations)} 个地点")

    print("🎬 正在切分场景并提取原文片段...")
    scenes = segment_scenes_with_text(text, assets, model)
    print(f"   共切分 {len(scenes)} 个场景")

    print("📝 正在为每个场景生成节拍...")
    for i, scene in enumerate(scenes):
        print(f"   处理 {scene.scene_id}...")
        generate_beats_for_scene(scene, assets, model)
        print(f"   ✅ {scene.scene_id} - {len(scene.beats)} beats")

    script = Script(
        title=os.path.splitext(os.path.basename(novel_file))[0],
        author="AI 辅助改编",
        assets=assets,
        scenes=scenes
    )
    return script

def export_yaml(script: Script, output_file: str):
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 120
    # 将 script 转为字典，使用 exclude_none 等
    script_dict = json.loads(script.model_dump_json(exclude_none=True, by_alias=True))
    # 清理资产中的空字段
    with open(output_file, 'w', encoding='utf-8') as f:
        yaml.dump(script_dict, f)
    print(f"✨ 剧本已保存至 {output_file}")

def main():
    parser = argparse.ArgumentParser(description="AI 小说转剧本工具")
    parser.add_argument("input", help="小说文本文件路径")
    parser.add_argument("--output", "-o", default="script.yaml", help="输出 YAML 文件路径")
    parser.add_argument("--model", "-m", default="deepseek-v4-pro", help="模型名称")
    args = parser.parse_args()

    try:
        script = novel_to_script(args.input, model=args.model)
        export_yaml(script, args.output)
    except Exception as e:
        print(f"❌ 错误：{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()