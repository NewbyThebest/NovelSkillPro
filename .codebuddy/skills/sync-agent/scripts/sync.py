#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步脚本：以 .agents/skills/ 为唯一源头，把 skills 镜像到 .claude/ 和 .codebuddy/

用法：
    python sync.py            # 预览：只显示会改动哪些文件，不实际写入
    python sync.py --apply    # 执行：真正同步

规则：改技能时，只改 .agents/skills/ 下的源文件，然后跑本脚本推给另外两套。
项目文本规则维护在仓库根目录的 AGENTS.md，不由本脚本同步。

说明：用纯 Python 标准库实现，跨平台（Windows / macOS / Linux 均可），
不依赖 bash、rsync 等外部命令。
"""

import argparse
import filecmp
import shutil
from pathlib import Path

# 定位项目根：本脚本在 .agents/skills/sync-agent/scripts/sync.py
# parents[0]=scripts  [1]=sync-agent  [2]=skills  [3]=.agents  [4]=项目根
PROJECT_ROOT = Path(__file__).resolve().parents[4]

SRC = ".agents"
DESTS = [".claude", ".codebuddy"]
SUBDIRS = ["skills"]
IGNORED_FILE_NAMES = {".DS_Store"}
IGNORED_DIR_NAMES = {"__pycache__"}
IGNORED_SUFFIXES = {".pyc"}


def iter_files(base: Path):
    """返回应镜像文件的相对路径，本机缓存不纳入同步。"""
    if not base.is_dir():
        return
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if any(part in IGNORED_DIR_NAMES for part in rel.parts):
            continue
        if p.name in IGNORED_FILE_NAMES or p.suffix.lower() in IGNORED_SUFFIXES:
            continue
        yield rel


def sync_one(src_dir: Path, dest_dir: Path, apply: bool) -> int:
    """把 src_dir 镜像到 dest_dir，返回改动文件数。"""
    print(f"--- {src_dir.relative_to(PROJECT_ROOT)}  ->  {dest_dir.relative_to(PROJECT_ROOT)} ---")
    n = 0

    src_files = set(iter_files(src_dir))
    dest_files = set(iter_files(dest_dir))

    # 1) 源头有的文件：目标缺失=新增，内容不同=更新
    for rel in sorted(src_files):
        s = src_dir / rel
        d = dest_dir / rel
        if not d.exists():
            print(f"  [新增] {rel.as_posix()}")
            n += 1
            if apply:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
        elif not filecmp.cmp(s, d, shallow=False):
            print(f"  [更新] {rel.as_posix()}")
            n += 1
            if apply:
                shutil.copy2(s, d)

    # 2) 目标多出来的文件（源头没有）：删除，保证是真镜像
    for rel in sorted(dest_files - src_files):
        print(f"  [删除] {rel.as_posix()}  （源头已无）")
        n += 1
        if apply:
            (dest_dir / rel).unlink()

    # 3) 清理目标里的空目录（源头没有对应目录时），保证真镜像不留空壳
    if apply and dest_dir.is_dir():
        src_dirs = {p.relative_to(src_dir) for p in src_dir.rglob("*") if p.is_dir()}
        # 自底向上遍历，先删深层空目录，再删其父目录
        dest_subdirs = sorted(
            (p for p in dest_dir.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        )
        for d in dest_subdirs:
            rel = d.relative_to(dest_dir)
            if any(part in IGNORED_DIR_NAMES for part in rel.parts):
                continue
            if rel in src_dirs:
                continue
            # 源头无此目录，且目标里已空 → 删除
            if not any(d.iterdir()):
                print(f"  [删除空目录] {rel.as_posix()}  （源头已无）")
                n += 1
                d.rmdir()

    if n == 0:
        print("  （无改动，已一致）")
    print()
    return n


def parse_args():
    parser = argparse.ArgumentParser(
        description="预览或执行 .agents/skills 到 .claude/.codebuddy 的镜像同步。"
    )
    parser.add_argument("--apply", action="store_true", help="执行同步；默认仅预览")
    return parser.parse_args()


def main():
    args = parse_args()
    apply = args.apply

    print("=== 执行模式（正在同步）===" if apply else "=== 预览模式（不写入任何文件）===")
    print(f"项目根：{PROJECT_ROOT}")
    print(f"源头：{SRC}/{{{','.join(SUBDIRS)}}}")
    print()

    changed_total = 0
    for sub in SUBDIRS:
        src_dir = PROJECT_ROOT / SRC / sub
        if not src_dir.is_dir():
            print(f"[跳过] 源头不存在：{SRC}/{sub}\n")
            continue
        for dest in DESTS:
            changed_total += sync_one(src_dir, PROJECT_ROOT / dest / sub, apply)

    print(f"=== 汇总：{changed_total} 处文件改动 ===")
    if not apply and changed_total > 0:
        print("以上为预览。执行同步请运行：python .agents/skills/sync-agent/scripts/sync.py --apply")


if __name__ == "__main__":
    main()
