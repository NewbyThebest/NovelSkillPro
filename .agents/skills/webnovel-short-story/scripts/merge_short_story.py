#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把番茄短故事的分章定稿合并成单一成稿。

成稿结构：导语（不写标签）→ 01 → 正文 → 02 → 正文 …… → 全文完
输出到 4-正文/<书名>.md，UTF-8、LF 换行。
"""

import argparse
import re
import sys
from pathlib import Path

DINGGAO_RE = re.compile(r"^第(\d+)章_定稿_.*\.md$")
CAOGAO_RE = re.compile(r"^第(\d+)章_草稿_.*\.md$")
DAOYU_HEADING_RE = re.compile(r"^#{1,6}\s")


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[错误] 无法解码文件：{path}")


def to_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_daoyu(path: Path) -> str:
    """读取 4-正文/导语.md。该文件是纯导语文本，只做换行归一，跳过 Markdown 标题行。"""
    lines = to_lf(read_text(path)).split("\n")
    body = [ln.rstrip() for ln in lines if not DAOYU_HEADING_RE.match(ln.strip())]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if not body:
        raise SystemExit(f"[错误] 导语文件为空：{path}")
    return "\n".join(body)


def collect_chapters(zhengwen_dir: Path):
    finals, drafts = {}, {}
    for f in zhengwen_dir.iterdir():
        if not f.is_file():
            continue
        m = DINGGAO_RE.match(f.name)
        if m:
            finals.setdefault(int(m.group(1)), []).append(f)
            continue
        m = CAOGAO_RE.match(f.name)
        if m:
            drafts.setdefault(int(m.group(1)), []).append(f)

    if drafts:
        names = "、".join(sorted(f.name for v in drafts.values() for f in v))
        raise SystemExit(f"[停止] 仍有未定稿草稿，全书未定稿完成：\n  {names}")
    if not finals:
        raise SystemExit("[停止] 4-正文/ 下未找到任何 `第X章_定稿_*.md`")

    dup = {k: v for k, v in finals.items() if len(v) > 1}
    if dup:
        detail = "\n".join(
            f"  第{k}章：{'、'.join(f.name for f in v)}" for k, v in sorted(dup.items())
        )
        raise SystemExit(f"[停止] 存在重复章号：\n{detail}")

    nums = sorted(finals)
    missing = [n for n in range(1, nums[-1] + 1) if n not in finals]
    if missing:
        raise SystemExit("[停止] 章号缺号：" + "、".join(f"第{n}章" for n in missing))

    return [(n, finals[n][0]) for n in nums]


def main() -> int:
    ap = argparse.ArgumentParser(description="合并番茄短故事分章定稿为单一成稿")
    ap.add_argument("--title", required=True, help="书名，用作成稿文件名")
    ap.add_argument(
        "--workdir",
        default=".",
        help="项目根目录（含 4-正文/），默认为当前目录",
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="成稿已存在时直接覆盖；不加此参数则拒绝覆盖",
    )
    args = ap.parse_args()

    root = Path(args.workdir).resolve()
    zhengwen = root / "4-正文"
    daoyu_path = zhengwen / "导语.md"
    out_path = zhengwen / f"{args.title}.md"

    if not daoyu_path.is_file():
        raise SystemExit(f"[停止] 未找到导语文件：{daoyu_path}")
    if not zhengwen.is_dir():
        raise SystemExit(f"[停止] 未找到正文目录：{zhengwen}")
    if out_path.exists() and not args.overwrite:
        raise SystemExit(f"[停止] 成稿已存在，如确认覆盖请加 --overwrite：{out_path}")

    chapters = collect_chapters(zhengwen)
    daoyu = read_daoyu(daoyu_path)

    blocks = [daoyu]
    for num, path in chapters:
        body = to_lf(read_text(path)).strip("\n")
        if not body:
            raise SystemExit(f"[停止] 章节正文为空：{path}")
        blocks.append(f"{num:02d}\n\n{body}")
    blocks.append("全文完")

    content = "\n\n".join(blocks) + "\n"
    out_path.write_text(content, encoding="utf-8", newline="\n")

    total = sum(len(re.sub(r"\s", "", b)) for b in blocks[:-1])
    print(f"[完成] 成稿已写入：{out_path}")
    print(f"       章节数：{len(chapters)}    总字数（含导语，去空白）：{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
