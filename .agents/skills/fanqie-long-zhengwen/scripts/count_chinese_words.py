#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
from pathlib import Path

def count_chinese_words(text):
    """
    统计中文字数（包含标点符号）
    排除：空格、换行符、英文字母、数字
    包含：中文字符、中文标点
    """
    # 移除空白字符
    text = re.sub(r'\s+', '', text)
    # 移除英文字母和数字
    text = re.sub(r'[a-zA-Z0-9]+', '', text)
    # 移除 markdown 标记符号
    text = re.sub(r'[#*_`\[\]\(\)]+', '', text)
    
    return len(text)

def resolve_chapter_dir(chapter_dir=None):
    """优先使用项目当前目录下的 4-正文。"""
    if chapter_dir:
        return Path(chapter_dir)
    return Path.cwd() / "4-正文"


def find_chapter_file(chapter_num, chapter_dir):
    """兼容 第1章 / 第001章 两种命名。"""
    candidates = [
        f"第{chapter_num}章",
        f"第{chapter_num:03d}章",
    ]

    if not chapter_dir.exists():
        return None

    for path in chapter_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".md":
            continue
        if any(path.name.startswith(prefix) for prefix in candidates):
            return path
    return None


def count_single_chapter(chapter_num, chapter_dir=None):
    """统计单个章节的字数"""
    chapter_dir = resolve_chapter_dir(chapter_dir)

    found_file = find_chapter_file(chapter_num, chapter_dir)
    if not found_file:
        print(f"❌ 错误：未找到第{chapter_num}章文件")
        print(f"当前搜索目录：{chapter_dir}")
        return None

    with open(found_file, 'r', encoding='utf-8') as f:
        content = f.read()
        words = count_chinese_words(content)
    
    print(f"=== 第{chapter_num}章字数统计 ===")
    print(f"字数: {words} 字")
    print()
    
    if words < 2300:
        shortage = 2300 - words
        print(f"⚠️  字数不足：还需 {shortage} 字才能达到最低标准 (2300字)")
    elif words > 4000:
        excess = words - 4000
        print(f"✅ 字数充足：超出建议上限 {excess} 字 (可接受)")
    else:
        print(f"✅ 字数达标：符合标准范围 (2300-4000字)")
    
    return words

def count_all_chapters(chapter_dir=None):
    """统计所有章节的字数"""
    chapter_dir = resolve_chapter_dir(chapter_dir)
    print("=== 章节字数统计报告 (中文字数 + 标点) ===")
    print()
    
    total_words = 0
    chapter_stats = []
    
    for i in range(1, 200):
        found_file = find_chapter_file(i, chapter_dir)

        if found_file:
            with open(found_file, 'r', encoding='utf-8') as f:
                content = f.read()
                words = count_chinese_words(content)
                total_words += words
                chapter_stats.append((i, words))
                print(f"第{i:3d}章: {words:5d} 字")
        # else:
            # print(f"第{i:3d}章: 文件不存在")
            # chapter_stats.append((i, 0))
    
    print()
    print("=== 统计汇总 ===")
    print(f"总字数: {total_words:,} 字")
    chapter_count = len(chapter_stats)
    avg_words = total_words // chapter_count if chapter_count else 0
    print(f"平均字数: {avg_words:,} 字/章")
    
    # 统计字数分布
    ranges = [
        (0, 1500, "< 1500"),
        (1500, 2000, "1500-2000"),
        (2000, 2500, "2000-2500"),
        (2500, 3000, "2500-3000"),
        (3000, float('inf'), "> 3000")
    ]
    
    print()
    print("=== 字数分布 ===")
    for min_w, max_w, label in ranges:
        count = sum(1 for _, w in chapter_stats if min_w <= w < max_w)
        if count > 0:
            percent = count * 100 // chapter_count if chapter_count else 0
            print(f"{label:12s} 字: {count:2d} 章 ({percent:2d}%)")
    
    # 找出字数不足的章节
    print()
    print("=== 字数不足章节 (< 2300 字) ===")
    insufficient = [(i, w) for i, w in chapter_stats if 0 < w < 2300]
    
    if insufficient:
        for i, w in insufficient:
            print(f"⚠️  第{i:3d}章: {w:5d} 字 (不足 {2300-w} 字)")
    else:
        print("✅ 所有章节字数均达标")
    
    # 找出最短和最长的章节
    print()
    print("=== 极值统计 ===")
    valid_stats = [(i, w) for i, w in chapter_stats if w > 0]
    if valid_stats:
        min_chapter = min(valid_stats, key=lambda x: x[1])
        max_chapter = max(valid_stats, key=lambda x: x[1])
        print(f"最短章节: 第{min_chapter[0]}章 ({min_chapter[1]} 字)")
        print(f"最长章节: 第{max_chapter[0]}章 ({max_chapter[1]} 字)")

def main():
    # 检查命令行参数
    if len(sys.argv) > 1:
        # 单章模式
        try:
            chapter_num = int(sys.argv[1])
            chapter_dir = sys.argv[2] if len(sys.argv) > 2 else None
            count_single_chapter(chapter_num, chapter_dir)
        except ValueError:
            count_all_chapters(sys.argv[1])
    else:
        # 批量模式
        count_all_chapters()

if __name__ == "__main__":
    main()
