# Skill: 节拍审核与修正 (Review Beats)

## 审核规则
以下检查必须逐条执行，每发现一个问题记录一条 `issue`。

### 1. 角色引用检查
- `character_ref` 如果非空且非 "GROUP"，必须存在于可用角色 ID 列表中，或以 `TEMP_` 开头。
- `to` 字段如果存在，同样检查。
- 若角色名称包含群体关键词（如“众人”“宇航员们”“监测人员”），应标记为群体角色问题。

### 2. 字段完整性检查
- 若 `type` 为 "dialogue"，则 `line` 必须存在且非空。
- 若 `type` 为 "action"，则 `description` 必须存在且非空。

### 3. 情绪检查
- 若 `emotion` 存在，必须属于以下白名单：
  高兴、愤怒、悲伤、惊讶、恐惧、厌恶、紧张、兴奋、好奇、冷漠、得意、不屑、无奈、坚定、犹豫、感动、尴尬
- 若 `emotion` 为英文，直接按映射表替换为中文，并记录一条 issue（说明已自动修正），**不视为错误**。

### 4. 原子性检查
- 若 `type` 为 "action" 且 `description` 中包含中文引号（“ ”）或冒号引导的对话，标记为“包含对话文本，应拆分”。
- 若 `description` 中包含“一边...一边...”结构，标记为“包含并行动作，可能需拆分”。
- 若 `description` 中包含两个或以上不同的角色 ID（从可用角色列表中匹配），标记为“包含多个角色主体，应拆分”。

## 情绪映射表
shock: 震惊
awe: 敬畏
disbelief: 难以置信
urgent: 急迫
angry: 愤怒
sad: 悲伤
surprised: 惊讶
fear: 恐惧
disgusted: 厌恶
nervous: 紧张
excited: 兴奋
curious: 好奇
indifferent: 冷漠
proud: 得意
disdainful: 不屑
helpless: 无奈
firm: 坚定
hesitant: 犹豫
touched: 感动
embarrassed: 尴尬
confident: 自信
calm: 冷静
anxious: 焦虑
confused: 困惑
utter shock: 震惊
stunned disbelief: 难以置信
chaotic excitement: 混乱的兴奋
tense anticipation: 紧张的期待
overwhelmed: 不知所措

## 修正指引
- 遇到原子性问题时，必须提供具体的拆分示例，要求模型重写该 beat。
- 遇到情绪问题时，优先自动修正并记录，若不在映射表也不在白名单，则要求模型替换为标准情绪。
- 其他问题直接给出修正指令。

## 输出格式
JSON 对象：`{ "pass": true/false, "issues": ["问题1", "问题2", ...] }`