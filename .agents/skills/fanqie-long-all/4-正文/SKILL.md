---
name: fanqie-write-redirect
description: "Redirect legacy Fanqie long-all body-text calls to the unified fanqie-long-zhengwen skill."
---

# 正文阶段转向说明

本项目不再使用 `fanqie-long-all/4-正文/SKILL.md` 作为正文执行技能。

正文阶段统一读取并执行：

` .agents/skills/fanqie-long-zhengwen/SKILL.md`

## 执行原则

- `4-正文/` 仍然是正文章节草稿的输出目录。
- 正文写作、完稿校准、章节审查、去 AI 味、人物真实性检查、记忆更新，全部以 `.agents/skills/fanqie-long-zhengwen/SKILL.md` 为准。
- 如果其他流程提示“加载 4-正文”，应理解为加载 `.agents/skills/fanqie-long-zhengwen/SKILL.md`，而不是执行本文件。

