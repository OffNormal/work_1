#!/usr/bin/env python3
"""
AI 小说转剧本 - 多章节增强版流水线

目标：
1. 支持单文件或 txt 目录输入，自动处理 3 个章节以上内容。
2. 以共享资产库 + 段落锚点场景切分，减少场景复述与空间漂移。
3. 通过本地归一化和 Agent/Skill 双重校验，提高 YAML 初稿可编辑性。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DEFAULT_MODEL = "deepseek-v4-pro"
EMOTION_WHITELIST = {
    "高兴", "愤怒", "悲伤", "惊讶", "恐惧", "厌恶", "紧张", "兴奋", "好奇", "冷漠",
    "得意", "不屑", "无奈", "坚定", "犹豫", "感动", "尴尬", "其他",
}
EMOTION_MAP = {
    "shock": "惊讶",
    "awe": "惊讶",
    "disbelief": "惊讶",
    "urgent": "紧张",
    "urgency": "紧张",
    "angry": "愤怒",
    "sad": "悲伤",
    "surprised": "惊讶",
    "fear": "恐惧",
    "disgusted": "厌恶",
    "nervous": "紧张",
    "excited": "兴奋",
    "curious": "好奇",
    "indifferent": "冷漠",
    "proud": "得意",
    "disdainful": "不屑",
    "helpless": "无奈",
    "firm": "坚定",
    "hesitant": "犹豫",
    "touched": "感动",
    "embarrassed": "尴尬",
    "confident": "坚定",
    "calm": "冷漠",
    "anxious": "紧张",
    "confused": "其他",
    "utter shock": "惊讶",
    "stunned disbelief": "惊讶",
    "chaotic excitement": "兴奋",
    "tense anticipation": "紧张",
    "overwhelmed": "其他",
    "平静": "冷漠",
    "淡然": "冷漠",
    "淡淡": "冷漠",
    "冷静": "冷漠",
    "轻松": "高兴",
    "愉快": "高兴",
    "热情": "高兴",
    "开心": "高兴",
    "怀旧": "其他",
    "认真": "坚定",
    "释然": "无奈",
    "询问": "其他",
    "回忆": "其他",
    "回想": "其他",
    "感慨": "无奈",
    "调和": "其他",
    "圆场": "其他",
    "催促": "紧张",
    "玩笑": "高兴",
    "妩媚": "高兴",
    "歉意": "尴尬",
    "略带歉意": "尴尬",
    "假装歉意": "尴尬",
    "假意抱歉": "尴尬",
    "轻视": "不屑",
    "随意": "冷漠",
    "微笑": "高兴",
    "积极": "坚定",
    "耐心": "坚定",
    "调侃": "高兴",
}
GROUP_KEYWORDS = (
    "众人", "大家", "众多", "宇航员们", "科学家们", "监测人员", "工作人员",
    "几名宇航员", "人员", "队员们", "乘客们", "学生们",
)
CROSS_SPACE_KEYWORDS = ("与此同时", "画面切换", "镜头切换", "镜头转向", "切到", "时间跳转")


@dataclass
class ChapterUnit:
    ref: str
    title: str
    text: str
    paragraphs: List[str]


class Character(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="角色 ID，如 CHAR_LIN")
    name: str
    aliases: List[str] = Field(default_factory=list)
    type: str = "supporting"
    description: str = ""
    traits: List[str] = Field(default_factory=list)
    voice_tone: str = ""


class Location(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="地点 ID，如 LOC_CAFE")
    name: str
    type: str = "INT"
    description: str = ""


class AssetBox(BaseModel):
    model_config = ConfigDict(extra="ignore")

    characters: List[Character] = Field(default_factory=list)
    locations: List[Location] = Field(default_factory=list)
    props: List[str] = Field(default_factory=list)


class Beat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = Field(description="action 或 dialogue")
    character_ref: Optional[str] = None
    emotion: Optional[str] = None
    description: Optional[str] = None
    line: Optional[str] = None
    parenthetical: Optional[str] = None
    subtext: Optional[str] = None
    to: Optional[str] = None


class Scene(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scene_id: str = Field(description="场次编号，如 S01")
    chapter_ref: str = Field(default="", description="来源章节，如 num_01")
    slug: str = Field(description="场标，如 INT. 咖啡馆 - 黄昏")
    location_ref: Optional[str] = None
    time_of_day: str = "日"
    summary: str = ""
    intention: str = ""
    source_paragraph_start: Optional[int] = None
    source_paragraph_end: Optional[int] = None
    source_text: Optional[str] = None
    beats: List[Beat] = Field(default_factory=list)


class Script(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = "1.0"
    title: str = "未命名剧本"
    author: str = "AI 辅助改编"
    assets: AssetBox = Field(default_factory=AssetBox)
    scenes: List[Scene] = Field(default_factory=list)


class ScenePlanItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scene_id: str = ""
    chapter_ref: str = ""
    slug: str
    location_ref: Optional[str] = None
    time_of_day: str = "日"
    summary: str
    intention: str
    source_paragraph_start: int
    source_paragraph_end: int


class ScenePlanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scenes: List[ScenePlanItem] = Field(default_factory=list)


class AssetResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    characters: List[Character] = Field(default_factory=list)
    locations: List[Location] = Field(default_factory=list)
    props: List[str] = Field(default_factory=list)


class BeatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    beats: List[Beat] = Field(default_factory=list)


def get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("请设置 OPENAI_API_KEY 环境变量或在 .env 文件中填写")
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
    )


def structured_completion(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL) -> dict:
    client = get_client()
    json_notice = "\n请输出一个严格的 JSON 对象，不要包含任何额外解释或 markdown 标记。"
    system_prompt_json = system_prompt + json_notice
    user_prompt_json = user_prompt + "\n注意：只输出 JSON 对象，且确保字符串正确转义。"

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt_json},
                    {"role": "user", "content": user_prompt_json},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                top_p=0.95,
                reasoning_effort="high",
                stream=False,
            )
            raw = response.choices[0].message.content
            if not raw or not raw.strip():
                print(f"  ⚠️ 第 {attempt + 1} 次尝试返回空内容，重试...")
                continue

            json_str = raw.strip()
            if json_str.startswith("```"):
                json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
                json_str = re.sub(r"\s*```$", "", json_str)
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"  ⚠️ 第 {attempt + 1} 次 JSON 解析失败: {exc}")
            if "raw" in locals():
                print(f"  📄 原始返回（前 500 字符）:\n{raw[:500]}")
            if attempt == 2:
                print("  🔄 JSON Output 模式失败，降级为普通模式（手动清洗）...")
                return _fallback_completion(system_prompt, user_prompt, model, client)
            print("  🔄 正在重试...")
    raise RuntimeError("结构化调用完全失败")


def _fallback_completion(system_prompt: str, user_prompt: str, model: str, client: OpenAI) -> dict:
    strict_system = (
        system_prompt
        + "\n\n【重要】你必须只输出一个合法的 JSON 对象，不要包含 markdown 标记，确保所有字符串正确转义。"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": strict_system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        top_p=0.95,
        reasoning_effort="high",
        stream=False,
    )
    raw = response.choices[0].message.content
    json_str = (raw or "").strip()
    if json_str.startswith("```"):
        json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
        json_str = re.sub(r"\s*```$", "", json_str)
    return json.loads(json_str)


def load_markdown(relative_path: str) -> str:
    full_path = os.path.join(BASE_DIR, relative_path)
    with open(full_path, "r", encoding="utf-8") as handle:
        return handle.read()


def run_agent(agent_file: str, user_prompt: str, model: str = DEFAULT_MODEL, extra_system: str = "") -> dict:
    system = load_markdown(os.path.join("agents", f"{agent_file}.md"))
    if extra_system:
        system += "\n\n" + extra_system
    system += "\n\n请输出一个严格的 JSON 对象，不要包含 markdown 标记或额外解释。"
    return structured_completion(system, user_prompt, model)


def natural_sort_key(value: str) -> List[object]:
    parts = re.split(r"(\d+)", value)
    key: List[object] = []
    for part in parts:
        key.append(int(part) if part.isdigit() else part.lower())
    return key


def split_paragraphs(text: str) -> List[str]:
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    return paragraphs


def load_chapters(input_path: str) -> List[ChapterUnit]:
    absolute = input_path if os.path.isabs(input_path) else os.path.join(BASE_DIR, input_path)
    if os.path.isfile(absolute):
        with open(absolute, "r", encoding="utf-8") as handle:
            text = handle.read()
        ref = os.path.splitext(os.path.basename(absolute))[0]
        return [ChapterUnit(ref=ref, title=ref, text=text, paragraphs=split_paragraphs(text))]

    if not os.path.isdir(absolute):
        raise FileNotFoundError(f"输入路径不存在：{input_path}")

    files = [
        os.path.join(absolute, name)
        for name in os.listdir(absolute)
        if name.lower().endswith(".txt")
    ]
    files.sort(key=lambda item: natural_sort_key(os.path.basename(item)))
    if not files:
        raise FileNotFoundError(f"目录中未找到 txt 文件：{input_path}")

    chapters: List[ChapterUnit] = []
    for path in files:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        ref = os.path.splitext(os.path.basename(path))[0]
        chapters.append(ChapterUnit(ref=ref, title=ref, text=text, paragraphs=split_paragraphs(text)))
    return chapters


def prune_empty(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            pruned = prune_empty(item)
            if pruned not in (None, "", [], {}):
                cleaned[key] = pruned
        return cleaned
    if isinstance(value, list):
        cleaned_list = [prune_empty(item) for item in value]
        return [item for item in cleaned_list if item not in (None, "", [], {})]
    return value


def normalize_text_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", (value or "").lower())


def normalize_list(values: Iterable[str], limit: int = 8) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        cleaned = (value or "").strip()
        if not cleaned:
            continue
        marker = normalize_text_key(cleaned)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def ensure_unique_id(candidate: Optional[str], prefix: str, existing_ids: set[str]) -> str:
    raw = re.sub(r"[^A-Za-z0-9_]+", "_", (candidate or "").upper()).strip("_")
    if raw and not raw.startswith(prefix + "_"):
        raw = f"{prefix}_{raw}"
    if not raw:
        index = len(existing_ids) + 1
        raw = f"{prefix}_{index:03d}"
    final_id = raw
    counter = 2
    while final_id in existing_ids:
        final_id = f"{raw}_{counter}"
        counter += 1
    existing_ids.add(final_id)
    return final_id


def is_group_character_name(name: str) -> bool:
    candidate = (name or "").strip()
    return any(keyword in candidate for keyword in GROUP_KEYWORDS)


def find_character_by_name(assets: AssetBox, name: str, aliases: Iterable[str] = ()) -> Optional[Character]:
    target_keys = {normalize_text_key(name), *(normalize_text_key(alias) for alias in aliases)}
    target_keys.discard("")
    for character in assets.characters:
        keys = {normalize_text_key(character.name), *(normalize_text_key(alias) for alias in character.aliases)}
        if target_keys & keys:
            return character
    return None


def find_location_by_name(assets: AssetBox, name: str) -> Optional[Location]:
    target_key = normalize_text_key(name)
    if not target_key:
        return None
    for location in assets.locations:
        keys = location_aliases(location)
        if target_key in keys:
            return location
    return None


def merge_text(old: str, new: str, fallback: str = "") -> str:
    old_clean = (old or "").strip()
    new_clean = (new or "").strip()
    if len(new_clean) > len(old_clean):
        return new_clean
    if old_clean:
        return old_clean
    return fallback


def location_aliases(location: Location) -> set[str]:
    aliases = {
        normalize_text_key(location.name),
        normalize_text_key(location.name.replace("前", "")),
        normalize_text_key(location.name.replace("内", "")),
        normalize_text_key(location.name.replace("外", "")),
        normalize_text_key(location.name.replace("里", "")),
        normalize_text_key(location.name.replace("中", "")),
    }
    aliases.discard("")
    return aliases


def merge_assets(base_assets: AssetBox, incoming_payload: dict, chapter_ref: str) -> AssetBox:
    merged = AssetBox(
        characters=[Character(**item.model_dump()) for item in base_assets.characters],
        locations=[Location(**item.model_dump()) for item in base_assets.locations],
        props=list(base_assets.props),
    )
    existing_character_ids = {item.id for item in merged.characters}
    existing_location_ids = {item.id for item in merged.locations}

    for raw in incoming_payload.get("characters", []):
        if not isinstance(raw, dict):
            continue
        name = (raw.get("name") or "").strip()
        if not name or is_group_character_name(name):
            continue
        aliases = normalize_list(raw.get("aliases", []))
        matched = find_character_by_name(merged, name, aliases)
        if matched:
            matched.aliases = normalize_list([*matched.aliases, *aliases])
            matched.description = merge_text(
                matched.description,
                raw.get("description", ""),
                fallback=f"{matched.name}，在 {chapter_ref} 相关段落中出现的重要角色。",
            )
            matched.traits = normalize_list([*matched.traits, *(raw.get("traits", []) or [])], limit=6)
            matched.voice_tone = merge_text(matched.voice_tone, raw.get("voice_tone", ""), fallback="待补充")
            if matched.type == "supporting" and raw.get("type") in {"protagonist", "antagonist"}:
                matched.type = raw["type"]
            continue

        candidate_id = ensure_unique_id(raw.get("id"), "CHAR", existing_character_ids)
        merged.characters.append(
            Character(
                id=candidate_id,
                name=name,
                aliases=aliases,
                type=raw.get("type") or "supporting",
                description=(raw.get("description") or "").strip() or f"{name}，在 {chapter_ref} 相关段落中出现的重要角色。",
                traits=normalize_list(raw.get("traits", []), limit=6),
                voice_tone=(raw.get("voice_tone") or "").strip() or "待补充",
            )
        )

    for raw in incoming_payload.get("locations", []):
        if not isinstance(raw, dict):
            continue
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        matched = find_location_by_name(merged, name)
        if matched:
            matched.description = merge_text(
                matched.description,
                raw.get("description", ""),
                fallback=f"{matched.name}，在 {chapter_ref} 章节中被提及的场景空间。",
            )
            if matched.type == "INT" and (raw.get("type") or "").upper() == "EXT":
                matched.type = "EXT"
            continue

        candidate_id = ensure_unique_id(raw.get("id"), "LOC", existing_location_ids)
        merged.locations.append(
            Location(
                id=candidate_id,
                name=name,
                type=(raw.get("type") or "INT").upper(),
                description=(raw.get("description") or "").strip() or f"{name}，在 {chapter_ref} 章节中被提及的场景空间。",
            )
        )

    merged.props = normalize_list([*merged.props, *(incoming_payload.get("props", []) or [])], limit=100)
    return merged


def ensure_scene_location(scene: Scene, assets: AssetBox) -> str:
    if scene.location_ref and any(location.id == scene.location_ref for location in assets.locations):
        return scene.location_ref

    slug_head = scene.slug.split(" - ")[0].replace("INT. ", "").replace("EXT. ", "").strip()
    matched = find_location_by_name(assets, slug_head)
    if matched:
        scene.location_ref = matched.id
        return matched.id

    existing_ids = {location.id for location in assets.locations}
    location_id = ensure_unique_id(None, "LOC", existing_ids)
    location_type = "EXT" if scene.slug.startswith("EXT.") else "INT"
    assets.locations.append(
        Location(
            id=location_id,
            name=slug_head or "未命名地点",
            type=location_type,
            description="由场景切分阶段自动补录。",
        )
    )
    scene.location_ref = location_id
    return location_id


def build_asset_review(asset_data: dict, skill_content: str, model: str) -> dict:
    review_prompt = f"""请根据以下审核规则审核提取的资产，并给出审核结果。

