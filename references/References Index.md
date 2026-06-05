# References Index

本目录是 `work_1` 的运行时知识层。
目标：以最少文档承载最多可执行规则。

## 文档清单

### 核心原则与系统（A 级 - 必读）
1. `00-first-principles.md` — 第一性原则与目标函数
2. `01-adaptation-system.md` — 小说改编分析系统（含性别频率、情绪曲线、Buff 系统）
3. `02-episode-architecture.md` — 分集与情绪曲线系统（含系统化分集框架）
4. `03-script-writing-standard.md` — 单集写作标准（含类型模板、格式标记）
5. `04-review-gates.md` — 业务审核与一致性门控（含 Aligner 方法论）
6. `18-theme-selection-philosophy.md` — 题材选择哲学（开天眼方法论、众生好恶、颠倒真相）

### 分镜与视频化（B 级 - 按需）
7. `06-storyboard-handoff.md` — 剧本到分镜/动态提示词桥接（含两种工作流）
8. `08-camera-and-cinematography.md` — 镜头与摄影技巧（景别、角度、运镜）
9. `09-storyboard-methodology.md` — 分镜方法论（Beat breakdown、九宫格、四宫格）
10a. `10a-action-dialogue-scenes.md` — 动作与对话场景设计
10b. `10b-atmosphere-fantasy.md` — 氛围营造与奇幻视觉设计
10c. `10c-suspense-montage.md` — 悬疑惊悚与蒙太奇设计
11a. `11a-seedance-prompt-methodology.md` — Seedance 2.0 提示词方法论
11b. `11b-image-motion-prompt.md` — 图像与动态提示词方法论
11c. `11c-sora2-rhythm-control.md` — Sora2 方法论与节奏控制
12. `12-genre-specific-techniques.md` — 类型化技巧（玄幻、末世、网文、短剧）
13. `19-micro-drama-storyboard-system.md` — 微短剧分镜两阶段系统（视觉词典 + 视听单元生成）
14. `20-frame-description-elements.md` — 帧图描述完整元素表（26 项元素清单，整合 08/11b/15/17/19）

### 视觉叙事与心理学（D 级 - 进阶）
14. `13-show-dont-tell-methodology.md` — Show Don't Tell 方法论（情绪翻译、动作化、画面语言）
15. `14-story-psychology.md` — 故事心理学（观众心理、情绪共鸣、悬念设计、认知负荷）
16. `15-color-psychology.md` — 色彩心理学（色彩情绪、色彩叙事、类型化色彩）
17. `16-dramatic-principles.md` — 剧作原理（三幕结构、冲突设计、人物弧光、节奏控制）
18. `17-lighting-narrative.md` — 光影叙事（光影情绪、明暗对比、光影与人物）

### 知识管理（C 级 - 参考）
19. `07-knowledge-curation.md` — 知识增量收编与去重规则
20. `21-agent-logging-standard.md` — Agent 日志记录规范（统一格式、记录时机、内容要求）

## 优先级说明

- **A 级（必读）**：所有 Agent 和 Skill 必须理解的核心规则
- **B 级（按需）**：特定阶段或工作流需要的专业知识
- **C 级（参考）**：系统维护和知识管理相关
- **D 级（进阶）**：视觉叙事、心理学、剧作理论等进阶知识

## 使用规则

1. `skills/` 只允许引用本目录文档作为执行依据
2. `sources/` 已归档，仅用于历史参考，不直接作为运行时依赖
3. 每次知识更新后，必须更新 `knowledge/absorption-map-index.md`
4. 遵循单一信息源原则：每个知识点只在一个位置维护

## 可选资料池

开源版默认不分发 `sources/`。本目录的核心规则应足以支撑运行时使用；如果你有可授权的本地补充资料，可以自行创建 `sources/` 或 `pending-knowledge/`，经知识收编后把稳定结论沉淀回 `references/` 或 `skills/`。

**使用原则**：
- 优先使用本目录（references/）的核心规则
- `sources/` 只作为本地吸收输入，不作为开源版运行时依赖
- 可公开、可授权、可复用的规则必须回写到单一信息源

## 工作流映射

