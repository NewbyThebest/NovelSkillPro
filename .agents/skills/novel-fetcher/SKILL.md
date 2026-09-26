---
name: novel-fetcher
description: 抓取指定小说平台上某本书的正文、简介与榜单搜索信息，长篇与短篇短故事均可。支持抓某几章、指定范围或整本，也支持查看作品详情、抓取多平台排行榜与推荐位（含番茄新书榜/阅读榜并可按分类一键扫榜、起点月票榜、刺猬猫、SF轻小说、Kakuyomu）、按关键词搜索作品，输出为本地 TXT 或终端列表供拆解、选题、仿写或素材引用。用于“抓某本书的正文”“下载这本书”“这个平台有什么榜单”“番茄新书榜”“扫榜”“搜一下这本书”“看看这本书的简介和成绩”“抓短篇故事”“找选题看看各站排行”。已内置番茄、起点专用通道与多站榜单；抓取本地已有文件、分析样板书内容或审查稿件都不使用本技能。
---

# 多平台小说抓取

## 边界与路径

- 将本技能目录记为 `SKILL_DIR`，包含 `.agents/` 的项目根目录记为 `WORKSPACE_ROOT`。
- 正文默认输出到 `<WORKSPACE_ROOT>/.temp/novel-fetch/<书名>/`，文件名形如 `0001-第1章 xxx.txt`，另有 `_fetch_meta.json` 记录抓取清单与失败原因。
- 脚本**零第三方依赖**，只用 Python 标准库，可直接运行，不需要 pip 安装。
- 只抓取用户有权访问的公开内容。遇到付费、会员或登录限制的章节，脚本会如实报失败，不绕过付费墙、不保存被截断的内容。
- 抓到的内容是原始素材，不是拆解报告。需要提炼卖点与节奏时，再交给 `book-analysis`。

## 四类能力

| 能力 | 命令 | 说明 |
| --- | --- | --- |
| 作品详情 | `inspect <链接>` | 书名、作者、分类、状态、字数、最新章节、简介、完整目录 |
| 榜单推荐 | `rank --channel <通道>` | 多平台排行榜与推荐位，可翻页 |
| 关键词搜索 | `search <关键词>` | 按书名/作者/关键词检索作品 |
| 正文抓取 | `fetch <链接>` | 抓指定章节或整本，输出 TXT |

**用户只给书名**时，先用 `search` 找到作品页链接，再用 `inspect` 确认，最后才 `fetch`。不要凭猜测拼 URL。

## 站点支持范围

| 站点 | 详情 | 目录 | 正文 | 搜索 | 榜单 |
| --- | --- | --- | --- | --- | --- |
| 番茄小说 | ✅ | ✅ | ✅ 双通道 | ✅ | ✅ 14 个 |
| 起点中文网 | ✅ | ✅ | ✅ 免费章 | ✅ | ✅ 12 个 |
| 刺猬猫 | ✅ | ✅ | ⚠️ 见下 | ➖ | ✅ 8 个 |
| SF 轻小说 | ➖ | ➖ | ➖ | ➖ | ✅ 9 个 |
| Kakuyomu | ➖ | ➖ | ➖ | ➖ | ✅ 16 个 |
| 其他 HTTP 小说站 | ✅ 启发式 | ✅ | ✅ | ➖ | ➖ |

共 59 个榜单通道。「➖」表示上游没有对应接口，或本技能暂未适配。

**刺猬猫正文的限制**：详情与目录可正常解析，但章节页会返回验证码拦截页，正文暂无法抓取。这是站点侧的反爬限制，不是脚本缺陷；不要尝试绕过验证码。

## 核心命令

所有命令在 `SKILL_DIR/scripts/` 下执行：

