#!/usr/bin/env python3
"""Validate that the character-state dashboard stays current and non-historical."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


HEADING = re.compile(r"^## (.+?)\s*$", re.M)
FIELD = re.compile(r"^- \*\*(.+?)\*\*：\s*(.*)$", re.M)
CHAPTER_REFERENCE = re.compile(r"第\s*\d+\s*章")
RECENT_BASIS = re.compile(r"^第\s*\d+\s*章。?$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workspace_root",
        nargs="?",
        default=".",
        help="Project root containing 控制台/角色状态.md.",
    )
    return parser.parse_args()


def role_sections(text: str) -> list[tuple[str, str]]:
    headings = list(HEADING.finditer(text))
    sections: list[tuple[str, str]] = []
    for index, heading in enumerate(headings):
        name = heading.group(1).strip()
        if name == "使用规则":
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        sections.append((name, text[heading.end() : end]))
    return sections


def validate_text(text: str) -> list[str]:
    errors: list[str] = []

    if "## 使用规则" not in text:
        errors.append("缺少“## 使用规则”")
    if "**本章变化依据**" in text:
        errors.append("仍存在“本章变化依据”，应改为单一的“最近更新依据”")

    roles = role_sections(text)
    if not roles:
        errors.append("没有可识别的角色状态条目")
        return errors

    for role, body in roles:
        fields = FIELD.findall(body)
        names = [name.strip() for name, _ in fields]
        duplicates = [name for name, count in Counter(names).items() if count > 1]
        if duplicates:
            errors.append(f"角色“{role}”存在重复字段：{duplicates}")

        basis_values = [value.strip() for name, value in fields if name.strip() == "最近更新依据"]
        if len(basis_values) != 1:
            errors.append(
                f"角色“{role}”必须恰有一个“最近更新依据”，实际为{len(basis_values)}个"
            )
            continue

        basis = basis_values[0]
        if not RECENT_BASIS.fullmatch(basis):
            errors.append(
                f"角色“{role}”的“最近更新依据”只能填写一个章节号，实际为“{basis}”"
            )

        body_without_basis = re.sub(
            r"^- \*\*最近更新依据\*\*：.*$", "", body, flags=re.M
        )
        references = CHAPTER_REFERENCE.findall(body_without_basis)
        if references:
            errors.append(
                f"角色“{role}”的状态字段仍含章节号{references}，应改写为当前快照"
            )

    return errors


def main() -> int:
    root = Path(parse_args().workspace_root).resolve()
    path = root / "控制台" / "角色状态.md"
    if not path.is_file():
        print(f"角色状态文件校验失败：缺少 {path}")
        return 1

    errors = validate_text(path.read_text(encoding="utf-8-sig"))
    if errors:
        print("角色状态文件校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print("角色状态文件校验通过：角色条目、最近更新依据和当前快照结构均符合要求。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
