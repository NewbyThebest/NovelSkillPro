#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Count chapter Chinese characters and report optional reference ranges."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


CHAPTER_FILE_RE = re.compile(r"^第0*(\d+)章.*\.md$", re.IGNORECASE)


def count_chinese_words(text: str) -> int:
    """Count Chinese characters and punctuation while excluding markup and ASCII words."""
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[a-zA-Z0-9]+", "", text)
    text = re.sub(r"[#*_`\[\]\(\)]+", "", text)
    return len(text)


def resolve_chapter_dir(explicit_dir: Path | None) -> Path:
    return explicit_dir if explicit_dir is not None else Path.cwd() / "4-正文"


def chapter_priority(path: Path) -> tuple[int, str]:
    """Prefer finalized prose when a draft and final file share a chapter number."""
    return (1 if "定稿" in path.stem else 0, path.name)


def collect_chapter_files(chapter_dir: Path) -> dict[int, Path]:
    if not chapter_dir.is_dir():
        return {}

    selected: dict[int, Path] = {}
    for path in chapter_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".md":
            continue
        match = CHAPTER_FILE_RE.match(path.name)
        if not match:
            continue
        chapter_num = int(match.group(1))
        current = selected.get(chapter_num)
        if current is None or chapter_priority(path) > chapter_priority(current):
            selected[chapter_num] = path
    return selected


def reference_label(min_chars: int | None, max_chars: int | None) -> str | None:
    if min_chars is None and max_chars is None:
        return None
    if min_chars is None:
        return f"不高于 {max_chars} 字"
    if max_chars is None:
        return f"不少于 {min_chars} 字"
    return f"{min_chars}-{max_chars} 字"


def reference_message(words: int, min_chars: int | None, max_chars: int | None) -> str | None:
    if min_chars is not None and words < min_chars:
        return f"低于当前参考下限 {min_chars} 字；请结合章节功能判断是否缺少必要推进、结果或场景。"
    if max_chars is not None and words > max_chars:
        return f"高于当前参考上限 {max_chars} 字；请检查是否存在重复信息或无效停留。"
    if min_chars is not None or max_chars is not None:
        return "位于当前参考范围内；这不是质量或定稿判定。"
    return None


def count_file(path: Path) -> int:
    return count_chinese_words(path.read_text(encoding="utf-8"))


def report_single_chapter(
    chapter_num: int,
    chapter_dir: Path,
    min_chars: int | None,
    max_chars: int | None,
) -> int:
    files = collect_chapter_files(chapter_dir)
    found_file = files.get(chapter_num)
    if found_file is None:
        print(f"错误：未在 {chapter_dir} 找到第 {chapter_num} 章 Markdown 文件。")
        return 1

    words = count_file(found_file)
    print(f"=== 第 {chapter_num} 章字数统计 ===")
    print(f"文件：{found_file.name}")
    print(f"字数：{words} 字")
    label = reference_label(min_chars, max_chars)
    if label:
        print(f"当前参考：{label}")
    message = reference_message(words, min_chars, max_chars)
    if message:
        print(f"提示：{message}")
    return 0


def report_all_chapters(
    chapter_dir: Path,
    min_chars: int | None,
    max_chars: int | None,
) -> int:
    files = collect_chapter_files(chapter_dir)
    if not chapter_dir.is_dir():
        print(f"错误：章节目录不存在：{chapter_dir}")
        return 1
    if not files:
        print(f"未在 {chapter_dir} 找到可识别的章节 Markdown 文件。")
        return 1

    stats = [(chapter_num, count_file(path)) for chapter_num, path in sorted(files.items())]
    total_words = sum(words for _, words in stats)
    average_words = total_words // len(stats)

    print("=== 章节字数统计报告 ===")
    for chapter_num, words in stats:
        print(f"第 {chapter_num:>4} 章：{words} 字")
    print()
    print(f"章节数：{len(stats)}")
    print(f"总字数：{total_words:,} 字")
    print(f"平均字数：{average_words:,} 字/章")

    label = reference_label(min_chars, max_chars)
    if label:
        print(f"当前参考：{label}")
    if min_chars is not None:
        below = [(chapter_num, words) for chapter_num, words in stats if words < min_chars]
        print(f"低于参考下限（{min_chars} 字）：" + ("无" if not below else ""))
        for chapter_num, words in below:
            print(f"- 第 {chapter_num} 章：{words} 字")
    if max_chars is not None:
        above = [(chapter_num, words) for chapter_num, words in stats if words > max_chars]
        print(f"高于参考上限（{max_chars} 字）：" + ("无" if not above else ""))
        for chapter_num, words in above:
            print(f"- 第 {chapter_num} 章：{words} 字")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="统计小说章节的中文字数；参考范围只用于辅助判断，不判定正文是否合格。"
    )
    parser.add_argument("chapter_num", type=int, nargs="?", help="要统计的章节号；省略时统计全部章节")
    parser.add_argument("chapter_dir", type=Path, nargs="?", help="章节目录；默认当前目录下的 4-正文")
    parser.add_argument("--chapter-dir", dest="chapter_dir_option", type=Path, help="章节目录，替代第二个位置参数")
    parser.add_argument("--min-chars", type=int, help="参考下限，不作为硬门槛")
    parser.add_argument("--max-chars", type=int, help="参考上限，不作为硬门槛")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.chapter_dir is not None and args.chapter_dir_option is not None:
        print("错误：章节目录只能通过位置参数或 --chapter-dir 指定一次。")
        return 2
    if args.min_chars is not None and args.min_chars < 0:
        print("错误：--min-chars 不能小于 0。")
        return 2
    if args.max_chars is not None and args.max_chars < 0:
        print("错误：--max-chars 不能小于 0。")
        return 2
    if (
        args.min_chars is not None
        and args.max_chars is not None
        and args.min_chars > args.max_chars
    ):
        print("错误：--min-chars 不能大于 --max-chars。")
        return 2

    chapter_dir = resolve_chapter_dir(args.chapter_dir_option or args.chapter_dir)
    if args.chapter_num is None:
        return report_all_chapters(chapter_dir, args.min_chars, args.max_chars)
    if args.chapter_num < 1:
        print("错误：章节号必须大于等于 1。")
        return 2
    return report_single_chapter(args.chapter_num, chapter_dir, args.min_chars, args.max_chars)


if __name__ == "__main__":
    raise SystemExit(main())
