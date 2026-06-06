# 剧本 YAML Schema

本文定义小说自动改编为结构化剧本时使用的 YAML Schema，并解释字段设计原因。目标不是替代最终成稿格式，而是提供一份适合 Agent 流水线生成、校验、回溯、人工续写的中间剧本稿。

## 设计目标

1. 支持多章节输入：能够连续处理 `txt/` 目录下 3 个章节以上的文本。
2. 保证场景可回溯：每个场景都能追溯到原始章节和段落范围，便于定位错分、漏分、重复覆盖。
3. 保证资产一致性：角色、地点、道具集中管理，避免“同人不同 ID”“同地不同 ID”。
4. 保证剧本可编辑：生成结果既能被程序校验，也能被作者直接打开后手工打磨。
5. 兼容 Agent + Skill 架构：字段要能支撑“生成 -> 审核 -> 回改”的闭环。

## Schema 总览

```yaml
schema_version: "1.0"
title: "num_01"
author: "AI 辅助改编"
assets:
  characters:
    - id: "CHAR_YE"
      name: "叶凡"
      aliases: []
      type: "protagonist"
      description: "大学毕业后留在城市，对古籍和上古历史充满兴趣。"
      traits: ["淡然", "好奇", "不喜计较"]
      voice_tone: "平静，偶尔调侃"
  locations:
    - id: "LOC_ROOM"
      name: "叶凡的房间"
      type: "INT"
      description: "叶凡阅读古籍的私人空间。"
  props:
    - "黄帝内经"
    - "手机"
scenes:
  - scene_id: "S01"
    chapter_ref: "num_01"
    slug: "INT. 叶凡的房间 - 黄昏"
    location_ref: "LOC_ROOM"
    time_of_day: "黄昏"
    summary: "叶凡在房间阅读古籍，接到林佳电话后准备出门。"
    intention: "建立人物气质，并引出同学聚会。"
    source_paragraph_start: 1
    source_paragraph_end: 20
    source_text: |
      第二章 素问
      　　“上古之人……”
    beats:
      - type: "action"
        character_ref: "CHAR_YE"
        emotion: "好奇"
        description: "叶凡合上《黄帝内经》，仍在回味上古文明的神秘。"
      - type: "dialogue"
        character_ref: "CHAR_LIN"
        emotion: "高兴"
        line: "我不太清楚聚会的地点，一会儿同去。"
        to: "CHAR_YE"
```

## 顶层字段

### `schema_version`
- 类型：`string`
- 含义：当前 YAML 结构的版本号。
- 设计原因：便于后续升级字段而不破坏旧稿兼容性，尤其适合 Agent 管线持续迭代。

### `title`
- 类型：`string`
- 含义：剧本标题，通常取输入文件名或章节集合名。
- 设计原因：保证输出文件在目录中可识别，也方便后续接入封面页、项目管理或导出器。

### `author`
- 类型：`string`
- 含义：当前初稿的作者标识，可写为工具名、作者名或联合署名。
- 设计原因：帮助区分人工稿、AI 初稿、联合修订稿。

### `assets`
- 类型：`object`
- 含义：全局资产库。
- 设计原因：把“角色/地点/道具”抽到顶层，避免每个场景反复发明资产定义，保证跨章节一致性。

### `scenes`
- 类型：`array`
- 含义：按叙事顺序排列的场景列表。
- 设计原因：场景是剧本生成与审核的核心单元，也是最适合作者逐场修改的粒度。

## `assets` 结构

### `assets.characters`
- 类型：`array<object>`
- 每项字段：
  - `id`: 角色唯一 ID，例如 `CHAR_YE`
  - `name`: 角色名
  - `aliases`: 别名列表
  - `type`: `protagonist | antagonist | supporting`
  - `description`: 身份、关系、剧情功能的简述
  - `traits`: 稳定性格或行为倾向
  - `voice_tone`: 说话风格
- 设计原因：
  - `id` 让 beats 能稳定引用角色，不受名字改写影响。
  - `aliases` 解决“本名/昵称/代称”共指问题。
  - `description + traits + voice_tone` 让后续对白生成更稳定，不只是“有这个人”，而是“知道这个人怎么说话、怎么行动”。

### `assets.locations`
- 类型：`array<object>`
- 每项字段：
  - `id`: 地点唯一 ID，例如 `LOC_MARKET`
  - `name`: 地点名称
  - `type`: `INT | EXT`
  - `description`: 该地点的空间说明
- 设计原因：
  - `location_ref` 必须依赖一个统一地点库，才能做场景空间绑定校验。
  - `INT/EXT` 直接服务于场标 `slug`，减少后续格式转换成本。

### `assets.props`
- 类型：`array<string>`
- 含义：重要道具名称列表。
- 设计原因：道具通常不需要像角色那样高频引用，但仍需保留，便于后续场面调度、分镜或美术清单扩展。

## `scenes` 结构

### `scene_id`
- 类型：`string`
- 含义：场次编号，例如 `S01`
- 设计原因：是人工沟通、审稿、导出拍摄单时最常用的定位键。

### `chapter_ref`
- 类型：`string`
- 含义：该场景来自哪个原始章节文件，例如 `num_01`
- 设计原因：支持多章节自动转换，也便于在出错时快速回到原始章节修正。

### `slug`
- 类型：`string`
- 含义：标准场标，格式如 `INT. 叶凡的房间 - 黄昏`
- 设计原因：这是剧本行业最直接的场景标签，同时承载空间和时间信息。

