# -*- coding: utf-8 -*-
"""站点适配器注册表。"""
from __future__ import annotations

from .base import ADAPTERS, BookInfo, ChapterContent, ChapterRef, SiteAdapter, find_adapter
from .fanqie import FanqieAdapter
from .generic import GenericAdapter
from .qidian import QidianAdapter
from .ranks import CiweimaoRankAdapter, KakuyomuRankAdapter, SfacgRankAdapter

# 顺序无关，实际按 priority 选择；
# 仅榜单适配器（supports_content=False）不参与正文匹配。
ADAPTERS.clear()
ADAPTERS.extend([
    FanqieAdapter(),
    QidianAdapter(),
    CiweimaoRankAdapter(),
    SfacgRankAdapter(),
    KakuyomuRankAdapter(),
    GenericAdapter(),
])

__all__ = [
    "ADAPTERS", "BookInfo", "ChapterContent", "ChapterRef", "SiteAdapter",
    "find_adapter", "FanqieAdapter", "QidianAdapter", "GenericAdapter",
    "CiweimaoRankAdapter", "SfacgRankAdapter", "KakuyomuRankAdapter",
]