```bash
# 作品详情与目录（不下载正文）
python "<SKILL_DIR>/scripts/fetch_novel.py" inspect "<作品链接>"

# 搜索作品
python "<SKILL_DIR>/scripts/fetch_novel.py" search "关键词" --limit 10
python "<SKILL_DIR>/scripts/fetch_novel.py" search "关键词" --site qidian

# 查看全部榜单通道，然后抓取
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --list-channels
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel rank_hot_male --limit 20
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel qidian_yuepiao --page 2
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel kakuyomu_weekly --limit 10

# 扫榜：一次遍历全部分类（番茄新书榜/阅读榜用）
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel rank_new_male --sweep --limit 5
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel rank_new_male --list-categories

# 抓正文
python "<SKILL_DIR>/scripts/fetch_novel.py" fetch "<作品链接>" --first 3
python "<SKILL_DIR>/scripts/fetch_novel.py" fetch "<作品链接>" --range 10-20
python "<SKILL_DIR>/scripts/fetch_novel.py" fetch "<作品链接>" --all

# 查看支持的站点；运行内置自检
python "<SKILL_DIR>/scripts/fetch_novel.py" sites
python "<SKILL_DIR>/scripts/fetch_novel.py" selftest
```

未指定范围时 `fetch` **默认只抓前 3 章**，抓整本必须显式加 `--all`，避免误触发大量请求。

`fetch` 常用参数：

| 参数 | 说明 |
| --- | --- |
| `--all` | 抓整本 |
| `--first N` / `--last N` | 抓最前／最后 N 章 |
| `--range A-B` | 抓指定范围，可省略一端如 `--range 50-` |
| `--limit N` | 配合 `--all` 限制总数 |
| `--delay S` | 每章额外等待秒数（站点限速已内置，一般不用加） |
| `--output DIR` | 覆盖默认输出根目录 |

`rank` 常用参数：`--list-channels` 列出通道、`--channel` 指定通道、`--site` 限定站点、`--category` 分类 id、`--gender 0/1` 男/女频、`--page` 翻页、`--limit` 条数（扫榜时为每类条数）、`--intro` 同时显示简介。

`rank` 另有两个扫榜参数，用于**只提供分类榜、没有全部分类页**的站点（如番茄新书榜）：

| 参数 | 说明 |
| --- | --- |
| `--sweep` | 自动遍历该通道的全部分类并汇总输出 |
| `--merge` | 配合 `--sweep`：把各分类合并成**一张总表**，按热度降序重排，分类列标明每本所属分类 |
| `--list-categories` | 只列出该通道可扫的分类，不抓取 |

**通道名一律带站点前缀**（番茄除外），例如 `qidian_yuepiao`、`ciweimao_yp`、`sfacg_cat_21`、`kakuyomu_weekly`。不清楚有哪些通道时先跑 `rank --list-channels`。

## 工作流程

### 1. 先确认作品与范围

用 `inspect` 拿到书名、作者、章节总数和目录，把书名与章节数报给用户，确认无误再抓取。这一步不下载正文。

### 2. 按需选择抓取范围

- “抓某几章”“先看看开头” → `--first N` 或 `--range A-B`
- “抓整本” → `--all`
- 范围不明确且章节很多时，先抓少量样本确认质量，再决定是否抓整本。

### 3. 抓取并如实汇报

脚本会输出成功／失败章节数与输出目录。**失败章节必须如实报告**，说明原因（付费锁定、需要登录、站点改版等），不要声称整本抓全。

抓完后读一两个文件抽查正文质量，确认没有乱码、广告行或章节错位。

### 4. 选题与对标场景

用户要做选题分析或看市场时：

1. 用 `rank --list-channels` 了解可用榜单，再抓目标榜单（如番茄男频分类热榜、起点月票榜）。
2. 用 `search` 检索同类作品，对比书名、简介、字数与阅读量。
3. 需要深入拆解时，把榜单里选中的作品用 `fetch` 抓下来，再交给 `book-analysis`。

**不要编造榜单数据或成绩**；只报告脚本真实返回的内容。

## 通道机制

脚本按链接自动匹配适配器，优先级从高到低：

1. **专用适配器**：针对特定站点，解析最可靠。
2. **通用回退**：适用于任何 HTTP 小说站，靠启发式规则找目录与正文。

