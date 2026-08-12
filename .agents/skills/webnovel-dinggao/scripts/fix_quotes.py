#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
中文标点与引号校准脚本
============================================================
目标：按项目 AGENTS.md 的排版规则统一中文正文标点：
- 对话使用中文双引号“”；嵌套引用使用中文单引号‘’。
- 英文半角句读改为中文全角：，。！？；：。
- 半角括号改为中文全角括号（）。
- ASCII 破折号改为——，省略号改为……。

脚本会保护 Markdown 代码、链接地址、网址、文件路径、版本号、小数、
时间、数字分组与列表标记，避免把结构性或技术性符号误改。

用法：
    python fix_quotes.py                   # 只诊断（默认），扫描 4-正文 全部 md
    python fix_quotes.py --fix             # 诊断并修复 4-正文 下全部 md
    python fix_quotes.py --fix 文件或目录  # 只处理指定文件/目录
    python fix_quotes.py --fix --strict    # 修复后若引号仍不配对则返回非零退出码

修复直接覆盖原文件，不生成备份。
"""

import argparse
import re
from collections import Counter
from pathlib import Path


def find_workspace_root(start: Path) -> Path:
    """从脚本位置向上查找包含 AGENTS.md 的目录作为项目根。"""
    for directory in (start, *start.parents):
        if (directory / "AGENTS.md").is_file():
            return directory
    return start.parent if start.parent.is_dir() else start


ROOT = find_workspace_root(Path(__file__).resolve().parent)
DEFAULT_DIR = ROOT / "4-正文"

LEFT_Q = "\u201c"     # “
RIGHT_Q = "\u201d"    # ”
LEFT_SQ = "\u2018"    # ‘
RIGHT_SQ = "\u2019"   # ’

BAD_QUOTES = {
    '"': (False, "英文直双引号 U+0022"),
    "\uff02": (False, "全角直双引号 U+FF02"),
    "\u201e": (True, "低双引号 U+201E"),
    "\u300c": (True, "日式左引号 U+300C"),
    "\u300d": (True, "日式右引号 U+300D"),
    "\u300e": (True, "日式左引号 U+300E"),
    "\u300f": (True, "日式右引号 U+300F"),
}

BAD_SINGLE_QUOTES = {
    "'": (False, "英文直单引号 U+0027"),
    "\uff07": (False, "全角直单引号 U+FF07"),
    "\u201a": (True, "低单引号 U+201A"),
}

PUNCT_MAP = {
    ",": ("，", "英文逗号"),
    ".": ("。", "英文句号"),
    "?": ("？", "英文问号"),
    "!": ("！", "英文感叹号"),
    ";": ("；", "英文分号"),
    ":": ("：", "英文冒号"),
    "(": ("（", "英文左括号"),
    ")": ("）", "英文右括号"),
}

END_PUNCT = set("。.!！?？……")
AFTER_CLOSE = set("，,；;：:、）)")
TRAILING_URL_PUNCT = set(",.!?;:)]}")


def mark(mask, start, end):
    start = max(0, start)
    end = min(len(mask), end)
    for idx in range(start, end):
        mask[idx] = True


def line_ranges(text):
    offset = 0
    for line in text.splitlines(keepends=True):
        yield offset, offset + len(line), line
        offset += len(line)
    if offset < len(text):
        yield offset, len(text), text[offset:]


def protect_regex(text, mask, pattern, flags=0, group=0, trim_url=False):
    for match in re.finditer(pattern, text, flags):
        start, end = match.span(group)
        if trim_url:
            while end > start and text[end - 1] in TRAILING_URL_PUNCT:
                end -= 1
        mark(mask, start, end)


def build_protected_mask(text):
    """标记不应做中文标点转换的 Markdown 与技术文本区间。"""
    mask = [False] * len(text)

    # YAML frontmatter。
    lines = list(line_ranges(text))
    if lines and lines[0][2].strip() == "---":
        mark(mask, lines[0][0], lines[0][1])
        for start, end, line in lines[1:]:
            mark(mask, start, end)
            if line.strip() in {"---", "..."}:
                break

    # 围栏代码块、分隔线、表格分隔行与 Markdown 列表标记。
    fence_char = None
    fence_len = 0
    for start, end, line in lines:
        stripped = line.lstrip()
        fence_match = re.match(r"(`{3,}|~{3,})", stripped)
        if fence_char is not None:
            mark(mask, start, end)
            if fence_match and fence_match.group(1)[0] == fence_char \
                    and len(fence_match.group(1)) >= fence_len:
                fence_char = None
                fence_len = 0
            continue
        if fence_match:
            fence_char = fence_match.group(1)[0]
            fence_len = len(fence_match.group(1))
            mark(mask, start, end)
            continue

        body = line.rstrip("\r\n")
        if re.fullmatch(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*", body):
            mark(mask, start, end)
            continue
        if re.fullmatch(
            r"\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*",
            body,
        ):
            mark(mask, start, end)
            continue

        marker = re.match(r"^(\s*)(?:[-+*]|\d+[.)])(?=\s)", line)
        if marker:
            mark(mask, start + len(marker.group(1)), start + marker.end())

    # 行内代码。不同长度的反引号必须成对。
    idx = 0
    while idx < len(text):
        if mask[idx] or text[idx] != "`":
            idx += 1
            continue
        run_end = idx + 1
        while run_end < len(text) and text[run_end] == "`":
            run_end += 1
        token = text[idx:run_end]
        close = text.find(token, run_end)
        if close == -1:
            idx = run_end
            continue
        mark(mask, idx, close + len(token))
        idx = close + len(token)

    # Markdown 链接目标、HTML/自动链接。
    protect_regex(
        text,
        mask,
        r"!?\[[^\]\n]*\]\((?:\\.|[^)\n])*\)",
    )
    protect_regex(text, mask, r"<[^>\n]+>")

    # URL、邮箱、路径、常见文件名和命令行长参数。
    protect_regex(
        text,
        mask,
        r"(?i)\b(?:https?://|ftp://|www\.)[^\s<>\"“”]+",
        trim_url=True,
    )
    protect_regex(
        text,
        mask,
        r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    )
    protect_regex(
        text,
        mask,
        r"(?i)\b[A-Z]:[\\/][^\s，。！？；：、\"“”‘’<>|]+",
        trim_url=True,
    )
    protect_regex(text, mask, r"(?<!\w)(?:\.\.?/|/)[A-Za-z0-9_./-]+")
    protect_regex(
        text,
        mask,
        r"(?i)(?<![\w.-])[\w.-]+\.(?:md|py|js|jsx|ts|tsx|json|toml|yaml|yml|txt|docx|pdf|xlsx|csv|png|jpe?g|webp|gif|mp4|wav)(?!\w)",
    )
    protect_regex(text, mask, r"(?<!\w)--[A-Za-z0-9][\w-]*")

    return mask


def is_ascii_word(ch):
    return bool(ch) and ch.isascii() and (ch.isalnum() or ch == "_")


def previous_char(text, idx):
    return text[idx - 1] if idx > 0 else None


def following_char(text, idx):
    return text[idx + 1] if idx + 1 < len(text) else None


def keep_ascii_punct(text, idx, ch):
    prev = previous_char(text, idx)
    nxt = following_char(text, idx)

    if ch == "," and prev and nxt and prev.isdigit() and nxt.isdigit():
        return True
    if ch == ".":
        if prev and nxt and is_ascii_word(prev) and is_ascii_word(nxt):
            return True
        if prev in "/\\" or nxt in "/\\":
            return True
    if ch == ":":
        if prev and nxt and prev.isdigit() and nxt.isdigit():
            return True
        if prev and prev.isascii() and prev.isalpha() and nxt in "/\\":
            return True
    return False


def normalize_punctuation(text):
    """修复半角句读、括号、破折号和省略号。"""
    mask = build_protected_mask(text)
    output = []
    fixes = []
    idx = 0

    while idx < len(text):
        ch = text[idx]
        if mask[idx]:
            output.append(ch)
            idx += 1
            continue

        if ch == ".":
            end = idx
            while end < len(text) and text[end] == "." and not mask[end]:
                end += 1
            run = text[idx:end]
            if len(run) >= 3:
                output.append("……")
                fixes.append((idx, run, "……", "英文省略号"))
                idx = end
                continue

        if ch == "…":
            end = idx
            while end < len(text) and text[end] == "…" and not mask[end]:
                end += 1
            run = text[idx:end]
            if len(run) != 2:
                output.append("……")
                fixes.append((idx, run, "……", "中文省略号长度"))
            else:
                output.append(run)
            idx = end
            continue

        if ch == "-":
            end = idx
            while end < len(text) and text[end] == "-" and not mask[end]:
                end += 1
            run = text[idx:end]
            if len(run) >= 2:
                output.append("——")
                fixes.append((idx, run, "——", "英文破折号"))
                idx = end
                continue

        if ch == "—":
            end = idx
            while end < len(text) and text[end] == "—" and not mask[end]:
                end += 1
            run = text[idx:end]
            prev = previous_char(text, idx)
            nxt = text[end] if end < len(text) else None
            if len(run) == 1 and prev and nxt and prev.isdigit() and nxt.isdigit():
                output.append(run)
            elif len(run) != 2:
                output.append("——")
                fixes.append((idx, run, "——", "中文破折号长度"))
            else:
                output.append(run)
            idx = end
            continue

        if ch in PUNCT_MAP and not keep_ascii_punct(text, idx, ch):
            new_ch, desc = PUNCT_MAP[ch]
            output.append(new_ch)
            fixes.append((idx, ch, new_ch, desc))
        else:
            output.append(ch)
        idx += 1

    return "".join(output), fixes


def prev_nonspace(text, idx):
    pos = idx - 1
    while pos >= 0 and text[pos] in " \t":
        pos -= 1
    return text[pos] if pos >= 0 else None


def next_nonspace(text, idx):
    pos = idx + 1
    while pos < len(text) and text[pos] in " \t":
        pos += 1
    return text[pos] if pos < len(text) else None


def decide_side(text, idx, open_count, left_quote, right_quote):
    prev = prev_nonspace(text, idx)
    nxt = next_nonspace(text, idx)

    if prev is not None and prev in END_PUNCT:
        return right_quote
    if prev is None or prev == "\n" or prev == "：":
        return left_quote
    if nxt is None or nxt == "\n" or nxt in END_PUNCT or nxt in AFTER_CLOSE:
        return right_quote
    return right_quote if open_count > 0 else left_quote


def normalize_quotes(text):
    """修复双引号与可安全判断的直单引号。"""
    mask = build_protected_mask(text)
    fixes = []
    suspects = []
    chars = list(text)
    double_open = 0
    single_open = 0

    for idx, ch in enumerate(chars):
        if mask[idx]:
            continue
        if ch == LEFT_Q:
            double_open += 1
            continue
        if ch == RIGHT_Q:
            double_open = max(0, double_open - 1)
            continue
        if ch == LEFT_SQ:
            single_open += 1
            continue
        if ch == RIGHT_SQ:
            single_open = max(0, single_open - 1)
            continue

        if ch in BAD_QUOTES:
            direct, desc = BAD_QUOTES[ch]
            if direct:
                new_ch = LEFT_Q if ch in "\u300c\u300e" else RIGHT_Q
            else:
                new_ch = decide_side(text, idx, double_open, LEFT_Q, RIGHT_Q)
            double_open += 1 if new_ch == LEFT_Q else -1
            double_open = max(0, double_open)
            chars[idx] = new_ch
            fixes.append((idx, ch, new_ch, desc))
            continue

        if ch in BAD_SINGLE_QUOTES:
            prev = previous_char(text, idx)
            nxt = following_char(text, idx)
            if ch == "'" and is_ascii_word(prev) and is_ascii_word(nxt):
                suspects.append((idx, ch, "英文单词内撇号，已保留"))
                continue
            direct, desc = BAD_SINGLE_QUOTES[ch]
            if direct:
                new_ch = RIGHT_SQ
            else:
                new_ch = decide_side(text, idx, single_open, LEFT_SQ, RIGHT_SQ)
            single_open += 1 if new_ch == LEFT_SQ else -1
            single_open = max(0, single_open)
            chars[idx] = new_ch
            fixes.append((idx, ch, new_ch, desc))

    return "".join(chars), fixes, suspects


def scan_pairs(text, left_quote, right_quote):
    mask = build_protected_mask(text)
    stack = []
    extra_rights = []
    for idx, ch in enumerate(text):
        if mask[idx]:
            continue
        if ch == left_quote:
            stack.append(idx)
        elif ch == right_quote:
            if stack:
                stack.pop()
            else:
                extra_rights.append(idx)
    return extra_rights, stack


def find_reversed_pairs(text):
    _, unclosed = scan_pairs(text, LEFT_Q, RIGHT_Q)
    unclosed_set = set(unclosed)
    mask = build_protected_mask(text)
    swap_pairs = []
    to_left = []

    for idx, ch in enumerate(text):
        if mask[idx] or ch != RIGHT_Q:
            continue
        prev = prev_nonspace(text, idx)
        if not (idx == 0 or text[idx - 1] == "\n" or prev == "："):
            continue
        line_end = text.find("\n", idx)
        if line_end == -1:
            line_end = len(text)
        pos = idx + 1
        while pos < line_end:
            if text[pos] in (LEFT_Q, RIGHT_Q):
                break
            pos += 1
        if pos < line_end and text[pos] == LEFT_Q and pos in unclosed_set:
            swap_pairs.append((idx, pos))
            unclosed_set.discard(pos)
        elif pos < line_end and text[pos] == RIGHT_Q:
            to_left.append(idx)
    return swap_pairs, to_left


def fix_reversed_pairs(text):
    swap_pairs, to_left = find_reversed_pairs(text)
    if not swap_pairs and not to_left:
        return text, []
    chars = list(text)
    records = []
    for right_idx, left_idx in swap_pairs:
        chars[right_idx], chars[left_idx] = LEFT_Q, RIGHT_Q
        records.append((right_idx, "左右写反的中文双引号"))
    for idx in to_left:
        chars[idx] = LEFT_Q
        records.append((idx, "行首写反的中文双引号"))
    return "".join(chars), records


def show_context(text, idx, width=14):
    start = max(0, idx - width)
    end = min(len(text), idx + width + 1)
    return text[start:end].replace("\n", "↵")


def line_col(text, idx):
    line = text.count("\n", 0, idx) + 1
    last_newline = text.rfind("\n", 0, idx)
    return line, idx - last_newline


def quote_stats(text):
    counter = Counter(text)
    chars = [
        LEFT_Q, RIGHT_Q, LEFT_SQ, RIGHT_SQ, '"', "'", "\uff02", "\uff07",
        "\u300c", "\u300d", "\u300e", "\u300f", "\u201e", "\u201a",
    ]
    return {char: counter.get(char, 0) for char in chars}


def aggregate_fixes(fixes):
    counts = Counter(record[3] for record in fixes)
    return "、".join(f"{desc} {count} 处" for desc, count in sorted(counts.items()))


def pairing_issues(text):
    issues = []
    for left, right, label in (
        (LEFT_Q, RIGHT_Q, "双引号"),
        (LEFT_SQ, RIGHT_SQ, "单引号"),
    ):
        extra, unclosed = scan_pairs(text, left, right)
        issues.extend((f"多余右{label}", idx) for idx in extra)
        issues.extend((f"未闭合左{label}", idx) for idx in unclosed)
    return issues


def process_file(path, do_fix):
    """处理单个文件，返回（修复数、待确认数、是否配对、报告）。"""
    text = path.read_text(encoding="utf-8")
    punct_text, punct_fixes = normalize_punctuation(text)
    quote_text, quote_fixes, suspects = normalize_quotes(punct_text)
    new_text, reverse_records = fix_reversed_pairs(quote_text)

    fix_count = len(punct_fixes) + len(quote_fixes) + len(reverse_records)
    issues = pairing_issues(new_text)

    report = ["=" * 72, f"文件：{path}", "-" * 72]
    stats = quote_stats(text)
    stat_line = "  ".join(f"{char}={count}" for char, count in stats.items() if count)
    report.append(f"引号统计：{stat_line or '无'}")

    if punct_fixes:
        report.append(f"标点修复：{aggregate_fixes(punct_fixes)}")
    if quote_fixes:
        report.append(f"引号修复：{aggregate_fixes(quote_fixes)}")
    if reverse_records:
        report.append(f"引号方向修复：{len(reverse_records)} 处")
    if not fix_count:
        report.append("未发现需要修复的标点或引号。")

    if suspects:
        report.append("-" * 72)
        report.append("保留项（疑似英文单词内撇号）：")
        for idx, char, desc in suspects:
            line, _ = line_col(new_text, idx)
            report.append(f"  第{line}行：{char!r}，{desc}")

    if issues:
        report.append("-" * 72)
        report.append("配对检查（仍需人工处理）：")
        for label, idx in issues:
            line, _ = line_col(new_text, idx)
            report.append(f"  [{label}] 第{line}行：…{show_context(new_text, idx)}…")
    else:
        report.append("配对检查：通过，中文单双引号全部配对。")

    if do_fix and new_text != text:
        path.write_text(new_text, encoding="utf-8")
        report.append(f"结果：已修复 {fix_count} 处，原文件已直接更新")
    elif do_fix:
        report.append("结果：无需修复。")
    else:
        report.append("结果：仅诊断，未修改（加 --fix 执行修复）。")

    return fix_count, len(suspects), not issues, "\n".join(report)


def collect_md(target):
    path = Path(target)
    if path.is_file():
        return [path] if path.suffix.lower() == ".md" else []
    if path.is_dir():
        return sorted(path.rglob("*.md"))
    return []


def fix_argv_encoding(raw: str) -> str:
    """修复旧版 GBK 终端导致的中文路径参数乱码。"""
    try:
        restored = raw.encode("gbk").decode("utf-8")
        if restored != raw and Path(restored).exists():
            return restored
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return raw


def main():
    parser = argparse.ArgumentParser(description="中文标点与引号校准脚本")
    parser.add_argument("--fix", action="store_true", help="执行修复（默认只诊断）")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="修复后若中文单双引号仍不配对则返回非零退出码",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=str(DEFAULT_DIR),
        help="目标 Markdown 文件或目录，默认扫描 4-正文",
    )
    args = parser.parse_args()

    target = fix_argv_encoding(args.path)
    files = collect_md(target)
    if not files:
        print(f"未找到 Markdown 文件：{target}")
        return 1

    total_fix = 0
    total_suspect = 0
    all_paired = True
    for file_path in files:
        fix_count, suspect_count, paired, report = process_file(file_path, args.fix)
        total_fix += fix_count
        total_suspect += suspect_count
        all_paired = all_paired and paired
        print(report)
        print()

    print("=" * 72)
    print(
        f"汇总：共扫描 {len(files)} 个文件，修复 {total_fix} 处，"
        f"待人工确认 {total_suspect} 处"
    )
    if not all_paired:
        print("警告：仍有中文单双引号不配对的文件，见上方配对扫描。")
        if args.strict:
            return 1
    elif args.fix:
        print("全部文件中文单双引号配对正常。")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