### `location_ref`
- 类型：`string`
- 含义：指向 `assets.locations[].id`
- 设计原因：`slug` 是给人看的，`location_ref` 是给程序校验和复用的。两者分离能避免“名字改了但还是同一地点”带来的混乱。

### `time_of_day`
- 类型：`string`
- 含义：时间段，如 `清晨 / 日 / 黄昏 / 夜`
- 设计原因：保留结构化时间信息，方便后续导出拍摄场次或进行视觉风格标注。

### `summary`
- 类型：`string`
- 含义：一句话概括本场事件。
- 设计原因：用于快速浏览剧本结构，也用于自动检查“是否与别的场景重复描述同一事件”。

### `intention`
- 类型：`string`
- 含义：该场戏的叙事功能。
- 设计原因：这是从“事件”到“写作意图”的关键桥梁，能帮助作者判断这场戏是否值得保留、是否需要重写。

### `source_paragraph_start`
- 类型：`integer`
- 含义：原文起始段落编号。
- 设计原因：这是本 Schema 的关键增强字段之一。它把场景切分从“模糊摘录”变成“可计算的锚点”，能显著减少场景重叠、漏段和三场景复述同一事件的问题。

### `source_paragraph_end`
- 类型：`integer`
- 含义：原文结束段落编号。
- 设计原因：与 `source_paragraph_start` 共同形成一个闭区间，便于程序验证场景是否连续、无重叠、无遗漏。

### `source_text`
- 类型：`string`
- 含义：与段落区间对应的原文摘录。
- 设计原因：
  - 给作者直接对照原文，无需再去 TXT 里查。
  - 给后续 beat 生成提供明确语料边界。
  - 即使段落编号正确，保留文本摘录仍然更方便人工审阅。

### `beats`
- 类型：`array<object>`
- 含义：该场戏的节拍列表。
- 设计原因：beats 是从叙事段落转为可拍摄戏剧动作的最小可编辑单位。

## `beats` 结构

### 公共字段

#### `type`
- 类型：`string`
- 取值：`action | dialogue`
- 设计原因：先区分动作和对白，后续的字段校验才能有明确规则。

#### `character_ref`
- 类型：`string`
- 含义：执行动作或说出台词的角色 ID，也允许使用 `GROUP`
- 设计原因：
  - 对已命名角色，必须稳定指向资产库。
  - 对环境动作、群体反应、未命名路人，允许用 `GROUP`，避免把群体误塞进角色资产库。

#### `emotion`
- 类型：`string`
- 含义：情绪标签，建议使用标准中文词表。
- 设计原因：帮助后续表演理解、对白润色和风格控制；同时适合作为可校验字段。

### `action` 专用字段

#### `description`
- 类型：`string`
- 含义：动作或画面描述。
- 设计原因：动作 beats 应只承载一个主体的一个动作或一个画面焦点，便于后续拆镜与表演。

### `dialogue` 专用字段

#### `line`
- 类型：`string`
- 含义：台词正文。
- 设计原因：对白必须独立成 beat，避免动作与台词混写。

#### `parenthetical`
- 类型：`string`
- 含义：括号提示，如语气、停顿、小动作。
- 设计原因：给演员和作者额外提示，但保持可选，避免过度导演化。

#### `subtext`
- 类型：`string`
- 含义：潜台词。
- 设计原因：在保留对白简洁的同时，为后续精修提供意图层信息。

#### `to`
- 类型：`string`
- 含义：对白对象角色 ID。
- 设计原因：在多人场景中帮助明确对话指向，降低对白关系歧义。

## 为什么这个 Schema 能更好解决当前问题

### 1. 解决“三场景覆盖相同事件”
- 核心字段：`source_paragraph_start`、`source_paragraph_end`、`summary`
- 原因：同一段原文只能被一个场景占用；同时 `summary` 可做重复语义检查。结构上先把重叠空间压缩掉，再做语义去重。

### 2. 解决“场景空间绑定失效”
- 核心字段：`location_ref`、`slug`、`source_text`
- 原因：`location_ref` 提供程序可校验的唯一地点锚；`slug` 保留给人看的场标；`source_text` 允许用地点别名做反查，发现跨空间混写时可以回改。

### 3. 解决“资产库不一致”
- 核心字段：`assets.characters[].id`、`assets.locations[].id`、`aliases`
- 原因：所有场景与 beats 都必须引用顶层统一资产库，不能各写各的；`aliases` 用来吸收不同章节的称呼差异。

### 4. 解决“角色定义不完整”
- 核心字段：`description`、`traits`、`voice_tone`
- 原因：这三个字段共同构成“可用于写戏”的角色定义。只有名字，没有性格和语气，后续对白生成会极不稳定。

## 推荐约束

1. `scene_id` 按全剧连续编号，不按章节重置。
2. 每个场景只能绑定一个 `location_ref`。
3. 每个 beat 只表达一个动作或一句对白。
4. `GROUP` 只用于群体或环境，不进入顶层角色资产库。
5. 若输入是多章节目录，`chapter_ref` 必填。
6. 输出时应清理空字符串、空数组和 `null` 字段，降低人工编辑噪音。

## 总结

这份 YAML Schema 不是单纯“把剧本内容序列化”，而是把改编工作流中的几个关键问题显式结构化：

- 用 `assets` 解决全局一致性
- 用 `chapter_ref + paragraph range` 解决原文回溯与场景去重
- 用 `location_ref` 解决空间绑定
- 用 `beats` 解决从小说叙述到可编辑剧本动作的落地

因此它更适合作为 AI 辅助改编工具的“初稿中间层”，而不是一次性终稿格式。
