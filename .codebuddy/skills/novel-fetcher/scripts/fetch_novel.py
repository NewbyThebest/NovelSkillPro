#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""novel-fetcher 命令行入口。

用法示例：
    # 查看作品信息与目录（不下载）
    python fetch_novel.py inspect "<作品链接>"

    # 抓前 3 章
    python fetch_novel.py fetch "<作品链接>" --first 3

    # 抓指定章节范围
    python fetch_novel.py fetch "<作品链接>" --range 10-20

    # 抓整本
    python fetch_novel.py fetch "<作品链接>" --all

    # 自检密码学原语
    python fetch_novel.py selftest
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from novel_fetch import __version__  # noqa: E402
from novel_fetch.fetcher import FetchError, Fetcher  # noqa: E402


def _default_output_root() -> Path:
    """默认输出到工作区的 .temp/novel-fetch/。

    脚本路径为 <root>/.agents/skills/novel-fetcher/scripts/fetch_novel.py，
    因此 parents[0]=scripts, [1]=novel-fetcher, [2]=skills, [3]=.agents, [4]=工作区根。
    """
    here = Path(__file__).resolve()
    if len(here.parents) > 4 and (here.parents[4] / ".agents").is_dir():
        return here.parents[4] / ".temp" / "novel-fetch"
    return Path.cwd() / ".temp" / "novel-fetch"


def _parse_range(value: str) -> tuple[int | None, int | None]:
    raw = value.strip()
    if "-" not in raw:
        try:
            n = int(raw)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("范围格式应为 10-20 或单个数 5") from exc
        return n, n
    left, _, right = raw.partition("-")
    try:
        start = int(left) if left.strip() else None
        end = int(right) if right.strip() else None
    except ValueError as exc:
        raise argparse.ArgumentTypeError("范围格式应为 10-20，允许省略一端") from exc
    return start, end


def cmd_inspect(args: argparse.Namespace) -> int:
    with Fetcher(output_root=Path(args.output)) as fetcher:
        try:
            book = fetcher.inspect(args.url)
        except FetchError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 2
        print(f"作品：{book.title}")
        if book.author:
            print(f"作者：{book.author}")
        print(f"站点：{book.site}")
        meta_bits = []
        if book.category:
            meta_bits.append(f"分类：{book.category}")
        if book.status:
            meta_bits.append(f"状态：{book.status}")
        if book.word_count:
            meta_bits.append(f"字数：{book.word_count}")
        if book.score:
            meta_bits.append(f"阅读量：{book.score}")
        if meta_bits:
            print("  ".join(meta_bits))
        if book.last_chapter:
            print(f"最新章节：{book.last_chapter}")
        if book.synopsis:
            print(f"简介：{book.synopsis}")
        print(f"目录：{book.chapter_count} 章")
        for chapter in book.chapters[:10]:
            print(f"  {chapter.index:>5}. {chapter.title}")
        if book.chapter_count > 10:
            print(f"  ...（其余 {book.chapter_count - 10} 章略）")
        print(f"\n输出目录将为：{Path(args.output) / book.title}")
    return 0


def _print_rank_items(items, *, show_intro: bool = False) -> None:
    for item in items:
        head = f"  {item.rank:>3}. " if item.rank else "  - "
        line = f"{head}{item.title}"
        if item.author:
            line += f"　作者：{item.author}"
        extras = []
        if item.category and item.category != "None":
            extras.append(item.category)
        if item.status and item.status != "None":
            extras.append(item.status)
        if item.word_count:
            # 部分站点（如起点）的字段自带"字"后缀，避免重复追加
            word = item.word_count.strip()
            extras.append(word if word.endswith("字") else f"{word}字")
        if item.score:
            extras.append(f"阅读{item.score}")
        if extras:
            line += "　[" + " / ".join(extras) + "]"
        print(line)
        if item.latest_chapter:
            print(f"      最新章节：{item.latest_chapter}")
        if show_intro and item.intro:
            intro = item.intro.replace("\n", " ")
            print(f"      简介：{intro[:100]}{'...' if len(intro) > 100 else ''}")
        if item.url:
            print(f"      {item.url}")


