#!/usr/bin/env python3
"""Validate that the novel progress dashboard stays compact and current."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


REQUIRED_HEADINGS = [
    "## 1. 当前承接",
    "## 2. 近期情节流",
    "## 3. 最新定稿复盘",
    "## 4. 下一步与阶段缺口",
    "## 5. 里程碑日志",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workspace_root",
        nargs="?",
        default=".",
        help="Project root containing 3-大纲, 4-正文 and 控制台.",
    )
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    next_heading = re.search(r"^## \d+\. ", text[start + len(heading) :], re.M)
    if not next_heading:
        return text[start:]
    end = start + len(heading) + next_heading.start()
    return text[start:end]


def current_stage_name(outline_text: str) -> str | None:
    match = re.search(
        r"^## 当前阶段\s*$([\s\S]*?)(?=^## |\Z)", outline_text, re.M
    )
    if not match:
        return None
    stage = re.search(r"^### (.+?)\s*$", match.group(1), re.M)
    return stage.group(1).strip() if stage else None


def main() -> int:
    root = Path(parse_args().workspace_root).resolve()
    progress_path = root / "控制台" / "进度.md"
    body_dir = root / "4-正文"
    outline_path = root / "3-大纲" / "3.1_全书结构总纲.md"
    errors: list[str] = []

    if not progress_path.is_file():
        print(f"FAIL: missing {progress_path}")
        return 1
    if not body_dir.is_dir():
        print(f"FAIL: missing {body_dir}")
        return 1

    progress = read_text(progress_path)
    for heading in REQUIRED_HEADINGS:
        if heading not in progress:
            errors.append(f"缺少固定分节：{heading}")

    chapter_files: dict[int, list[Path]] = {}
    chapter_pattern = re.compile(r"^第(\d+)章_定稿_.+\.md$")
    for path in body_dir.glob("第*章_定稿_*.md"):
        match = chapter_pattern.match(path.name)
        if match:
            chapter_files.setdefault(int(match.group(1)), []).append(path)

    if not chapter_files:
        errors.append("4-正文中没有可识别的定稿章节")
    else:
        duplicates = [number for number, files in chapter_files.items() if len(files) > 1]
        if duplicates:
            errors.append(f"存在重复定稿章节：{duplicates}")

        latest = max(chapter_files)
        current = re.search(r"\*\*当前章节\*\*：第(\d+)章", progress)
        if not current or int(current.group(1)) != latest:
            actual = current.group(1) if current else "缺失"
            errors.append(f"当前章节应为第{latest}章，实际为{actual}")

        recent_text = section(progress, "## 2. 近期情节流")
        recent = [int(value) for value in re.findall(r"^- \*\*第(\d+)章\*\*", recent_text, re.M)]
        expected_recent = sorted(chapter_files)[-3:]
        if recent != expected_recent:
            errors.append(f"近期情节流应为{expected_recent}，实际为{recent}")

        latest_path = chapter_files[latest][0]
        expected_count = len(re.sub(r"\s", "", read_text(latest_path)))
        recorded_count = re.search(r"\*\*字数与状态\*\*：(\d+)\s*/", progress)
        if not recorded_count or int(recorded_count.group(1)) != expected_count:
            actual = recorded_count.group(1) if recorded_count else "缺失"
            errors.append(f"最新章字数应为{expected_count}，实际为{actual}")

    next_section = section(progress, "## 4. 下一步与阶段缺口")
    if re.search(r"^\s*- \[[xX]\]", next_section, re.M):
        errors.append("下一步与阶段缺口中仍有已完成待办 `[x]`")

    core_tasks = len(re.findall(r"^- \*\*下一章核心任务\*\*：", next_section, re.M))
    if core_tasks != 1:
        errors.append(f"下一章核心任务必须恰好一项，实际为{core_tasks}项")

    recent_actions = re.search(
        r"^- \*\*近期行动\*\*：\s*$([\s\S]*?)(?=^- \*\*阶段完成缺口\*\*：)",
        next_section,
        re.M,
    )
    recent_count = (
        len(re.findall(r"^\s+- \[ \]", recent_actions.group(1), re.M))
        if recent_actions
        else 0
    )
    if not 1 <= recent_count <= 3:
        errors.append(f"近期行动应保留1至3项，实际为{recent_count}项")

    stage_gaps = re.search(
        r"^- \*\*阶段完成缺口\*\*：\s*$([\s\S]*?)(?=^- \*\*持续约束\*\*：)",
        next_section,
        re.M,
    )
    gap_count = (
        len(re.findall(r"^\s+- \[ \]", stage_gaps.group(1), re.M))
        if stage_gaps
        else 0
    )
    if gap_count > 3:
        errors.append(f"阶段完成缺口不得超过3项，实际为{gap_count}项")

    if outline_path.is_file():
        expected_stage = current_stage_name(read_text(outline_path))
        recorded_stage = re.search(r"^- \*\*当前阶段\*\*：(.+?)。?\s*$", next_section, re.M)
        actual_stage = recorded_stage.group(1).rstrip("。").strip() if recorded_stage else None
        if expected_stage and actual_stage != expected_stage:
            errors.append(f"当前阶段应为“{expected_stage}”，实际为“{actual_stage or '缺失'}”")

    milestone_text = section(progress, "## 5. 里程碑日志")
    milestones = re.findall(r"^- \[已完成\]", milestone_text, re.M)
    if len(milestones) > 10:
        errors.append(f"里程碑超过10条，当前为{len(milestones)}条，应合并同类事件")
    if re.search(r"^- \[已完成\].*第\d+章.*定稿", milestone_text, re.M):
        errors.append("里程碑中存在逐章定稿记录")

    recent_numbers = re.findall(r"^- \*\*第(\d+)章\*\*", section(progress, "## 2. 近期情节流"), re.M)
    repeated = [number for number, count in Counter(recent_numbers).items() if count > 1]
    if repeated:
        errors.append(f"近期情节流存在重复章节：{repeated}")

    if errors:
        print("进度文件校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print("进度文件校验通过：当前章节、最近三章、字数、阶段、待办和里程碑结构均符合要求。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
