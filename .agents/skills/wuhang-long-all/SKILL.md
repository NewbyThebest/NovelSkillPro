---
name: wuhang-long-all
description: Run Wuhang's full long-form web novel pipeline—project init, boundary analysis, ideation, outline, writing, and optional review checkpoints. Use when the user asks for 武行全流程, 武行长篇全流程, long web novel workflow, loading the Wuhang novel kit, or initializing a new long-novel project.
---

# 武行·长篇小说流程 Kit（全流程入口）

## 触发词

用户说以下内容时，可加载本 SKILL 进入全流程模式：
- **武行全流程** / **武行长篇全流程**
- **我想写一本长篇网络小说** / **我想写长篇**
- **我想写一本小说**（并确认为长篇）
- **加载武行小说技能包** / **项目初始化**（从零开始写长篇时）

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
- 若技能包根目录有 `武行-长篇小说技能说明书.md`，可复制到项目根供用户查阅。
- 完成后提示用户「项目已初始化」，再进入第一步。

**第一步**：读取并执行 `1-边界确定/SKILL.md`
→ 样板书拆解，产出 1-边界/ 系列文件。完成后继续。

**第二步**：读取并执行 `2-创意与设定/SKILL.md`
→ 脑暴、设定案、角色表、宪法。完成后继续。

**第三步**（可选）：读取并执行 `5-审查/SKILL.md`
→ 对当前设定做质检，发现问题回到第二步修正，确认无误后继续。

**第四步**：读取并执行 `3-大纲/SKILL.md`
→ 总纲、卷纲、章纲。完成后继续。

**第五步**（可选）：读取并执行 `5-审查/SKILL.md`
→ 对大纲做质检，确认无误后继续。

**第六步**：读取并执行 `4-正文/SKILL.md`
→ 按章写作，本卷完成或剧情偏离时回到第四步修订或开写下一卷。

**第七步**（可选，每章或每卷后）：读取并执行 `5-审查/SKILL.md`
→ 正文/设定回溯，发现问题回对应阶段修正。

---

> 若用户只明确说了某个阶段（如「我只要写大纲」），请停止执行本全流程，提示用户直接加载 `3-大纲/SKILL.md`。
