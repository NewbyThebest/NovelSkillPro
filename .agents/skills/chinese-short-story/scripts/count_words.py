#!/usr/bin/env python3
"""
字数统计脚本 - 番茄短故事创作

用法：
  python3 scripts/count_words.py 章节/第01章.md
  python3 scripts/count_words.py 章节/第01章.md 章节/第02章.md

统计规则：
  - 中文字符（汉字、全角标点）每个计 1 字
  - 英文/数字按空格分词后每个单词计 1 字
  - Markdown 标题符号（#）、加粗符号（**）等不计入字数
"""

import sys
import re


def count_chars(text: str) -> int:
    # 去除 Markdown 语法符号
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)  # 标题
    text = re.sub(r"\*{1,3}|_{1,3}|~~|`", "", text)             # 加粗/斜体/删除线/代码
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)                  # 图片
    text = re.sub(r"\[.*?\]\(.*?\)", "", text)                   # 链接
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)        # 引用符
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)    # 列表符

    chinese = re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", text)
    # 去除中文后统计英文单词
    non_chinese = re.sub(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", " ", text)
    english_words = re.findall(r"[a-zA-Z0-9]+", non_chinese)

    return len(chinese) + len(english_words)


def process_file(path: str) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"[错误] 文件不存在：{path}")
        return
    except UnicodeDecodeError:
        print(f"[错误] 编码不是 UTF-8：{path}")
        return

    total = count_chars(content)
    status = "[达标]" if 800 <= total <= 1500 else ("[偏少]" if total < 800 else "[偏多]")
    print(f"{path} -> {total} 字 {status}（目标：800-1500）")


def main() -> None:
    if len(sys.argv) < 2:
        print("用法：python3 scripts/count_words.py <文件> [文件2 ...]")
        sys.exit(1)

    for path in sys.argv[1:]:
        process_file(path)


if __name__ == "__main__":
    main()
