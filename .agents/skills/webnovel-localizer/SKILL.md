---
name: webnovel-localizer
description: "Rewrite and localize Chinese webnovel manuscripts into platform-ready English for Dreame, GoodNovel, Webnovel, and similar CP short-fiction apps. Specializes in Mafia Romance and Werewolf Romance with Deep POV, trope voice, pacing, hooks, and cliffhangers. Use when users ask to translate or westernize Chinese romance to English webnovel style, polish translationese in English chapters, adapt alpha/luna or fated-mate werewolf stories, mafia arranged-marriage beats, or match overseas short-fiction platform rhythm."
---

# 海外短篇网文本地化改写 Skill

## 定位

将中国作者的中文网文内容改写为地道的海外英文网文风格。主要品类：Mafia Romance、Werewolf Romance。目标市场：北美英语 + 东南亚。

## 文件结构

本 Skill 采用模块化结构，主文件负责诊断引导，子目录 `docs/` 存放按需加载的规范与素材（相对本 Skill 目录）：

```
skills/overseas-webnovel-localizer/
├── SKILL.md              ← 诊断引导模块（本文件）
├── icon.png
└── docs/
    ├── mafia-romance.md       ← Mafia 品类：设定体系 + Trope + 表达库
    ├── werewolf-romance.md    ← Werewolf 品类：设定体系 + Trope + 表达库
    ├── style-guide.md         ← 语言风格：改写规则 + 翻译腔替换表
    ├── platform-guide.md      ← 平台适配：Dreame / GoodNovel / Webnovel
    └── quality-checklist.md   ← 质量检查清单
```

**读取规则**：
- 收到原文后，先执行本文件的「诊断引导模块」
- 诊断出品类后，读取 `docs/mafia-romance.md` 或 `docs/werewolf-romance.md`
- 所有改写必须读取 `docs/style-guide.md`
- 确认目标平台后，读取 `docs/platform-guide.md`
- 改写完成后，对照 `docs/quality-checklist.md` 逐项检查

---

## ⚡ 诊断引导模块（核心工作流）

收到用户提交的原文后，**严格按三步执行，不得跳过任何一步**。

### 第一步：自动诊断（DIAGNOSE）

从五个维度评估原文，每个维度0-10分：

| 维度 | 评估标准 | 评分锚点 |
|------|---------|---------|
| **文风 Prose** | 叙事视角、show vs tell、感官描写密度、内心独白风格 | 0=全知视角/直白告知，10=Deep POV/五感并用 |
| **对话 Dialogue** | 长度、口语化程度、缩写使用、punchy程度 | 0=长句演讲式，10=短促口语化 |
| **设定 Setting** | 品类核心设定元素是否到位、是否符合海外读者期待 | 0=中式修仙/宗门逻辑，10=标准Mafia/Pack体系 |
| **节奏 Pacing** | 章节结构、hook/cliffhanger、信息密度 | 0=慢热铺垫，10=快节奏+强hook |
| **角色 Characters** | 是否符合品类角色原型期待 | 0=中式言情角色，10=标准MMC/FMC原型 |

根据**综合得分**判定级别：

---

#### 🟢 Level A：精修（Polish）— 综合 7-10 分

**画像**：文风基本地道，设定西式，角色到位。少量翻译腔残留或描写可更生动。

**处理**：保留95%+内容结构，仅做：
- 替换残留翻译腔（查 `docs/style-guide.md` 替换表）
- 提升个别感官描写
- 微调对话punchy度
- 确认hook/cliffhanger效果
- 检查品类术语准确性

**改动幅度**：约5-15%

---

#### 🟡 Level B：西化改造（Westernize）— 综合 4-6 分

**画像**："穿着西装的中式灵魂"——设定框架西式，但文风有明显翻译腔，对话偏长偏文学化，情感直白（tell非show），感官描写以视觉为主。

**处理**：保留核心情节线和设定框架，深度改造：
- 全面切换Deep POV
- 重写所有对话（缩短+口语化+缩写）
- tell→show改造
- 增加触觉/嗅觉/听觉描写
- 加入斜体内心独白
- 加强opening hook和cliffhanger
- 全面替换翻译腔

**改动幅度**：约40-60%

---

#### 🔴 Level C：完全改写（Full Rewrite）— 综合 0-3 分

**画像**：整体非常中式——西式名字但中式设定逻辑（狼人写成修仙宗门、黑手党写成古代门派），文风完全翻译体，角色行为不符海外期待。

**处理**：提取核心故事梗概和情感走向，完全重建：
- 按品类文件重建世界观
- 按品类原型重构角色
- 用英文网文章节结构重组内容
- 完全重写所有文字
- 调整情节逻辑

**改动幅度**：约80-100%

---

### 第二步：向操作者确认（CONFIRM）

诊断完成后，**必须展示以下报告并等待确认，不得跳过直接执行**：

```
═══════════════════════════════════════════
📋 原文诊断报告
═══════════════════════════════════════════

📂 识别品类：[Mafia Romance / Werewolf Romance / 其他]
📏 原文字数：[X字/词]

┌─────────────────────────────────────────┐
│ 五维评分                                 │
├──────────────┬──────────┬───────────────┤
│ 文风 Prose   │  X/10    │ [一句话简评]   │
│ 对话 Dialog  │  X/10    │ [一句话简评]   │
│ 设定 Setting │  X/10    │ [一句话简评]   │
│ 节奏 Pacing  │  X/10    │ [一句话简评]   │
│ 角色 Chars   │  X/10    │ [一句话简评]   │
├──────────────┼──────────┼───────────────┤
│ 综合评分     │  X/10    │               │
└──────────────┴──────────┴───────────────┘

🏷️ 判定级别：🟢A精修 / 🟡B西化改造 / 🔴C完全改写

📝 诊断依据（附原文举例）：
   1. [问题 + "原文：..."]
   2. [问题 + "原文：..."]
   3. [问题 + "原文：..."]

🔧 改写计划：
   1. [具体改动1]
   2. [具体改动2]
   3. [具体改动3]
   4. [具体改动4]

💡 预计改动幅度：约 X%

═══════════════════════════════════════════
⚠️ 请确认：
   1. 按建议执行
   2. 调整级别（升/降一级）
   3. 针对某个维度特别调整
   4. 其他要求
═══════════════════════════════════════════
```

**确认规则**：
- 选1 → 进入执行
- 选2 → 按新级别重制计划，再次确认
- 选3 → 针对性调整，再次确认
- 选4 → 灵活调整
- **必须得到明确确认才能进第三步**

---

### 第三步：执行改写（EXECUTE）

确认后，根据级别执行。**执行前必须先读取以下文件**：

| 级别 | 必读文件 |
|------|---------|
| 所有级别 | `docs/style-guide.md` + `docs/platform-guide.md` |
| Mafia品类 | + `docs/mafia-romance.md` |
| Werewolf品类 | + `docs/werewolf-romance.md` |
| 完成后 | 对照 `docs/quality-checklist.md` |

**Level A 执行**：逐段扫描 → 替换翻译腔 → 微调描写对话 → 检查术语 → 输出全文+修改标注

**Level B 执行**：提取场景/情节线 → 确定POV → 逐场景改造（对话/感官/POV） → 重构节奏 → 输出全文+逐处改写说明

**Level C 执行**：提取核心故事线 → 重建设定 → 重构角色 → 重新写作 → 输出全文+对照说明

**所有级别通用输出要求**：
- 标注每章/段词数
- 标注POV角色
- 关键改写处用 `【改写说明】` 注释原因
- 结尾附「本次改写学习要点」3-5条
