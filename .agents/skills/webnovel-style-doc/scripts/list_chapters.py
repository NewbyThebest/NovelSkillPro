#!/usr/bin/env python3
"""列出参照作品的章节骨架：章号、章名、起止行号、字数。

用来快速看清参照作品有哪些章、各类场面分布在哪里，好挑出要通读的 15–30 章。

用法：
    python list_chapters.py <参照作品路径> [--json <输出文件>]

参照作品路径可以是单个 txt，也可以是一章一个文件的目录。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


CHAPTER_RE = re.compile(r"^\s*第\s*([0-9０-９一二三四五六七八九十百千两]+)\s*[章回节]")

DIGITS = "0123456789"
CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def parse_number(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    if all(ch in DIGITS for ch in text):
        return int(text)
    if all(ch in "０１２３４５６７８９" for ch in text):
        return int(text.translate(str.maketrans("０１２３４５６７８９", DIGITS)))

    total = 0
    section = 0
    for ch in text:
        if ch in CN_DIGITS:
            section = CN_DIGITS[ch]
        elif ch in CN_UNITS:
            unit = CN_UNITS[ch]
            total += (section or 1) * unit
            section = 0
        else:
            return None
    return total + section if (total or section) else None


def count_chars(text: str) -> int:
    return len(re.sub(r"\s|\u3000", "", text))


def scan_file(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split(newline)

    hits: list[tuple[int, str, int]] = []
    for index, line in enumerate(lines):
        matched = CHAPTER_RE.match(line)
        if not matched:
            continue
        number = parse_number(matched.group(1))
        if number is None:
            continue
        hits.append((index, line.strip(), number))

    chapters: list[dict] = []
    for order, (index, title, number) in enumerate(hits):
        end = hits[order + 1][0] if order + 1 < len(hits) else len(lines)
        body = newline.join(lines[index:end])
        chapters.append({
            "order": order + 1,
            "number": number,
            "title": title,
            "start_line": index + 1,
            "end_line": end,
            "chars": count_chars(body),
        })
    return chapters


def scan_dir(path: Path) -> list[dict]:
    files = sorted(p for p in path.iterdir() if p.is_file())
    chapters: list[dict] = []
    for order, item in enumerate(files, start=1):
        matched = CHAPTER_RE.match(item.stem) or re.search(r"第\s*([0-9０-９一二三四五六七八九十百千两]+)\s*[章回节]", item.stem)
        number = parse_number(matched.group(1)) if matched else None
        chapters.append({
            "order": order,
            "number": number if number is not None else order,
            "title": item.stem,
            "path": str(item),
            "chars": count_chars(item.read_text(encoding="utf-8", errors="replace")),
        })
    return chapters


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    source = Path(argv[1])
    if not source.exists():
        print(f"找不到参照作品：{source}")
        return 1

    chapters = scan_dir(source) if source.is_dir() else scan_file(source)
    if not chapters:
        print(f"没有识别出任何章节：{source}")
        print("章节标题需形如「第1章」「第一章」「第 12 回」。")
        return 1

    total = sum(item["chars"] for item in chapters)
    print(f"{source}  共 {len(chapters)} 章  {total:,} 字")
    print()
    print(f'{"序":>4}  {"章号":>5}  {"起-止":>13}  {"字数":>7}  章名')
    for item in chapters:
        span = f'{item["start_line"]}-{item["end_line"]}' if "start_line" in item else "-"
        print(f'{item["order"]:>4}  {item["number"]:>5}  {span:>13}  {item["chars"]:>7}  {item["title"][:34]}')

    if "--json" in argv:
        target = Path(argv[argv.index("--json") + 1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(chapters, ensure_ascii=False, indent=1), encoding="utf-8")
        print()
        print(f"已写出章节骨架：{target}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
