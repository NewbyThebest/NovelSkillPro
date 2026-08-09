#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
中文引号修复脚本
============================================================
目标：把正文里 AI 写错的各种引号统一修复成标准中文引号 “ ”。

背景：AGENTS.md 排版约束要求「对话使用中文引号：“”」。
AI 偶尔会把引号写成英文直引号 " ' 、全角直引号 ＂ ＇、
日式引号 「」『』、低引号 „，或左右写反/不配对。
本脚本扫描目标文件，诊断 + 一键修复。

用法：
    python fix_quotes.py                   # 只诊断（默认），扫描 4-正文 全部 md
    python fix_quotes.py --fix             # 诊断并修复 4-正文 下全部 md
    python fix_quotes.py --fix 文件或目录  # 只处理指定文件/目录
    python fix_quotes.py --fix --strict    # 修复后若仍左右不配对则返回非零退出码

说明：传入含中文的路径时，若在 GBK 终端（旧版 cmd）下发生乱码，
脚本会尝试自动还原为正确路径。

修复逻辑：
- 自动修复范围：英文直双引号 " 、全角直双引号 ＂ 、低双引号 „ 、
  日式引号 「」『』。左右方向由上下文启发式 + 全文配对状态共同判定。
- 单引号 ' ‘ ’ ＇ 默认只诊断不自动改，避免误伤对话内嵌套引用
  （“他说‘你好’” 这种嵌套单引号是合法的），需要人工确认。
- 对已存在的中文引号做配对扫描：定位"多余右引号 / 未闭合左引号"，
  只报告位置，不改动（左右写反需人工判断）。