## 审核规则
{skill_content}

## 资产数据
{json.dumps(asset_data, ensure_ascii=False, indent=2)}

返回 JSON: {{ "pass": true/false, "issues": ["问题"] }}
"""
    try:
        result = structured_completion("你是严格的资产审核员。只输出 JSON。", review_prompt, model)
        return {"pass": result.get("pass", False), "issues": result.get("issues", [])}
    except Exception:
        return {"pass": False, "issues": ["资产审核执行失败"]}


def extract_assets_for_chapter(chapter: ChapterUnit, assets: AssetBox, model: str = DEFAULT_MODEL) -> AssetBox:
    schema_desc = json.dumps(AssetResponse.model_json_schema(), ensure_ascii=False, indent=2)
    review_skill = load_markdown(os.path.join("skills", "asset-review.md"))
    existing_assets_json = json.dumps(prune_empty(assets.model_dump()), ensure_ascii=False, indent=2)
    chapter_excerpt = "\n".join(chapter.paragraphs[:120])
    user_prompt = f"""章节编号：{chapter.ref}

已有资产库（优先复用已有 ID）：
{existing_assets_json}

章节原文：
{chapter_excerpt}
"""
    extra_system = (
        "补充要求：\n"
        "1. 群体角色不得进入资产库；群体动作和群体对白请留给 beats 阶段使用 GROUP 表达。\n"
        "2. 若人物已存在于已有资产库中，必须复用其 ID，不得新建同人异 ID。\n"
        "3. 每个角色都要尽量补全 description、traits、voice_tone。\n"
        f"4. 输出必须符合以下 JSON Schema：\n{schema_desc}"
    )

    best_assets = assets
    max_retries = 2
    for retry in range(max_retries + 1):
        result = run_agent("asset-extractor", user_prompt, model, extra_system=extra_system)
        merged = merge_assets(best_assets, result, chapter.ref)
        merged_dict = prune_empty(merged.model_dump())
        review = build_asset_review(merged_dict, review_skill, model)
        best_assets = merged
        if review["pass"]:
            return merged
        if retry < max_retries:
            user_prompt += "\n\n【上一版问题】\n" + "\n".join(review["issues"])
            user_prompt += "\n请只做去重、补全和复用，不要重新发明已有资产。"
            print(f"  🔄 资产审核未通过，重试 {retry + 1}/{max_retries}")
        else:
            print("  ⚠️ 资产审核仍未完全通过，保留当前已归一化结果。")
    return best_assets


def format_numbered_paragraphs(chapter: ChapterUnit) -> str:
    return "\n".join(f"[P{index}] {paragraph}" for index, paragraph in enumerate(chapter.paragraphs, start=1))


def build_scene_source_text(chapter: ChapterUnit, start: int, end: int) -> str:
    return "\n".join(chapter.paragraphs[start - 1:end])


def find_location_conflicts(scene: Scene, assets: AssetBox) -> List[str]:
    if not scene.source_text or not scene.location_ref:
        return []
    issues: List[str] = []
    source_key = normalize_text_key(scene.source_text)
    for location in assets.locations:
        if location.id == scene.location_ref:
            continue
        for alias in location_aliases(location):
            if alias and alias in source_key:
                issues.append(f"{scene.scene_id or '未编号场景'} 的 source_text 包含其他地点 `{location.name}`。")
                break
    return issues


def local_scene_issues(scenes: List[Scene], chapter: ChapterUnit, assets: AssetBox) -> List[str]:
    issues: List[str] = []
    previous_end = 0
    seen_summaries = set()
    for index, scene in enumerate(scenes, start=1):
        start = scene.source_paragraph_start or 0
        end = scene.source_paragraph_end or 0
        if start < 1 or end < 1 or end < start or end > len(chapter.paragraphs):
            issues.append(f"场景 {scene.scene_id or index} 的段落范围无效：{start}-{end}。")
            continue
        if start <= previous_end:
            issues.append(f"场景 {scene.scene_id or index} 与前序场景段落重叠：{start}-{end}。")
        if start > previous_end + 1:
            issues.append(f"场景 {scene.scene_id or index} 之前存在未覆盖段落：P{previous_end + 1}-P{start - 1}。")
        previous_end = end

        summary_key = normalize_text_key(scene.summary)
        if summary_key and summary_key in seen_summaries:
            issues.append(f"场景 {scene.scene_id or index} 的 summary 与其他场景重复。")
        seen_summaries.add(summary_key)
        issues.extend(find_location_conflicts(scene, assets))

    if previous_end < len(chapter.paragraphs):
        issues.append(f"章节结尾段落未覆盖：P{previous_end + 1}-P{len(chapter.paragraphs)}。")
    return issues


def build_scene_review(scenes_data: dict, skill_content: str, model: str) -> dict:
    review_prompt = f"""请根据以下审核规则审核场景切分，并给出审核结果。