def cmd_rank(args: argparse.Namespace) -> int:
    if args.list_categories:
        with Fetcher(output_root=Path(args.output)) as fetcher:
            cats = fetcher.sweep_categories(args.channel, site=args.site)
        if not cats:
            print(f"通道 {args.channel} 没有分类维度（或通道不存在）。")
            return 0
        print(f"通道 {args.channel} 可用于扫榜的分类（{len(cats)} 个）：")
        for cat_id, cat_name in cats:
            print(f"  {cat_id:<8} {cat_name}")
        return 0

    if args.merge and not args.sweep:
        print("❌ --merge 需要配合 --sweep 使用。", file=sys.stderr)
        return 1

    if args.sweep:
        if not args.channel:
            print("❌ 扫榜需要 --channel 指定通道。", file=sys.stderr)
            return 1
        options = {}
        if args.gender is not None:
            options["gender"] = args.gender
        with Fetcher(output_root=Path(args.output)) as fetcher:
            try:
                if args.merge:
                    channel, merged, results = fetcher.merge_sweep(
                        args.channel, site=args.site, limit=args.limit,
                        options=options or None,
                    )
                else:
                    channel, results = fetcher.sweep(
                        args.channel, site=args.site, limit=args.limit,
                        options=options or None,
                    )
                    merged = None
            except FetchError as exc:
                print(f"❌ {exc}", file=sys.stderr)
                return 2

        if merged is not None:
            failed = [name for name, r in results if r.error]
            print(f"合并榜：{channel.name}（{channel.key}）"
                  f"　分类 {len(results)} 个　作品 {len(merged)} 条"
                  f"　每类最多 {args.limit} 条")
            print(f"（各分类已合并，按热度降序重排；分类列标明每本所属分类）")
            print()
            _print_rank_items(merged, show_intro=args.intro)
            if failed:
                print(f"\n（{len(failed)} 个分类抓取失败：{'、'.join(failed)}）")
            return 0

        total = sum(r.count for _, r in results)
        failed = [name for name, r in results if r.error]
        print(f"扫榜：{channel.name}（{channel.key}）"
              f"　分类 {len(results)} 个　作品 {total} 条"
              f"　每类最多 {args.limit} 条")
        print()
        for cat_name, res in results:
            if res.error:
                print(f"── {cat_name}　（失败：{res.error}）")
                continue
            print(f"── {cat_name}　{res.count} 条")
            _print_rank_items(res.items, show_intro=args.intro)
            print()
        if failed:
            print(f"（{len(failed)} 个分类抓取失败：{'、'.join(failed)}）")
        return 0

    if args.list_channels:
        with Fetcher(output_root=Path(args.output)) as fetcher:
            rows = fetcher.list_channels(site=args.site)
            if not rows:
                print("当前没有站点提供榜单通道。")
                return 0
            current = None
            for adapter_name, channel in rows:
                if adapter_name != current:
                    print(f"\n[{adapter_name}]")
                    current = adapter_name
                pageable = "可翻页" if channel.pageable else "单页"
                group = f"{channel.group} / " if channel.group else ""
                print(f"  {channel.key:<22} {channel.name}（{group}{pageable}）")
                if channel.description:
                    print(f"      {channel.description}")
        return 0

    if not args.channel:
        print("❌ 请用 --channel 指定榜单通道；用 --list-channels 查看全部可用通道。",
              file=sys.stderr)
        return 1

    options = {}
    if args.category:
        options["category_id"] = args.category
    if args.gender is not None:
        options["gender"] = args.gender

    with Fetcher(output_root=Path(args.output)) as fetcher:
        try:
            result = fetcher.rank(
                args.channel, site=args.site, page=args.page,
                limit=args.limit, options=options or None,
            )
        except FetchError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 2
        print(f"榜单：{result.channel.name}（{result.channel.key}）"
              f"　第 {result.page} 页　共 {result.count} 条")
        print()
        _print_rank_items(result.items, show_intro=args.intro)
        if result.has_more:
            print(f"\n（还有更多，用 --page {result.page + 1} 翻页）")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    with Fetcher(output_root=Path(args.output)) as fetcher:
        try:
            items = fetcher.search(args.keyword, site=args.site, limit=args.limit)
        except FetchError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 2
        if not items:
            print(f"未找到与“{args.keyword}”相关的作品。")
            return 0
        print(f"关键词：{args.keyword}　共 {len(items)} 条")
        print()
        _print_rank_items(items, show_intro=args.intro or True)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    if args.all:
        select, start, end, limit = "all", None, None, None
    elif args.first:
        select, start, end, limit = "first", None, None, args.first
    elif args.last:
        select, start, end, limit = "last", None, None, args.last
    elif args.range:
        start, end = _parse_range(args.range)
        select, limit = "range", None
    else:
        # 未指定范围时默认只抓前 3 章，避免误抓整本
        select, start, end, limit = "first", None, None, 3
        print("提示：未指定抓取范围，默认只抓前 3 章。"
              "抓整本请显式使用 --all。", file=sys.stderr)

    def progress(position: int, total: int, chapter) -> None:  # noqa: ANN001
        print(f"[{position}/{total}] {chapter.title}", file=sys.stderr)

    with Fetcher(output_root=Path(args.output)) as fetcher:
        try:
            result = fetcher.run(
                args.url,
                select=select,
                start=start,
                end=end,
                limit=limit,
                delay=args.delay,
                on_progress=progress,
            )
        except FetchError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 2
        print()
        print(result.summary())
        if result.failed and not result.saved:
            return 3
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    from novel_fetch import crypto
    print("密码学原语自检：")
    results = crypto.selftest()
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
    from novel_fetch.htmlparse import parse_html
    doc = parse_html('<div id="list"><a href="/1">第一章</a></div>')
    ok = len(doc.select("#list a")) == 1
    print(f"  {'✅' if ok else '❌'} HTML 选择器")
    results.append(("html", ok))
    return 0 if all(ok for _, ok in results) else 1


