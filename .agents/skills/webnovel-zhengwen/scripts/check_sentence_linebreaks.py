#!/usr/bin/env python3
"""Check or fix Chinese full stops that do not end their physical lines."""

from __future__ import annotations

import argparse
import codecs
from dataclasses import dataclass
from pathlib import Path
import sys


CLOSING_MARKS = frozenset('”’）》】〕〉』」〗〙〛）"')


@dataclass(frozen=True)
class Violation:
    line_number: int
    period_column: int
    next_text_column: int
    line: str


def find_violations(text: str) -> list[Violation]:
    violations: list[Violation] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        for index, character in enumerate(line):
            if character != "。":
                continue

            cursor = index + 1
            while cursor < len(line) and line[cursor] in CLOSING_MARKS:
                cursor += 1
            while cursor < len(line) and line[cursor] in " \t":
                cursor += 1

            if cursor < len(line):
                violations.append(
                    Violation(
                        line_number=line_number,
                        period_column=index + 1,
                        next_text_column=cursor + 1,
                        line=line,
                    )
                )

    return violations


def split_line_at_full_stops(line: str) -> list[str]:
    if not find_violations(line):
        return [line]

    indentation = line[: len(line) - len(line.lstrip(" \t"))]
    fixed_lines: list[str] = []
    current: list[str] = []
    in_chinese_quote = False
    index = 0

    while index < len(line):
        character = line[index]
        current.append(character)

        if character == "“":
            in_chinese_quote = True
        elif character == "”":
            in_chinese_quote = False

        if character != "。":
            index += 1
            continue

        cursor = index + 1
        while cursor < len(line) and line[cursor] in CLOSING_MARKS:
            closing_mark = line[cursor]
            current.append(closing_mark)
            if closing_mark == "”":
                in_chinese_quote = False
            cursor += 1

        next_text = cursor
        while next_text < len(line) and line[next_text] in " \t":
            next_text += 1

        if next_text >= len(line):
            index = len(line)
            break

        reopen_quote = in_chinese_quote
        if reopen_quote:
            current.append("”")
            in_chinese_quote = False

        fixed_lines.append("".join(current).rstrip())
        current = list(indentation)
        if reopen_quote:
            current.append("“")
            in_chinese_quote = True
        index = next_text

    if current:
        fixed_lines.append("".join(current).rstrip())

    return fixed_lines


def fix_text(text: str) -> str:
    if not text:
        return text

    newline = "\r\n" if "\r\n" in text else "\r" if "\r" in text else "\n"
    had_trailing_newline = text.endswith(("\r", "\n"))
    fixed_lines: list[str] = []

    for line in text.splitlines():
        split_lines = split_line_at_full_stops(line)
        for index, split_line in enumerate(split_lines):
            if index > 0:
                fixed_lines.append("")
            fixed_lines.append(split_line)

    fixed = newline.join(fixed_lines)
    if had_trailing_newline:
        fixed += newline
    return fixed


def read_file(path: Path) -> tuple[str | None, bool, str | None]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return None, False, str(exc)

    return text, raw.startswith(codecs.BOM_UTF8), None


def write_file(path: Path, text: str, has_bom: bool) -> str | None:
    try:
        encoded = text.encode("utf-8")
        if has_bom:
            encoded = codecs.BOM_UTF8 + encoded
        path.write_bytes(encoded)
    except (OSError, UnicodeError) as exc:
        return str(exc)

    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="检查或修复中文句号、句号加闭合引号后仍有同一行正文的问题。"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="直接拆行并空一行；中文引号内拆行时自动闭合并重新打开引号",
    )
    parser.add_argument("files", nargs="+", type=Path, help="要检查的 Markdown 正文文件")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    violation_count = 0
    read_error = False

    for path in args.files:
        text, has_bom, error = read_file(path)
        if error is not None:
            read_error = True
            print(f"[错误] 无法读取 {path}: {error}", file=sys.stderr)
            continue

        assert text is not None
        violations = find_violations(text)
        if not violations:
            print(f"[通过] {path}: 未发现句号后继续书写下一句。")
            continue

        if args.fix:
            fixed_text = fix_text(text)
            write_error = write_file(path, fixed_text, has_bom)
            if write_error is not None:
                read_error = True
                print(f"[错误] 无法写入 {path}: {write_error}", file=sys.stderr)
                continue

            remaining = find_violations(fixed_text)
            if not remaining:
                print(f"[已修正] {path}: 已处理 {len(violations)} 处句号换行问题。")
                continue

            violations = remaining

        violation_count += len(violations)
        print(f"[失败] {path}: 发现 {len(violations)} 处句号换行问题。")
        for violation in violations:
            print(
                f"  {path}:{violation.line_number}:{violation.period_column} "
                f"下一句从第 {violation.next_text_column} 列开始"
            )
            print(f"    {violation.line}")

    if read_error:
        return 2
    if violation_count:
        print("请修正上述位置后重新运行检查。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
