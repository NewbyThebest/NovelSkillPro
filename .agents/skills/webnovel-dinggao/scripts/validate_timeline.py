#!/usr/bin/env python3
"""Validate that the novel timeline stays structured and current."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_HEADINGS = [
    "## 维护边界",
    "## 当前时间锚点",
    "## 已定稿时间段",
    "## 持续中的期限与固定时刻",
    "## 时间不确定项",
]

REQUIRED_CURRENT_FIELDS = [
    "当前章节",
    "当前时段",
    "当前事件位置",
    "最近明确时长",
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


def parse_period_ranges(text: str) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    heading_pattern = re.compile(
        r"^###\s+(.+?)（第(\d+)(?:[—-](\d+))?章）\s*$",
        re.M,
    )
    for match in heading_pattern.finditer(text):
        start = int(match.group(2))
        end = int(match.group(3) or start)
        ranges.append((start, end, match.group(1).strip()))
    return ranges


def main() -> int:
    root = Path(parse_args().workspace_root).resolve()
    timeline_path = root / "控制台" / "时间线.md"
    body_dir = root / "4-正文"
    errors: list[str] = []

    if not timeline_path.is_file():
        print(f"FAIL: missing {timeline_path}")
        return 1
    if not body_dir.is_dir():
        print(f"FAIL: missing {body_dir}")
        return 1

    try:
        latest_info = latest_finalized_chapter(body_dir)
    except ValueError as error:
        print(f"时间线校验失败：\n- {error}")
        return 1

    if latest_info is None:
        print("时间线校验失败：\n- 4-正文中没有可识别的定稿章节")
        return 1

    latest_number, latest_title = latest_info
    text = read_text(timeline_path)

    if not text.startswith("# 时间线"):
        errors.append("文件必须以 `# 时间线` 开头")

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

    current = re.search(r"^- \*\*当前章节\*\*：第(\d+)章《(.+?)》。?\s*$", text, re.M)
    if not current:
        errors.append("缺少规范的当前章节行")
    else:
        current_number = int(current.group(1))
        current_title = current.group(2).strip()
        if current_number != latest_number or current_title != latest_title:
            errors.append(
                f"当前章节应为第{latest_number}章《{latest_title}》，"
                f"实际为第{current_number}章《{current_title}》"
            )

    for field in REQUIRED_CURRENT_FIELDS:
        matches = re.findall(rf"^- \*\*{re.escape(field)}\*\*：.+$", text, re.M)
        if len(matches) != 1:
            errors.append(f"当前时间锚点中的“{field}”必须恰好一项，实际为{len(matches)}项")

    ranges = parse_period_ranges(text)
    if not ranges:
        errors.append("已定稿时间段中没有可识别的章节范围标题")
    else:
        previous_end = 0
        for start, end, label in ranges:
            if start > end:
                errors.append(f"时间段“{label}”章节范围倒置：第{start}—{end}章")
            if start <= previous_end:
                errors.append(f"时间段“{label}”与前一时间段重叠或倒序")
            if end > latest_number:
                errors.append(f"时间段“{label}”越过最新定稿第{latest_number}章")
            previous_end = max(previous_end, end)

        if not any(start <= latest_number <= end for start, end, _ in ranges):
            errors.append(f"已定稿时间段未覆盖最新定稿第{latest_number}章")

    future_chapter_refs = [
        int(number)
        for number in re.findall(r"第(\d+)章", text)
        if int(number) > latest_number
    ]
    if future_chapter_refs:
        errors.append(
            f"时间线引用了尚未定稿章节：{sorted(set(future_chapter_refs))}"
        )

    if "不得自行补" not in text:
        errors.append("维护边界中缺少不得自行补全时间的约束")

    if errors:
        print("时间线校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "时间线校验通过：事实截止、当前锚点、章节范围、固定栏目与定稿边界均符合要求。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
