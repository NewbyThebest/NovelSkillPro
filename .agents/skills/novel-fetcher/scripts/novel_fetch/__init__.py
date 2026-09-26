# -*- coding: utf-8 -*-
"""novel-fetcher：多站点小说正文抓取工具（零依赖）。"""
from __future__ import annotations

__version__ = "1.0.0"

from .fetcher import FetchError, Fetcher, FetchResult

__all__ = ["Fetcher", "FetchResult", "FetchError", "__version__"]
