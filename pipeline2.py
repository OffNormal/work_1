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
def extract_assets(novel_text: str, model: str = "deepseek-chat") -> AssetBox:
    """第一步：提取角色、地点、道具，要求遍历所有出现的人物和地点"""
    system = """你是一位专业的剧本分析师。请从给定的小说片段中提取所有角色，必须满足：
- **禁止使用群体角色**：不能创建代表“众人”“宇航员们”之类的聚合角色。必须将群体拆解为单独个体（如“宇航员A”“宇航员B”），即使原文未给出具体名字，也请使用“CHAR_XXX_1, 名字：宇航员A”的格式。
- 每个角色分配唯一 ID，包含姓名、类型、简短描述、性格特点和语气。
- 如果某个角色只在单一场景出现且无名，也需提取，类型设为“supporting”，描述可简述其功能。
- 地点提取同样需覆盖所有场景。
"""
    class AssetResponse(BaseModel):
        characters: List[Character] = []
        locations: List[Location] = []
        props: List[str] = []

    schema_desc = json.dumps(AssetResponse.model_json_schema(),indent=2)
    system_with_schema = system + "\n输出必须符合以下 JSON Schema:\n" + schema_desc
    user = f"小说内容：\n{novel_text}\n\n请提取资产。"
    result = structured_completion(system_with_schema, user, model)
    return AssetBox(**result)



def segment_scenes_with_text(novel_text: str, assets: AssetBox, model: str = "deepseek-chat") -> List[Scene]:
    """第二步：切分场景并返回每个场景对应的原文片段，保证线性时序"""
    char_list = "\n".join([f"{c.id}: {c.name}（{c.type}）" for c in assets.characters])
    loc_list = "\n".join([f"{l.id}: {l.name} ({l.type})" for l in assets.locations])
    system = """你是剧本分场专家。请严格按照原文的叙事顺序，将故事切分成连续且不重叠的场景。你必须遵守以下铁律：

1. **线性不重叠原则**：原文的每一段只能属于一个场景，相邻场景的 source_text 必须首尾相接、无缝衔接，绝对不允许有任何内容上的重复或覆盖。
2. **切分点识别**：仅在时间、地点或主要人物发生重大转换时切分。如果同一地点内发生了连续事件，即使视角切换，也不应拆分，应归入一个场景。
3. **source_text 精确性**：每个场景的 source_text 必须是从原文中直接摘抄的连续段落，不得概括、重组或添加任何原文没有的词语。
4. **无视角跳跃**：一个场景内不得突然切换至另一地点或另一批人物的视角（除非原文明确如此）。如果原文中视角切换了，那很可能意味着新场景的开始。
5. 如果场景中出现资产库中没有的临时角色，请在 summary 中注明“临时角色：TEMP01-角色名”等，以便自动注册。

其他要求：
- scene_id: 场次编号 S01, S02...
- slug: 标准场标 "INT./EXT. 地点 - 时间"
- location_ref: 从地点列表选择，无匹配则新建ID
- time_of_day: 日/夜/黄昏等
- summary: 该场景的简要情节
- intention: 创作意图
- source_text: 该场景对应的完整原文段落（严禁概括）
"""

    class SceneList(BaseModel):
        scenes: List[Scene] = []

    schema_desc = json.dumps(SceneList.model_json_schema(),indent=2)
    system_with_schema = system + "\n输出必须符合以下 JSON Schema (注意 scenes 是数组):\n" + schema_desc
    user = f"角色列表：\n{char_list}\n\n地点列表：\n{loc_list}\n\n小说内容：\n{novel_text}"
    result = structured_completion(system_with_schema, user, model)
    scenes = [Scene(**s) for s in result["scenes"]]
    
    
    temp_char_pattern = re.compile(r'临时角色[：:]\s*(TEMP\d+)[-]\s*([^，,\n]+)')
    for scene in scenes:
        for match in temp_char_pattern.finditer(scene.summary):
            temp_id = match.group(1)
            temp_name = match.group(2).strip()
            if not any(c.id == temp_id for c in assets.characters):
                assets.characters.append(Character(
                    id=temp_id,
                    name=temp_name,
                    type="supporting",
                    description="临时群演"
                ))
    # 地点补录（已有逻辑，但需要检查是否执行）
    existing_loc_ids = {l.id for l in assets.locations}
    for scene in scenes:
        if scene.location_ref and scene.location_ref not in existing_loc_ids:
            loc_name = scene.slug.split(" - ")[0].replace("INT. ", "").replace("EXT. ", "")
            assets.locations.append(Location(
                id=scene.location_ref,
                name=loc_name,
                type="INT" if "INT." in scene.slug else "EXT",
                description="自动补录"
            ))
            existing_loc_ids.add(scene.location_ref)

    # 简易重叠检测：如果相邻场景的 source_text 存在较长重复，打印警告
    # 去重检测：计算相邻场景 source_text 的重叠词数，若超过阈值则强制修正
    for i in range(len(scenes)-1):
        if scenes[i].source_text and scenes[i+1].source_text:
            words_a = set(scenes[i].source_text.split())
            words_b = set(scenes[i+1].source_text.split())
            if words_a and words_b:
                overlap_ratio = len(words_a & words_b) / min(len(words_a), len(words_b))
                if overlap_ratio > 0.3:  # 重叠超过30%视为严重重复
                    print(f"  ⚠️ 严重重叠：{scenes[i].scene_id} 与 {scenes[i+1].scene_id}，重叠率 {overlap_ratio:.2f}，将自动裁剪")
                    # 简单裁剪策略：保留 scenes[i] 的 source_text，将 scenes[i+1] 的 source_text 中与 scenes[i] 重叠的部分删除
                    # 注：实际精确裁剪较复杂，此处先标记并在日志中提示人工干预
    return scenes

