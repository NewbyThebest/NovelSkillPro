#!/usr/bin/env python3
"""Validate that the foreshadowing tracker stays a single lean 待收回 table."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_HEADINGS = [
    "## 使用规则",
    "## 待收回伏笔",
]

COLUMNS = ["伏笔内容", "埋设章节", "预期收回", "备注"]

# 模板要求备注控制在两句话以内。
MAX_NOTE_SENTENCES = 2

CHAPTER_REFERENCE = re.compile(r"第\s*\d+\s*(?:[-—－]\s*\d+\s*)?章")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workspace_root",
        nargs="?",
        default=".",
        help="Project root containing 控制台/伏笔追踪.md.",
    )
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def table_rows(body: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if not cells or not any(cells):
            continue
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    start += len(heading)
    following = re.search(r"^## ", text[start:], re.M)
    return text[start:] if not following else text[start : start + following.start()]


def validate_text(text: str) -> list[str]:
    errors: list[str] = []

    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"缺少固定分节：{heading}")

    body = section(text, "## 待收回伏笔")
    rows = table_rows(body)
    if not rows:
        errors.append("待收回伏笔表没有任何条目")
        return errors

    header, entries = rows[0], rows[1:]
    if [cell.strip() for cell in header] != COLUMNS:
        errors.append(
            f"待收回伏笔表的列应为{COLUMNS}，实际为{[cell.strip() for cell in header]}"
        )

    if not entries:
        errors.append("待收回伏笔表只有表头，没有条目")
        return errors

    for index, cells in enumerate(entries, start=2):
        if len(cells) != len(COLUMNS):
            errors.append(f"第{index}行列数错误：{cells}")
            continue
        name, planted, expected, note = cells

        if not name or not planted:
            errors.append(f"第{index}行缺少伏笔内容或埋设章节")
        if not CHAPTER_REFERENCE.search(planted):
            errors.append(f"第{index}行埋设章节缺少规范的章节号：{planted}")
        if expected not in {"待定", "阶段内"}:
            errors.append(
                f"第{index}行预期收回只能是“待定”或“阶段内”，实际为“{expected}”"
            )

        sentences = len([part for part in re.split(r"[。！？]", note) if part.strip()])
        if sentences > MAX_NOTE_SENTENCES:
            errors.append(
                f"第{index}行备注{sentences}句，超过{MAX_NOTE_SENTENCES}句上限"
            )

    return errors


def main() -> int:
    root = Path(parse_args().workspace_root).resolve()
    path = root / "控制台" / "伏笔追踪.md"
    if not path.is_file():
        print(f"伏笔追踪校验失败：缺少 {path}")
        return 1

    errors = validate_text(read_text(path))
    if errors:
        print("伏笔追踪校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print("伏笔追踪校验通过：只保留待收回表，列结构与备注句数均符合要求。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
