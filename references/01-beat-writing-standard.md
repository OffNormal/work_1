# 节拍写作标准

## 情绪词表（必须使用中文）
高兴、愤怒、悲伤、惊讶、恐惧、厌恶、紧张、兴奋、好奇、冷漠、得意、不屑、无奈、坚定、犹豫、感动、尴尬、其他

## 字段要求
- **dialogue**：必须包含 `character_ref` 和 `line`，`line` 不能为空
- **action**：必须包含 `character_ref`（群体动作可用 "GROUP"）和 `description`，`description` 不能为空
- **character_ref** 必须来自资产库中的角色 ID
- **to** 字段表示说话对象，必须是合法角色 ID 或为空
- 不输出值为 null 或空字符串的字段