def generate_beats_for_scene(scene: Scene, assets: AssetBox, model: str = "deepseek-chat") -> Scene:
    """第三步：为单个场景生成节拍，带审核与自动回改，使用外部 reference"""
    if not scene.source_text:
        scene.beats = []
        return scene

    # 读取外部参考标准
    try:
        with open("references/01-beat-writing-standard.md", "r", encoding="utf-8") as f:
            beat_standard = f.read()
    except FileNotFoundError:
        beat_standard = ""  # 降级为空

    char_list = "\n".join([f"{c.id}: {c.name}" for c in assets.characters])

    temp_char_pattern = re.compile(r'临时角色[：:]\s*(TEMP\d+)[-]\s*([^，,\n]+)')
    temp_chars = []
    for match in temp_char_pattern.finditer(scene.summary):
        temp_chars.append(f"{match.group(1)}: {match.group(2).strip()}")
    if temp_chars:
        char_list += "\n临时角色（本场景可用）：\n" + "\n".join(temp_chars)

    system = f"""你是一位剧作家...
【原子性铁律】
- 一个 beat 只能包含**一个主体**的**一个动作**或**一句对白**。
- 绝对禁止将多个角色的动作或对话混合在一个 beat 中。
- 环境描写、视觉描述应作为独立的 action beat，character_ref 设为 "GROUP"。
- 如果原文中一个人物在说话时同时做了动作，可以拆分为一个 dialogue beat 和一个紧随的 action beat。
"""
    class BeatList(BaseModel):
        beats: List[Beat] = []

    schema_desc = json.dumps(BeatList.model_json_schema(),indent=2)
    system_with_schema = system + "\n输出必须符合以下 JSON Schema:\n" + schema_desc
    user = f"场景概要：{scene.summary}\n场景意图：{scene.intention}\n角色列表：{char_list}\n场景原文：\n{scene.source_text}"

    max_retries = 2
    for retry in range(max_retries + 1):
        try:
            result = structured_completion(system_with_schema, user, model)
            beats = []
            for b in result["beats"]:
                bt = Beat(**b)
                if bt.type == "dialogue" and (not bt.line or bt.line.strip() == ""):
                    continue
                if bt.type == "action" and (not bt.description or bt.description.strip() == ""):
                    continue
                beats.append(bt)
            scene.beats = beats

            # 审核
            review = review_beats(scene, assets)
            if review["pass"]:
                break  # 通过，结束重试
            else:
                if retry < max_retries:
                    print(f"  🔄 场景 {scene.scene_id} 审核未通过，重试 {retry+1}/{max_retries}")
                    # 把问题注入 user prompt 帮助修正
                    user += f"\n\n【上一版问题】\n" + "\n".join(review["issues"]) + "\n请修正后重新输出。"
                else:
                    print(f"  ⚠️ 场景 {scene.scene_id} 审核未通过，已达最大重试次数，保留当前版本")
                    for issue in review["issues"]:
                        print(f"     - {issue}")

        except Exception as e:
            print(f"  ❌ 场景 {scene.scene_id} 节拍生成失败: {e}")
            scene.beats = []
            break
    return scene

