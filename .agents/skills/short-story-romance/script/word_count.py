#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章节/全篇字数统计（中文短篇常用：不含空白字符的可见字符数）。
用法:
  python3 script/word_count.py chapters/chapter_01.md
  python3 script/word_count.py chapters/*.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _strip_yaml_front_matter(text: str) -> str:
    if not text.startswith("---"):
        return text
    m = re.match(r"^---\s*\n.*?\n---\s*\n", text, flags=re.DOTALL)
    if m:
        return text[m.end() :]
    return text


def _strip_fenced_code_blocks(text: str) -> str:
    return re.sub(r"^```.*?^```\s*", "", text, flags=re.DOTALL | re.MULTILINE)


def count_chars_no_whitespace(text: str) -> int:
    """与常见「字数（不计空格）」一致：去掉所有空白后计长度。"""
    return len(re.sub(r"\s+", "", text, flags=re.UNICODE))


def analyze_file(path: Path, strip_md: bool) -> tuple[str, int]:
    raw = path.read_text(encoding="utf-8")
    body = _strip_yaml_front_matter(raw)
    body = _strip_fenced_code_blocks(body)
    if strip_md:
        body = re.sub(r"[#>*_`\[\]()\\|-]", "", body)
    n = count_chars_no_whitespace(body)
    return path.as_posix(), n


def chapter_band_ok(n: int, low: int, high: int) -> str:
    if n < low:
        return f"低于单章下限（<{low}）"
    if n > high:
        return f"高于单章上限（>{high}）"
    return "符合单章区间"


def main() -> int:
    p = argparse.ArgumentParser(description="统计 Markdown 章节字数（不含空白）。")
    p.add_argument(
        "paths",
        nargs="+",
        help="章节 .md 路径，可多个（如全章 glob）",
    )
    p.add_argument(
        "--strip-md",
        action="store_true",
        help="粗略去掉常见 Markdown 符号后再统计（可选）",
    )
    p.add_argument(
        "--low",
        type=int,
        default=1000,
        help="单章字数下限（默认 1000，与 SKILL 一致）",
    )
    p.add_argument(
        "--high",
        type=int,
        default=1500,
        help="单章字数上限（默认 1500）",
    )
    args = p.parse_args()

    rows: list[tuple[str, int]] = []
    for s in args.paths:
        path = Path(s)
        if not path.is_file():
            print(f"跳过（非文件）: {path}", file=sys.stderr)
            continue
        rows.append(analyze_file(path, args.strip_md))

    if not rows:
        print("未找到可统计的文件。", file=sys.stderr)
        return 1

    total = 0
    for fp, n in rows:
        total += n
        band = chapter_band_ok(n, args.low, args.high)
        print(f"{fp}\t{n}\t{band}")

    if len(rows) > 1:
        print(f"---\n合计\t{total}\t（{len(rows)} 个文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
