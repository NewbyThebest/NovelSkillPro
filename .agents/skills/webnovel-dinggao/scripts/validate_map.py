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
]

# 每张表的固定列数（不含首尾空列）。
TABLE_COLUMNS = {
    "区域索引": 3,
    "地点索引": 3,
    "已确认连通关系": 4,
    "空间限制与通行条件": 2,
}


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


def split_sections(text: str) -> dict[str, str]:
    """Return {heading: body} for each level-2 heading."""
    sections: dict[str, str] = {}
    headings = list(re.finditer(r"^##\s+(.+?)\s*$", text, re.M))
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        sections[heading.group(1).strip()] = text[heading.end():end]
    return sections


def table_rows(body: str) -> list[tuple[int, list[str]]]:
    """Return (line number, cells) for data rows; table starts after header+separator."""
    rows: list[tuple[int, list[str]]] = []
    for offset, raw in enumerate(body.splitlines()):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            rows.append((offset, cells))
    return rows


def check_tables(body: str, columns: int, label: str) -> list[str]:
    """Validate a markdown table: intact header, consistent column count."""
    errors: list[str] = []
    stripped = [line.strip() for line in body.splitlines()]
    non_empty = [(i, line) for i, line in enumerate(stripped) if line]

    if not non_empty:
        errors.append(f"{label}表为空")
        return errors

    if not non_empty[0][1].startswith("|"):
        errors.append(f"{label}表缺少表头行")
        return errors

    header_cells = [cell.strip() for cell in non_empty[0][1].strip("|").split("|")]

    # 表头之后必须紧跟分隔行，否则渲染会出错。
    if len(non_empty) < 2 or not re.fullmatch(r"\|[\s:|-]+\|", non_empty[1][1]):
        errors.append(f"{label}表头后缺少分隔行（`| :--- |` 一行）")
    if len(header_cells) != columns:
        errors.append(f"{label}表头列数应为 {columns}，实际为 {len(header_cells)}")

    # 数据行必须与表头列数一致；分隔行本身列数不参与比较。
    for index, line in non_empty[1:]:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if set("".join(cells)) <= set(":- "):
            continue
        if len(cells) != columns:
            errors.append(
                f"{label}表第 {index + 1} 行有 {len(cells)} 列，应为 {columns} 列"
            )

    # 表体中出现空行 = 表格被打断
    start = next((i for i, line in enumerate(stripped) if line.startswith("|")), None)
    if start is not None:
        for index in range(start, len(stripped)):
            if not stripped[index]:
                following = [line for line in stripped[index + 1:] if line]
                if following and following[0].startswith("|"):
                    errors.append(
                        f"{label}表在第 {index + 1} 行被空行断开，应合并为一张表"
                    )
                break

    return errors


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
        number for number in re.findall(r"第(\d+)章", text) if int(number) > latest_number
    ]
    if future_chapter_refs:
        errors.append(f"地图引用了尚未定稿章节：{sorted(set(future_chapter_refs))}")

    sections = split_sections(text)

    table_errors: list[str] = []
    for name, columns in TABLE_COLUMNS.items():
        body = sections.get(name)
        if body is None:
            continue
        table_errors.extend(check_tables(body, columns, name))

    errors.extend(table_errors)

    # 区域索引与地点索引引用的上级区域都必须已经定义过。
    defined_areas = set()
    for _, cells in table_rows(sections.get("区域索引", "")):
        if len(cells) >= 1 and cells[0] not in {"区域名称", "无"}:
            defined_areas.add(cells[0])
    if defined_areas:
        unknown_parents: set[str] = set()
        for _, cells in table_rows(sections.get("区域索引", "")):
            if len(cells) >= 2 and cells[1] not in {"上级区域", "无"}:
                if cells[1] not in defined_areas:
                    unknown_parents.add(cells[1])
        if unknown_parents:
            errors.append(
                f"区域索引的上级区域在区域索引中未定义：{sorted(unknown_parents)}"
            )

        unknown: set[str] = set()
        for _, cells in table_rows(sections.get("地点索引", "")):
            if len(cells) >= 2 and cells[1] not in {"所属区域", "无"}:
                if cells[1] not in defined_areas:
                    unknown.add(cells[1])
        if unknown:
            errors.append(
                f"地点索引引用了区域索引中未定义的区域：{sorted(unknown)}"
            )

    if errors:
        print("地图校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print("地图校验通过：事实截止、固定栏目与事实边界均符合要求。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
