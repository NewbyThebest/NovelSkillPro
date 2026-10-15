#!/usr/bin/env python3
"""Validate that the character-state dashboard holds only current snapshots."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


HEADING = re.compile(r"^## (.+?)\s*$", re.M)
FIELD = re.compile(r"^- \*\*(.+?)\*\*：\s*(.*)$", re.M)
CHAPTER_REFERENCE = re.compile(r"第\s*\d+\s*章")


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


def documented_main_roles(root: Path) -> set[str] | None:
    """Return the role names documented in 2.3_主要角色设定表.md, or None if unavailable."""
    path = root / "2-设定" / "2.3_主要角色设定表.md"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig")
    names: set[str] = set()
    for raw in re.findall(r"^### (.+?)\s*$", text, re.M):
        name = raw.strip()
        # 标题形如“楚管事／楚渊”，两种叫法都算已建档
        for part in re.split(r"[／/]", name):
            part = part.strip()
            if part:
                names.add(part)
        names.add(name)
    return names


def validate_text(text: str, main_roles: set[str] | None = None) -> list[str]:
    errors: list[str] = []

    if "## 使用规则" not in text:
        errors.append("缺少“## 使用规则”")

    roles = role_sections(text)
    if not roles:
        errors.append("没有可识别的角色状态条目")
        return errors

    if main_roles is not None:
        for role, _ in roles:
            if role not in main_roles:
                errors.append(
                    f"角色“{role}”未在 `2-设定/2.3_主要角色设定表.md` 建档，"
                    "本文件只追踪已建档的主要角色"
                )

    for role, body in roles:
        fields = FIELD.findall(body)
        names = [name.strip() for name, _ in fields]
        duplicates = [name for name, count in Counter(names).items() if count > 1]
        if duplicates:
            errors.append(f"角色“{role}”存在重复字段：{duplicates}")

        references = CHAPTER_REFERENCE.findall(body)
        if references:
            errors.append(
                f"角色“{role}”的字段含章节号{references}，本文件只写当前快照，不写章节概念"
            )

    return errors


def main() -> int:
    root = Path(parse_args().workspace_root).resolve()
    path = root / "控制台" / "角色状态.md"
    if not path.is_file():
        print(f"角色状态文件校验失败：缺少 {path}")
        return 1

    errors = validate_text(
        path.read_text(encoding="utf-8-sig"), documented_main_roles(root)
    )
    if errors:
        print("角色状态文件校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print("角色状态文件校验通过：角色条目、字段结构与当前快照均符合要求。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
