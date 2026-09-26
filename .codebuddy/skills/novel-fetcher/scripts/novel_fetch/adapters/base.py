# -*- coding: utf-8 -*-
"""站点适配器基础类型与注册表。"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from ..channels import Channel, RankItem, RankResult

__all__ = ["BookInfo", "ChapterRef", "ChapterContent", "SiteAdapter", "ADAPTERS", "find_adapter"]


@dataclass
class ChapterRef:
    """目录中的一个章节条目。"""

    title: str
    url: str
    index: int = 0
    locked: bool = False


@dataclass
class BookInfo:
    """作品元信息与目录。"""

    title: str
    source_url: str
    site: str
    author: str = ""
    synopsis: str = ""
    cover: str = ""
    chapters: list[ChapterRef] = field(default_factory=list)
    book_kind: str = "长小说"
    # 详情元信息（站点提供时填充）
    book_id: str = ""
    category: str = ""
    status: str = ""            # 连载中 / 已完结
    word_count: str = ""
    score: str = ""             # 阅读量 / 热度
    last_chapter: str = ""
    tags: list[str] = field(default_factory=list)
    # 站点适配器自行携带的上下文（如番茄的 book_id）
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)


@dataclass
class ChapterContent:
    """抓到的章节正文。"""

    title: str
    text: str
    url: str = ""
    index: int = 0
    source: str = ""          # 内容来源通道，如 web / app_full_api
    word_count: int = 0
    images: list[str] = field(default_factory=list)


class SiteAdapter:
    """站点适配器接口。

    子类至少要实现 matches() 与 fetch_book() / fetch_chapter()。
    榜单与搜索为可选能力：不支持的站点保持默认实现（报不支持）。
    """

    name: str = "base"
    domains: tuple[str, ...] = ()
    priority: int = 100   # 越小越优先

    # 站点宣称支持的榜单通道；空表示不支持榜单
    channels: tuple[Channel, ...] = ()
    supports_search: bool = False
    # 是否支持作品/正文抓取；仅提供榜单的适配器应设为 False，
    # 这样正文请求会继续落到通用的网页回退上，而不是被拦截后报错。
    supports_content: bool = True

    def matches(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def fetch_book(self, url: str, client) -> BookInfo:  # noqa: ANN001
        raise NotImplementedError

    def fetch_chapter(self, book: BookInfo, chapter: ChapterRef, client) -> ChapterContent:  # noqa: ANN001
        raise NotImplementedError

    # -- 可选能力：榜单 --------------------------------------------------
    def list_channels(self) -> tuple[Channel, ...]:
        return self.channels

    def category_options(self, channel: Channel) -> list[tuple[str, str]]:
        """该通道可遍历的分类，返回 [(分类id, 分类名)]。

        用于"扫榜"：部分站点（如番茄新书榜）只提供按分类浏览，
        没有全部分类页，需要逐个分类取再汇总。
        默认返回空，表示该通道没有分类维度。
        """
        return []

    def fetch_rank(
        self,
        channel: Channel,
        client,  # noqa: ANN001
        *,
        page: int = 1,
        limit: int = 20,
        options: dict | None = None,
    ) -> RankResult:
        """抓取一个榜单通道。默认实现报不支持。"""
        raise NotImplementedError(f"{self.name} 不支持榜单通道 {channel.key}")

    # -- 可选能力：搜索 --------------------------------------------------
    def search(self, keyword: str, client, limit: int = 20) -> list[RankItem]:  # noqa: ANN001
        """按关键词搜索作品。默认实现报不支持。"""
        raise NotImplementedError(f"{self.name} 不支持搜索")

    def close(self) -> None:
        """释放适配器持有的资源。"""


# 注册表：由 adapters/__init__.py 填充
ADAPTERS: list[SiteAdapter] = []


def find_adapter(url: str) -> SiteAdapter | None:
    """按优先级选第一个匹配且能解析内容的适配器。

    只提供榜单的适配器会被跳过，让正文请求落到通用网页回退上。
    """
    for adapter in sorted(ADAPTERS, key=lambda a: a.priority):
        if not adapter.supports_content:
            continue
        if adapter.matches(url):
            return adapter
    return None