## 审核规则
{skill_content}

## 场景数据
{json.dumps(scenes_data, ensure_ascii=False, indent=2)}

返回 JSON: {{ "pass": true/false, "issues": ["问题"] }}
"""
    try:
        result = structured_completion("你是严格的场景审核员。只输出 JSON。", review_prompt, model)
        return {"pass": result.get("pass", False), "issues": result.get("issues", [])}
    except Exception:
        return {"pass": False, "issues": ["场景审核执行失败"]}


def coerce_scene_plan_items(raw_scenes: list, chapter: ChapterUnit, assets: AssetBox) -> List[Scene]:
    scenes: List[Scene] = []
    for index, raw in enumerate(raw_scenes, start=1):
        if not isinstance(raw, dict):
            continue
        start = int(raw.get("source_paragraph_start", 0) or 0)
        end = int(raw.get("source_paragraph_end", 0) or 0)
        if start < 1 or end < start or end > len(chapter.paragraphs):
            continue
        scene = Scene(
            scene_id=raw.get("scene_id") or f"S{index:02d}",
            chapter_ref=raw.get("chapter_ref") or chapter.ref,
            slug=(raw.get("slug") or "").strip(),
            location_ref=raw.get("location_ref"),
            time_of_day=(raw.get("time_of_day") or "日").strip(),
            summary=(raw.get("summary") or "").strip(),
            intention=(raw.get("intention") or "").strip(),
            source_paragraph_start=start,
            source_paragraph_end=end,
            source_text=build_scene_source_text(chapter, start, end),
        )
        ensure_scene_location(scene, assets)
        scenes.append(scene)
    return scenes


def fill_scene_gaps(scenes: List[Scene], chapter: ChapterUnit, assets: AssetBox) -> List[Scene]:
    if not chapter.paragraphs:
        return scenes
    repaired: List[Scene] = []
    previous_end = 0
    for scene in sorted(scenes, key=lambda item: (item.source_paragraph_start or 0, item.source_paragraph_end or 0)):
        start = scene.source_paragraph_start or 0
        end = scene.source_paragraph_end or 0
        if start > previous_end + 1:
            gap_start = previous_end + 1
            gap_end = start - 1
            filler = Scene(
                scene_id=f"GAP_{len(repaired) + 1:02d}",
                chapter_ref=chapter.ref,
                slug="INT. 待确认空间 - 日",
                time_of_day="日",
                summary="待补写：承接原文连续性的桥接段落。",
                intention="保留原文覆盖范围，等待人工细化场景归属。",
                source_paragraph_start=gap_start,
                source_paragraph_end=gap_end,
                source_text=build_scene_source_text(chapter, gap_start, gap_end),
            )
            ensure_scene_location(filler, assets)
            repaired.append(filler)
        if start <= previous_end:
            scene.source_paragraph_start = previous_end + 1
        if (scene.source_paragraph_start or 0) <= (scene.source_paragraph_end or 0):
            scene.source_text = build_scene_source_text(
                chapter,
                scene.source_paragraph_start or 1,
                scene.source_paragraph_end or 1,
            )
            repaired.append(scene)
            previous_end = scene.source_paragraph_end or previous_end
    if previous_end < len(chapter.paragraphs):
        filler = Scene(
            scene_id=f"GAP_{len(repaired) + 1:02d}",
            chapter_ref=chapter.ref,
            slug="INT. 待确认空间 - 日",
            time_of_day="日",
            summary="待补写：承接原文连续性的桥接段落。",
            intention="保留原文覆盖范围，等待人工细化场景归属。",
            source_paragraph_start=previous_end + 1,
            source_paragraph_end=len(chapter.paragraphs),
            source_text=build_scene_source_text(chapter, previous_end + 1, len(chapter.paragraphs)),
        )
        ensure_scene_location(filler, assets)
        repaired.append(filler)
    return repaired


def segment_chapter_scenes(chapter: ChapterUnit, assets: AssetBox, model: str = DEFAULT_MODEL) -> List[Scene]:
    review_skill = load_markdown(os.path.join("skills", "scene-segmentation-review.md"))
    schema_desc = json.dumps(ScenePlanResponse.model_json_schema(), ensure_ascii=False, indent=2)
    char_list = "\n".join(f"{item.id}: {item.name}（{item.type}）" for item in assets.characters) or "无"
    loc_list = "\n".join(f"{item.id}: {item.name}（{item.type}）" for item in assets.locations) or "无"
    numbered_paragraphs = format_numbered_paragraphs(chapter)
    user_prompt = f"""章节编号：{chapter.ref}

