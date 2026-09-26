# -*- coding: utf-8 -*-
"""辅助站点适配器：只提供榜单能力，不负责正文抓取。

这些站点的正文解析需要各自的专用实现，本技能暂不覆盖，
但它们的公开榜单可以直接读取，用于跨平台选题与对标。

包含：
- 刺猬猫（ciweimao.com）
- SF 轻小说（sfacg.com）
- Kakuyomu（kakuyomu.jp）
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import uuid

from ..channels import KIND_RECOMMEND, KIND_RANK, Channel, RankItem, RankResult
from ..htmlparse import parse_html
from .base import BookInfo, ChapterRef, SiteAdapter

__all__ = ["CiweimaoRankAdapter", "SfacgRankAdapter", "KakuyomuRankAdapter"]

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class _RankOnlyAdapter(SiteAdapter):
    """只支持榜单的适配器基类。

    supports_content=False 让它不参与作品/正文匹配，
    这样该域名的正文请求会继续由通用网页回退处理。
    """

    supports_search = False
    supports_content = False

    def fetch_book(self, url: str, client) -> BookInfo:  # noqa: ANN001
        raise ValueError(
            f"{self.name} 当前只支持榜单抓取，暂不支持作品正文解析。"
            "如需正文，请为该站点补充专用适配器。"
        )

    def fetch_chapter(self, book: BookInfo, chapter: ChapterRef, client):  # noqa: ANN001
        raise ValueError(f"{self.name} 不支持章节正文抓取。")

    @staticmethod
    def _policy(headers: dict[str, str] | None = None, timeout: float = 25.0):
        from ..http import FetchPolicy
        base = {"User-Agent": DESKTOP_UA, "Accept-Language": "zh-CN,zh;q=0.9"}
        if headers:
            base.update(headers)
        return FetchPolicy(headers=base, timeout=timeout)


# ---------------------------------------------------------------------------
# 刺猬猫
# ---------------------------------------------------------------------------

class CiweimaoRankAdapter(_RankOnlyAdapter):
    name = "ciweimao"
    domains = ("ciweimao.com",)
    priority = 60

    _RANKS = (
        ("ciweimao_yp", "月票榜", "yp"),
        ("ciweimao_yp_new", "新书榜", "yp_new"),
        ("ciweimao_favor", "收藏榜", "favor"),
        ("ciweimao_recommend", "推荐榜", "recommend"),
        ("ciweimao_buy", "订阅榜", "buy"),
        ("ciweimao_tsukkomi", "吐槽榜", "tsukkomi"),
        ("ciweimao_blade", "刀片榜", "blade"),
        ("ciweimao_update", "更新榜", "get-update-most-week"),
    )
    channels = tuple(
        Channel(key, name, KIND_RANK, "刺猬猫",
                f"刺猬猫{name}（/rank-index/{slug}）", pageable=False,
                params={"slug": slug})
        for key, name, slug in _RANKS
    )

    def fetch_rank(self, channel: Channel, client, *, page: int = 1,  # noqa: ANN001
                   limit: int = 20, options: dict | None = None) -> RankResult:
        opts = dict(channel.params)
        if options:
            opts.update({k: v for k, v in options.items() if v not in (None, "")})
        slug = str(opts.get("slug") or "").strip()
        if not slug:
            raise ValueError(f"刺猬猫{channel.name}缺少 slug 参数。")
        url = f"https://www.ciweimao.com/rank-index/{slug}"
        resp = client.get(url, policy=self._policy({"Referer": "https://www.ciweimao.com/"}))
        doc = parse_html(resp.text)

        rows = doc.select("li[data-book-id]")
        items: list[RankItem] = []
        seen: set[str] = set()
        for row in rows:
            link = row.select('a[href*="/book/"]')
            if not link:
                continue
            href = link[0].get("href", "")
            match = re.search(r"/book/(\d+)", href)
            book_id = match.group(1) if match else row.get("data-book-id", "")
            if not book_id or book_id in seen:
                continue
            seen.add(book_id)
            # 书名取最长的一段链接文本（列表里同时有封面和标题两个 a）
            titles = [a.all_text().strip() for a in link if a.all_text().strip()]
            title = max(titles, key=len) if titles else f"作品{book_id}"
            items.append(RankItem(
                title=title,
                rank=len(items) + 1,
                book_id=book_id,
                url=f"https://www.ciweimao.com/book/{book_id}",
                site="ciweimao.com",
                channel=channel.key,
                channel_name=channel.name,
            ))
            if len(items) >= limit:
                break
        return RankResult(channel=channel, items=items, page=page, limit=limit, has_more=False)


# ---------------------------------------------------------------------------
# SF 轻小说
# ---------------------------------------------------------------------------

class SfacgRankAdapter(_RankOnlyAdapter):
    name = "sfacg"
    domains = ("sfacg.com",)
    priority = 60

    API = "https://api.sfacg.com"
    WEB = "https://book.sfacg.com"
    # 逆向自安卓客户端的公开常量
    BASIC_AUTH = "Basic YW5kcm9pZHVzZXI6MWEjJDUxLXl0Njk7KkFjdkBxeHE="
    APP_KEY = "FMLxgOdsfxmN!Dt4"
    APP_VERSION = "4.8.42(android;25)"
    TYPE_NAMES = {
        21: "魔幻", 22: "玄幻", 23: "古风", 24: "科幻",
        25: "校园", 26: "都市", 27: "游戏", 29: "悬疑",
    }

    channels = tuple(
        Channel(f"sfacg_cat_{tid}", f"{name}推荐榜", KIND_RANK, "分类",
                f"SF轻小说分类「{name}」推荐榜（/novels?tid={tid}）；上游不分页",
                pageable=False, params={"tid": tid})
        for tid, name in TYPE_NAMES.items()
    ) + (
        Channel("sfacg_hot", "热门推荐位", KIND_RECOMMEND, "首页推荐位",
                "SF轻小说热门推荐位", pageable=False, params={"push_name": "hotpush"}),
    )

    def __init__(self) -> None:
        self._device_token = str(uuid.uuid4()).upper()

    def _sf_security(self) -> str:
        nonce = str(uuid.uuid4()).upper()
        ts = int(time.time() * 1000)
        device = self._device_token.upper()
        source = f"{nonce}{ts}{device}{self.APP_KEY}"
        sign = hashlib.md5(source.encode("utf-8")).hexdigest().upper()
        return f"nonce={nonce}&timestamp={ts}&devicetoken={device}&sign={sign}"

    def _sf_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.sfacg.api+json;version=1",
            "Accept-Charset": "UTF-8",
            "Authorization": self.BASIC_AUTH,
            "User-Agent": f"boluobao/{self.APP_VERSION}/HomePage/{self._device_token.lower()}",
            "SFSecurity": self._sf_security(),
        }

    def fetch_rank(self, channel: Channel, client, *, page: int = 1,  # noqa: ANN001
                   limit: int = 20, options: dict | None = None) -> RankResult:
        opts = dict(channel.params)
        if options:
            opts.update({k: v for k, v in options.items() if v not in (None, "")})

        if channel.key.startswith("sfacg_cat_"):
            return self._category_rank(channel, client, opts, limit)
        if channel.key == "sfacg_hot":
            return self._hot_push(channel, client, limit)
        raise ValueError(f"SF轻小说未实现的通道：{channel.key}")

    def _data(self, client, path: str, params: dict, what: str):  # noqa: ANN001
        url = f"{self.API}{path}?" + urllib.parse.urlencode(params)
        resp = client.get(url, policy=self._policy(self._sf_headers()))
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError(f"SF轻小说{what}返回结构异常。")
        status = payload.get("status") or {}
        code = status.get("httpCode")
        if code not in (200, None):
            raise ValueError(f"SF轻小说{what}失败：httpCode={code}")
        return payload.get("data")

    def _category_rank(self, channel: Channel, client, opts: dict, limit: int) -> RankResult:  # noqa: ANN001
        rows = self._data(client, "/novels", {
            "page": 0, "size": limit, "tid": str(opts.get("tid") or ""),
            "categoryId": 0, "filter": "recom",
            "expand": "discount,discountExpireDate,typeName,intro",
        }, channel.name)
        rows = rows if isinstance(rows, list) else []
        items = [
            self._sf_item(channel, row, idx)
            for idx, row in enumerate(rows[:limit], start=1)
            if isinstance(row, dict)
        ]
        return RankResult(channel=channel, items=items, limit=limit, has_more=False)

    def _hot_push(self, channel: Channel, client, limit: int) -> RankResult:
        data = self._data(client, "/novels/specialpushs",
                          {"pushNames": "hotpush"}, channel.name)
        rows = []
        if isinstance(data, dict):
            rows = data.get("hotpush") or data.get("hotPush") or []
        rows = rows if isinstance(rows, list) else []
        items: list[RankItem] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            novel = row.get("novel") if isinstance(row.get("novel"), dict) else row
            items.append(self._sf_item(channel, novel, len(items) + 1))
        return RankResult(channel=channel, items=items, limit=limit, has_more=False)

    def _sf_item(self, channel: Channel, raw: dict, rank: int) -> RankItem:
        expand = raw.get("expand") if isinstance(raw.get("expand"), dict) else {}
        book_id = str(raw.get("novelId") or raw.get("bookId") or raw.get("id") or "").strip()
        type_id = raw.get("typeId")
        try:
            category = self.TYPE_NAMES.get(int(type_id), "") if type_id is not None else ""
        except (TypeError, ValueError):
            category = ""
        return RankItem(
            title=str(raw.get("novelName") or raw.get("title") or "").strip(),
            rank=rank,
            author=str(raw.get("authorName") or "").strip(),
            book_id=book_id,
            url=f"{self.WEB}/Novel/{book_id}/" if book_id else "",
            intro=str(expand.get("intro") or raw.get("intro") or "").strip(),
            category=str(expand.get("typeName") or category).strip(),
            status="已完结" if raw.get("isFinish") else "连载中",
            word_count=str(raw.get("charCount") or "").strip(),
            score=str(raw.get("point") or "").strip(),
            cover=str(raw.get("novelCover") or "").strip(),
            site="sfacg.com",
            channel=channel.key,
            channel_name=channel.name,
        )


# ---------------------------------------------------------------------------
# Kakuyomu
# ---------------------------------------------------------------------------

class KakuyomuRankAdapter(_RankOnlyAdapter):
    name = "kakuyomu"
    domains = ("kakuyomu.jp",)
    priority = 60

    # 周期取值来自站点实际路径（全期间是 entire，不是 all）
    _PERIODS = (
        ("DAILY", "日间"), ("WEEKLY", "週間"), ("MONTHLY", "月間"), ("ENTIRE", "全期間"),
    )
    # 分类路径与显示名，取自站点排行页的真实链接
    _GENRES = (
        ("Drama", "ドラマ"), ("Romance", "恋愛"), ("Fantasy", "ファンタジー"),
        ("Action", "アクション"), ("SF", "SF"), ("Horror", "ホラー"),
        ("Mystery", "ミステリー"), ("Nonfiction", "ノンフィクション"),
        ("History", "歴史"), ("Criticism", "評論・エッセイ"), ("Others", "その他"),
    )
    channels = tuple(
        Channel(f"kakuyomu_{period.lower()}", f"综合{label}排行", KIND_RANK, "综合",
                f"Kakuyomu 综合{label}排行（/rankings/all/{period.lower()}）",
                pageable=False, params={"period": period, "variation": "LONG"})
        for period, label in _PERIODS
    ) + (
        Channel("kakuyomu_short", "综合周间短篇排行", KIND_RANK, "综合",
                "Kakuyomu 短篇（SHORT）周榜", pageable=False,
                params={"period": "WEEKLY", "variation": "SHORT"}),
    ) + tuple(
        Channel(f"kakuyomu_{genre.lower()}", f"{label}周间排行", KIND_RANK, "分类",
                f"Kakuyomu「{label}」周间排行（/rankings/{genre.lower()}/weekly）",
                pageable=False, params={"genre": genre, "period": "WEEKLY"})
        for genre, label in _GENRES
    )

    def fetch_rank(self, channel: Channel, client, *, page: int = 1,  # noqa: ANN001
                   limit: int = 20, options: dict | None = None) -> RankResult:
        opts = dict(channel.params)
        if options:
            opts.update({k: v for k, v in options.items() if v not in (None, "")})
        period = str(opts.get("period") or "WEEKLY")
        variation = str(opts.get("variation") or "LONG").upper()
        genre = opts.get("genre")
        # 站点路径用小写周期名；全期间是 entire
        period_path = period.lower()

        if genre:
            path = f"/rankings/{str(genre).lower()}/{period_path}"
        else:
            path = f"/rankings/all/{period_path}"
            if variation == "SHORT":
                path += "?work_variation=short"
        url = f"https://kakuyomu.jp{path}"

        resp = client.get(url, policy=self._policy({"Referer": "https://kakuyomu.jp/"}))
        state = self._apollo_state(resp.text)
        if state is None:
            raise ValueError("Kakuyomu 排行页缺少 __NEXT_DATA__ 数据，页面结构可能已改版。")

        # Apollo state 中 Work: 键的插入顺序与页面排名一致
        items: list[RankItem] = []
        for key, node in state.items():
            if not key.startswith("Work:") or not isinstance(node, dict):
                continue
            work_id = key.split(":", 1)[1]
            items.append(self._work_item(channel, node, work_id, len(items) + 1))
            if len(items) >= limit:
                break
        return RankResult(channel=channel, items=items, limit=limit, has_more=False)

    def _work_item(self, channel: Channel, node: dict, work_id: str, rank: int) -> RankItem:
        author = node.get("author")
        author_name = ""
        if isinstance(author, dict):
            author_name = str(
                author.get("activityName") or author.get("screenName") or author.get("name") or ""
            ).strip()
        tags = node.get("tagLabels")
        return RankItem(
            title=str(node.get("title") or "").strip(),
            rank=rank,
            author=author_name,
            book_id=work_id,
            url=f"https://kakuyomu.jp/works/{work_id}",
            intro=str(node.get("introduction") or node.get("catchphrase") or "").strip(),
            category=", ".join(str(t) for t in tags[:3]) if isinstance(tags, list) else "",
            status="已完结" if node.get("serialStatus") == "COMPLETED" else "连载中",
            score=str(node.get("totalReviewPoint") or "").strip(),
            site="kakuyomu.jp",
            channel=channel.key,
            channel_name=channel.name,
        )

    @staticmethod
    def _apollo_state(html_text: str) -> dict | None:
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.DOTALL
        )
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        page_props = ((data.get("props") or {}).get("pageProps")) or {}
        state = page_props.get("__APOLLO_STATE__")
        return state if isinstance(state, dict) else None