仅提供榜单的适配器（刺猬猫/SF/Kakuyomu）标记为 `supports_content=False`，**不参与正文匹配**。因此这些站点的正文请求会继续落到通用回退上，不会被拦截报错。

### 番茄小说

支持正文抓取、作品详情、13 个榜单通道与关键词搜索。正文有两条通道，网页通道失败时自动降级到 APP 通道：

- **网页通道**：解析页面里的 `__INITIAL_STATE__`，用私用区字体映射表还原正文。只覆盖免费章节。
- **APP 通道**：调用官方阅读接口取全文，能拿到网页锁定章节。请求需签名，正文需 AES 解密。

榜单与搜索接口返回的作者名、简介**同样带字体加密**，脚本会统一解码——直接看原始接口会得到乱码。

字体映射表与签名算法是外站公开研究的成果，随上游改版会失效。脚本的 `crypto.py` 已用 NIST 与国标公开测试向量自检，算法本身是可靠的。

#### 短篇与短故事

番茄短故事与长篇共用 `/page/<作品编号>` 链接格式，**无需额外处理即可抓取**，脚本会自动适配两种形态：

- **单章短篇**：目录只有 1 章，正文含 `导语：` 段落，整篇一次抓完。
- **多章短篇集**：目录为若干独立短篇（每篇自成一章），按普通章节逐篇抓取。

两处平台差异脚本已自动处理，不需人工干预：

1. 短篇的 `abstract` 字段常被平台填成书名占位，真正的简介在 `description`，脚本会自动改用后者。
2. 短故事**没有独立的榜单接口**，用 `search` 检索短篇选题即可（如 `search "短篇"`）。

抓短篇推荐直接用 `--all`（目录本来就短），例如：

```bash
python "<SKILL_DIR>/scripts/fetch_novel.py" fetch "<短篇链接>" --all
```

#### 榜单分三类，别混用

番茄的榜单按「作品体量」分三类，用途完全不同。做选题时要选对，否则会把成熟作品当成新书参考：

| 榜单 | 通道 | 入选条件 | 适合看什么 |
| --- | --- | --- | --- |
| 分类热榜 | `rank_hot_male` / `rank_hot_female` | 各分类在读热度 | 当前什么题材在爆 |
| **新书榜** | `rank_new_male` / `rank_new_female` | 30 万字**以下**、已签约、未断更 | **新人怎么切入、新书都在写什么** |
| 阅读榜 | `rank_read_male` / `rank_read_female` | 30 万字**以上**、已签约、已推荐 | 长线成熟作品的写法 |
| **巅峰榜** | `rank_peak` | 全平台综合分（好评+人气+互动） | **平台当下最被认可的一批书** |

> 实测对照：同一分类（西方奇幻）下，新书榜首条是 14 万字的《被压抑的病娇精灵妻子复活了》，阅读榜首条是 59 万字的《人在诡异，靠第四天灾登顶至高》——两个榜单内容完全不同，不能互相替代。

**巅峰榜是整体榜**：全平台统一、**不分男女频**（实测 30 条里都市高武/悬疑脑洞/青春甜宠/古风世情混排），每月更新一次，约 30 条，不分分类：

```bash
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel rank_peak --limit 30
```

