#!/usr/bin/env python3
"""
AI 小说转剧本 - 初版流水线
用法: python pipeline.py <小说文件路径> [--output 输出YAML路径]
"""

import argparse
import os
from typing import List, Optional
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field
from ruamel.yaml import YAML
import json
import re

# 加载 .env 文件
load_dotenv()

# ============================================================
# 数据模型 (IR) - 对应之前定义的 YAML Schema
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
    props: List[str] = []             # 道具名称列表（初版简化）

class Beat(BaseModel):
    type: str = Field(description="action 或 dialogue")
    character_ref: Optional[str] = None
    emotion: Optional[str] = None
    description: Optional[str] = None # 用于 action
    line: Optional[str] = None        # 用于 dialogue
    parenthetical: Optional[str] = None
    subtext: Optional[str] = None
    to: Optional[str] = None          # 对话对象角色 ID

class Scene(BaseModel):
    scene_id: str = Field(description="场次编号，如 S01")
    slug: str = Field(description="场标，如 INT. 咖啡馆 - 黄昏")
    location_ref: Optional[str] = None
    time_of_day: str = "day"
    summary: str = ""
    intention: str = ""
    beats: List[Beat] = []

class Script(BaseModel):
    title: str = "未命名剧本"
    author: str = "未知"
    assets: AssetBox = AssetBox()
    scenes: List[Scene] = []

# ============================================================
# LLM 交互工具
# ============================================================

def get_client() -> OpenAI:
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("请设置 OPENAI_API_KEY 环境变量或在 .env 文件中填写")
    return OpenAI(api_key=api_key, base_url=base_url)

# 通用结构化请求
def structured_completion(system_prompt: str, user_prompt: str, model: str = "deepseek-v4-pro") -> dict:
    client = get_client()

    json_notice = "\n请输出一个严格的 JSON 对象，不要包含任何额外解释或 markdown 标记。"
    system_prompt_json = system_prompt + json_notice
    user_prompt_json = user_prompt + "\n注意：只输出 JSON 对象。"
#---------------------------------------------------------------------
    # 第一次尝试：使用 response_format
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
            if raw is None or raw.strip() == "":
                print(f"  ⚠️ 第 {attempt+1} 次尝试返回空内容，重试中...")
                continue  # 空 content，重试

            # 清洗可能的 markdown 包裹（安全兜底）
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
                # 三次均失败，启用 fallback：不使用 response_format，手动解析
                print("  🔄 JSON Output 模式失败，降级为普通模式（手动清洗）...")
                return _fallback_completion(system_prompt, user_prompt, model, client)
            print("  🔄 正在重试...")

    # 理论上不会走到这里，但保险
    raise RuntimeError("结构化调用完全失败")

def _fallback_completion(system_prompt: str, user_prompt: str, model: str, client) -> dict:
    """
    不使用 response_format，通过 prompt 强制输出 JSON，并手动清洗
    """
    strict_system = (
        system_prompt +
        "\n\n【重要】你必须只输出一个合法的 JSON 对象，不要包含任何 markdown 标记（如 ```json），"
        "不要添加解释，确保所有字符串都已正确转义。"
    )
    try:
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
    except Exception as e:
        raise RuntimeError(f"Fallback 解析失败: {e}")

# ============================================================
# 三步转换流水线
# ============================================================

def extract_assets(novel_text: str) -> AssetBox:
    """第一步：提取角色、地点、道具"""
    system = """你是一位专业的剧本分析师。请从给定的小说片段中提取所有角色、地点和重要道具，并以 JSON 格式返回。
要求：
- 每个角色分配一个唯一 ID (CHAR_XXX)，包含姓名、别名、类型(protagonist/antagonist/supporting)、简短描述、性格特点和说话语气。
- 每个地点分配一个唯一 ID (LOC_XXX)，包含名称、类型(INT/EXT)和描述。
- 道具用字符串列表表示。
请严格遵循给出的 JSON Schema。"""

    user = f"小说内容：\n{novel_text}\n\n请提取资产。"
    
    # 使用 Pydantic 模型定义输出结构
    class AssetResponse(BaseModel):
        characters: List[Character] = []
        locations: List[Location] = []
        props: List[str] = []

    # 需要将 Pydantic 模型转为 JSON Schema 描述，嵌入提示词
    schema_desc = json.dumps(AssetResponse.model_json_schema(),indent=2)
    system_with_schema = system + "\n输出必须符合以下 JSON Schema:\n" + schema_desc

    result = structured_completion(system_with_schema, user)
    return AssetBox(**result)

