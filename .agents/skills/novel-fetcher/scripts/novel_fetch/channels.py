# -*- coding: utf-8 -*-
"""榜单通道与条目的通用模型。

站点适配器可以声明自己支持哪些榜单通道（ranking），
并提供统一结构的条目，便于跨站点汇总与输出。
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Channel", "RankItem", "RankResult"]

# 通道类型
KIND_RANK = "rank"          # 排行榜
KIND_RECOMMEND = "recommend"  # 推荐位
KIND_CATEGORY = "category"    # 分类榜


@dataclass
class Channel:
    """一个榜单或推荐位通道。"""

    key: str                      # 稳定标识，如 rank_hot_male
    name: str                     # 中文名，如 男频分类热榜
    kind: str = KIND_RANK
    group: str = ""               # 分组，如 男频 / 女频 / 综合
    description: str = ""
    pageable: bool = True
    params: dict = field(default_factory=dict)   # 默认参数，如 category_id


@dataclass
class RankItem:
    """榜单里的一个作品条目。所有站点归一化成同一结构。"""

    title: str
    rank: int | None = None
    author: str = ""
    book_id: str = ""
    url: str = ""
    intro: str = ""
    category: str = ""
    status: str = ""          # 连载中 / 已完结
    word_count: str = ""
    score: str = ""           # 阅读量 / 热度 / 票数
    cover: str = ""
    latest_chapter: str = ""
    update_time: str = ""
    site: str = ""
    channel: str = ""
    channel_name: str = ""


@dataclass
class RankResult:
    """单个通道的抓取结果。"""

    channel: Channel
    items: list[RankItem] = field(default_factory=list)
    page: int = 1
    limit: int = 20
    has_more: bool = False
    error: str = ""

    @property
    def count(self) -> int:
        return len(self.items)