> 说明：巅峰榜网页首页有对应板块（JS 里标题即「番茄巅峰榜」），但首页 SSR 的 `topRankList` 为 `null`，是客户端异步加载，抓首页取不到。这里按公开客户端 [fanqie-novel-reader](https://github.com/denniemok/fanqie-novel-reader) 的做法，走它的公开接口 `api.fanqietc.com/rank?board=peak`（token 打包在其前端 JS 中）。**该来源为第三方服务，非本项目可控**；若失效，脚本会明确报错说明原因，不影响其他通道。

#### 新书榜／阅读榜：默认汇总全部，也可单看某分类

平台的新书榜/阅读榜页面本身是**按分类**的（官方名称「分类排行榜」），没有「全部分类」页。
脚本把 19/18 个分类自动汇总，所以两种用法都支持：

```bash
# 默认：汇总全部分类，按在读降序（男频 190 条 / 女频 180 条）
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel rank_new_male --limit 10

# 只看某个分类（保留页面原始排名顺序）
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel rank_new_male --category 124

# 女频新书榜
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel rank_new_female --category 79
```

**男频分类 id**（19 个）：

| id | 分类 | id | 分类 | id | 分类 |
| --- | --- | --- | --- | --- | --- |
| 1141 | 西方奇幻 | 1140 | 东方仙侠 | 8 | 科幻末世 |
| 261 | 都市日常 | 124 | 都市修真 | 1014 | 都市高武 |
| 273 | 历史古代 | 27 | 战神赘婿 | 263 | 都市种田 |
| 258 | 传统玄幻 | 272 | 历史脑洞 | 539 | 悬疑脑洞 |
| 262 | 都市脑洞 | 257 | 玄幻脑洞 | 751 | 悬疑灵异 |
| 504 | 抗战谍战 | 746 | 游戏体育 | 718 | 动漫衍生 |
| 1016 | 男频衍生 | | | | |

**女频分类 id**（18 个）：

| id | 分类 | id | 分类 | id | 分类 |
| --- | --- | --- | --- | --- | --- |
| 1139 | 古风世情 | 8 | 科幻末世 | 746 | 游戏体育 |
| 1015 | 女频衍生 | 248 | 玄幻言情 | 23 | 种田 |
| 79 | 年代 | 267 | 现言脑洞 | 246 | 宫斗宅斗 |
| 539 | 悬疑脑洞 | 253 | 古言脑洞 | 24 | 快穿 |
| 749 | 青春甜宠 | 745 | 星光璀璨 | 747 | 女频悬疑 |
| 750 | 职场婚恋 | 748 | 豪门总裁 | 1017 | 民国言情 |

**跨分类扫榜**：平台没有「全部分类」页，但脚本有两种方式一次看全：

```bash
# 方式一（推荐）：不带 --category，自动汇总全部分类，按在读降序排成一张总榜
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel rank_new_male --limit 20

# 方式二：--sweep 保留分类分段，逐类罗列（方便对比各赛道）
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel rank_new_male --sweep --limit 5

# 只看某个分类（保留页面原始排名顺序）
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel rank_new_male --category 1141 --limit 10

# 不确定有哪些分类时，先列出来
python "<SKILL_DIR>/scripts/fetch_novel.py" rank --channel rank_new_male --list-categories
```

三种用法对同一批数据，区别只在**汇总方式**：

| 用法 | 输出 | 排序 |
| --- | --- | --- |
| 不带 `--category` | 全部分类合并成一张总榜（男频 190 条 / 女频 180 条） | 按在读量降序 |
| `--sweep` | 按分类分段罗列 | 每类内部沿用页面排名 |
| `--category <id>` | 只取该分类 | 页面原始排名 |

`--sweep` 时 `--limit` 是**每个分类**取几条；不带 `--category` 时 `--limit` 是**汇总后**取几条。做选题时用 `--sweep --limit 3~5` 看各赛道头部，用不带 `--category` 的 `--limit 20` 看整体头部。

四类榜单（新书榜/阅读榜 男女频）都默认汇总全部分类。新书榜与阅读榜每屏 10 条；热榜每页 20 条。

榜单接口返回的书名、作者、简介都带**字体加密**，脚本会统一解码。

### 起点中文网

起点主站（www.qidian.com）对目录页做了防爬，直接抓只返回 202 空壳，通用回退无法解析。脚本改走移动站与小程序接口：

- **作品详情与目录**：`wxapp.qidian.com/api/book/*`
- **章节正文**：`m.qidian.com/chapter/...` 页面中的 `vite-plugin-ssr_pageContext` JSON，**正文明文，无需解密**
- **搜索**：`m.qidian.com/so/<关键词>.html`
- **榜单**：`m.qidian.com/webcommon/rank/*`，需要先取 `_csrfToken`（脚本自动处理）

两点实测结论：

1. 起点的目录字段 `sS`：**值为 1 表示免费，非 1 表示 VIP**（容易看反，脚本按实测结果处理）。
2. VIP/收费章节只返回极短提示；脚本会**报失败而不是保存半截正文**，不绕过付费限制。

### 其他榜单站点

刺猬猫、SF 轻小说、Kakuyomu 只提供榜单能力（上游没有统一的正文接口，或需各自专用解析）：

- **刺猬猫**：解析 `/rank-index/<slug>` 页面的 `li[data-book-id]`。
- **SF 轻小说**：调用官方 API，请求头需要 `SFSecurity` 签名（MD5 拼接，脚本已实现）。
- **Kakuyomu**：解析排行页 `__NEXT_DATA__` 里的 Apollo state，`Work:` 键的**插入顺序即排名顺序**。

### 通用回退

按以下顺序尝试：

1. 优先读 `og:novel:*` 等 meta 标签取书名、作者、简介；并清理「最新章节(作者)…无弹窗全文阅读-站点名」这类标题噪声。
2. 在多个候选容器里**打分**挑出真正的目录：从第 1 章开始、序号连续、规模大的得分高。
3. 自动识别倒序目录（最新章节在前）并还原为升序。
4. 正文按常见容器选择器 + 段落密度打分提取。
5. 识别正文被 Base64 藏进脚本的站点（`document.writeln(qsbs.bb('...'))` 这类）并解码。
6. 清除“上一章／下一章／推荐票”等导航行和句间推广语。

## 新增站点支持

在 `<SKILL_DIR>/scripts/novel_fetch/adapters/` 下新增适配器：

1. 继承 `SiteAdapter`，实现 `fetch_book()` 与 `fetch_chapter()`。
2. 设置 `domains` 与 `priority`（数值越小越优先）。
3. 需要榜单/搜索时，声明 `channels` 元组并实现 `fetch_rank()` / `search()`，同时设 `supports_search = True`。
4. **只做榜单、不做正文的适配器**，必须设 `supports_content = False`，否则会拦截该域名的正文请求、破坏通用回退。
5. 通道 key 加站点前缀（如 `mysite_hot`），避免与其他站点同名通道冲突。
6. 在 `adapters/__init__.py` 的 `ADAPTERS` 里注册。

写适配器前先抓一份真实页面或接口返回确认结构：正文是明文、在脚本变量里、还是加密的。**先验证再写代码**，不要凭猜测选择器。

## 排错

| 现象 | 处理 |
| --- | --- |
| 提示“未能解析出章节目录” | 确认给的是作品目录页而非首页或章节页；起点/番茄有自己的适配器，其他站结构特殊时需专用适配器 |
| 提示“未能提取章节正文” | 该页可能由脚本渲染、需登录、正文在图片中，或触发了验证码拦截（如刺猬猫）；用 `inspect` 确认目录后抽查单章 |
| 提示“未知的榜单通道” | 先跑 `rank --list-channels` 看可用通道名；注意通道名带站点前缀 |
| 提示“VIP/收费章节” | 属预期结果，如实报告，不要尝试绕过 |
| 搜索无结果 | 换更短的关键词；确认该站点适配器声明了搜索能力 |
| 短篇简介显示成书名 | 已自动处理；若仍异常，说明平台改了字段，按 `description` 排查 |
| 提示“拒绝访问非公网地址” | 脚本只允许公网地址，内网与云元数据地址被主动拒绝 |
| 大量章节失败且集中在后半段 | 通常是付费／会员章节，属预期结果，如实报告 |
| 抓取速度异常慢 | 站点限速在生效；可减少抓取范围，不要盲目加并发 |
| 看到的书名或简介是乱码方块 | 该站点文本有字体加密且未解码，报告给维护者补映射表 |
