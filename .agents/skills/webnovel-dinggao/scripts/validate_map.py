#!/usr/bin/env python3
"""Validate that the novel spatial ledger stays structured and current."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_HEADINGS = [
    "## 维护边界",
    "## 区域索引",
    "## 地点索引",
    "## 已确认连通关系",
    "## 空间限制与通行条件",
    "## 未确认空间",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workspace_root",
        nargs="?",
        default=".",
        help="Project root containing 4-正文 and 控制台.",
    )
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def latest_finalized_chapter(body_dir: Path) -> tuple[int, str] | None:
    pattern = re.compile(r"^第(\d+)章_定稿_(.+)\.md$")
    chapters: dict[int, list[str]] = {}
    for path in body_dir.glob("第*章_定稿_*.md"):
        match = pattern.match(path.name)
        if match:
            chapters.setdefault(int(match.group(1)), []).append(match.group(2))

    if not chapters:
        return None

    duplicates = [number for number, titles in chapters.items() if len(titles) > 1]
    if duplicates:
        raise ValueError(f"存在重复定稿章节：{duplicates}")

    latest = max(chapters)
    return latest, chapters[latest][0]


def chapter_references(text: str) -> set[int]:
    references = {int(number) for number in re.findall(r"第(\d+)章", text)}
    for start, end in re.findall(r"第(\d+)\s*(?:—|－|-|至)\s*(\d+)章", text):
        references.update((int(start), int(end)))
    return references


def main() -> int:
    root = Path(parse_args().workspace_root).resolve()
    map_path = root / "控制台" / "地图.md"
    body_dir = root / "4-正文"
    errors: list[str] = []

    if not map_path.is_file():
        print(f"FAIL: missing {map_path}")
        return 1
    if not body_dir.is_dir():
        print(f"FAIL: missing {body_dir}")
        return 1

    try:
        latest_info = latest_finalized_chapter(body_dir)
    except ValueError as error:
        print(f"地图校验失败：\n- {error}")
        return 1

    if latest_info is None:
        print("地图校验失败：\n- 4-正文中没有可识别的定稿章节")
        return 1

    latest_number, latest_title = latest_info
    text = read_text(map_path)

    if not text.startswith("# 地图与空间事实"):
        errors.append("文件必须以 `# 地图与空间事实` 开头")

    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"缺少固定分节：{heading}")

    cutoff = re.search(r"^- \*\*事实截止\*\*：第(\d+)章《(.+?)》定稿后。?\s*$", text, re.M)
    if not cutoff:
        errors.append("缺少规范的事实截止行")
    else:
        cutoff_number = int(cutoff.group(1))
        cutoff_title = cutoff.group(2).strip()
        if cutoff_number != latest_number or cutoff_title != latest_title:
            errors.append(
                f"事实截止应为第{latest_number}章《{latest_title}》，"
                f"实际为第{cutoff_number}章《{cutoff_title}》"
            )

    future_chapter_refs = [
        number for number in chapter_references(text) if number > latest_number
    ]
    if future_chapter_refs:
        errors.append(f"地图引用了尚未定稿章节：{sorted(set(future_chapter_refs))}")

    if "只写定稿正文" not in text:
        errors.append("维护边界中缺少只采用定稿正文的事实约束")
    if "不得自行补" not in text:
        errors.append("维护边界中缺少不得自行补全空间关系的约束")
    if "人物当前" not in text or "角色状态" not in text:
        errors.append("维护边界中缺少地图与人物动态位置的职责区分")

    if errors:
        print("地图校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print("地图校验通过：事实截止、固定栏目、事实边界与未确认空间分层均符合要求。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