def cmd_sites(_args: argparse.Namespace) -> int:
    from novel_fetch.adapters import ADAPTERS
    print("已注册的站点适配器：")
    for adapter in sorted(ADAPTERS, key=lambda a: a.priority):
        domains = ", ".join(adapter.domains) if adapter.domains else "（任意站点，兜底）"
        print(f"  {adapter.name:<12} 优先级 {adapter.priority:<5} {domains}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_novel",
        description="多站点小说正文抓取工具（零依赖，仅用 Python 标准库）",
    )
    parser.add_argument("--version", action="version", version=f"novel-fetcher {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="查看作品信息、简介与目录，不下载")
    p_inspect.add_argument("url", help="作品目录页链接")
    p_inspect.add_argument("--output", default=str(_default_output_root()), help="输出根目录")
    p_inspect.set_defaults(func=cmd_inspect)

    p_rank = sub.add_parser("rank", help="抓取榜单或推荐位")
    p_rank.add_argument("--channel", help="榜单通道标识，如 rank_hot_male")
    p_rank.add_argument("--list-channels", action="store_true", help="列出所有可用榜单通道")
    p_rank.add_argument("--sweep", action="store_true",
                        help="扫榜：自动遍历该通道的全部分类并汇总")
    p_rank.add_argument("--merge", action="store_true",
                        help="配合 --sweep：把各分类合并成一张总表，按热度降序重排")
    p_rank.add_argument("--list-categories", action="store_true",
                        help="列出该通道可用于扫榜的分类")
    p_rank.add_argument("--site", help="限定站点适配器，如 fanqie")
    p_rank.add_argument("--category", help="分类 id（分类榜用）")
    p_rank.add_argument("--gender", type=int, choices=[0, 1], help="0=男频，1=女频")
    p_rank.add_argument("--page", type=int, default=1, help="页码，默认 1")
    p_rank.add_argument("--limit", type=int, default=20, help="每页条数，默认 20")
    p_rank.add_argument("--intro", action="store_true", help="同时显示简介")
    p_rank.add_argument("--output", default=str(_default_output_root()), help="输出根目录")
    p_rank.set_defaults(func=cmd_rank)

    p_search = sub.add_parser("search", help="按关键词搜索作品")
    p_search.add_argument("keyword", help="搜索关键词")
    p_search.add_argument("--site", help="限定站点适配器，如 fanqie")
    p_search.add_argument("--limit", type=int, default=10, help="返回条数，默认 10")
    p_search.add_argument("--intro", action="store_true", help="同时显示简介")
    p_search.add_argument("--output", default=str(_default_output_root()), help="输出根目录")
    p_search.set_defaults(func=cmd_search)

    p_fetch = sub.add_parser("fetch", help="抓取章节正文")
    p_fetch.add_argument("url", help="作品目录页链接")
    p_fetch.add_argument("--all", action="store_true", help="抓取整本")
    p_fetch.add_argument("--first", type=int, metavar="N", help="抓取前 N 章")
    p_fetch.add_argument("--last", type=int, metavar="N", help="抓取最后 N 章")
    p_fetch.add_argument("--range", metavar="A-B", help="抓取章节范围，如 10-20")
    p_fetch.add_argument("--limit", type=int, help="最多抓取 N 章")
    p_fetch.add_argument("--delay", type=float, default=0.0,
                         help="每章之间的额外延迟秒数（默认 0，站点限速已内置）")
    p_fetch.add_argument("--output", default=str(_default_output_root()), help="输出根目录")
    p_fetch.set_defaults(func=cmd_fetch)

    sub.add_parser("sites", help="列出站点适配器").set_defaults(func=cmd_sites)
    sub.add_parser("selftest", help="运行内置自检").set_defaults(func=cmd_selftest)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