def segment_scenes(novel_text: str, assets: AssetBox) -> List[Scene]:
    """第二步：切分场景，生成空壳 Scene（包含场标、概要、意图，不含 beats）"""
    # 将角色和地点列表转为简要参考
    char_list = "\n".join([f"{c.id}: {c.name}（{c.type}）" for c in assets.characters])
    loc_list = "\n".join([f"{l.id}: {l.name} ({l.type})" for l in assets.locations])

    system = """你是剧本分场专家。请根据小说内容，将故事切分成若干场景，并以 JSON 数组返回。
每个场景包含：
- scene_id: 场次编号，如 S01, S02
- slug: 标准剧本场标，格式 "INT./EXT. 地点 - 时间"，时间可用清晨/日/黄昏/夜等
- location_ref: 从给定的地点 ID 中选择，若都不匹配可新建一个临时 ID
- time_of_day: 日/夜/黄昏等
- summary: 该场景的简要情节
- intention: 创作意图，即这场戏在叙事上的功能
请尽可能精确，并确保使用提供的地点 ID 和角色 ID。
"""

    class SceneList(BaseModel):
        scenes: List[Scene] = []

    schema_desc = json.dumps(SceneList.model_json_schema(),indent=2)
    system_with_schema = system + "\n输出必须符合以下 JSON Schema (注意 scenes 是数组):\n" + schema_desc

    user = f"角色列表：\n{char_list}\n\n地点列表：\n{loc_list}\n\n小说内容：\n{novel_text}"
    
    result = structured_completion(system_with_schema, user)
    return [Scene(**s) for s in result["scenes"]]

def generate_beats(scene: Scene, scene_text: str, assets: AssetBox) -> Scene:
    """第三步：为每个场景生成细致的节拍（动作和对白）"""
    char_list = "\n".join([f"{c.id}: {c.name}" for c in assets.characters])

    system = """你是一位剧作家。请将给定的场景叙事转换为一系列表演节拍（beats）。
每个节拍可以是动作（action）或对白（dialogue）。
- action: 包含 description（动作描述）、emotion（情绪）、character_ref（执行角色）
- dialogue: 包含 character_ref（说话人）、line（台词）、parenthetical（括号提示，可选）、emotion（情绪）、subtext（潜台词，可选）、to（说话对象角色ID，可选）
请严格按照 JSON 数组格式返回 beats。
"""

    class BeatList(BaseModel):
        beats: List[Beat] = []

    schema_desc = json.dumps(BeatList.model_json_schema(),indent=2)
    system_with_schema = system + "\n输出必须符合以下 JSON Schema:\n" + schema_desc

    # 为了准确，提供当前场景的上下文
    user = f"场景概要：{scene.summary}\n场景意图：{scene.intention}\n角色列表：{char_list}\n场景内容：\n{scene_text}"
    
    result = structured_completion(system_with_schema, user)
    scene.beats = [Beat(**b) for b in result["beats"]]
    return scene

# ============================================================
# 主流水线
# ============================================================

def novel_to_script(novel_file: str) -> Script:
    with open(novel_file, 'r', encoding='utf-8') as f:
        text = f.read()

    print("📖 正在提取角色与场景资产...")
    assets = extract_assets(text)
    print(f"   发现 {len(assets.characters)} 个角色，{len(assets.locations)} 个地点")

    print("🎬 正在切分场景...")
    scenes = segment_scenes(text, assets)
    print(f"   共切分 {len(scenes)} 个场景")

    # 为简单起见，我们暂时让每个场景的文本是整个小说（后续可切分匹配）
    # 更好的做法是让 LLM 在 segment_scenes 时也输出每个场景对应的原文片段，
    # 这里作为初版我们使用全文，但告知 LLM 场景概要以便聚焦。
    print("📝 正在为每个场景生成节拍...")
    for i, scene in enumerate(scenes):
        # 可以在这里改进：通过 scene.summary 从原文中提取相关段落再送入，
        # 目前直接送入完整文本，但通过提示聚焦。
        scene = generate_beats(scene, text, assets)
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
    # 转换为字典以使用自定义格式
    script_dict = script.model_dump()
    with open(output_file, 'w', encoding='utf-8') as f:
        yaml.dump(script_dict, f)
    print(f"✨ 剧本已保存至 {output_file}")

# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="AI 小说转剧本工具")
    parser.add_argument("input", help="小说文本文件路径")
    parser.add_argument("--output", "-o", default="script.yaml", help="输出 YAML 文件路径")
    args = parser.parse_args()

    try:
        script = novel_to_script(args.input)
        export_yaml(script, args.output)
    except Exception as e:
        print(f"❌ 错误：{e}")
        exit(1)

if __name__ == "__main__":
    main()