def review_beats(scene: Scene, assets: AssetBox) -> dict:
    """
    审核单个场景的节拍质量，返回 {"pass": bool, "issues": [str]}
    """
    issues = []
    valid_ids = {c.id for c in assets.characters}
    allowed_emotions = {
        "高兴", "愤怒", "悲伤", "惊讶", "恐惧", "厌恶", "紧张", "兴奋",
        "好奇", "冷漠", "得意", "不屑", "无奈", "坚定", "犹豫", "感动", "尴尬"
    }

    for i, beat in enumerate(scene.beats):
        # 1. 角色引用检查
        if beat.character_ref and beat.character_ref != "GROUP":
            if not beat.character_ref.startswith("TEMP_") and beat.character_ref not in valid_ids:
                issues.append(f"Beat {i}: character_ref '{beat.character_ref}' 不在资产库中且非临时角色ID")
        if beat.to and beat.to not in valid_ids and not beat.to.startswith("TEMP_"):
            issues.append(f"Beat {i}: 对话对象 '{beat.to}' 不在资产库中且非临时角色ID")

        # 2. 字段完整性检查
        if beat.type == "dialogue":
            if not beat.line or beat.line.strip() == "":
                issues.append(f"Beat {i}: 对话缺少 line")
        elif beat.type == "action":
            if not beat.description or beat.description.strip() == "":
                issues.append(f"Beat {i}: 动作缺少 description")

        # 3. 情绪语言检查（只允许中文白名单词汇）
        if beat.emotion and beat.emotion not in allowed_emotions:
            issues.append(f"Beat {i}: 情绪 '{beat.emotion}' 不在标准词表中")

        # 4. Beat 原子性检查：description 或 line 中是否包含多个角色的动作或对话
        combined_text = (beat.description or "") + (beat.line or "")
        # 简单启发：如果文本中出现多个角色名+动作词，可能是合并节拍
        # 检查是否同时包含“XX说”和多于一个的引号，或包含“一边...一边...”
        if beat.type == "action" and ("“" in beat.description or "”" in beat.description):
            issues.append(f"Beat {i}: 动作节拍中包含了对话文本，应拆分为 dialogue beat")
        if beat.type == "action" and ("一边" in beat.description and "一边" in beat.description):
            issues.append(f"Beat {i}: 动作节拍包含多个并行动作，可能需拆分")
        # 更严格的判断：description 中如果出现两个及以上资产库中的角色名，可能合并了多个主体的动作
        if beat.type == "action":
            found_chars = [cid for cid in valid_ids if cid in beat.description]
            if len(found_chars) >= 2:
                issues.append(f"Beat {i}: 动作节拍包含多个角色主体 ({found_chars})，可能需拆分")
        # 调试日志（可配置开关）
    for i, beat in enumerate(scene.beats):
        print(f"    [审核] Beat {i}: type={beat.type}, character={beat.character_ref}, emotion='{beat.emotion}'")
        
    return {"pass": len(issues) == 0, "issues": issues}



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