角色列表：
{char_list}

地点列表：
{loc_list}

带段落编号的原文：
{numbered_paragraphs}
"""
    extra_system = (
        "补充要求：\n"
        "1. 你必须输出 source_paragraph_start 和 source_paragraph_end，使用上方段落编号。\n"
        "2. source_text 由调度器根据段落范围自动回填，因此不得让场景重叠或漏段落。\n"
        "3. 每个场景只能绑定一个 location_ref。\n"
        f"4. 输出必须符合以下 JSON Schema：\n{schema_desc}"
    )

    best_scenes: List[Scene] = []
    max_retries = 2
    for retry in range(max_retries + 1):
        result = run_agent("scene-segmenter", user_prompt, model, extra_system=extra_system)
        current_scenes = coerce_scene_plan_items(result.get("scenes", []), chapter, assets)
        current_scenes = fill_scene_gaps(current_scenes, chapter, assets)
        review_payload = {"chapter_ref": chapter.ref, "scenes": prune_empty([scene.model_dump() for scene in current_scenes])}
        local_issues = local_scene_issues(current_scenes, chapter, assets)
        review = build_scene_review(review_payload, review_skill, model)
        issues = [*local_issues, *review.get("issues", [])]
        best_scenes = current_scenes
        if not issues or review.get("pass", False):
            return current_scenes
        if retry < max_retries:
            print(f"  🔄 场景切分审核未通过，重试 {retry + 1}/{max_retries}")
            user_prompt += "\n\n【上一版问题】\n" + "\n".join(issues[:20])
            user_prompt += "\n请重新切分，并确保段落范围连续、无重叠、无跨空间混杂。"
        else:
            print("  ⚠️ 场景切分仍有残余问题，保留当前已修复版本。")
    return best_scenes


def normalize_emotion(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    tokens = re.split(r"[，,、/；;|]+", value)
    for token in tokens:
        cleaned = token.strip()
        if not cleaned:
            continue
        mapped = EMOTION_MAP.get(cleaned.lower(), EMOTION_MAP.get(cleaned, cleaned))
        if mapped in EMOTION_WHITELIST:
            return mapped
        if mapped:
            return "其他"
    return None


def location_name_by_id(assets: AssetBox, location_id: Optional[str]) -> str:
    if not location_id:
        return ""
    for location in assets.locations:
        if location.id == location_id:
            return location.name
    return ""


def recent_beat_context(previous_scenes: List[Scene], limit: int = 12) -> List[str]:
    fingerprints: List[str] = []
    for scene in previous_scenes[-4:]:
        for beat in scene.beats:
            text = (beat.line or beat.description or "").strip()
            if text:
                fingerprints.append(text)
    return fingerprints[-limit:]


def beat_mentions_other_location(text: str, scene: Scene, assets: AssetBox) -> bool:
    if not text:
        return False
    text_key = normalize_text_key(text)
    for location in assets.locations:
        if location.id == scene.location_ref:
            continue
        if any(alias in text_key for alias in location_aliases(location)):
            return True
    return any(keyword in text for keyword in CROSS_SPACE_KEYWORDS)


def normalize_beats(raw_beats: list, scene: Scene, assets: AssetBox, previous_scenes: List[Scene]) -> List[Beat]:
    valid_character_ids = {item.id for item in assets.characters}
    prior_fingerprints = {normalize_text_key(item) for item in recent_beat_context(previous_scenes, limit=40)}
    local_fingerprints = set()
    beats: List[Beat] = []

    for raw in raw_beats:
        if not isinstance(raw, dict):
            continue
        beat_type = (raw.get("type") or "").strip().lower()
        if beat_type not in {"action", "dialogue"}:
            continue

        line = (raw.get("line") or "").strip()
        description = (raw.get("description") or "").strip()
        content = line if beat_type == "dialogue" else description
        if not content:
            continue
        if beat_mentions_other_location(content, scene, assets):
            continue

        fingerprint = normalize_text_key(content)
        if fingerprint in local_fingerprints or fingerprint in prior_fingerprints:
            continue

        character_ref = (raw.get("character_ref") or "").strip()
        if character_ref not in valid_character_ids and character_ref != "GROUP":
            character_ref = "GROUP" if beat_type == "action" else "GROUP"

        to_ref = (raw.get("to") or "").strip() or None
        if to_ref and to_ref not in valid_character_ids:
            to_ref = None

        beat = Beat(
            type=beat_type,
            character_ref=character_ref,
            emotion=normalize_emotion(raw.get("emotion")),
            description=description if beat_type == "action" else None,
            line=line if beat_type == "dialogue" else None,
            parenthetical=(raw.get("parenthetical") or "").strip() or None,
            subtext=(raw.get("subtext") or "").strip() or None,
            to=to_ref,
        )
        beats.append(beat)
        local_fingerprints.add(fingerprint)
    return beats


def apply_review_skill(
    scene: Scene,
    assets: AssetBox,
    skill_content: str,
    previous_scenes: List[Scene],
    model: str = DEFAULT_MODEL,
) -> dict:
    valid_ids = {character.id for character in assets.characters}
    current_location = location_name_by_id(assets, scene.location_ref) or scene.slug
    other_locations = [location.name for location in assets.locations if location.id != scene.location_ref]
    prior_context = recent_beat_context(previous_scenes, limit=12)
    beats_json = json.dumps(prune_empty([beat.model_dump() for beat in scene.beats]), ensure_ascii=False, indent=2)
    review_prompt = f"""请根据以下审核规则审核剧本节拍列表，并给出审核结果。

