#!/usr/bin/env python3
"""Validate the required protagonist dynamic-asset ledger."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_HEADINGS = (
    "## 当前概况",
    "## 事实截止",
    "## 1. 当前层级与承载状态",
    "## 2. 当前可调用能力与手段",
    "## 3. 当前持有",
)
CUTOFF = re.compile(r"^- \*\*章节\*\*：第\s*(\d+)\s*章《(.+?)》定稿后。?$", re.M)
SUMMARY = re.compile(r"^- \*\*概况\*\*：(.+?)\s*$", re.M)
NO_ASSETS_SUMMARY = "当前无需要追踪的动态资产"
FINAL_FILE = re.compile(r"^第(\d+)章_定稿_(.+)\.md$")
ABILITY_HEADING = re.compile(r"^#### (.+?)\s*$", re.M)
PLACEHOLDER_ABILITY_NAMES = {"能力或机制名称", "能力名称", "无已定稿项目"}
NAMED_BULLET = re.compile(r"^- \*\*(.+?)\*\*：\s*(.*?)\s*$", re.M)
EMPTY_VALUES = {
    "",
    "无",
    "无。",
    "不适用",
    "不适用。",
    "无已定稿项目",
    "无已定稿项目。",
    "[待填]",
    "[填写]",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workspace_root",
        nargs="?",
        default=".",
        help="Project root containing 控制台/主角能力与资源.md after the first final chapter.",
    )
    return parser.parse_args()


def latest_final(draft_dir: Path) -> tuple[int, str] | None:
    finals: list[tuple[int, str]] = []
    if not draft_dir.is_dir():
        return None
    for path in draft_dir.iterdir():
        match = FINAL_FILE.fullmatch(path.name)
        if match:
            finals.append((int(match.group(1)), match.group(2)))
    return max(finals, default=None, key=lambda item: item[0])


def section(text: str, heading: str, next_heading: str | None = None) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    start += len(heading)
    if next_heading is None:
        return text[start:]
    end = text.find(next_heading, start)
    return text[start:] if end < 0 else text[start:end]


def markdown_table_rows(body: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if not cells or not any(cells) or all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def named_entries(body: str, placeholder_names: set[str] | None = None) -> list[tuple[str, str]]:
    placeholders = placeholder_names or set()
    return [
        (name.strip(), value.strip())
        for name, value in NAMED_BULLET.findall(body)
        if name.strip() not in placeholders and value.strip() not in EMPTY_VALUES
    ]


def validate_text(text: str, latest: tuple[int, str] | None) -> list[str]:
    errors: list[str] = []

    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"缺少“{heading}”")

    summary_body = section(text, "## 当前概况", "## 事实截止")
    summary_matches = [value.strip() for value in SUMMARY.findall(summary_body) if value.strip()]
    if len(summary_matches) != 1:
        errors.append(f"必须恰有一个非空概况字段，实际为{len(summary_matches)}个")
        summary = ""
    else:
        summary = summary_matches[0]
    summary_says_no_assets = NO_ASSETS_SUMMARY in summary

    cutoff_matches = CUTOFF.findall(text)
    if len(cutoff_matches) != 1:
        errors.append(f"必须恰有一个事实截止章节，实际为{len(cutoff_matches)}个")
    elif latest is not None:
        cutoff = (int(cutoff_matches[0][0]), cutoff_matches[0][1].strip())
        if cutoff != latest:
            errors.append(
                "事实截止与最新定稿不一致："
                f"总账为第{cutoff[0]}章《{cutoff[1]}》，"
                f"最新定稿为第{latest[0]}章《{latest[1]}》"
            )

    level_body = section(
        text,
        "## 1. 当前层级与承载状态",
        "## 2. 当前可调用能力与手段",
    )
    ability_body = section(
        text,
        "## 2. 当前可调用能力与手段",
        "## 3. 当前持有",
    )
    move_body = section(ability_body, "### 当前手段", None)
    holding_body = section(text, "## 3. 当前持有", None)

    fact_body = "".join((level_body, ability_body, holding_body))

    level_entries = named_entries(level_body)
    abilities = [
        match
        for match in ABILITY_HEADING.finditer(ability_body)
        if match.group(1).strip() not in PLACEHOLDER_ABILITY_NAMES
    ]
    for index, match in enumerate(abilities):
        name = match.group(1).strip()
        end = abilities[index + 1].start() if index + 1 < len(abilities) else len(ability_body)
        body = ability_body[match.end() : end]
        for field in ("**作用**", "**限制**"):
            if field not in body:
                errors.append(f"核心机制“{name}”缺少字段“{field}”")

    # 同一机制的派生信息（如识海小字）写在该机制的字段里，不另立条目。
    mechanism_names = [match.group(1).strip() for match in abilities]
    for name in mechanism_names:
        for other in mechanism_names:
            if other != name and other.startswith(name):
                errors.append(
                    f"核心机制“{other}”是“{name}”的派生信息，"
                    f"应并进“{name}”的字段里，不另立条目"
                )

    # 具体招法以表格维护，一行一门，避免随承技次数线性膨胀。
    moves = markdown_table_rows(move_body)
    if not moves:
        errors.append("缺少“### 当前手段”表")
    else:
        if [cell.strip() for cell in moves[0]] != ["手段", "类型", "作用", "限制"]:
            errors.append(
                f"当前手段表的列应为['手段', '类型', '作用', '限制']，"
                f"实际为{[cell.strip() for cell in moves[0]]}"
            )
        move_entries = moves[1:]
        if not move_entries:
            errors.append("当前手段表只有表头，没有任何手段")
        for row in move_entries:
            if len(row) != 4:
                errors.append(f"当前手段表行列数错误：{row}")
            elif not row[0] or not row[1] or not row[2] or not row[3]:
                errors.append(f"当前手段表存在缺项的条目：{row}")

    holding_rows = markdown_table_rows(holding_body)
    if not holding_rows:
        errors.append("缺少“## 3. 当前持有”表")
    else:
        if [cell.strip() for cell in holding_rows[0]] != ["物品或资源", "数量", "位置"]:
            errors.append(
                f"当前持有表的列应为['物品或资源', '数量', '位置']，"
                f"实际为{[cell.strip() for cell in holding_rows[0]]}"
            )
        holding_entries = holding_rows[1:]
        for row in holding_entries:
            if len(row) != 3:
                errors.append(f"当前持有表行列数错误：{row}")
            elif not row[0] or not row[1]:
                errors.append(f"当前持有表存在缺少名称或数量的条目：{row}")

    has_assets = bool(level_entries or abilities or holding_rows)

    if summary and not summary_says_no_assets and not has_assets:
        errors.append("当前概况说明存在动态资产，但总账没有任何实际条目")
    if summary_says_no_assets and has_assets:
        errors.append("当前概况写明无动态资产，但总账存在实际动态资产条目")

    return errors


def main() -> int:
    root = Path(parse_args().workspace_root).resolve()
    latest = latest_final(root / "4-正文")
    ledger_path = root / "控制台" / "主角能力与资源.md"

    if not ledger_path.is_file():
        if latest is None:
            print("主角动态资产总账校验通过：项目尚无定稿章节，首次定稿时必须创建总账。")
            return 0
        print(f"主角动态资产总账校验失败：已有定稿但缺少 {ledger_path}")
        return 1

    ledger_text = ledger_path.read_text(encoding="utf-8-sig")
    errors = validate_text(ledger_text, latest)
    if errors:
        print("主角动态资产总账校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print("主角动态资产总账校验通过：当前概况、核心机制、当前手段与当前持有均符合要求。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
