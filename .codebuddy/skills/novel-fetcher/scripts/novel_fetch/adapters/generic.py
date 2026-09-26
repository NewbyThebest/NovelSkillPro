# -*- coding: utf-8 -*-
"""通用网页适配器：用启发式规则抓任意小说站。

这是不针对特定站点的回退方案，思路参考 QingJuan 的 generic_web / scraper：
先按常见容器选择器找目录，再用模板选择器 + 内容密度打分找正文。

对结构规范的站点通常够用；结构特殊的站点应新增专用适配器。
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..htmlparse import Node, extract_text, parse_html
from .base import BookInfo, ChapterContent, ChapterRef, SiteAdapter

__all__ = ["GenericAdapter"]

# 目录容器候选（覆盖常见小说站结构）
TOC_SELECTORS = (
    "#list a[href]",
    ".listmain a[href]",
    "#chapter-list a[href]",
    ".chapter-list a[href]",
    ".chapterlist a[href]",
    ".episode-list a[href]",
    ".episodes a[href]",
    ".toc a[href]",
    ".table-of-contents a[href]",
    "[id*='chapter'] a[href]",
    "[class*='chapter'] a[href]",
    "[id*='list'] a[href]",
    "[class*='list'] a[href]",
    "[class*='section'] a[href]",
    ".row-section a[href]",
    "dl dd a[href]",
    ".volume a[href]",
)

# 正文容器候选
CONTENT_SELECTORS = (
    "#content",
    "#chaptercontent",
    "#chapter-content",
    ".content",
    ".chapter-content",
    ".chapterContent",
    ".read-content",
    ".reading-content",
    ".article-content",
    ".txt",
    "#booktext",
    ".text",
    ".showtxt",
    "article",
)

# 目录链接文本特征
CHAPTER_TEXT_RE = re.compile(r"(第\s*[0-9一二三四五六七八九十百千万零两]+\s*[章节话回卷篇]|chapter|episode|^\s*\d+[\.、])", re.I)
# 噪声行
NOISE_RE = re.compile(
    r"^(上一[章页]|下一[章页]|返回目录|目\s*录|加[入书]书架|投推荐票|"
    r"本站.*|手机用户请|最新网址|章节错误|内容加载失败|请记住本站|"
    r"天才一秒记住|广告|點擊|点击这里|『加入书签|$\s*$)", re.I
)
# 正文里插入的推广语（常出现在段落之间）
AD_LINE_RE = re.compile(
    r"(看最新章节内容|星文阅读|请收藏本站|最新网址|"
    r"本章未完|点击下一页|加入书签|推荐票|手机版阅读网址|"
    r"笔趣阁|记住本站域名|一秒记住|全文免费阅读)", re.I
)
# 正文起始标记（这些行之后才是正文）
CONTENT_START_RE = re.compile(r"(正文|内容开始|start)", re.I)


def _b64_to_html(encoded: str) -> str:
    """把 Base64 还原成文本，并校验看起来像 HTML 正文。"""
    import base64
    import binascii
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return ""
    for enc in ("utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if "<" in text or len(text) > 20:
            return text
    return ""


def extract_html_fragment(html_text: str) -> str:
    """把 HTML 片段转成正文文本（保留段落）。"""
    from ..htmlparse import html_to_text
    return html_to_text(html_text)


class GenericAdapter(SiteAdapter):
    name = "generic"
    domains = ()
    priority = 1000   # 最低优先级，始终兜底

    def matches(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)

    # -- 作品与目录 -------------------------------------------------------
    def fetch_book(self, url: str, client) -> BookInfo:  # noqa: ANN001
        resp = client.get(url)
        doc = parse_html(resp.text)
        final_url = resp.url

        title = self._extract_meta(doc, (
            "og:novel:book_name", "og:title", "book_name",
        ), css=("h1", ".book-name", "#info h1"))
        title = self._clean_book_title(title)
        author = self._extract_meta(doc, (
            "og:novel:author", "author",
        ), css=(".author", "#info p", ".bookinfo .author"))
        synopsis = self._extract_meta(doc, (
            "og:novel:description", "og:description", "description",
        ), css=("#intro", ".intro", ".book-intro", ".summary"))
        cover = self._extract_cover(doc, final_url)
        chapters = self._collect_chapters(doc, final_url)
        if not chapters:
            raise ValueError(
                "未能从该页面解析出章节目录。请确认链接是作品目录页；"
                "若站点结构特殊，需要为该站点编写专用适配器。"
            )
        return BookInfo(
            title=title or self._title_from_url(final_url),
            source_url=final_url,
            site=urlparse(final_url).hostname or "",
            author=author,
            synopsis=synopsis,
            cover=cover,
            chapters=chapters,
        )

    def _extract_meta(self, doc: Node, props: tuple[str, ...],
                      css: tuple[str, ...] = ()) -> str:
        wanted = {p.lower() for p in props}
        # 1. meta 标签（og:novel:* 等最可靠）
        for m in doc.select("meta"):
            key = (m.get("property") or m.get("name") or "").lower()
            if key in wanted:
                content = (m.get("content") or "").strip()
                if content and not self._is_junk(content):
                    return self._clean_meta(content)
        # 2. 指定选择器
        for sel in css:
            found = doc.select(sel)
            if found:
                text = found[0].all_text().strip()
                if text and not self._is_junk(text):
                    return self._clean_meta(text)
        # 3. <title> 兜底（只取书名部分）
        if any("title" in p for p in props):
            t = doc.select("title")
            if t:
                raw = t[0].all_text().strip()
                if raw:
                    for sep in ("_", "-", "|", "—", "－"):
                        if sep in raw:
                            head = raw.split(sep)[0].strip()
                            if len(head) >= 2:
                                return self._clean_meta(head)
                    return self._clean_meta(raw)
        return ""

    @staticmethod
    def _is_junk(value: str) -> bool:
        """过滤站点名、导航词等无效元信息。"""
        stripped = value.strip()
        if len(stripped) < 2:
            return True
        junk_exact = {
            "新笔趣阁", "笔趣阁", "首页", "网站地图", "书架", "排行榜",
            "小说", "全文阅读", "最新章节",
        }
        return stripped in junk_exact

    @staticmethod
    def _clean_meta(value: str) -> str:
        value = re.sub(r"\s+", " ", value).strip()
        return value[:2000]

    @staticmethod
    def _clean_book_title(value: str) -> str:
        """清理站点在标题里附加的噪声。

        形如「书名最新章节(作者),书名无弹窗全文阅读-站点名」或「书名_站点名」。
        """
        title = re.sub(r"\s+", " ", value or "").strip()
        if not title:
            return ""
        # 去掉“最新章节(...)”及其后面的重复内容
        title = re.split(r"最新章节", title)[0].strip()
        # 去掉“无弹窗全文阅读”等套话及其后缀
        title = re.split(r"无弹窗|全文阅读|免费阅读|最新章节列表", title)[0].strip()
        # 站点名后缀
        for sep in ("_", "-", "|", "－", "—"):
            if sep in title:
                head = title.split(sep)[0].strip()
                # 仅当切分后仍是较完整的标题时才采用，避免误切书名里的连字符
                if len(head) >= 2:
                    title = head
                    break
        return title.strip()

    def _extract_cover(self, doc: Node, base: str) -> str:
        for m in doc.select("meta"):
            key = (m.get("property") or m.get("name") or "").lower()
            if key in {"og:image", "twitter:image"}:
                src = m.get("content", "").strip()
                if src:
                    return urljoin(base, src)
        for img in doc.select("#fmimg img, .book-cover img, .cover img, #sidebar img"):
            src = img.get("src") or img.get("data-src")
            if src:
                return urljoin(base, src)
        return ""

    def _collect_chapters(self, doc: Node, base: str) -> list[ChapterRef]:
        # 收集候选：各选择器命中 + 所有含足量章节链接的容器
        candidates: list[list[Node]] = []
        for selector in TOC_SELECTORS:
            found = [a for a in doc.select(selector)
                     if CHAPTER_TEXT_RE.search(a.all_text())]
            if len(found) >= 3:
                candidates.append(found)
        for container in doc.select("ul, div, dl"):
            links = [a for a in container.select("a[href]")
                     if CHAPTER_TEXT_RE.search(a.all_text())]
            if len(links) >= 8:
                candidates.append(links)
        if not candidates:
            return []

        # 同一组链接可能被多个选择器命中，按 URL 序列去重
        unique: list[list[Node]] = []
        seen_keys: set[tuple] = set()
        for group in candidates:
            key = tuple(a.get("href") for a in group[:5]) + (len(group),)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique.append(group)

        best = max(unique, key=self._score_group)

        chapters: list[ChapterRef] = []
        seen_urls: set[str] = set()
        for a in best:
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            full = urljoin(base, href)
            text = re.sub(r"\s+", " ", a.all_text()).strip()
            if not text or len(text) > 200:
                continue
            if full in seen_urls:
                continue
            seen_urls.add(full)
            chapters.append(ChapterRef(title=text, url=full, index=len(chapters) + 1))

        chapters = self._order_chapters(chapters)
        for i, chapter in enumerate(chapters, start=1):
            chapter.index = i
        return chapters

    def _score_group(self, group: list[Node]) -> float:
        """给目录候选打分：优先从第 1 章开始、序号连续、规模大的。"""
        numbers = [self._chapter_number(a.all_text().strip()) for a in group]
        known = [n for n in numbers if n is not None]
        score = float(len(group))
        if known:
            # 从第 1 章（或很靠前）开始是完整目录的强信号
            first = known[0]
            if first <= 5:
                score += 500
            elif first <= 20:
                score += 120
            else:
                score -= 80
            # 升序优于倒序（倒序会在此扣分，排序阶段可还原，但升序更可能是完整目录）
            ascending = sum(1 for i in range(len(known) - 1) if known[i] < known[i + 1])
            score += ascending * 3
            # 覆盖范围越大越好
            score += (max(known) - min(known)) * 0.5
        return score

    @staticmethod
    def _chapter_number(title: str) -> int | None:
        """从标题里取章节序号，用于判断目录是否倒序。"""
        m = re.search(r"第\s*([0-9]+)\s*[章节话回卷篇]", title)
        if m:
            return int(m.group(1))
        m = re.search(r"^\s*([0-9]+)[\.、]", title)
        if m:
            return int(m.group(1))
        return None

    def _order_chapters(self, chapters: list[ChapterRef]) -> list[ChapterRef]:
        """目录可能是倒序（最新章节在前），按序号还原为升序。"""
        numbers = [self._chapter_number(c.title) for c in chapters]
        known = [n for n in numbers if n is not None]
        if len(known) < max(3, len(chapters) // 2):
            return chapters
        # 前几个序号持续递减，判定为倒序
        head = [n for n in numbers[:5] if n is not None]
        if len(head) >= 3 and all(head[i] > head[i + 1] for i in range(len(head) - 1)):
            return list(reversed(chapters))
        return chapters

    @staticmethod
    def _title_from_url(url: str) -> str:
        path = urlparse(url).path.rstrip("/")
        return path.rsplit("/", 1)[-1] or "未命名作品"

    # -- 正文 -------------------------------------------------------------
    def fetch_chapter(self, book: BookInfo, chapter: ChapterRef, client) -> ChapterContent:  # noqa: ANN001
        resp = client.get(chapter.url, policy=self._chapter_policy())
        raw_html = resp.text
        doc = parse_html(raw_html)

        # 先处理正文被 Base64 藏进脚本的常见混淆
        decoded = self._decode_obfuscated(raw_html)
        if decoded and len(decoded) > 200:
            text = self._clean_text(extract_html_fragment(decoded))
            if text:
                return ChapterContent(
                    title=chapter.title, text=text, url=resp.url,
                    index=chapter.index, source="web-base64", word_count=len(text),
                )

        text = self._extract_content(doc, resp.url)
        if not text or len(text.strip()) < 50:
            by_density = self._extract_by_density(doc)
            if len(by_density) > len(text):
                text = by_density
        if not text:
            raise ValueError(
                f"未能提取章节正文：{chapter.title}。"
                "该页面可能由脚本渲染、需要登录，或正文在图片中。"
            )
        text = self._clean_text(text)
        return ChapterContent(
            title=chapter.title,
            text=text,
            url=resp.url,
            index=chapter.index,
            source="web",
            word_count=len(text),
        )

    @staticmethod
    def _decode_obfuscated(raw_html: str) -> str:
        """解出正文被 Base64 藏在脚本里的站点。

        常见形态：document.writeln(qsbs.bb('PHA+...')); 或 直接 base64 字符串数组。
        返回拼好的 HTML 片段；若未识别到则返回空串。
        """
        chunks: list[str] = []
        # 形式一：xxx.bb('base64') / xxx.bb("base64")
        for m in re.finditer(r"\.\w+\s*\(\s*['\"]([A-Za-z0-9+/=]{40,})['\"]\s*\)", raw_html):
            text = _b64_to_html(m.group(1))
            if text:
                chunks.append(text)
        if chunks:
            return "".join(chunks)

        # 形式二：脚本里一个大 base64 串
        for m in re.finditer(r"['\"]([A-Za-z0-9+/=]{200,})['\"]", raw_html):
            text = _b64_to_html(m.group(1))
            if text and ("<" in text):
                chunks.append(text)
        return "".join(chunks)

    @staticmethod
    def _chapter_policy():
        from ..http import FetchPolicy
        return FetchPolicy()

    def _extract_content(self, doc: Node, base: str) -> str:
        """按候选选择器找正文，取文本最长的一个。"""
        best = ""
        for selector in CONTENT_SELECTORS:
            for node in doc.select(selector):
                text = extract_text(node)
                if len(text) > len(best):
                    best = text
        # 有些站点正文在 meta 或特定 name 容器里
        for name in ("content", "chaptercontent", "booktext"):
            for node in doc.select(f"[name='{name}']"):
                text = extract_text(node)
                if len(text) > len(best):
                    best = text
        return best

    def _extract_by_density(self, doc: Node) -> str:
        """按段落密度找正文容器：块级子节点多且文本长的节点。"""
        best_score = 0.0
        best_text = ""
        body = doc.select("body")
        roots = body if body else [doc]
        candidates = []
        for root in roots:
            for node in root.iter():
                if node.tag in {"script", "style", "head", "#document"}:
                    continue
                candidates.append(node)
        for node in candidates:
            # 统计直接文本与 <p>/<br> 密度
            text = extract_text(node)
            if len(text) < 200:
                continue
            p_count = len(node.select("p"))
            br_count = len([c for c in node.iter() if c.tag == "br"])
            link_text = sum(len(a.all_text()) for a in node.select("a"))
            # 正文特征：段落多、链接占比低
            score = len(text) + p_count * 80 + br_count * 30 - link_text * 2.5
            if score > best_score:
                best_score = score
                best_text = text
        return best_text

    def _clean_text(self, text: str) -> str:
        lines = []
        for raw in text.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if NOISE_RE.match(line):
                continue
            # 推广行只在较短时剔除，避免误删包含这些词的正常正文
            if len(line) < 60 and AD_LINE_RE.search(line):
                continue
            lines.append(line)
        # 去掉连续重复行
        deduped: list[str] = []
        for line in lines:
            if deduped and line == deduped[-1]:
                continue
            deduped.append(line)
        return "\n\n".join(deduped)
