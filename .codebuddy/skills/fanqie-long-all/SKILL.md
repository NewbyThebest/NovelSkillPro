---
name: fanqie-long-all
description: "Run a Fanqie-style long-form Chinese webnovel pipeline: project init, sample-book boundary teardown, ideation, outline, chapter drafting, and review checkpoints. Use when the user asks for 番茄全流程, 番茄长篇全流程, 番茄长篇工作流, loading the Fanqie novel kit, or initializing a long webnovel project for Fanqie."
---

# 番茄长篇小说流程 Kit（全流程入口）

## 触发词

用户说以下内容时，可加载本 SKILL 进入全流程模式：
- **番茄全流程** / **番茄长篇全流程**
- **番茄长篇工作流** / **按番茄流程写一本长篇**
- **我想写一本长篇网络小说** / **我想写长篇**
- **我想写一本小说**（并确认为长篇）
- **加载番茄小说技能包** / **项目初始化**（从零开始写长篇时）

**只做某一阶段？**  
用户若只明确某一阶段（如「我只要写大纲」），不要走全流程，提示其直接加载对应阶段的 `SKILL.md`。

---

## 执行顺序

**第零步：项目初始化（在流程内完成，不依赖插件）**  
若当前项目根目录尚未初始化，则先执行以下动作，再进入第一步；若已存在 `SOLOENT.md` 及标准目录结构，可跳过。
- 在项目根创建目录：`1-边界`、`2-设定`、`3-大纲`、`4-正文`、`5-审查`、`.novelkit/constitution`、`.novelkit/memory`。
- 从本技能包 `1-边界确定/docs/` 读取并写入项目：
  - `SOLOENT.md` → 项目根目录
  - `MASTER.md` → `.novelkit/constitution/MASTER.md`
  - `TEMPLATE_CHARACTER_STATE.md` → `.novelkit/memory/character_state.md`
  - `TEMPLATE_FORESHADOWING.md` → `.novelkit/memory/foreshadowing.md`
  - `expectation_template.md` → `1-边界/预期.md`
- 若技能包根目录有 `番茄长篇小说技能说明书.md`，可复制到项目根供用户查阅。
- 完成后提示用户「项目已初始化」，再进入第一步。

**第一步**：读取并执行 `1-边界确定/SKILL.md`
→ 拆解样板书的题材边界、首屏钩子、爽点循环、追读结构与投流素材，产出 1-边界/ 系列文件。完成后继续。

**第二步**：读取并执行 `2-创意与设定/SKILL.md`
→ 围绕番茄题材适配、核心卖点、金手指/关系爆点、角色表与宪法做创意设定。完成后继续。

**第三步**（可选）：读取并执行 `5-审查/SKILL.md`
→ 对当前设定做质检，发现问题回到第二步修正，确认无误后继续。

**第四步**：读取并执行 `3-大纲/SKILL.md`
→ 只生成全书方向大纲/总纲，不要求开书时写完整卷纲或批量章纲；重点锁定题材承诺、主线方向、阶段爽点、换图逻辑、前 30-50 章留存爆点与可动态调整的近期锚点。完成后继续。

**第五步**（可选）：读取并执行 `5-审查/SKILL.md`
→ 对大纲做质检，确认无误后继续。

**第六步**：读取并执行 `.agents/skills/fanqie-long-zhengwen/SKILL.md`
→ 每次写第 X 章前，先基于总纲、设定、上一章正文、角色状态、伏笔进度和用户本章意图即时生成并确认第 X 章章纲，再按章写作；确保首屏抓力、单章冲突推进、爽点兑现、章尾钩子、移动端阅读节奏、去 AI 味、人物真实和记忆更新。剧情偏离时优先修订下一章即时章纲，必要时再回到第四步修订总纲。

**第七步**（可选，每章或每卷后）：读取并执行 `5-审查/SKILL.md`
→ 正文/设定回溯，发现问题回对应阶段修正。

---

> 若用户只明确说了某个阶段（如「我只要写大纲」），请停止执行本全流程，提示用户直接加载 `3-大纲/SKILL.md`。