### 小说 → 剧本流程
- 知识收编：07
- 改编分析：00, 01, 02, 18
- 分集规划：00, 02, 18
- 剧本写作：00, 03, 12, 18
- 业务审核：04, 18
- 合规审核：05

### 剧本 → 分镜流程（标准分镜流）
- 分镜桥接：06
- Beat 拆解：09
- Beat Board：08, 09, 11
- Sequence Board：08, 09, 11
- Motion Prompt：08, 11

### 剧本 → 分镜流程（Seedance 流）
- 分镜桥接：06
- 导演分析：08, 09, 10
- 服化道设计：10, 11, 12, 20
- Seedance 提示词：11, 12, 19, 20

## 内容归属地图

易混淆主题的快速归属查阅（详见 `07-knowledge-curation.md`「内容归属边界」章节）：

| 主题 | 归属 | 不归属 | 区分 |
|------|------|--------|------|
| 情绪曲线/观众心理 | 14（故事心理学） | 16（剧作原理） | 14=心理视角，16=结构视角 |
| 冲突设计/矛盾公式 | 16（剧作原理） | 14（故事心理学） | 16=结构方法，14=心理机制 |
| 节奏控制 | 16（剧作原理） | 14（故事心理学） | 16=写作节奏，14=情绪节奏 |
| 动作场景设计 | 10（场景设计） | 13（Show Don't Tell） | 10=场景层面，13=表达手法 |
| 视觉化表达 | 13（Show Don't Tell） | 10（场景设计） | 13=SDT方法，10=场景技巧 |
| 镜头构图 | 08（镜头摄影） | 17（光影叙事） | 08=构图运镜，17=光影叙事 |
| 爽感/共鸣设计 | 14（故事心理学） | 16（剧作原理） | 14=观众心理，16=结构设计 |
| 人设弧光 | 16（剧作原理） | 14（故事心理学） | 16=角色结构，14=心理共鸣 |

## 健康状态

> 由 knowledge-curator 每次收编后更新。状态标准：OK < 800 行 / WARNING 800-1199 行 / OVERSIZED >= 1200 行

| 文件 | 状态 |
|------|------|
| 00-first-principles.md | — |
| 01-adaptation-system.md | — |
| 02-episode-architecture.md | — |
| 03-script-writing-standard.md | — |
| 04-review-gates.md | — |
| 05-compliance-boundaries.md | — |
| 06-storyboard-handoff.md | — |
| 07-knowledge-curation.md | — |
| 08-camera-and-cinematography.md | — |
| 09-storyboard-methodology.md | — |
| 10a-action-dialogue-scenes.md | — |
| 10b-atmosphere-fantasy.md | — |
| 10c-suspense-montage.md | — |
| 11a-seedance-prompt-methodology.md | — |
| 11b-image-motion-prompt.md | — |
| 11c-sora2-rhythm-control.md | — |
| 12-genre-specific-techniques.md | — |
| 13-show-dont-tell-methodology.md | — |
| 14-story-psychology.md | — |
| 15-color-psychology.md | — |
| 16-dramatic-principles.md | — |
| 17-lighting-narrative.md | — |
| 18-theme-selection-philosophy.md | — |
| 19-micro-drama-storyboard-system.md | — |
| 20-frame-description-elements.md | — |
| 21-agent-logging-standard.md | — |

## 更新记录

- 2026-03-15：新增 `21-agent-logging-standard.md`（Agent 日志记录规范：统一格式、记录时机、内容要求）
- 2026-03-12：新增「内容归属地图」和「健康状态」章节，更新 absorption-map 引用路径
- 2026-03-12：新增 `19-micro-drama-storyboard-system.md`（微短剧分镜两阶段系统：视觉词典 + 视听单元生成）
- 2026-03-11：新增 `18-theme-selection-philosophy.md`（题材选择哲学：开天眼方法论、众生好恶、颠倒真相）
- 2026-03-07：完成 sources/ 内容整合，新增 5 个参考文档（08-12），增强 6 个现有文档（01-06）
- 整合范围：~180 文件，4 个子目录
- 新增内容：镜头摄影、分镜方法论、场景设计、视频提示词、类型化技巧
