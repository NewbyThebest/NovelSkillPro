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
    "## 3. 当前资源余额",
    "## 4. 关键物品、凭证与证据",
    "## 5. 不再持有或已耗尽",
    "## 6. 当前未决事实",
)
CUTOFF = re.compile(r"^- \*\*章节\*\*：第\s*(\d+)\s*章《(.+?)》定稿后。?$", re.M)
SUMMARY = re.compile(r"^- \*\*概况\*\*：(.+?)\s*$", re.M)
NO_ASSETS_SUMMARY = "当前无需要追踪的动态资产"
FINAL_FILE = re.compile(r"^第(\d+)章_定稿_(.+)\.md$")
ABILITY_HEADING = re.compile(r"^#### (.+?)\s*$", re.M)
PLACEHOLDER_ABILITY_NAMES = {"能力或机制名称", "能力名称", "无已定稿项目"}
NAMED_BULLET = re.compile(r"^- \*\*(.+?)\*\*：\s*(.*?)\s*$", re.M)
FUTURE_MARKERS = ("创作原料", "草稿", "计划中的", "尚未获得的奖励", "下一章奖励")
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
        "## 3. 当前资源余额",
    )
    resource_body = section(
        text,
        "## 3. 当前资源余额",
        "## 4. 关键物品、凭证与证据",
    )
    item_body = section(
        text,
        "## 4. 关键物品、凭证与证据",
        "## 5. 不再持有或已耗尽",
    )
    history_body = section(
        text,
        "## 5. 不再持有或已耗尽",
        "## 6. 当前未决事实",
    )
    unresolved_body = section(text, "## 6. 当前未决事实", None)

    fact_body = "".join(
        (level_body, ability_body, resource_body, item_body, history_body, unresolved_body)
    )
    for marker in FUTURE_MARKERS:
        if marker in fact_body:
            errors.append(f"总账事实区含未来或草稿标记“{marker}”，只能记录定稿事实")

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
        for field in ("**当前作用**", "**当前限制**", "**事实依据**"):
            if field not in body:
                errors.append(f"能力或手段“{name}”缺少字段“{field}”")

    resource_rows = markdown_table_rows(resource_body)
    resource_entries = resource_rows[1:] if resource_rows else []
    for row in resource_entries:
        if len(row) != 5:
            errors.append(f"资源表行列数错误：{row}")
        elif not row[0] or not row[1] or not row[4]:
            errors.append(f"资源表存在缺少名称、余额或事实依据的条目：{row}")

    item_rows = markdown_table_rows(item_body)
    item_entries = item_rows[1:] if item_rows else []
    for row in item_entries:
        if len(row) != 4:
            errors.append(f"关键物品表行列数错误：{row}")
        elif not row[0] or not row[1] or not row[3]:
            errors.append(f"关键物品表存在缺少名称、状态或事实依据的条目：{row}")

    history_entries = named_entries(history_body, {"物品或资源"})
    unresolved_entries = named_entries(unresolved_body, {"未决项目"})
    has_assets = bool(
        level_entries
        or abilities
        or resource_entries
        or item_entries
        or history_entries
        or unresolved_entries
    )

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

    print("主角动态资产总账校验通过：当前概况、事实条目和事实截止符合要求。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
