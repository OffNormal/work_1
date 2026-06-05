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
    system = """你是一位专业的剧本分析师。请从给定的小说片段中提取所有角色、地点和重要道具，并以 JSON 格式返回。
要求：
- 每个角色分配一个唯一 ID (CHAR_XXX)，包含姓名、别名、类型(protagonist/antagonist/supporting)、简短描述、性格特点和说话语气。
- 每个地点分配一个唯一 ID (LOC_XXX)，包含名称、类型(INT/EXT)和描述，确保覆盖所有场景（包括卧室、街道等），ID命名要明确。
- 道具用字符串列表表示。
请严格遵循给出的 JSON Schema。"""
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

    system = """你是剧本分场专家。请仔细阅读小说，将故事按时间顺序切分成若干连续的场景。每个场景需包含：
- scene_id: 场次编号 S01, S02 ...
- slug: 标准场标，格式 "INT./EXT. 地点 - 时间"，时间用清晨/日/黄昏/夜等
- location_ref: 从提供的地点 ID 中选择；若都不匹配，请新建一个合理ID并确保稍后添加到资产中
- time_of_day: 日/夜/黄昏等
- summary: 该场景的简要情节
- intention: 创作意图，即这场戏在叙事上的功能
- source_text: 从原文中摘抄的该场景对应的全部原文片段（请尽量完整保留段落，不要概括）
要求：
- 场景必须严格按原文时间顺序，不允许跳跃或重复
- 所有场景的 source_text 加起来应基本覆盖原文，不要遗漏重要情节
"""
    class SceneList(BaseModel):
        scenes: List[Scene] = []

    schema_desc = json.dumps(SceneList.model_json_schema(),indent=2)
    system_with_schema = system + "\n输出必须符合以下 JSON Schema (注意 scenes 是数组):\n" + schema_desc
    user = f"角色列表：\n{char_list}\n\n地点列表：\n{loc_list}\n\n小说内容：\n{novel_text}"
    result = structured_completion(system_with_schema, user, model)
    scenes = [Scene(**s) for s in result["scenes"]]
    # 动态补全地点：检查 scene 中 location_ref 是否在资产中，若不在则添加一个基础地点
    existing_loc_ids = {l.id for l in assets.locations}
    for scene in scenes:
        if scene.location_ref and scene.location_ref not in existing_loc_ids:
            # 自动补一个地点
            new_loc = Location(
                id=scene.location_ref,
                name=scene.slug.split(" - ")[0].replace("INT. ", "").replace("EXT. ", ""),
                type="INT" if "INT." in scene.slug else "EXT",
                description="自动补录"
            )
            assets.locations.append(new_loc)
            existing_loc_ids.add(scene.location_ref)
    return scenes

def generate_beats_for_scene(scene: Scene, assets: AssetBox, model: str = "deepseek-chat") -> Scene:
    """第三步：为单个场景生成节拍，只传入该场景的 source_text"""
    if not scene.source_text:
        # 若没有原文片段，跳过
        scene.beats = []
        return scene

    char_list = "\n".join([f"{c.id}: {c.name}" for c in assets.characters])

    system = """你是一位剧作家。请将下面的场景原文转换为一系列表演节拍（beats）。
每个节拍可以是动作（action）或对白（dialogue）。
- action: 必须包含 description（动作描述）和 emotion（情绪），character_ref 必填（除非是环境/群体动作，可用 "GROUP" 或留空，但尽量指定具体人物）
- dialogue: 必须包含 character_ref（说话人）、line（台词），可选 parenthetical、emotion、subtext、to（说话对象角色ID）
情绪请全部使用中文，从以下标准词中选择最合适的：高兴、愤怒、悲伤、惊讶、恐惧、厌恶、紧张、兴奋、好奇、冷漠、得意、不屑、无奈、坚定、犹豫、感动、尴尬、其他。
必须遵守：
- character_ref 必须使用提供的角色 ID，不要编造
- 对话必须有 line 且不能为空
- 动作必须有 description 且不能为空
- 不要输出多余的字段，遵循 JSON Schema
"""
    class BeatList(BaseModel):
        beats: List[Beat] = []

    schema_desc = json.dumps(BeatList.model_json_schema(),indent=2)
    system_with_schema = system + "\n输出必须符合以下 JSON Schema:\n" + schema_desc
    user = f"场景概要：{scene.summary}\n场景意图：{scene.intention}\n角色列表：{char_list}\n场景原文：\n{scene.source_text}"

    try:
        result = structured_completion(system_with_schema, user, model)
        beats = []
        for b in result["beats"]:
            # 简单校验
            bt = Beat(**b)
            if bt.type == "dialogue" and (not bt.line or bt.line.strip() == ""):
                continue  # 跳过无效对白
            if bt.type == "action" and (not bt.description or bt.description.strip() == ""):
                continue
            # 统一情绪为中文（已在 prompt 要求，但做一次映射兜底）
            if bt.emotion and bt.emotion.strip() in ["curious","excited","amused","angry","sad","surprised","fearful","disgusted","nervous","excited","curious","indifferent","proud","disdainful","helpless","firm","hesitant","touched","embarrassed","other"]:
                # 简单映射
                mapping = {
                    "curious": "好奇", "excited": "兴奋", "amused": "有趣", "angry": "愤怒", "sad": "悲伤",
                    "surprised": "惊讶", "fearful": "恐惧", "disgusted": "厌恶", "nervous": "紧张",
                    "indifferent": "冷漠", "proud": "得意", "disdainful": "不屑", "helpless": "无奈",
                    "firm": "坚定", "hesitant": "犹豫", "touched": "感动", "embarrassed": "尴尬"
                }
                bt.emotion = mapping.get(bt.emotion.strip(), bt.emotion)
            beats.append(bt)
        scene.beats = beats
    except Exception as e:
        print(f"  ❌ 场景 {scene.scene_id} 节拍生成失败: {e}")
        scene.beats = []
    return scene

def review_beats(scene: Scene, assets: AssetBox) -> dict:
    """
    审核单个场景的节拍质量，返回 {"pass": bool, "issues": [str]}
    """
    issues = []
    valid_ids = {c.id for c in assets.characters}

    for i, beat in enumerate(scene.beats):
        # 1. 角色引用检查
        if beat.character_ref and beat.character_ref != "GROUP" and beat.character_ref not in valid_ids:
            issues.append(f"Beat {i}: character_ref '{beat.character_ref}' 不在资产库中")
        if beat.to and beat.to not in valid_ids:
            issues.append(f"Beat {i}: 对话对象 '{beat.to}' 不在资产库中")

        # 2. 字段完整性检查
        if beat.type == "dialogue":
            if not beat.line or beat.line.strip() == "":
                issues.append(f"Beat {i}: 对话缺少 line")
        elif beat.type == "action":
            if not beat.description or beat.description.strip() == "":
                issues.append(f"Beat {i}: 动作缺少 description")

        # 3. 情绪语言检查（只允许中文）
        if beat.emotion and beat.emotion.isascii():
            issues.append(f"Beat {i}: 情绪 '{beat.emotion}' 应为中文")

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