## 审核规则
{skill_content}

## 当前场景地点
{current_location}

## 其他地点名称（不得误写入本场）
{", ".join(other_locations) if other_locations else "无"}

## 已在前序场景出现过的节拍内容
{json.dumps(prior_context, ensure_ascii=False, indent=2)}

## 可用角色 ID
{", ".join(sorted(valid_ids)) if valid_ids else "无"}

## 节拍数据
{beats_json}

请返回一个 JSON 对象：
{{ "pass": true/false, "issues": ["问题描述1", "问题描述2"] }}
"""
    try:
        result = structured_completion(
            system_prompt="你是一个严格的剧本审核员。请只输出 JSON。",
            user_prompt=review_prompt,
            model=model,
        )
        return {"pass": result.get("pass", False), "issues": result.get("issues", [])}
    except Exception as exc:
        print(f"  ❌ 审核 Skill 执行失败: {exc}")
        return {"pass": False, "issues": [f"审核异常: {exc}"]}


def beat_generator_agent(scene: Scene, assets: AssetBox, previous_scenes: List[Scene], model: str = DEFAULT_MODEL) -> Scene:
    if not scene.source_text:
        scene.beats = []
        return scene

    agent_prompt = load_markdown(os.path.join("agents", "beat-generator.md"))
    beat_standard = load_markdown(os.path.join("references", "01-beat-writing-standard.md"))
    review_skill = load_markdown(os.path.join("skills", "review-beats.md"))
    schema_desc = json.dumps(BeatResponse.model_json_schema(), ensure_ascii=False, indent=2)

    char_list = "\n".join(f"{character.id}: {character.name}" for character in assets.characters) or "无"
    scene_location = location_name_by_id(assets, scene.location_ref) or scene.slug
    prior_context = "\n".join(f"- {item}" for item in recent_beat_context(previous_scenes)) or "- 无"

    system = agent_prompt.format(
        scene_summary=scene.summary,
        scene_intention=scene.intention,
        scene_source_text=scene.source_text,
        character_list=char_list,
        beat_writing_standard=beat_standard,
        scene_location=f"{scene_location}（{scene.location_ref or '未绑定地点'}）",
    )
    system += (
        "\n\n补充要求：\n"
        "1. 本场 beats 只能覆盖本场段落，不得复述前序场景已经呈现过的事件。\n"
        "2. 群体动作或环境描写使用 GROUP，不要凭空创建新的角色 ID。\n"
        f"3. 输出必须符合以下 JSON Schema：\n{schema_desc}"
    )

    user = f"""章节：{scene.chapter_ref}
