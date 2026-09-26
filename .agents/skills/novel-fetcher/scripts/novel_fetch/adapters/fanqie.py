# -*- coding: utf-8 -*-
"""番茄小说适配器。

两条通道，与 QingJuan 同思路：
1. 网页通道：解析 __INITIAL_STATE__，用私用区字体映射表解码正文。
   只能拿到免费章节（锁定章节只返回约 200 字预览）。
2. APP 通道：走 reading.snssdk.com 的 /reader/full/v 全文接口，
   需要 argus/ladon 签名与 AES 解密，能拿到网页锁定章节。

签名与解密原语来自 QingJuan（GPL-3.0）及 naiyQAQ/fanqie-assistant 的公开研究。
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import time
import urllib.parse

from .. import crypto
from ..channels import KIND_RANK, KIND_RECOMMEND, Channel, RankItem, RankResult
from ..htmlparse import html_to_text
from ..http import HttpError
from .base import BookInfo, ChapterContent, ChapterRef, SiteAdapter

__all__ = ["FanqieAdapter"]

BOOK_PATH_RE = re.compile(r"/page/(\d+)")


def _read_count_key(row: dict) -> float:
    """榜单条目按在读数排序用的键（解析不出记 0）。"""
    for key in ("read_count", "readCount", "reading_count", "readingCount"):
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return float(str(value).replace(",", "").strip())
        except ValueError:
            continue
    return 0.0
READER_PATH_RE = re.compile(r"/reader/(\d+)")
MAX_STATE_CHARS = 900_000

# ---------------------------------------------------------------------------
# 网页私用区字体映射表
# 番茄网页正文用私用区码位（U+E3E8 起）配自绘字体渲染，需要映射回真实字符。
# 改编自 naiyQAQ/fanqie-assistant 的 src/fontDecrypt.ts（GPL-3.0），
# 与 QingJuan 同源。未收录项保留原字符，避免静默损坏正文。
# ---------------------------------------------------------------------------
FONT_CODEPOINT_START = 58_344
FONT_MAPPING = (
    "D在主特家军然表场4要只v和?6别还g现儿岁??此象月3出战工相o男直失世F都平文什VO将真T那当?会立些u是十张学气大爱两命全后东性通被1它乐接而感车山公了常"
    "以何可话先pi叫轻M士w着变尔快l个说少色里安花远7难师放t报认面道S?克地度I好机U民写把万同水新没书电吃像斯5为y白几日教看但第加候作上拉住有法r事应位利你"
    "声身国问马女他Y比父xAHNsX边美对所金活回意到z从j知又内因点Q三定8Rb正或夫向德听更?得告并本q过记L让打f人就者去原满体做经K走如孩cG给使物?最笑部"
    "?员等受k行一条果动光门头见往自解成处天能于名其发总母的死手入路进心来h时力多开已许d至由很界n小与Z想代么分生口再妈望次西风种带J?实情才这?E我神格长觉间年"
    "眼无不亲关结0友信下却重己老2音字m呢明之前高PB目太e9起稜她也W用方子英每理便四数期中C外样a海们任"
)

# 章节受限提示：命中说明正文被截断
RESTRICTED_HINTS = (
    "本章内容需在番茄小说app内阅读",
    "本章内容暂不支持网页阅读",
    "登录后继续阅读",
    "购买后继续阅读",
    "开通会员后继续阅读",
)

# APP 接口
APP_BASE_URL = "https://reading.snssdk.com/reading"
APP_USER_AGENT = "com.dragon.read"
DEFAULT_DEVICE_ID = "2187355326004404"
DEFAULT_INSTALL_ID = "2187355326270644"
SHARED_KEY = bytes.fromhex("ac25c67ddd8f38c1b37a2348828e222e")
SIGN_KEY = bytes.fromhex("ac1adaae95a7af94a5114ab3b3a97dd80050aa0a39314c40528caec95256c28c")
APP_CONFIG = {
    "aid": "1967",
    "license_id": "1611921764",
    "sdk_version": "v04.04.05-ov-android",
    "sdk_version_int": 134744640,
    "call_type": 738,
}
LOW_RAND = bytes((0xF2, 0x81))
HIGH_RAND = b"ao"
XOR_PREFIX = bytes((0xF2, 0xF7, 0xFC, 0xFF, 0xF2, 0xF7, 0xFC, 0xFF))
APP_MAX_RETRIES = 2

# 分类 id -> 名称（来自公开的榜单页配置）
MALE_CATEGORIES = (
    ("1141", "西方奇幻"), ("1140", "东方仙侠"), ("8", "科幻末世"), ("261", "都市日常"),
    ("124", "都市修真"), ("1014", "都市高武"), ("273", "历史古代"), ("27", "战神赘婿"),
    ("263", "都市种田"), ("258", "传统玄幻"), ("272", "历史脑洞"), ("539", "悬疑脑洞"),
    ("262", "都市脑洞"), ("257", "玄幻脑洞"), ("751", "悬疑灵异"), ("504", "抗战谍战"),
    ("746", "游戏体育"), ("718", "动漫衍生"), ("1016", "男频衍生"),
)
FEMALE_CATEGORIES = (
    ("1139", "古风世情"), ("8", "科幻末世"), ("746", "游戏体育"), ("1015", "女频衍生"),
    ("248", "玄幻言情"), ("23", "种田"), ("79", "年代"), ("267", "现言脑洞"),
    ("246", "宫斗宅斗"), ("539", "悬疑脑洞"), ("253", "古言脑洞"), ("24", "快穿"),
    ("749", "青春甜宠"), ("745", "星光璀璨"), ("747", "女频悬疑"), ("750", "职场婚恋"),
    ("748", "豪门总裁"), ("1017", "民国言情"),
)
CATEGORY_NAMES = dict(MALE_CATEGORIES + FEMALE_CATEGORIES)

# 新书榜／阅读榜的榜单类型（取自站点前端常量 rankMold）
RANK_MOLD = {"hot": 0, "new": 1, "read": 2}

# 巅峰榜数据源。
#
# 番茄 App 端有一组不分分类的整体榜（巅峰/推荐/完本/新书/追更/黑马/阅读），
# 网页端首页的「番茄巅峰榜」板块是同一批数据：首页 SSR 里 topRankList 为 null，
# 由客户端异步加载，直接抓首页取不到。
# 这里按公开客户端 fanqie-novel-reader（github.com/denniemok/fanqie-novel-reader）
# 的做法走它的公开接口：GET /rank?board=<board>&api=default，带 X-API-Token。
# 该 token 打包在其前端 JS 中，属公开值；服务非本项目可控，失效时会在报错里提示。
APP_PEAK_BASE = "https://api.fanqietc.com"
APP_PEAK_TOKEN = "fqtc_7nKp2mQ8xR4vL6wT1yZ3bC5dF0hJ8aE9uI3kM7"
APP_PEAK_BOARD = "peak"

# APP 端榜单接口。
#
# 番茄的 APP 与网页是**两套独立数据源**：同一分类下返回的书目几乎不重合。
# 用户在 APP 里看到的榜单，只有这个域名能给出来。
APP_RANK_BASE = "https://api.fanqiesdk.com/api/novel/channel/homepage"
APP_RANK_UA = "com.dragon.read/7.0.1.32 (Linux; U; Android 10; zh_CN)"
APP_RANK_AID = "1967"
# APP 分类书单的排序方式；1=按上架时间倒序（即 APP 的新书榜顺序）
APP_NEW_SORT_FIELD = 1

# 搜索接口设备参数
SEARCH_DEVICE_PARAMS = {
    "aid": "1967", "app_name": "novelapp",
    "ac": "wifi", "channel": "43536163a", "device_platform": "android",
    "os": "android", "device_type": "P30", "version_code": "70132",
    "version_name": "7.0.1.32", "os_version": "10", "ssmix": "a",
    "manifest_version_code": "70132", "update_version_code": "70132",
}
SEARCH_RESULT_SHOW_TYPE = 110


def decode_fanqie_text(text: str) -> str:
    """把网页正文里的私用区字符映射回真实汉字。"""
    out: list[str] = []
    for ch in text:
        idx = ord(ch) - FONT_CODEPOINT_START
        if 0 <= idx < len(FONT_MAPPING):
            mapped = FONT_MAPPING[idx]
            out.append(ch if mapped == "?" else mapped)
        else:
            out.append(ch)
    return "".join(out)


class FanqieAdapter(SiteAdapter):
    name = "fanqie"
    domains = ("fanqienovel.com",)
    priority = 10
    supports_search = True
    channels = (
        Channel("rank_list", "综合榜", KIND_RANK, "综合", "站点综合精选书单，固定单页", pageable=False),
        Channel("rank_recommend", "推荐榜", KIND_RANK, "综合", "官方推荐书单，固定单页", pageable=False),
        Channel("rank_recent_update", "最近更新榜", KIND_RANK, "综合", "按最近更新时间排序", pageable=True),
        Channel("rank_hot_male", "男频分类热榜", KIND_RANK, "男频",
                "男频分类热榜；可用 --category 指定分类", pageable=True,
                params={"category_id": MALE_CATEGORIES[0][0], "gender": 1}),
        Channel("rank_hot_female", "女频分类热榜", KIND_RANK, "女频",
                "女频分类热榜；可用 --category 指定分类", pageable=True,
                params={"category_id": FEMALE_CATEGORIES[0][0], "gender": 0}),
        Channel("rank_new_male", "男频新书榜", KIND_RANK, "男频",
                "男频新书榜（30万字以下、已签约未断更）；默认汇总全部分类并按在读排序，"
                "用 --category 可只看某个分类", pageable=True,
                params={"gender": 1, "mold": "new"}),
        Channel("rank_new_female", "女频新书榜", KIND_RANK, "女频",
                "女频新书榜（30万字以下、已签约未断更）；默认汇总全部分类并按在读排序，"
                "用 --category 可只看某个分类", pageable=True,
                params={"gender": 0, "mold": "new"}),
        Channel("rank_read_male", "男频阅读榜", KIND_RANK, "男频",
                "男频阅读榜（30万字以上、已签约已推荐）；默认汇总全部分类并按在读排序，"
                "用 --category 可只看某个分类", pageable=True,
                params={"gender": 1, "mold": "read"}),
        Channel("rank_read_female", "女频阅读榜", KIND_RANK, "女频",
                "女频阅读榜（30万字以上、已签约已推荐）；默认汇总全部分类并按在读排序，"
                "用 --category 可只看某个分类", pageable=True,
                params={"gender": 0, "mold": "read"}),
        Channel("rank_peak", "番茄巅峰榜", KIND_RANK, "综合",
                "番茄巅峰榜（全平台统一榜，不分男女频；每月更新，"
                "按作品好评、人气、互动等综合得分排行）", pageable=False),
        Channel("recommend_editor", "编辑推荐", KIND_RECOMMEND, "首页推荐位",
                "首页编辑精选书单", pageable=False),
        Channel("recommend_week", "本周推荐", KIND_RECOMMEND, "首页推荐位",
                "首页本周热门书单", pageable=False),
        Channel("recommend_boy", "男生推荐", KIND_RECOMMEND, "首页推荐位",
                "首页男频推荐位", pageable=False),
        Channel("recommend_girl", "女生推荐", KIND_RECOMMEND, "首页推荐位",
                "首页女频推荐位", pageable=False),
    )

    # 首页推荐位所在的状态字段 -> 通道
    _HOME_RAILS = {
        "recommend_editor": "editorList",
        "recommend_week": "weekList",
        "recommend_boy": "boyList",
        "recommend_girl": "girlList",
    }

    def __init__(self) -> None:
        self._device_id = os.environ.get("NOVEL_FETCH_FANQIE_DEVICE_ID", DEFAULT_DEVICE_ID).strip()
        self._install_id = os.environ.get("NOVEL_FETCH_FANQIE_INSTALL_ID", DEFAULT_INSTALL_ID).strip()
        self._key: bytes | None = None
        self._key_version: int | None = None
        self._use_app = True

    # -- URL 归一化 -------------------------------------------------------
    def normalize_book_url(self, url: str) -> str:
        m = BOOK_PATH_RE.search(url)
        if m:
            return f"https://fanqienovel.com/page/{m.group(1)}"
        m = READER_PATH_RE.search(url)
        if m:
            # 章节链接需回到作品页才能拿目录
            raise ValueError(
                "这是章节链接，不是作品目录页。请改用作品页链接"
                "（形如 https://fanqienovel.com/page/<作品编号>）。"
            )
        return url

    # -- 作品与目录 -------------------------------------------------------
    def fetch_book(self, url: str, client) -> BookInfo:  # noqa: ANN001
        url = self.normalize_book_url(url)
        m = BOOK_PATH_RE.search(url)
        book_id = m.group(1) if m else ""
        resp = client.get(url)
        state = self._initial_state(resp.text)
        page = state.get("page") if isinstance(state, dict) else None
        page = page if isinstance(page, dict) else {}

        book_name = decode_fanqie_text(str(page.get("bookName") or page.get("book_name") or "").strip())
        author = decode_fanqie_text(str(page.get("author") or page.get("authorName") or "").strip())
        synopsis = self._synopsis_from_page(page, book_name)
        cover = str(page.get("thumbUrl") or page.get("thumbUri") or "").strip()
        category = self._category_from_page(page)
        status = self._status_text(page.get("creationStatus"))
        word_count = str(page.get("wordNumber") or "").strip()
        last_chapter = decode_fanqie_text(str(page.get("lastChapterTitle") or "").strip())

        # 目录优先从 page.chapterList 取，失败则退回正则
        chapters = self._chapters_from_state(page, book_id)
        if not chapters:
            chapters = self._chapters_from_html(resp.text, book_id)
        if not chapters:
            raise ValueError("未能解析番茄作品目录，页面结构可能已变化。")

        return BookInfo(
            title=book_name or f"番茄作品{book_id}",
            source_url=url,
            site="fanqienovel.com",
            author=author,
            synopsis=synopsis,
            cover=cover,
            chapters=chapters,
            book_id=book_id,
            category=category,
            status=status,
            word_count=word_count,
            last_chapter=last_chapter,
            extra={"book_id": book_id, "item_ids": [c.url.rsplit("/", 1)[-1] for c in chapters]},
        )

    @classmethod
    def _synopsis_from_page(cls, page: dict, book_name: str) -> str:
        """取作品简介。

        短篇的 abstract 常被平台填成书名占位，真正的简介在 description；
        长篇则相反，abstract 是简介、description 往往是作者头衔。
        """
        abstract = decode_fanqie_text(str(page.get("abstract") or "").strip())
        description = decode_fanqie_text(str(page.get("description") or "").strip())
        # abstract 与书名重复（忽略标点空白）说明是短篇占位，改用 description
        if abstract and book_name and _normalize_for_compare(abstract) == _normalize_for_compare(book_name):
            return description or abstract
        if abstract:
            return abstract
        return description

    @classmethod
    def _category_from_page(cls, page: dict) -> str:
        """取作品分类名。

        page.categoryV2 可能是 JSON 字符串、JSON 对象数组，或纯文本。
        """
        raw = page.get("categoryV2")
        # 字符串形态：可能内嵌 JSON 数组
        if isinstance(raw, str):
            text = raw.strip()
            if text.startswith("[") or text.startswith("{"):
                try:
                    raw = json.loads(text)
                except (json.JSONDecodeError, ValueError):
                    raw = None
            elif text:
                return decode_fanqie_text(text)
        if isinstance(raw, list) and raw:
            names: list[str] = []
            for entry in raw:
                if isinstance(entry, dict):
                    name = str(entry.get("Name") or "").strip()
                    if name:
                        names.append(name)
                elif isinstance(entry, str) and entry.strip():
                    names.append(entry.strip())
            if names:
                return "/".join(names[:2])
        fallback = page.get("category")
        if isinstance(fallback, str) and fallback.strip():
            return decode_fanqie_text(fallback.strip())
        return ""

    @staticmethod
    def _status_text(value: object) -> str:
        """创作状态。

        番茄取值：0=连载中，1=已完结，4=下架或不可读（保留原值提示）。
        """
        if value is None:
            return ""
        raw = str(value).strip()
        if not raw or raw == "None":
            return ""
        mapping = {
            "0": "连载中", "连载中": "连载中", "serializing": "连载中",
            "1": "已完结", "已完结": "已完结", "finished": "已完结",
            "4": "不可读",
        }
        return mapping.get(raw, raw)

    def _initial_state(self, html_text: str) -> dict:
        """从页面里取出 window.__INITIAL_STATE__ 对象。"""
        marker = "__INITIAL_STATE__"
        pos = html_text.find(marker)
        if pos < 0:
            raise ValueError("页面缺少 __INITIAL_STATE__，番茄可能已改版。")
        start = html_text.find("{", pos)
        if start < 0:
            raise ValueError("页面状态字段格式异常。")
        depth = 0
        quote = ""
        escaped = False
        end = -1
        limit = min(len(html_text), start + MAX_STATE_CHARS)
        for i in range(start, limit):
            ch = html_text[i]
            if quote:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = ""
                continue
            if ch in "\"'":
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end < 0:
            raise ValueError("页面状态对象不完整或过长。")
        raw = html_text[start:end]
        raw = re.sub(r"\bundefined\b", "null", raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"页面状态对象无法解析：{exc}") from exc
        return data if isinstance(data, dict) else {}

    def _chapters_from_state(self, page: dict, book_id: str) -> list[ChapterRef]:
        # chapterListWithVolume 是按卷分组的嵌套列表：[[章节, ...], [章节, ...]]
        # chapterList 通常是空列表，只能作为兜底。
        flat: list[dict] = []
        for key in ("chapterListWithVolume", "chapterList"):
            container = page.get(key)
            if not isinstance(container, list):
                continue
            for item in container:
                if isinstance(item, list):
                    flat.extend(c for c in item if isinstance(c, dict))
                elif isinstance(item, dict):
                    nested = item.get("chapterList")
                    if isinstance(nested, list):
                        flat.extend(c for c in nested if isinstance(c, dict))
                    else:
                        flat.append(item)
            if flat:
                break

        chapters: list[ChapterRef] = []
        seen: set[str] = set()
        for item in flat:
            item_id = str(item.get("itemId") or item.get("item_id") or "").strip()
            title = str(item.get("title") or item.get("chapterTitle") or "").strip()
            if not item_id or not item_id.isdigit() or item_id in seen:
                continue
            seen.add(item_id)
            chapters.append(ChapterRef(
                title=title or f"第{len(chapters) + 1}章",
                url=f"https://fanqienovel.com/reader/{item_id}",
                index=len(chapters) + 1,
            ))
        return chapters

    def _chapters_from_html(self, html_text: str, book_id: str) -> list[ChapterRef]:
        ids = re.findall(r'"itemId":"(\d+)"', html_text)
        seen: set[str] = set()
        chapters: list[ChapterRef] = []
        for item_id in ids:
            if item_id in seen:
                continue
            seen.add(item_id)
            chapters.append(ChapterRef(
                title=f"第{len(chapters) + 1}章",
                url=f"https://fanqienovel.com/reader/{item_id}",
                index=len(chapters) + 1,
            ))
        return chapters

    # -- 章节正文 ---------------------------------------------------------
    def fetch_chapter(self, book: BookInfo, chapter: ChapterRef, client) -> ChapterContent:  # noqa: ANN001
        item_id = chapter.url.rsplit("/", 1)[-1]
        web_error: Exception | None = None

        # 通道 1：网页
        try:
            content = self._fetch_web(item_id, client, chapter)
            if content is not None:
                return content
        except Exception as exc:
            web_error = exc

        # 通道 2：APP 全文接口
        if self._use_app:
            try:
                return self._fetch_app(item_id, client, chapter, book)
            except Exception as app_error:
                note = f"（网页：{web_error}）" if web_error else ""
                raise ValueError(
                    f"番茄章节抓取失败{note}；APP 全文接口也不可用：{app_error}"
                ) from app_error
        raise ValueError(f"番茄章节抓取失败：{web_error or '网页与 APP 通道均未返回正文'}")

    def _fetch_web(self, item_id: str, client, chapter: ChapterRef):  # noqa: ANN001, ANN201
        url = f"https://fanqienovel.com/reader/{item_id}"
        resp = client.get(url, policy=self._web_policy())
        state = self._initial_state(resp.text)
        reader = state.get("reader") if isinstance(state, dict) else None
        reader = reader if isinstance(reader, dict) else {}
        data = reader.get("chapterData") if isinstance(reader.get("chapterData"), dict) else {}
        raw_html = str(data.get("content") or "")

        title = str(data.get("title") or chapter.title).strip()
        locked = bool(data.get("isChapterLock")) or bool(data.get("needPay"))
        if not raw_html:
            return None
        # 锁定章节只给极短预览，交给 APP 通道
        if locked or len(raw_html) <= 400:
            return None
        if any(hint in raw_html for hint in RESTRICTED_HINTS):
            return None

        text = html_to_text(raw_html)
        text = decode_fanqie_text(text)
        text = self._clean(text)
        if not text:
            return None
        return ChapterContent(
            title=title,
            text=text,
            url=url,
            index=chapter.index,
            source="web",
            word_count=len(text),
        )

    @staticmethod
    def _web_policy():
        from ..http import FetchPolicy
        return FetchPolicy(headers={"Referer": "https://fanqienovel.com/"})

    def _fetch_app(self, item_id: str, client, chapter: ChapterRef, book: BookInfo) -> ChapterContent:
        self._ensure_key(client)
        last_error: Exception | None = None
        for attempt in range(APP_MAX_RETRIES + 1):
            try:
                query = self._build_query(item_id)
                headers = {**self._sign(query), "User-Agent": APP_USER_AGENT,
                           "Accept": "application/json", "Referer": "https://fanqienovel.com/"}
                resp = client.get(f"{APP_BASE_URL}/reader/full/v?{query}",
                                  policy=self._app_policy(headers))
                payload = resp.json()
                if not isinstance(payload, dict):
                    raise ValueError("APP 接口响应结构异常")
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                encrypted = str(data.get("content") or "").strip()
                if not encrypted or encrypted == "Invalid":
                    if attempt < APP_MAX_RETRIES:
                        self._key = None
                        self._ensure_key(client)
                        continue
                    raise ValueError("APP 接口未返回可解密正文")
                key_version = self._int(data.get("key_version"))
                if key_version and self._key_version and key_version != self._key_version:
                    if attempt < APP_MAX_RETRIES:
                        self._key = None
                        self._ensure_key(client)
                        continue
                if self._key is None:
                    raise ValueError("APP 解密密钥未初始化")
                plain = crypto.pkcs7_unpad(
                    crypto.aes_cbc_decrypt(self._key, base64.b64decode(encrypted)[:16],
                                           base64.b64decode(encrypted)[16:])
                )
                if self._int(data.get("compress_status")) == 1:
                    plain = gzip.decompress(plain)
                html_text = plain.decode("utf-8")
                text = html_to_text(html_text) if html_text.lstrip().startswith("<") else html_text
                text = self._clean(text)
                if not text:
                    raise ValueError("APP 解密结果为空")
                title = str(data.get("title") or data.get("chapter_title") or chapter.title).strip()
                return ChapterContent(
                    title=title,
                    text=text,
                    url=f"https://fanqienovel.com/reader/{item_id}",
                    index=chapter.index,
                    source="app_full_api",
                    word_count=len(text),
                )
            except Exception as exc:
                last_error = exc
                if attempt < APP_MAX_RETRIES:
                    continue
        raise ValueError(f"APP 全文接口失败：{last_error}")

    @staticmethod
    def _app_policy(headers: dict[str, str]):
        from ..http import FetchPolicy
        return FetchPolicy(headers=headers, timeout=30.0)

    def _ensure_key(self, client) -> None:  # noqa: ANN001
        if self._key is not None:
            return
        body = self._encrypt_register_body()
        query = self._build_query()
        headers = {**self._sign(query, body), "User-Agent": APP_USER_AGENT,
                   "Content-Type": "application/json; charset=utf-8",
                   "Referer": "https://fanqienovel.com/"}
        resp = client.post(f"{APP_BASE_URL}/crypt/registerkey?{query}",
                           data=body, policy=self._app_policy(headers))
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
        encoded = str(data.get("key") or "")
        if not encoded:
            raise ValueError("APP 密钥注册未返回密钥")
        raw = base64.b64decode(encoded)
        self._key = crypto.pkcs7_unpad(
            crypto.aes_cbc_decrypt(SHARED_KEY, raw[:16], raw[16:])
        )
        self._key_version = self._int(data.get("keyver")) or None

    def _build_query(self, item_id: str = "") -> str:
        values = {
            "iid": self._install_id, "device_id": self._device_id, "ac": "wifi",
            "channel": "43536163a", "aid": "1967", "app_name": "novelapp",
            "version_code": "70132", "version_name": "7.0.1.32",
            "device_platform": "android", "os": "android", "ssmix": "a",
            "os_version": "10", "device_type": "P30", "device_brand": "realme",
            "update_version_code": "70132", "manifest_version_code": "70132",
        }
        if item_id:
            values.update({"item_id": item_id, "req_type": "1"})
        return urllib.parse.urlencode(values)

    def _sign(self, query: str, body: bytes | str = b"") -> dict[str, str]:
        ts = int(time.time())
        rand = int.from_bytes(os.urandom(4), "little") & 0x7FFFFFFF
        body_bytes = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        stub = hashlib.md5(body_bytes).hexdigest() if body_bytes else ""
        headers = {
            "x-argus": self._argus(query, stub, ts, rand),
            "x-ladon": self._ladon(ts),
            "x-khronos": str(ts),
            "x-ss-req-ticket": str(int(time.time() * 1000)),
        }
        if stub:
            headers["X-SS-STUB"] = stub
        return headers

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
        dispatch = {
            "rank_list": self._rank_list,
            "rank_recommend": self._rank_recommend,
            "rank_recent_update": self._rank_recent,
            "rank_hot_male": self._rank_category,
            "rank_hot_female": self._rank_category,
            "rank_new_male": self._rank_new_or_read,
            "rank_new_female": self._rank_new_or_read,
            "rank_read_male": self._rank_new_or_read,
            "rank_read_female": self._rank_new_or_read,
            "rank_peak": self._rank_peak,
        }
        if channel.key in self._HOME_RAILS:
            items = self._home_rail(channel.key, client, limit)
            return RankResult(channel=channel, items=items, page=1, limit=limit, has_more=False)
        handler = dispatch.get(channel.key)
        if handler is None:
            raise ValueError(f"番茄未实现的榜单通道：{channel.key}")
        return handler(channel, client, page=page, limit=limit, opts=opts)

    def category_options(self, channel: Channel) -> list[tuple[str, str]]:
        """番茄分类榜只能按分类浏览，没有「全部分类」页。

        这里给出该频道要遍历的分类清单，供 `rank --sweep` 一次扫完。
        """
        gender = str(channel.params.get("gender", ""))
        if gender == "0":
            return list(FEMALE_CATEGORIES)
        if gender == "1":
            return list(MALE_CATEGORIES)
        # 热榜通道同样按分类
        if channel.key == "rank_hot_female":
            return list(FEMALE_CATEGORIES)
        if channel.key == "rank_hot_male":
            return list(MALE_CATEGORIES)
        return []

    def _rank_list(self, channel: Channel, client, *, page: int,  # noqa: ANN001
                   limit: int, opts: dict) -> RankResult:
        data = self._api_json(client, "/api/rank/list", {"limit": limit, "offset": 0}, "综合榜")
        rows = ((data.get("data") or {}).get("list")) or []
        items = [self._book_from_rank(channel, r, i) for i, r in enumerate(rows[:limit], 1)]
        return RankResult(channel=channel, items=items, limit=limit, has_more=False)

    def _rank_recommend(self, channel: Channel, client, *, page: int,  # noqa: ANN001
                        limit: int, opts: dict) -> RankResult:
        data = self._api_json(client, "/api/rank/recommend/list",
                              {"limit": limit, "offset": 0}, "推荐榜")
        rows = ((data.get("data") or {}).get("list")) or []
        items = [self._book_from_rank(channel, r, i) for i, r in enumerate(rows[:limit], 1)]
        return RankResult(channel=channel, items=items, limit=limit, has_more=False)

    def _rank_recent(self, channel: Channel, client, *, page: int,  # noqa: ANN001
                     limit: int, opts: dict) -> RankResult:
        offset = (page - 1) * limit
        data = self._api_json(client, "/api/rank/recent/update/list",
                              {"limit": limit, "offset": offset}, "最近更新榜")
        rows = ((data.get("data") or {}).get("data")) or []
        items: list[RankItem] = []
        for idx, row in enumerate(rows[:limit], start=1):
            item = self._book_from_rank(channel, row, offset + idx)
            stamp = row.get("updateTime")
            try:
                item.update_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(stamp)))
            except (TypeError, ValueError, OSError):
                item.update_time = ""
            item.latest_chapter = decode_fanqie_text(str(row.get("title") or ""))
            items.append(item)
        return RankResult(channel=channel, items=items, page=page, limit=limit,
                          has_more=len(rows) >= limit)

    def _rank_category(self, channel: Channel, client, *, page: int,  # noqa: ANN001
                       limit: int, opts: dict) -> RankResult:
        data = self._api_json(client, "/api/rank/category/list", {
            "app_id": 2503, "rank_list_type": 3,
            "category_id": opts.get("category_id", "0"),
            "gender": opts.get("gender", 0),
            "rank_version": "", "rank_mold": "",
            "limit": limit, "offset": (page - 1) * limit,
        }, "分类热榜")
        body = data.get("data") or {}
        rows = body.get("book_list") or body.get("rank_list") or body.get("list") or []
        cat_name = CATEGORY_NAMES.get(str(opts.get("category_id", "")), "")
        items: list[RankItem] = []
        for row in rows[:limit]:
            pos = row.get("currentPos")
            rank = int(pos) if isinstance(pos, (int, str)) and str(pos).isdigit() else None
            item = self._book_from_rank(channel, row, rank)
            if not item.category:
                item.category = cat_name
            items.append(item)
        return RankResult(channel=channel, items=items, page=page, limit=limit,
                          has_more=len(rows) >= limit)

    def _fetch_new_or_read_category(
        self, client, *, gender: str, mold: int, category_id: str,
        limit: int, page: int,
    ) -> list[dict]:
        """抓新书榜／阅读榜里单个分类的原始条目（榜单页 SSR，按屏翻页）。"""
        per_screen = 10
        offset = max(0, (page - 1) * limit)
        want = max(limit, per_screen)

        rows: list[dict] = []
        seen: set[str] = set()
        while len(rows) < want and offset < 100:
            url = f"https://fanqienovel.com/rank/{gender}_{mold}_{category_id}?offset={offset}"
            resp = client.get(url, policy=self._page_policy())
            state = self._initial_state(resp.text)
            rank = state.get("rank") if isinstance(state, dict) else None
            rank = rank if isinstance(rank, dict) else {}
            screen = rank.get("book_list") or []
            if not isinstance(screen, list) or not screen:
                break
            added = 0
            for row in screen:
                if not isinstance(row, dict):
                    continue
                bid = str(row.get("bookId") or "").strip()
                if bid and bid in seen:
                    continue
                if bid:
                    seen.add(bid)
                rows.append(row)
                added += 1
            if added == 0 or len(screen) < per_screen:
                break
            offset += per_screen
        return rows

    def _rank_new_or_read(self, channel: Channel, client, *, page: int,  # noqa: ANN001
                          limit: int, opts: dict) -> RankResult:
        """新书榜／阅读榜。

        参数语义取自站点前端（榜单页路由 `<gender>_<rankMold>_<category>`）：
        gender 1=男频、0=女频；rankMold 1=新书榜、2=阅读榜。

        数据源必须用**榜单页 SSR**，不能用 /api/rank/category/list：
        两者返回同一批书但顺序不同，而 SSR 才是页面真实渲染的顺序
        （前端 serverRendered=true 表示不再回填，用户看到的就是 SSR）。
        实测同一分类下，SSR 顺序按 read_count 降序，API 顺序则明显错乱。

        站点本身只提供**按分类**的榜单页，没有「全部分类」入口。
        所以这里分两种用法：

        * 不给 category_id：自动遍历该频道全部分类，合并成一份总榜，
          条目按热度降序重排（相当于「看全部」）。
        * 给了 category_id：只抓该分类，顺序沿用页面 SSR 的原始排名。
        """
        gender = str(opts.get("gender", 1))
        mold = RANK_MOLD.get(str(opts.get("mold")), 1)
        category_id = str(opts.get("category_id") or "").strip()

        # 未指定分类 -> 合并全部分类
        if not category_id:
            cats = MALE_CATEGORIES if gender == "1" else FEMALE_CATEGORIES
            merged: list[dict] = []
            seen: set[str] = set()
            for cat_id, cat_name in cats:
                try:
                    rows = self._fetch_new_or_read_category(
                        client, gender=gender, mold=mold,
                        category_id=cat_id, limit=limit, page=page,
                    )
                except (ValueError, HttpError):
                    continue
                for row in rows:
                    bid = str(row.get("bookId") or "").strip()
                    if bid and bid in seen:
                        continue
                    if bid:
                        seen.add(bid)
                    row = dict(row)
                    row.setdefault("_catName", cat_name)
                    merged.append(row)

            merged.sort(key=_read_count_key, reverse=True)
            items: list[RankItem] = []
            for idx, row in enumerate(merged, start=1):
                item = self._book_from_rank(channel, row, idx)
                if not item.category:
                    item.category = str(row.get("_catName") or "")
                items.append(item)
            return RankResult(channel=channel, items=items, page=page, limit=limit,
                              has_more=False)

        cat_name = CATEGORY_NAMES.get(category_id, "")
        rows = self._fetch_new_or_read_category(
            client, gender=gender, mold=mold,
            category_id=category_id, limit=limit, page=page,
        )

        items: list[RankItem] = []
        for idx, row in enumerate(rows[:limit], start=1):
            # 顺序即排名：SSR 数组序与页面显示的 01/02/... 一致
            pos = row.get("currentPos")
            rank_no = int(pos) if isinstance(pos, (int, str)) and str(pos).isdigit() else idx
            item = self._book_from_rank(channel, row, rank_no)
            if not item.category:
                item.category = cat_name
            items.append(item)
        return RankResult(channel=channel, items=items, page=page, limit=limit,
                          has_more=len(rows) >= limit)

    def _rank_peak(self, channel: Channel, client, *, page: int,  # noqa: ANN001
                   limit: int, opts: dict) -> RankResult:
        """番茄巅峰榜（整体榜，不分分类）。

        数据源为公开客户端 fanqie-novel-reader 使用的接口
        （https://api.fanqietc.com/rank?board=peak）。网页端首页的
        「番茄巅峰榜」板块是同一批数据，但首页 SSR 里 topRankList 为 null，
        只能靠这个接口取。
        """
        from ..http import FetchPolicy
        board = str(opts.get("board") or APP_PEAK_BOARD)
        url = f"{APP_PEAK_BASE}/rank?" + urllib.parse.urlencode(
            {"board": board, "api": "default"}
        )
        policy = FetchPolicy(
            timeout=30.0,
            headers={
                "X-API-Token": APP_PEAK_TOKEN,
                "Referer": "https://fanqietc.com/",
                "Origin": "https://fanqietc.com",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
        )
        try:
            resp = client.get(url, policy=policy)
        except HttpError as exc:
            raise HttpError(
                "番茄巅峰榜数据源（api.fanqietc.com）不可用："
                f"{exc}。该来源为第三方公开接口，可能已变更。"
            ) from exc
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError("番茄巅峰榜返回结构异常")
        data = payload.get("data") or {}
        rows = data.get("books") or []
        if not isinstance(rows, list):
            raise ValueError("番茄巅峰榜返回结构异常")

        items: list[RankItem] = []
        for idx, raw in enumerate(rows[:limit], start=1):
            if not isinstance(raw, dict):
                continue
            item = self._book_from_rank(channel, raw, idx)
            if not item.category:
                item.category = decode_fanqie_text(str(raw.get("category") or ""))
            # 巅峰值／在读量：该接口放在 sub_info（如「172.9万人在读」）
            sub = str(raw.get("sub_info") or "").strip()
            if sub:
                item.score = sub
            items.append(item)
        return RankResult(channel=channel, items=items, page=page, limit=limit,
                          has_more=bool(data.get("has_more")))

    @staticmethod
    def _page_policy():
        from ..http import FetchPolicy
        return FetchPolicy(headers={"Referer": "https://fanqienovel.com/"})

    def _home_rail(self, channel_key: str, client, limit: int) -> list[RankItem]:  # noqa: ANN001
        """首页 SSR 里一次可取多个推荐位，这里只解析首页状态。"""
        resp = client.get("https://fanqienovel.com/")
        state = self._initial_state(resp.text)
        home = state.get("home") if isinstance(state, dict) else None
        home = home if isinstance(home, dict) else {}
        rows = home.get(self._HOME_RAILS[channel_key]) or []
        channel = next((c for c in self.channels if c.key == channel_key),
                       Channel(channel_key, channel_key))
        items: list[RankItem] = []
        for idx, row in enumerate(rows[:limit], start=1):
            if isinstance(row, dict):
                items.append(self._book_from_rank(channel, row, idx))
        return items

    def _book_from_rank(self, channel: Channel, raw: dict, rank: int | None) -> RankItem:
        """把榜单原始条目归一化。注意番茄榜单文本同样有字体加密。"""
        book_id = str(raw.get("bookId") or raw.get("book_id") or raw.get("id") or "").strip()
        cat_id = str(raw.get("cureent_category_id") or raw.get("category_id") or "").strip()
        category = decode_fanqie_text(str(raw.get("category") or raw.get("categoryV2") or ""))
        if not category:
            category = CATEGORY_NAMES.get(cat_id, "")
        return RankItem(
            title=decode_fanqie_text(
                str(raw.get("bookName") or raw.get("book_name") or raw.get("title") or "")
            ).strip(),
            rank=rank,
            author=decode_fanqie_text(str(raw.get("author") or "")).strip(),
            book_id=book_id,
            url=f"https://fanqienovel.com/page/{book_id}" if book_id else "",
            intro=decode_fanqie_text(str(raw.get("abstract") or raw.get("description") or "")).strip(),
            category=category.strip(),
            status=self._status_text(raw.get("creationStatus")),
            word_count=self._first_value(raw, "wordNumber", "word_number"),
            score=self._first_value(raw, "read_count", "readCount"),
            cover=str(raw.get("thumbUri") or raw.get("thumbUrl") or "").strip(),
            latest_chapter=decode_fanqie_text(
                str(raw.get("lastChapterTitle") or "").strip()
            ),
            site="fanqienovel.com",
            channel=channel.key,
            channel_name=channel.name,
        )

    @staticmethod
    def _first_value(raw: dict, *keys: str) -> str:
        """取第一个有效（非空且非 0）的值；番茄的 readCount 常为占位 0。"""
        for key in keys:
            value = raw.get(key)
            if value in (None, "", 0, "0"):
                continue
            return str(value).strip()
        return ""

    def _api_json(self, client, path: str, params: dict, what: str) -> dict:  # noqa: ANN001
        url = f"https://fanqienovel.com{path}?" + urllib.parse.urlencode(params)
        resp = client.get(url, policy=self._web_api_policy())
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError(f"番茄{what}返回结构异常")
        code = payload.get("code")
        if code not in (0, None):
            raise ValueError(f"番茄{what}请求失败：code={code}")
        return payload

    @staticmethod
    def _web_api_policy():
        from ..http import FetchPolicy
        return FetchPolicy(headers={
            "Referer": "https://fanqienovel.com/",
            "Accept": "application/json, text/plain, */*",
        })

    # -- 搜索 -------------------------------------------------------------
    def search(self, keyword: str, client, limit: int = 20) -> list[RankItem]:  # noqa: ANN001
        kw = keyword.strip()
        if not kw:
            return []
        params = {
            **SEARCH_DEVICE_PARAMS,
            "iid": self._install_id, "device_id": self._device_id,
            "query": kw, "passback": "0", "selected_items": "", "tab_type": "1",
        }
        query = urllib.parse.urlencode(params)
        headers = {
            "Referer": f"https://fanqienovel.com/search/{urllib.parse.quote(kw, safe='')}",
            "Accept": "application/json, text/plain, */*",
            **self._sign(query),
        }
        from ..http import FetchPolicy
        resp = client.get(
            f"https://fanqienovel.com/reading/bookapi/search/tab/v?{query}",
            policy=FetchPolicy(headers=headers, timeout=30.0),
        )
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError("番茄搜索返回结构异常")
        if payload.get("code") not in (0, None):
            raise ValueError(f"番茄搜索失败：code={payload.get('code')}")

        results: list[RankItem] = []
        seen: set[str] = set()
        search_channel = Channel("search", "搜索结果")
        for tab in payload.get("search_tabs") or []:
            if not isinstance(tab, dict):
                continue
            for cell in tab.get("data") or []:
                if not isinstance(cell, dict):
                    continue
                if self._int(cell.get("show_type")) not in (0, SEARCH_RESULT_SHOW_TYPE):
                    continue
                books = cell.get("book_data")
                if isinstance(books, dict):
                    books = [books]
                if not isinstance(books, list):
                    continue
                for raw in books:
                    if not isinstance(raw, dict):
                        continue
                    item = self._search_item(search_channel, raw, cell)
                    if item is None or item.book_id in seen:
                        continue
                    seen.add(item.book_id)
                    results.append(item)
                    if len(results) >= limit:
                        return results
        return results

    def _search_item(self, channel: Channel, raw: dict, cell: dict) -> RankItem | None:
        book_id = str(raw.get("bookId") or raw.get("book_id") or "").strip()
        if not book_id:
            return None
        # 搜索接口用 snake_case 字段；book_name 是书名本身
        title = str(raw.get("book_name") or raw.get("bookName") or "").strip()
        if not title:
            # 退回高亮里的展示名（可能带"（别名：…）"）
            highlight = cell.get("search_high_light")
            if isinstance(highlight, dict):
                node = highlight.get("title")
                if isinstance(node, dict):
                    title = str(node.get("text") or "")
        intro = str(raw.get("abstract") or raw.get("description") or "").strip()
        if not intro:
            highlight = cell.get("search_high_light")
            if isinstance(highlight, dict):
                node = highlight.get("abstract")
                if isinstance(node, dict):
                    intro = str(node.get("text") or "")
        return RankItem(
            title=decode_fanqie_text(title).strip(),
            author=decode_fanqie_text(str(raw.get("author") or "")).strip(),
            book_id=book_id,
            url=f"https://fanqienovel.com/page/{book_id}",
            intro=decode_fanqie_text(intro).strip(),
            category=decode_fanqie_text(str(raw.get("category") or "")).strip(),
            status=self._status_text(raw.get("creation_status") or raw.get("creationStatus")),
            word_count=self._first_value(raw, "word_number", "wordNumber", "serial_count"),
            score=self._first_value(raw, "read_count", "readCount"),
            cover=str(raw.get("thumb_url") or raw.get("thumbUri") or "").strip(),
            latest_chapter=decode_fanqie_text(
                str(raw.get("last_chapter_title") or "").strip()
            ),
            site="fanqienovel.com",
            channel=channel.key,
            channel_name=channel.name,
        )

    # -- 签名算法（同 QingJuan fanqie_crypto） -----------------------------
    def _argus(self, query: str, xss_stub: str, ts: int, rand: int) -> str:
        pb = crypto.pkcs7_pad(self._argus_protobuf(query, xss_stub, ts, rand))
        simon_key = crypto.sm3(SIGN_KEY + LOW_RAND + HIGH_RAND + SIGN_KEY)
        encrypt = b"".join(
            self._simon_encrypt(pb[i:i + 16], simon_key) for i in range(0, len(pb), 16)
        )
        data = bytearray(XOR_PREFIX + encrypt)
        for i in range(len(XOR_PREFIX), len(data)):
            data[i] ^= data[i % 8]
        data.reverse()
        plaintext = (bytes((0xA6, 0x6E, 0xAD, 0x9F, 0x77, 0x01, 0xD0, 0x0C, 0x18))
                     + bytes(data) + HIGH_RAND)
        aes_key = hashlib.md5(SIGN_KEY[:16]).digest()
        iv = hashlib.md5(SIGN_KEY[16:]).digest()
        ct = crypto.aes_cbc_encrypt(aes_key, iv, crypto.pkcs7_pad(plaintext))
        return base64.b64encode(LOW_RAND + ct).decode("ascii")

    def _argus_protobuf(self, query: str, xss_stub: str, ts: int, rand: int) -> bytes:
        params = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
        device_id = params.get("device_id", "")
        version_name = params.get("version_name", "")
        body_hash = crypto.sm3(bytes.fromhex(xss_stub) if len(xss_stub) >= 32 else bytes(16))[:6]
        query_hash = crypto.sm3(query.encode("utf-8") if query else bytes(16))[:6]

        def vint(fn: int, v: int) -> bytes:
            return _varint((fn << 3) | 0) + _varint(v)

        def vbytes(fn: int, v: bytes) -> bytes:
            return _varint((fn << 3) | 2) + _varint(len(v)) + v

        def vstr(fn: int, v: str) -> bytes:
            return vbytes(fn, v.encode("utf-8"))

        nested_15 = vint(1, 1) + vint(2, 1) + vint(3, 1) + vint(7, 3348294860)
        nested_23 = vstr(1, "NX551J") + vint(2, 8196) + vint(4, 2162219008)
        return (
            vint(1, 0x20200929 * 2) + vint(2, 2) + vint(3, rand)
            + vstr(4, str(APP_CONFIG["aid"])) + vstr(5, device_id)
            + vstr(6, str(APP_CONFIG["license_id"])) + vstr(7, version_name)
            + vstr(8, str(APP_CONFIG["sdk_version"]))
            + vint(9, int(APP_CONFIG["sdk_version_int"]))
            + vbytes(10, bytes(8)) + vint(11, 0) + vint(12, ts * 2)
            + vbytes(13, body_hash) + vbytes(14, query_hash) + vbytes(15, nested_15)
            + vstr(16, "") + vstr(20, "none") + vint(21, int(APP_CONFIG["call_type"]))
            + vbytes(23, nested_23) + vint(25, 2)
        )

    @staticmethod
    def _simon_encrypt(block: bytes, key: bytes) -> bytes:
        mask = 0xFFFFFFFFFFFFFFFF
        z4 = 0x3DC94C3A046D678B
        key_words = [int.from_bytes(key[i:i + 8], "little") for i in range(0, 32, 8)]
        round_keys = list(key_words)

        def ror(v: int, b: int) -> int:
            return ((v >> b) | (v << (64 - b))) & mask

        def rol(v: int, b: int) -> int:
            return ((v << b) | (v >> (64 - b))) & mask

        for i in range(4, 72):
            tmp = ror(round_keys[i - 1], 3) ^ round_keys[i - 3]
            tmp ^= ror(tmp, 1)
            round_keys.append(
                (~round_keys[i - 4] ^ tmp ^ ((z4 >> ((i - 4) % 62)) & 1) ^ 3) & mask
            )
        x = int.from_bytes(block[:8], "little")
        y = int.from_bytes(block[8:], "little")
        for rk in round_keys[:72]:
            x, y = y, (x ^ (rol(y, 1) & rol(y, 8)) ^ rol(y, 2) ^ rk) & mask
        return x.to_bytes(8, "little") + y.to_bytes(8, "little")

    def _ladon(self, ts: int) -> str:
        random_bytes = os.urandom(4)
        key = hashlib.md5(
            random_bytes + str(APP_CONFIG["aid"]).encode("ascii")
        ).hexdigest().encode("ascii")
        plaintext = f"{ts}-{APP_CONFIG['license_id']}-{APP_CONFIG['aid']}".encode()
        return base64.b64encode(random_bytes + self._speck_encrypt(key, plaintext)).decode("ascii")

    @staticmethod
    def _speck_encrypt(key: bytes, plaintext: bytes) -> bytes:
        mask = 0xFFFFFFFFFFFFFFFF
        round_keys = [int.from_bytes(key[:8], "little")]
        ls = [int.from_bytes(key[i:i + 8], "little") for i in range(8, 32, 8)]
        for i in range(33):
            rotated_x = ((ls[i] >> 8) | (ls[i] << 56)) & mask
            new_x = (i ^ ((rotated_x + round_keys[i]) & mask)) & mask
            ls.append(new_x)
            rotated_y = ((round_keys[i] << 3) | (round_keys[i] >> 61)) & mask
            round_keys.append(new_x ^ rotated_y)
        padded = crypto.pkcs7_pad(plaintext)
        out = bytearray()
        for off in range(0, len(padded), 16):
            y = int.from_bytes(padded[off:off + 8], "little")
            x = int.from_bytes(padded[off + 8:off + 16], "little")
            for rk in round_keys[:34]:
                x = (((x >> 8) | (x << 56)) + y) & mask
                x ^= rk
                y = (((y << 3) | (y >> 61)) & mask) ^ x
            out.extend(y.to_bytes(8, "little") + x.to_bytes(8, "little"))
        return bytes(out)

    def _encrypt_register_body(self) -> str:
        device_hex = self._device_id
        if not device_hex.isdigit():
            raise ValueError("番茄 device_id 必须是数字")
        value = int(device_hex).to_bytes(16, "big", signed=False)[::-1][:8]
        iv = base64.b64encode(os.urandom(12)).decode("ascii")[:16].encode("ascii").ljust(16, b"0")
        encrypted = crypto.aes_cbc_encrypt(SHARED_KEY, iv, crypto.pkcs7_pad(value))
        return json.dumps(
            {"content": base64.b64encode(iv + encrypted).decode("ascii")},
            ensure_ascii=False, separators=(",", ":"),
        )

    # -- 工具 -------------------------------------------------------------
    @staticmethod
    def _int(value: object, default: int = 0) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clean(text: str) -> str:
        lines = [line.strip() for line in text.split("\n")]
        kept = [line for line in lines if line]
        deduped: list[str] = []
        for line in kept:
            if deduped and line == deduped[-1]:
                continue
            deduped.append(line)
        return "\n\n".join(deduped)


def _normalize_for_compare(value: str) -> str:
    """去掉空白与常见标点，用于判断两段文本是否实质相同。"""
    return re.sub(r"[\s，。！？、；：“”‘’（）《》【】,.!?;:'\"()\[\]]", "", value or "")


def _varint(value: int) -> bytes:
    value &= 0xFFFFFFFF
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)
