# -*- coding: utf-8 -*-
"""抓取编排：把适配器、HTTP、输出落盘串起来。"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .adapters import BookInfo, ChapterContent, ChapterRef, find_adapter
from .channels import Channel, RankItem, RankResult
from .http import HttpClient, HttpError

__all__ = ["Fetcher", "FetchResult", "FetchError", "list_all_channels", "find_channel"]


class FetchError(RuntimeError):
    """面向用户的抓取错误。"""


def _hotness_key(item: RankItem) -> float:
    """把热度字段转成可排序的数值。

    番茄的 score 是纯数字字符串（如 "73188"）；部分站点会给带单位的
    「12.3万」「1.2亿」，这里统一按中文数量级折算，解析不出来记 0。
    """
    raw = (item.score or "").strip().replace(",", "")
    if not raw:
        return 0.0
    m = re.match(r"([\d.]+)\s*(万|亿)?", raw)
    if not m:
        return 0.0
    try:
        value = float(m.group(1))
    except ValueError:
        return 0.0
    unit = m.group(2)
    if unit == "万":
        value *= 10_000
    elif unit == "亿":
        value *= 100_000_000
    return value


@dataclass
class FetchResult:
    book: BookInfo
    saved: list[dict]
    failed: list[dict]
    output_dir: str
    elapsed: float

    def summary(self) -> str:
        lines = [
            f"作品：{self.book.title}",
            f"站点：{self.book.site}",
            f"目录：{self.book.chapter_count} 章",
            f"成功：{len(self.saved)} 章，失败：{len(self.failed)} 章",
            f"输出：{self.output_dir}",
            f"耗时：{self.elapsed:.1f} 秒",
        ]
        if self.failed:
            lines.append("失败章节：")
            for item in self.failed[:10]:
                lines.append(f"  - {item['title']}：{item['error']}")
            if len(self.failed) > 10:
                lines.append(f"  ...另有 {len(self.failed) - 10} 章失败")
        return "\n".join(lines)


def _safe_name(value: str, limit: int = 80) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", value).strip().strip(".")
    return (cleaned[:limit] or "未命名")


class Fetcher:
    """按链接抓取作品。"""

    def __init__(self, *, output_root: Path, user_agent: str | None = None) -> None:
        self.output_root = Path(output_root)
        kwargs = {"user_agent": user_agent} if user_agent else {}
        self.client = HttpClient(**kwargs)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- 榜单 -------------------------------------------------------------
    def list_channels(self, site: str | None = None) -> list[tuple[str, Channel]]:
        """列出所有站点支持的榜单通道，返回 (适配器名, 通道)。"""
        from .adapters import ADAPTERS
        out: list[tuple[str, Channel]] = []
        for adapter in sorted(ADAPTERS, key=lambda a: a.priority):
            if site and adapter.name != site:
                continue
            for channel in adapter.list_channels():
                out.append((adapter.name, channel))
        return out

    def rank(
        self,
        channel_key: str,
        *,
        site: str | None = None,
        page: int = 1,
        limit: int = 20,
        options: dict | None = None,
    ) -> RankResult:
        """抓取指定榜单通道。"""
        from .adapters import ADAPTERS
        candidates = [
            a for a in sorted(ADAPTERS, key=lambda a: a.priority)
            if (site is None or a.name == site)
        ]
        for adapter in candidates:
            channel = next((c for c in adapter.list_channels() if c.key == channel_key), None)
            if channel is None:
                continue
            try:
                return adapter.fetch_rank(
                    channel, self.client, page=page, limit=limit, options=options
                )
            except NotImplementedError as exc:
                raise FetchError(str(exc)) from exc
            except (ValueError, HttpError) as exc:
                raise FetchError(f"榜单抓取失败：{exc}") from exc
        known = ", ".join(k for _, c in self.list_channels(site) for k in [c.key])
        raise FetchError(f"未知的榜单通道：{channel_key}。可用通道：{known}")

    def sweep(
        self,
        channel_key: str,
        *,
        site: str | None = None,
        limit: int = 10,
        options: dict | None = None,
        delay: float = 0.3,
    ) -> tuple[Channel, list[tuple[str, RankResult]]]:
        """扫榜：把该通道的所有分类逐个抓下来。

        番茄的新书榜/阅读榜只提供按分类浏览，没有「全部分类」页。
        这里自动遍历全部分类并汇总，省去手写循环。

        返回 (通道, [(分类名, 该分类结果)])。
        """
        from .adapters import ADAPTERS
        candidates = [
            a for a in sorted(ADAPTERS, key=lambda a: a.priority)
            if (site is None or a.name == site)
        ]
        for adapter in candidates:
            channel = next((c for c in adapter.list_channels() if c.key == channel_key), None)
            if channel is None:
                continue
            cats = adapter.category_options(channel)
            if not cats:
                raise FetchError(
                    f"通道 {channel_key} 没有分类维度，不能扫榜；"
                    "直接用 rank --channel 抓取即可。"
                )
            results: list[tuple[str, RankResult]] = []
            for idx, (cat_id, cat_name) in enumerate(cats):
                if idx:
                    time.sleep(delay)
                merged = dict(options or {})
                merged["category_id"] = cat_id
                try:
                    res = adapter.fetch_rank(
                        channel, self.client, page=1, limit=limit, options=merged
                    )
                except NotImplementedError as exc:
                    raise FetchError(str(exc)) from exc
                except (ValueError, HttpError) as exc:
                    results.append((cat_name, RankResult(
                        channel=channel, items=[], limit=limit, error=str(exc)
                    )))
                    continue
                results.append((cat_name, res))
            return channel, results
        known = ", ".join(k for _, c in self.list_channels(site) for k in [c.key])
        raise FetchError(f"未知的榜单通道：{channel_key}。可用通道：{known}")

    def merge_sweep(
        self,
        channel_key: str,
        *,
        site: str | None = None,
        limit: int = 10,
        options: dict | None = None,
        delay: float = 0.3,
    ) -> tuple[Channel, list[RankItem], list[tuple[str, RankResult]]]:
        """扫榜后合并：把各分类的作品汇总成一张总表。

        番茄的新书榜在平台上只按分类提供，没有跨分类的「总榜」页。
        这里在 sweep 的基础上把各分类结果合并，按热度（score）降序重排，
        给用户一个「一个榜」的观感；同时保留每个作品的原分类。

        返回 (通道, 合并后的条目列表, 原始分类结果)。
        """
        channel, results = self.sweep(
            channel_key, site=site, limit=limit, options=options, delay=delay
        )
        merged: list[RankItem] = []
        for cat_name, res in results:
            for item in res.items:
                if not item.category:
                    item.category = cat_name
                merged.append(item)
        merged.sort(key=_hotness_key, reverse=True)
        for idx, item in enumerate(merged, start=1):
            item.rank = idx
        return channel, merged, results

    def sweep_categories(self, channel_key: str, *, site: str | None = None) -> list[tuple[str, str]]:
        """列出某通道可用于扫榜的分类。"""
        from .adapters import ADAPTERS
        for adapter in sorted(ADAPTERS, key=lambda a: a.priority):
            if site and adapter.name != site:
                continue
            for channel in adapter.list_channels():
                if channel.key == channel_key:
                    return adapter.category_options(channel)
        return []

    # -- 搜索 -------------------------------------------------------------
    def search(
        self,
        keyword: str,
        *,
        site: str | None = None,
        limit: int = 20,
    ) -> list[RankItem]:
        """在支持搜索的站点里检索作品。"""
        from .adapters import ADAPTERS
        results: list[RankItem] = []
        errors: list[str] = []
        for adapter in sorted(ADAPTERS, key=lambda a: a.priority):
            if not adapter.supports_search:
                continue
            if site and adapter.name != site:
                continue
            try:
                results.extend(adapter.search(keyword, self.client, limit=limit))
            except (ValueError, HttpError, NotImplementedError) as exc:
                errors.append(f"{adapter.name}: {exc}")
            if len(results) >= limit:
                break
        if not results and errors:
            raise FetchError("搜索失败：" + "；".join(errors))
        if not results and not errors:
            raise FetchError("当前没有支持搜索的站点适配器。")
        return results[:limit]

    # -- 作品信息 ---------------------------------------------------------
    def inspect(self, url: str) -> BookInfo:
        adapter = find_adapter(url)
        if adapter is None:
            raise FetchError(f"没有适配器能处理该链接：{url}")
        try:
            book = adapter.fetch_book(url, self.client)
        except HttpError as exc:
            raise FetchError(str(exc)) from exc
        except ValueError as exc:
            raise FetchError(str(exc)) from exc
        return book

    # -- 抓取 -------------------------------------------------------------
    def run(
        self,
        url: str,
        *,
        select: str = "all",
        start: int | None = None,
        end: int | None = None,
        limit: int | None = None,
        delay: float = 0.0,
        on_progress=None,  # noqa: ANN001
    ) -> FetchResult:
        started = time.monotonic()
        adapter = find_adapter(url)
        if adapter is None:
            raise FetchError(f"没有适配器能处理该链接：{url}")
        try:
            book = adapter.fetch_book(url, self.client)
        except HttpError as exc:
            raise FetchError(str(exc)) from exc
        except ValueError as exc:
            raise FetchError(str(exc)) from exc

        targets = self._select_chapters(book.chapters, select, start, end, limit)
        if not targets:
            raise FetchError("筛选后没有需要抓取的章节，请检查范围参数。")

        out_dir = self.output_root / _safe_name(book.title)
        out_dir.mkdir(parents=True, exist_ok=True)

        saved: list[dict] = []
        failed: list[dict] = []
        total = len(targets)
        for position, chapter in enumerate(targets, start=1):
            if on_progress:
                on_progress(position, total, chapter)
            try:
                content = adapter.fetch_chapter(book, chapter, self.client)
            except (ValueError, HttpError) as exc:
                failed.append({"index": chapter.index, "title": chapter.title,
                               "url": chapter.url, "error": str(exc)})
                if delay:
                    time.sleep(delay)
                continue

            filename = f"{chapter.index:04d}-{_safe_name(content.title or chapter.title)}.txt"
            path = out_dir / filename
            path.write_text(self._render(content, chapter), encoding="utf-8")
            saved.append({
                "index": chapter.index,
                "title": content.title or chapter.title,
                "file": filename,
                "chars": content.word_count,
                "source": content.source,
            })
            if delay:
                time.sleep(delay)

        meta = {
            "title": book.title,
            "author": book.author,
            "site": book.site,
            "sourceUrl": book.source_url,
            "totalChapters": book.chapter_count,
            "fetched": len(saved),
            "failed": len(failed),
            "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "chapters": saved,
            "errors": failed,
        }
        # 分批抓取时合并历史记录，避免后一次覆盖前面的清单
        meta_path = out_dir / "_fetch_meta.json"
        previous = self._load_meta(meta_path)
        if previous:
            by_index: dict[int, dict] = {}
            for item in previous.get("chapters", []):
                if isinstance(item, dict) and isinstance(item.get("index"), int):
                    by_index[item["index"]] = item
            for item in saved:
                by_index[item["index"]] = item
            merged = [by_index[k] for k in sorted(by_index)]
            meta["chapters"] = merged
            meta["fetched"] = len(merged)
            errors = {e.get("index"): e for e in previous.get("errors", [])
                      if isinstance(e, dict)}
            for item in failed:
                errors[item["index"]] = item
            # 本次成功的章节不应再记为失败
            for item in merged:
                errors.pop(item["index"], None)
            meta["errors"] = [errors[k] for k in sorted(errors, key=lambda x: (x is None, x))]
            meta["failed"] = len(meta["errors"])
            meta["firstFetchedAt"] = previous.get("fetchedAt") or meta["fetchedAt"]

        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        return FetchResult(
            book=book,
            saved=saved,
            failed=failed,
            output_dir=str(out_dir),
            elapsed=time.monotonic() - started,
        )

    @staticmethod
    def _load_meta(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _render(content: ChapterContent, chapter: ChapterRef) -> str:
        header = content.title or chapter.title
        body = content.text
        # 上游正文有时把标题重复在首行，去掉避免与文件头重复
        first_line = body.split("\n", 1)[0].strip()
        if first_line and (first_line == header or first_line == chapter.title):
            body = body.split("\n", 1)[1].lstrip("\n") if "\n" in body else ""
        return f"{header}\n\n{body}\n"

    @staticmethod
    def _select_chapters(
        chapters: list[ChapterRef],
        select: str,
        start: int | None,
        end: int | None,
        limit: int | None,
    ) -> list[ChapterRef]:
        mode = (select or "all").strip().lower()
        if mode == "all":
            picked = list(chapters)
        elif mode == "range":
            if start is None and end is None:
                raise FetchError("range 模式需要 --start 或 --end 参数。")
            lo = 1 if start is None else max(1, start)
            hi = len(chapters) if end is None else min(len(chapters), end)
            if lo > hi:
                raise FetchError(f"章节范围无效：{lo} 到 {hi}")
            picked = [c for c in chapters if lo <= c.index <= hi]
        elif mode == "first":
            picked = chapters[: (limit or 1)]
        elif mode == "last":
            picked = chapters[-(limit or 1):]
        else:
            raise FetchError(f"不支持的选取模式：{select}（可用 all/range/first/last）")

        if limit is not None and mode == "all":
            picked = picked[:limit]
        return picked