场景编号：{scene.scene_id}
场景概要：{scene.summary}
场景意图：{scene.intention}
当前场景地点：{scene_location}
可用角色列表：
{char_list}

前序场景已使用的代表性节拍：
{prior_context}

当前场景原文：
{scene.source_text}
"""

    best_beats: List[Beat] = []
    max_retries = 2
    for retry in range(max_retries + 1):
        try:
            result = structured_completion(system, user, model)
            normalized = normalize_beats(result.get("beats", []), scene, assets, previous_scenes)
            scene.beats = normalized
            review = apply_review_skill(scene, assets, review_skill, previous_scenes, model)
            local_issues = []
            if not normalized:
                local_issues.append("beats 为空，未能覆盖本场原文。")
            issues = [*local_issues, *review.get("issues", [])]
            best_beats = normalized
            if normalized and (review.get("pass", False) or not issues):
                return scene
            if retry < max_retries:
                print(f"  🔄 场景 {scene.scene_id} 审核未通过，重试 {retry + 1}/{max_retries}")
                user += "\n\n【上一版问题】\n" + "\n".join(issues[:20])
                user += "\n请严格删除重复事件、跨空间内容，并仅保留本场新增信息。"
            else:
                print(f"  ⚠️ 场景 {scene.scene_id} 存在残余问题，保留已归一化 beats。")
        except Exception as exc:
            print(f"  ❌ 场景 {scene.scene_id} 节拍生成失败: {exc}")
            break
    scene.beats = best_beats
    return scene


def generate_beats_for_scene(scene: Scene, assets: AssetBox, previous_scenes: List[Scene], model: str = DEFAULT_MODEL) -> Scene:
    return beat_generator_agent(scene, assets, previous_scenes, model)


def renumber_scenes(scenes: List[Scene]) -> None:
    for index, scene in enumerate(scenes, start=1):
        scene.scene_id = f"S{index:02d}"


def novel_to_script(input_path: str, model: str = DEFAULT_MODEL) -> Script:
    chapters = load_chapters(input_path)
    title = os.path.splitext(os.path.basename(input_path.rstrip("\\/")))[0] if os.path.isfile(input_path) else os.path.basename(input_path.rstrip("\\/"))

    print("📚 正在装载章节...")
    print(f"   共载入 {len(chapters)} 个章节")

    print("📖 正在提取共享资产库...")
    assets = AssetBox()
    for chapter in chapters:
        print(f"   提取资产：{chapter.ref}")
        assets = extract_assets_for_chapter(chapter, assets, model)
    print(f"   最终得到 {len(assets.characters)} 个角色，{len(assets.locations)} 个地点，{len(assets.props)} 个道具")

    print("🎬 正在按章节切分场景并回填原文段落...")
    scenes: List[Scene] = []
    for chapter in chapters:
        print(f"   切分场景：{chapter.ref}")
        chapter_scenes = segment_chapter_scenes(chapter, assets, model)
        scenes.extend(chapter_scenes)
        print(f"   ✅ {chapter.ref} - {len(chapter_scenes)} 个场景")

    renumber_scenes(scenes)
    print(f"   共切分 {len(scenes)} 个场景")

    print("📝 正在为每个场景生成节拍...")
    completed_scenes: List[Scene] = []
    for scene in scenes:
        print(f"   处理 {scene.scene_id}（{scene.chapter_ref}）...")
        generate_beats_for_scene(scene, assets, completed_scenes, model)
        completed_scenes.append(scene)
        print(f"   ✅ {scene.scene_id} - {len(scene.beats)} beats")

    return Script(
        title=title or "未命名剧本",
        author="AI 辅助改编",
        assets=assets,
        scenes=completed_scenes,
    )


def export_yaml(script: Script, output_file: str) -> None:
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 120
    payload = prune_empty(script.model_dump())
    with open(output_file, "w", encoding="utf-8") as handle:
        yaml.dump(payload, handle)
    print(f"✨ 剧本已保存至 {output_file}")


def main():
    parser = argparse.ArgumentParser(description="AI 小说转剧本工具（支持单文件或 txt 目录）")
    parser.add_argument("input", help="小说文本文件路径，或包含多个 txt 章节的目录路径")
    parser.add_argument("--output", "-o", default="script.yaml", help="输出 YAML 文件路径")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL, help="模型名称")
    args = parser.parse_args()

    try:
        script = novel_to_script(args.input, model=args.model)
        export_yaml(script, args.output)
    except Exception as exc:
        print(f"❌ 错误：{exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