- 修复直接覆盖原文件，不生成备份（仅改符号，可随时重新运行）。
"""

import argparse
from collections import Counter
from pathlib import Path


def find_workspace_root(start: Path) -> Path:
    """从脚本位置向上查找包含 AGENTS.md 的目录作为项目根。
    脚本可能位于根目录 Script/ 或任意 skill 的 scripts/ 下。
    """
    for directory in (start, *start.parents):
        if (directory / "AGENTS.md").is_file():
            return directory
    return start.parent if start.parent.is_dir() else start


ROOT = find_workspace_root(Path(__file__).resolve().parent)
DEFAULT_DIR = ROOT / "4-正文"

# 标准中文引号
LEFT_Q = "\u201c"    # “
RIGHT_Q = "\u201d"   # ”

# 需要修复成中文双引号的“错误双引号”
# 值：True 表示方向明确（直接映射），False 表示需要判定左右
BAD_QUOTES = {
    '"':       (False, "英文直双引号 U+0022"),
    "\uff02":  (False, "全角直双引号 U+FF02"),
    "\u201e":  (True,  "低双引号 U+201E"),        # „ -> ”
    "\u300c":  (True,  "日式左引号 U+300C"),       # 「 -> “
    "\u300d":  (True,  "日式右引号 U+300D"),       # 」 -> ”
    "\u300e":  (True,  "日式左引号 U+300E"),       # 『 -> “
    "\u300f":  (True,  "日式右引号 U+300F"),       # 』 -> ”
}

# 只诊断、不自动改的引号
SUSPECT_QUOTES = {
    "'":        "英文直单引号 U+0027",
    "\uff07":   "全角直单引号 U+FF07",
    "\u2018":   "左单引号 U+2018",
    "\u2019":   "右单引号 U+2019",
    "\u201a":   "低单引号 U+201A",
}

# 结束标点：出现在引号【前】或【后】都提示这是右引号
END_PUNCT = set("。.!！?？…")
# 引号后出现这些标点，提示右引号（闭合后接标点/叙述）
AFTER_CLOSE = set("，,；;：:、")


def prev_char(text, idx):
    """前一个非空白字符（不跨换行判断）。"""
    i = idx - 1
    while i >= 0 and text[i] in " \t":
        i -= 1
    return text[i] if i >= 0 else None


def next_char(text, idx):
    i = idx + 1
    while i < len(text) and text[i] in " \t":
        i += 1
    return text[i] if i < len(text) else None


def decide_side(text, idx, open_count):
    """判定一个方向未知的直引号是左还是右。
    规则按优先级：
    1. 前是结束标点      -> 右（"……。" 的闭合）
    2. 前是行首/换行/冒号 -> 左（段首或“他说：”引出）
    3. 后是结束标点/行尾 -> 右（闭合后接句号或换行）
    4. 兜底：用全文配对状态（当前有未闭合则闭合，否则开启）
    """
    p = prev_char(text, idx)
    n = next_char(text, idx)

    if p is not None and p in END_PUNCT:
        return RIGHT_Q
    if p is None or p == "\n" or p == "：":
        return LEFT_Q
    if n is None or n == "\n" or n in END_PUNCT or n in AFTER_CLOSE:
        return RIGHT_Q
    return RIGHT_Q if open_count > 0 else LEFT_Q


def scan_pairs(text):
    """对现有中文引号做配对扫描。
    返回 (多余右引号位置列表, 未闭合左引号位置列表)
    """
    stack = []  # 存未闭合左引号的 index
    extra_rights = []
    for idx, ch in enumerate(text):
        if ch == LEFT_Q:
            stack.append(idx)
        elif ch == RIGHT_Q:
            if stack:
                stack.pop()
            else:
                extra_rights.append(idx)
    return extra_rights, stack


def find_reversed_pairs(text):
    """找“左右写反”的引号对。

    两种典型形态：
    A.  ”不动如山的玄武！“      —— 疑似写反的 ” 后同行内是未闭合左引号
        处理：交换 → “不动如山的玄武！”
    B.  ”伤倒是好得七七八八，……？” —— 疑似写反的 ” 在行首，行内后面有正常闭合
        处理：行首 ” 改为 “
    判定“疑似写反的左引号”：该 ” 位于行首，或紧跟在冒号后。
    标准排版中右引号紧跟对话内容收在行尾，不会单独出现在行首。
    """
    _, unclosed = scan_pairs(text)
    unclosed_set = set(unclosed)

    swap_pairs = []   # (r, j) 交换
    to_left = []      # 单个 idx，改为左引号

    for r, ch in enumerate(text):
        if ch != RIGHT_Q:
            continue
        # 行首 或 冒号后
        prev = prev_char(text, r)
        if not (r == 0 or text[r - 1] == "\n" or prev == "："):
            continue
        line_end = text.find("\n", r)
        if line_end == -1:
            line_end = len(text)
        j = r + 1
        while j < line_end:
            if text[j] in (LEFT_Q, RIGHT_Q):
                break
            j += 1
        if j < line_end and text[j] == LEFT_Q and j in unclosed_set:
            swap_pairs.append((r, j))
            unclosed_set.discard(j)
        elif j < line_end and text[j] == RIGHT_Q:
            to_left.append(r)
    return swap_pairs, to_left


def fix_reversed_pairs(text):
    """自动修复写反的引号，返回 (新文本, 修复记录)。"""
    swap_pairs, to_left = find_reversed_pairs(text)
    if not swap_pairs and not to_left:
        return text, []
    chars = list(text)
    records = []
    for r, j in swap_pairs:
        chars[r], chars[j] = LEFT_Q, RIGHT_Q   # 交换为 “…”
        line, _ = line_col(text, r)
        records.append(
            (r, "左右写反：第%d行 “” 对已交换位置" % line,
             show_context(text, r)))
    for r in to_left:
        chars[r] = LEFT_Q
        line, _ = line_col(text, r)
        records.append(
            (r, "行首写反：第%d行 “” 已改为左引号" % line,
             show_context(text, r)))
    return "".join(chars), records


def fix_text(text):
    """修复一段文本的引号。
    返回 (new_text, 修复记录列表, 配对警告列表)
    """
    fixes = []
    warnings = []
    open_count = 0  # 全文未闭合左引号数

    chars = list(text)
    for idx, ch in enumerate(chars):
        # 标准中文引号参与配对计数
        if ch == LEFT_Q:
            open_count += 1
            continue
        if ch == RIGHT_Q:
            open_count = max(0, open_count - 1)
            continue

        # 嫌疑单引号：只记录不修改
        if ch in SUSPECT_QUOTES:
            fixes.append((idx, ch, ch, SUSPECT_QUOTES[ch] + "（仅诊断，未修改）"))
            continue

        if ch not in BAD_QUOTES:
            continue

        direct, desc = BAD_QUOTES[ch]
        if direct:
            new_ch = LEFT_Q if ch in "\u300c\u300e" else RIGHT_Q
        else:
            new_ch = decide_side(text, idx, open_count)

        if new_ch == LEFT_Q:
            open_count += 1
        else:
            open_count = max(0, open_count - 1)

        fixes.append((idx, ch, new_ch, desc))
        chars[idx] = new_ch

    new_text = "".join(chars)
    return new_text, fixes, warnings


def show_context(text, idx, width=14):
    start = max(0, idx - width)
    end = min(len(text), idx + width + 1)
    return text[start:end].replace("\n", "↵")


def line_col(text, idx):
    line = text.count("\n", 0, idx) + 1
    last_nl = text.rfind("\n", 0, idx)
    return line, idx - last_nl


def quote_stats(text):
    counter = Counter(text)
    chars = [LEFT_Q, RIGHT_Q, '"', "'", "\uff02", "\uff07",
             "\u300c", "\u300d", "\u300e", "\u300f",
             "\u2018", "\u2019", "\u201e", "\u201a"]
    return {c: counter.get(c, 0) for c in chars}


def process_file(path, do_fix):
    """处理单个文件，返回 (修复数, 待确认数, 报告)。"""
    text = path.read_text(encoding="utf-8")
    new_text, fixes, warnings = fix_text(text)
    new_text, reverse_records = fix_reversed_pairs(new_text)

    suspect_count = sum(1 for _, _, _, d in fixes if "仅诊断" in d)
    fix_count = len(fixes) - suspect_count + len(reverse_records)

    report = []
    report.append("=" * 72)
    report.append(f"文件: {path}")
    report.append("-" * 72)

    stats = quote_stats(text)
    stat_line = "  ".join(
        f"{c if c.isprintable() else hex(ord(c))}={n}"
        for c, n in stats.items() if n)
    report.append(f"引号统计: {stat_line}")

    if not fixes and not reverse_records:
        report.append("未发现错误引号。")
    else:
        for idx, old, new, desc in fixes:
            line, col = line_col(text, idx)
            if "仅诊断" in desc:
                report.append(f"  [诊断] 第{line}行: {old!r} {desc}")
            else:
                report.append(f"  [修复] 第{line}行: {old!r} -> {new!r} ({desc})")
            report.append(f"          上下文: …{show_context(text, idx)}…")
        for idx, desc, ctx in reverse_records:
            report.append(f"  [修复] {desc}")
            report.append(f"          上下文: …{ctx}…")

    # 最终配对检查：修复后仍不配对才提示
    extra_rights, unclosed = scan_pairs(new_text)
    issues = ([("extra_right", i) for i in extra_rights] +
              [("unclosed_left", i) for i in unclosed])
    if issues:
        report.append("-" * 72)
        report.append("配对检查（修复后仍不配对，需人工处理）:")
        for kind, idx in issues:
            line, col = line_col(new_text, idx)
            label = "多余右引号" if kind == "extra_right" else "未闭合左引号"
            report.append(f"  [{label}] 第{line}行: …{show_context(new_text, idx)}…")
    elif fix_count > 0:
        report.append("-" * 72)
        report.append("配对检查: 通过，引号全部配对。")

    if warnings:
        report.append("-" * 72)
        for w in warnings:
            report.append(f"  [警告] {w}")

    # 直接覆盖写入
    if do_fix and fix_count > 0:
        path.write_text(new_text, encoding="utf-8")
        report.append(f"结果: 已修复 {fix_count} 处，原文件已直接更新")
    elif do_fix:
        report.append("结果: 无需修复。")
    else:
        report.append("结果: 仅诊断，未修改（加 --fix 执行修复）。")

    return fix_count, suspect_count, "\n".join(report)


def collect_md(target):
    p = Path(target)
    if p.is_file():
        return [p] if p.suffix.lower() == ".md" else []
    if p.is_dir():
        return sorted(p.rglob("*.md"))
    return []


def fix_argv_encoding(raw: str) -> str:
    """修复终端编码导致的命令行中文参数乱码。

    在 GBK 终端（如旧版 cmd）下，UTF-8 的中文路径参数被按 GBK 解码后
    会变成乱码 str。这里尝试把它按 GBK 重新编码再按 UTF-8 解码还原。
    若还原后的路径真实存在则采用，否则返回原值（交给后续逻辑处理）。
    """
    try:
        restored = raw.encode("gbk").decode("utf-8")
        if restored != raw and Path(restored).exists():
            return restored
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return raw


def main():
    parser = argparse.ArgumentParser(description="中文引号修复脚本")
    parser.add_argument("--fix", action="store_true",
                        help="执行修复（默认只诊断不改文件）")
    parser.add_argument("--strict", action="store_true",
                        help="修复后若仍左右不配对则返回非零退出码")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_DIR),
                        help="目标文件或目录，默认扫描 4-正文")
    args = parser.parse_args()

    # 对命令行传入的中文路径做一次 GBK 乱码还原（旧版 cmd 终端保护）
    target = fix_argv_encoding(args.path)

    files = collect_md(target)
    if not files:
        print(f"未找到 md 文件: {target}")
        return 1

    total_fix = 0
    total_suspect = 0
    all_paired = True
    for f in files:
        fix_n, susp_n, report = process_file(f, args.fix)
        total_fix += fix_n
        total_suspect += susp_n
        print(report)
        print()
        t = f.read_text(encoding="utf-8")
        if t.count(LEFT_Q) != t.count(RIGHT_Q):
            all_paired = False

    print("=" * 72)
    print(f"汇总: 共扫描 {len(files)} 个文件, 修复 {total_fix} 处, "
          f"待人工确认 {total_suspect} 处")
    if not all_paired:
        print("警告: 仍有左右引号不配对的文件，见上方配对扫描。")
        if args.strict:
            return 1
    elif args.fix:
        print("全部文件引号配对正常。")
    return 0


if __name__ == "__main__":
    sys_exit = main()
    import sys
    sys.exit(sys_exit)
