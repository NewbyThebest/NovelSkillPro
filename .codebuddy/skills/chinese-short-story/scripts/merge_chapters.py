#!/usr/bin/env python3
"""
合并章节脚本：将章节目录下的所有章节文件按序合并为完整正文。

用法：
    python merge_chapters.py [章节目录] [输出文件]

默认：
    章节目录 = ./章节
    输出文件 = ./正文.md

功能：
    - 自动识别引子/楔子/序章，放在最前面（无标题，直接正文）
    - 章节按序号标记（01、02 ...）
    - 自动将英文标点替换为中文标点
"""

import os
import sys
import re
import glob


PROLOGUE_NAMES = ["引子.md", "楔子.md", "序章.md", "序.md"]

# 中文引号
LEFT_DQ = "\u201c"
RIGHT_DQ = "\u201d"
LEFT_SQ = "\u2018"
RIGHT_SQ = "\u2019"

# 简单标点映射（引号、逗号、点号单独处理）
SIMPLE_MAP = {
    "!": "\uff01",
    "?": "\uff1f",
    ":": "\uff1a",
    ";": "\uff1b",
    "(": "\uff08",
    ")": "\uff09",
}


def replace_punctuation(text):
    """将文本中的英文标点替换为中文标点。"""
    result = []
    i = 0
    dq_open = False
    sq_open = False

    while i < len(text):
        ch = text[i]

        # 双引号
        if ch == '"':
            if dq_open:
                result.append(RIGHT_DQ)
            else:
                result.append(LEFT_DQ)
            dq_open = not dq_open
            i += 1
            continue

        # 单引号
        if ch == "'":
            if i > 0 and i < len(text) - 1:
                if text[i - 1].isalpha() and text[i + 1].isalpha():
                    result.append(ch)
                    i += 1
                    continue
            if sq_open:
                result.append(RIGHT_SQ)
            else:
                result.append(LEFT_SQ)
            sq_open = not sq_open
            i += 1
            continue

        # 点号（保留数字间和省略号）
        if ch == ".":
            if i > 0 and i < len(text) - 1 and text[i - 1].isdigit() and text[i + 1].isdigit():
                result.append(ch)
            elif (i < len(text) - 1 and text[i + 1] == ".") or (i > 0 and text[i - 1] == "."):
                result.append(ch)
            else:
                result.append("\u3002")
            i += 1
            continue

        # 逗号（保留数字间）
        if ch == ",":
            if i > 0 and i < len(text) - 1 and text[i - 1].isdigit() and text[i + 1].isdigit():
                result.append(ch)
            else:
                result.append("\uff0c")
            i += 1
            continue

        # 其他简单映射
        if ch in SIMPLE_MAP:
            result.append(SIMPLE_MAP[ch])
            i += 1
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def extract_chapter_number(filename):
    """从文件名中提取章节编号。"""
    match = re.search(r"第(\d+)章", filename)
    if match:
        return int(match.group(1))
    return 999


def merge_chapters(chapter_dir, output_file):
    """合并所有章节文件为一个完整正文。"""
    merged_content = []
    total_chars = 0
    file_count = 0

    # 1. 引子（无标题，直接正文）
    for prologue_name in PROLOGUE_NAMES:
        prologue_path = os.path.join(chapter_dir, prologue_name)
        if os.path.exists(prologue_path):
            with open(prologue_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            content = replace_punctuation(content)
            char_count = len(re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", content))
            total_chars += char_count
            file_count += 1
            merged_content.append(content)
            merged_content.append("")
            print(f"  \u2705 {prologue_name}  \u2192  {char_count} \u5b57")
            break

    # 2. 章节文件
    pattern = os.path.join(chapter_dir, "第*章*.md")
    files = glob.glob(pattern)
    if not files and file_count == 0:
        print(f"\u274c \u672a\u627e\u5230\u7ae0\u8282\u6587\u4ef6\uff1a{chapter_dir}")
        sys.exit(1)

    files.sort(key=lambda f: extract_chapter_number(os.path.basename(f)))

    for filepath in files:
        basename = os.path.basename(filepath)
        chapter_num = extract_chapter_number(basename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()
        content = replace_punctuation(content)
        char_count = len(re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", content))
        total_chars += char_count
        file_count += 1
        merged_content.append(f"{chapter_num:02d}")
        merged_content.append("")
        merged_content.append(content)
        merged_content.append("")
        print(f"  \u2705 {basename}  \u2192  {char_count} \u5b57")

    final_text = "\n".join(merged_content).rstrip() + "\n"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(final_text)

    print(f"\n{'=' * 40}")
    print(f"\U0001f4d6 \u5408\u5e76\u5b8c\u6210\uff1a{file_count} \u7bc7")
    print(f"\U0001f4dd \u603b\u5b57\u6570\uff1a{total_chars} \u5b57")
    print(f"\U0001f4be \u8f93\u51fa\u6587\u4ef6\uff1a{output_file}")


if __name__ == "__main__":
    chapter_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(".", "\u7ae0\u8282")
    output_file = sys.argv[2] if len(sys.argv) > 2 else os.path.join(".", "\u6b63\u6587.md")
    print(f"\U0001f4c2 \u7ae0\u8282\u76ee\u5f55\uff1a{chapter_dir}")
    print(f"\U0001f4c4 \u8f93\u51fa\u6587\u4ef6\uff1a{output_file}")
    print()
    merge_chapters(chapter_dir, output_file)
