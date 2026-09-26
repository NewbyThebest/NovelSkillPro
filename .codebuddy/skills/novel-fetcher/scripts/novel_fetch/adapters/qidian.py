# -*- coding: utf-8 -*-
"""起点中文网适配器。

起点主站（www.qidian.com）对目录页做了防爬，直接抓只返回 202 空壳。
因此走移动站与小程序接口，正文为明文，无需解密：

- 作品详情/目录：wxapp.qidian.com/api/book/info 与 /api/book/categoryV2
- 章节正文：m.qidian.com/chapter/<bookId>/<chapterId>/ 页面中的
  `<script id="vite-plugin-ssr_pageContext">` JSON
- 搜索：m.qidian.com/so/<关键词>.html 的同一份 pageContext
- 榜单：m.qidian.com/webcommon/rank/<类型>list，需要先取 _csrfToken

VIP 章节可能不返回完整正文，脚本如实报失败，不绕过付费限制。
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..channels import KIND_RANK, Channel, RankItem, RankResult
from ..htmlparse import html_to_text
from .base import BookInfo, ChapterContent, ChapterRef, SiteAdapter

__all__ = ["QidianAdapter"]

WEB = "https://www.qidian.com"
MOBILE = "https://m.qidian.com"
WXAPP = "https://wxapp.qidian.com"

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)

BOOK_ID_RE = re.compile(r"/(?:book|info)/(\d+)")
CHAPTER_ID_RE = re.compile(r"/chapter/(\d+)/(\d+)")
_PAGE_CONTEXT_RE = re.compile(
    r'<script\s+id="vite-plugin-ssr_pageContext"[^>]*>(.*?)</script>', re.DOTALL
)

# 榜单：(key, 中文名, page_type, group, gender)
# key 统一加 qidian_ 前缀，避免与其他站点同名通道冲突
_RANKS = (
    ("qidian_yuepiao", "月票榜", "yuepiao", "男频", "male"),
    ("qidian_hotsales", "热销榜", "hotsales", "男频", "male"),
    ("qidian_rec", "推荐榜", "rec", "男频", "male"),
    ("qidian_update", "更新榜", "update", "男频", "male"),
    ("qidian_newbook", "新书榜", "newbook", "男频", "male"),
    ("qidian_sign", "签约榜", "sign", "男频", "male"),
    ("qidian_readindex", "阅读指数榜", "readindex", "男频", "male"),
    ("qidian_newfans", "新增粉丝榜", "newfans", "男频", "male"),
    ("qidian_newauthor", "新人作者榜", "newauthor", "男频", "male"),
    ("qidian_yuepiao_female", "女频月票榜", "yuepiao", "女频", "female"),
    ("qidian_collect_female", "女频收藏榜", "collect", "女频", "female"),
    ("qidian_free_female", "女频免费榜", "free", "女频", "female"),
)
# 部分榜单接口路径与 page_type 不同名
_CGI_ALIAS = {"hotsales": "hotsales", "rec": "rec", "update": "update"}


class QidianAdapter(SiteAdapter):
    name = "qidian"
    domains = ("qidian.com",)
    priority = 20
    supports_search = True
    channels = tuple(
        Channel(
            key, name, KIND_RANK, group,
            f"起点{name}（m.qidian.com/rank/{page_type}/）；可用 --page 翻页",
            pageable=True,
            params={"page_type": page_type, "gender": gender},
        )
        for key, name, page_type, group, gender in _RANKS
    )

    def __init__(self) -> None:
        self._csrf_token = ""

    # -- URL 归一化 -------------------------------------------------------
    @staticmethod
    def normalize_book_url(url: str) -> str:
        match = BOOK_ID_RE.search(url)
        if match:
            return f"{WEB}/book/{match.group(1)}/"
        raise ValueError(
            "无法从链接中识别起点作品编号。请使用作品页链接"
            "（形如 https://www.qidian.com/book/<作品编号>/）。"
        )

    # -- 请求头 -----------------------------------------------------------
    @staticmethod
    def _wx_headers() -> dict[str, str]:
        return {
            "User-Agent": DESKTOP_UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://wxapp.qidian.com/",
        }

    @staticmethod
    def _mobile_headers(referer: str = "https://m.qidian.com/") -> dict[str, str]:
        return {
            "User-Agent": MOBILE_UA,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Referer": referer,
        }

    @staticmethod
    def _policy(headers: dict[str, str], timeout: float = 25.0):
        from ..http import FetchPolicy
        return FetchPolicy(headers=headers, timeout=timeout)

    # -- 作品与目录 -------------------------------------------------------
    def fetch_book(self, url: str, client) -> BookInfo:  # noqa: ANN001
        book_url = self.normalize_book_url(url)
        match = BOOK_ID_RE.search(book_url)
        book_id = match.group(1) if match else ""

        info = self._book_info(client, book_id)
        if not info:
            raise ValueError("起点作品信息接口未返回数据，作品可能不存在或已下架。")

        chapters = self._catalog(client, book_id)
        if not chapters:
            raise ValueError("起点目录接口未返回章节，作品可能已下架或需要登录。")

        status = "已完结" if info.get("finish") else "连载中"
        return BookInfo(
            title=str(info.get("bookName") or "").strip(),
            source_url=book_url,
            site="qidian.com",
            author=str(info.get("authorName") or "").strip(),
            synopsis=html_to_text(str(info.get("desc") or "")).strip(),
            book_id=book_id,
            category=str(info.get("chanName") or "").strip(),
            status=status,
            word_count=str(info.get("showWordsCnt") or "").strip(),
            last_chapter=str(info.get("updChapterName") or "").strip(),
            chapters=chapters,
            extra={"book_id": book_id, "chapter_ids": [c.url.rsplit("/", 2)[-2] for c in chapters]},
        )

    def _book_info(self, client, book_id: str) -> dict:  # noqa: ANN001
        resp = client.get(
            f"{WXAPP}/api/book/info?bookId={book_id}",
            policy=self._policy(self._wx_headers()),
        )
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        info = data.get("bookInfo") if isinstance(data, dict) else None
        return info if isinstance(info, dict) else {}

    def _catalog(self, client, book_id: str) -> list[ChapterRef]:
        resp = client.get(
            f"{WXAPP}/api/book/categoryV2?bookId={book_id}",
            policy=self._policy(self._wx_headers()),
        )
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        volumes = data.get("vs") if isinstance(data, dict) else None
        if not isinstance(volumes, list):
            return []

        chapters: list[ChapterRef] = []
        seen: set[str] = set()
        for volume in volumes:
            if not isinstance(volume, dict):
                continue
            for chapter in volume.get("cs") or []:
                if not isinstance(chapter, dict):
                    continue
                chapter_id = str(chapter.get("id") or "").strip()
                title = str(chapter.get("cN") or "").strip()
                if not chapter_id.isdigit() or chapter_id in seen:
                    continue
                seen.add(chapter_id)
                chapters.append(ChapterRef(
                    title=title or f"第{len(chapters) + 1}章",
                    url=f"{MOBILE}/chapter/{book_id}/{chapter_id}/",
                    index=len(chapters) + 1,
                    # 起点 sS 字段：1 表示免费，非 1 表示 VIP/收费（实测确认）
                    locked=chapter.get("sS") != 1,
                ))
        return chapters

    # -- 章节正文 ---------------------------------------------------------
    def fetch_chapter(self, book: BookInfo, chapter: ChapterRef, client) -> ChapterContent:  # noqa: ANN001
        resp = client.get(
            chapter.url, policy=self._policy(self._mobile_headers(), timeout=25.0)
        )
        context = self._page_context(resp.text)
        if context is None:
            raise ValueError(
                "起点章节页缺少 pageContext 数据，页面结构可能已改版。"
            )
        try:
            info = context["pageProps"]["pageData"]["chapterInfo"]
        except (KeyError, TypeError):
            raise ValueError("起点章节页未包含正文数据（可能已下架或需登录）。") from None
        if not isinstance(info, dict):
            raise ValueError("起点章节正文结构异常。")

        if info.get("fkp"):
            raise ValueError("该章节使用起点加密正文格式，当前解析器不支持。")

        raw_content = str(info.get("content") or "")
        text = self._content_to_text(raw_content).strip()
        if not text or self._looks_like_paywall(text):
            # VIP/收费章节通常只返回极短提示，不绕过付费限制
            if chapter.locked or info.get("vipStatus"):
                raise ValueError("该章节为 VIP/收费章节，未返回完整正文（不绕过付费限制）。")
            raise ValueError("起点章节未返回可用正文。")
        # 正文过短且不是正常短章时，视为被截断
        if len(text) < 200 and chapter.locked:
            raise ValueError("该章节正文疑似被截断（VIP/收费章节），未保存不完整内容。")

        title = str(info.get("chapterName") or chapter.title).strip()
        return ChapterContent(
            title=title,
            text=text,
            url=resp.url,
            index=chapter.index,
            source="qidian_mobile",
            word_count=len(text),
        )

    # -- 榜单 -------------------------------------------------------------
    def fetch_rank(
        self,
        channel: Channel,
        client,  # noqa: ANN001
        *,
        page: int = 1,
        limit: int = 20,
        options: dict | None = None,
    ) -> RankResult:
        opts = dict(channel.params)
        if options:
            opts.update({k: v for k, v in options.items() if v not in (None, "")})
        page_type = str(opts.get("page_type") or "yuepiao")
        gender = str(opts.get("gender") or "male")
        cgi = _CGI_ALIAS.get(page_type, page_type)

        rows, is_last = self._rank_rows(client, page_type, cgi, gender, page)
        items = [
            self._rank_item(channel, row, page, offset)
            for offset, row in enumerate(rows[:limit], start=1)
            if isinstance(row, dict)
        ]
        return RankResult(
            channel=channel, items=items, page=page, limit=limit,
            has_more=not is_last,
        )

    def _rank_rows(
        self, client, page_type: str, cgi: str, gender: str, page: int  # noqa: ANN001
    ) -> tuple[list, bool]:
        """取榜单数据。

        多数榜单走 webcommon 接口；个别榜单（如阅读指数榜）接口路径与
        页面名不同，退回到榜单页的 SSR 数据。
        """
        token = self._ensure_csrf(client)
        params = {"gender": gender, "pageNum": page}
        if token:
            params["_csrfToken"] = token
        url = f"{MOBILE}/webcommon/rank/{cgi}list?" + urllib.parse.urlencode(params)

        payload: dict = {}
        try:
            resp = client.get(url, policy=self._policy(self._mobile_headers()))
            payload = resp.json()
        except Exception:
            payload = {}

        if isinstance(payload, dict) and payload.get("code") == 1403:
            token = self._ensure_csrf(client, refresh=True)
            params["_csrfToken"] = token
            try:
                resp = client.get(
                    f"{MOBILE}/webcommon/rank/{cgi}list?" + urllib.parse.urlencode(params),
                    policy=self._policy(self._mobile_headers()),
                )
                payload = resp.json()
            except Exception:
                payload = {}

        code = payload.get("code") if isinstance(payload, dict) else None
        if code in (0, None) and payload:
            body = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            rows = body.get("records") or []
            if isinstance(rows, list) and rows:
                return rows, bool(body.get("isLast"))

        # 回退：榜单页 SSR
        return self._rank_rows_from_page(client, page_type)

    def _rank_rows_from_page(self, client, page_type: str) -> tuple[list, bool]:  # noqa: ANN001
        url = f"{MOBILE}/rank/{page_type}/"
        resp = client.get(url, policy=self._policy(self._mobile_headers()))
        context = self._page_context(resp.text)
        if context is None:
            raise ValueError("起点榜单页缺少 pageContext 数据，页面结构可能已改版。")
        data = context.get("pageProps", {}).get("pageData")
        if not isinstance(data, dict):
            raise ValueError("起点榜单页数据结构异常。")
        rows = data.get("records") or []
        return (rows if isinstance(rows, list) else []), bool(data.get("isLast"))

    def _ensure_csrf(self, client, *, refresh: bool = False) -> str:  # noqa: ANN001
        """起点榜单接口要求回传 _csrfToken，该值由榜单页下发的 Cookie 提供。"""
        if self._csrf_token and not refresh:
            return self._csrf_token
        try:
            client.get(f"{MOBILE}/rank/yuepiao/", policy=self._policy(self._mobile_headers()))
        except Exception:
            return self._csrf_token
        token = client.cookies().get("_csrfToken", "")
        if token:
            self._csrf_token = token
        return self._csrf_token

    def _rank_item(self, channel: Channel, raw: dict, page: int, offset: int) -> RankItem:
        book_id = str(raw.get("bid") or "").strip()
        pos = raw.get("rankNum")
        rank = int(pos) if isinstance(pos, (int, str)) and str(pos).isdigit() else (page - 1) * 20 + offset
        return RankItem(
            title=str(raw.get("bName") or "").strip(),
            rank=rank,
            author=str(raw.get("bAuth") or raw.get("authorName") or "").strip(),
            book_id=book_id,
            url=f"{WEB}/book/{book_id}/" if book_id else "",
            category=str(raw.get("cat") or "").strip(),
            word_count=str(raw.get("cnt") or "").strip(),
            score=str(raw.get("rankCnt") or "").strip(),
            site="qidian.com",
            channel=channel.key,
            channel_name=channel.name,
        )

    # -- 搜索 -------------------------------------------------------------
    def search(self, keyword: str, client, limit: int = 20) -> list[RankItem]:  # noqa: ANN001
        kw = keyword.strip()
        if not kw:
            return []
        url = f"{MOBILE}/so/{urllib.parse.quote(kw, safe='')}.html?pageNum=1&orderBy=0"
        resp = client.get(url, policy=self._policy(self._mobile_headers()))
        context = self._page_context(resp.text)
        if context is None:
            raise ValueError("起点搜索页缺少 pageContext 数据，页面结构可能已改版。")
        try:
            data = context["pageProps"]["pageData"]
        except (KeyError, TypeError):
            raise ValueError("起点搜索页数据格式异常。") from None
        book_info = data.get("bookInfo") if isinstance(data, dict) else None
        records = book_info.get("records") if isinstance(book_info, dict) else None
        if not isinstance(records, list):
            return []

        channel = Channel("search", "搜索结果")
        results: list[RankItem] = []
        for raw in records[:limit]:
            if not isinstance(raw, dict):
                continue
            book_id = str(raw.get("bid") or "").strip()
            title = str(raw.get("bName") or "").strip()
            if not book_id or not title:
                continue
            cover = str(raw.get("imgUrl") or "").strip()
            if cover.startswith("//"):
                cover = "https:" + cover
            results.append(RankItem(
                title=title,
                author=str(raw.get("bAuth") or "").strip(),
                book_id=book_id,
                url=f"{WEB}/book/{book_id}/",
                intro=html_to_text(str(raw.get("desc") or "")).strip(),
                category=str(raw.get("cat") or "").strip(),
                word_count=str(raw.get("cnt") or raw.get("wordCnt") or "").strip(),
                cover=cover,
                site="qidian.com",
                channel=channel.key,
                channel_name=channel.name,
            ))
        return results

    # -- 工具 -------------------------------------------------------------
    @staticmethod
    def _looks_like_paywall(text: str) -> bool:
        """识别 VIP 章节返回的提示文案，避免把它当成正文保存。"""
        if len(text) > 300:
            return False
        markers = ("订阅", "付费", "购买", "VIP", "vip", "会员", "章节内容", "请下载")
        return any(marker in text for marker in markers)

    @staticmethod
    def _content_to_text(markup: str) -> str:
        """起点正文用不闭合的 <p> 分隔段落，需要先补齐再转文本。"""
        normalized = re.sub(r"<p\s*/?>", "\n", markup, flags=re.I)
        normalized = re.sub(r"</p\s*>", "\n", normalized, flags=re.I)
        normalized = re.sub(r"<br\s*/?>", "\n", normalized, flags=re.I)
        text = html_to_text(normalized.replace("\n", "<br>"))
        lines = [line.strip() for line in text.split("\n")]
        return "\n\n".join(line for line in lines if line)

    @staticmethod
    def _page_context(html_text: str) -> dict | None:
        """取出 vite-plugin-ssr_pageContext 的内容。

        脚本里是 {"pageContext": {...}}，这里统一返回内层的 pageContext，
        便于调用方直接访问 pageProps。
        """
        match = _PAGE_CONTEXT_RE.search(html_text)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        inner = data.get("pageContext")
        return inner if isinstance(inner, dict) else data
