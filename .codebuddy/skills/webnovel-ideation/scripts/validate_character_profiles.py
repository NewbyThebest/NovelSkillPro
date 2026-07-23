#!/usr/bin/env python3
"""Validate field grouping in the main character profile document."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


CHARACTER_HEADING = re.compile(r"^###\s+(.+?)\s*$")
SECTION_HEADING = re.compile(r"^##(?!#)\s+")
FIELD_LINE = re.compile(r"^-\s+\*\*(.+?)\*\*[：:]\s*(.*)$")
NUMBERED_ITEM = re.compile(r"^\s{2,}(\d+)\.\s+\S")


def validate(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    errors: list[str] = []
    character: str | None = None
    fields: dict[str, int] = {}

    for index, line in enumerate(lines):
        line_number = index + 1

        heading = CHARACTER_HEADING.match(line)
        if heading:
            character = heading.group(1)
            fields = {}
            continue

        if SECTION_HEADING.match(line):
            character = None
            fields = {}
            continue

        if character is None:
            continue

        field = FIELD_LINE.match(line)
        if not field:
            continue

        name, inline_value = field.groups()
        if name in fields:
            errors.append(
                f"第 {line_number} 行：角色“{character}”的字段“{name}”重复出现，"
                f"首次位于第 {fields[name]} 行。"
            )
        else:
            fields[name] = line_number

        if inline_value:
            continue

        item_numbers: list[int] = []
        cursor = index + 1
        while cursor < len(lines):
            numbered = NUMBERED_ITEM.match(lines[cursor])
            if numbered:
                item_numbers.append(int(numbered.group(1)))
                cursor += 1
                continue
            break

        if len(item_numbers) < 2:
            errors.append(
                f"第 {line_number} 行：角色“{character}”的多项字段“{name}”"
                "应至少包含两个编号项；只有一项时应写在字段名后。"
            )
        elif item_numbers != list(range(1, len(item_numbers) + 1)):
            errors.append(
                f"第 {line_number} 行：角色“{character}”的字段“{name}”"
                "编号必须从 1 开始连续递增。"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="检查主要角色设定表的字段聚合格式。")
    parser.add_argument("path", type=Path, help="主要角色设定表路径")
    args = parser.parse_args()

    if not args.path.is_file():
        print(f"文件不存在：{args.path}", file=sys.stderr)
        return 2

    errors = validate(args.path)
    if errors:
        print("角色设定表格式校验失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("角色设定表格式校验通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
