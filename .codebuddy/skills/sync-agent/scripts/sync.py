#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步脚本：以 .agents/skills/ 为唯一源头，把 skills 镜像到 .claude/ 和 .codebuddy/

用法：
    python sync.py            # 预览：只显示会改动哪些文件和目录，不实际写入
    python sync.py --apply    # 执行：真正同步

规则：改技能时，只改 .agents/skills/ 下的源文件，然后跑本脚本推给另外两套。
项目文本规则维护在仓库根目录的 AGENTS.md，不由本脚本同步。

删除语义（真镜像）：
    镜像里源头已经不存在的顶层技能目录会被整体删除，包括目录内的缓存文件，
    因此源头删除一个技能后，镜像不会留下残留空壳。
    预览模式同样会报告这些删除，不会出现“预览说一致、实际有残留”的情况。

    安全阀：源头 skills 目录缺失或没有任何技能目录时，本脚本跳过该次同步，
    不执行任何删除，避免源头异常导致镜像被清空。

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

# 操作类型
COPY = "copy"        # 新增或更新单个文件
UNLINK = "unlink"    # 删除单个多余文件
RMTREE = "rmtree"    # 整体删除多余的目录（含内部缓存）


def is_ignored_dir(name: str) -> bool:
    return name in IGNORED_DIR_NAMES


def is_ignored_file(name: str) -> bool:
    return name in IGNORED_FILE_NAMES or Path(name).suffix.lower() in IGNORED_SUFFIXES


def rel_dir_set(base: Path) -> set:
    """base 下所有子目录的相对路径（不含 base 自身），忽略缓存目录。"""
    out = set()
    if not base.is_dir():
        return out
    for p in base.rglob("*"):
        if not p.is_dir():
            continue
        rel = p.relative_to(base)
        if any(is_ignored_dir(part) for part in rel.parts):
            continue
        out.add(rel)
    return out


def rel_file_set(base: Path) -> set:
    """base 下所有应参与镜像的文件相对路径，忽略缓存文件与缓存目录。"""
    out = set()
    if not base.is_dir():
        return out
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        # 父目录链上任何一层是缓存目录就跳过
        if any(is_ignored_dir(part) for part in rel.parts[:-1]):
            continue
        if is_ignored_file(p.name):
            continue
        out.add(rel)
    return out


def ignored_entries(base: Path) -> set:
    """base 下所有本机缓存条目的相对路径（__pycache__ 目录、*.pyc、.DS_Store）。

    这些不属于镜像范围。命中父目录后不再列出其子项，避免重复删除。
    """
    out = set()
    if not base.is_dir():
        return out
    for p in base.rglob("*"):
        rel = p.relative_to(base)
        if any(anc in out for anc in rel.parents):
            continue
        if p.is_dir() and is_ignored_dir(p.name):
            out.add(rel)
        elif p.is_file() and is_ignored_file(p.name):
            out.add(rel)
    return out


def build_plan(src_dir: Path, dest_dir: Path):
    """计算镜像操作计划，不触碰文件系统。返回 (操作列表, 说明)。

    预览与执行共用本函数，保证预览结果与实际改动完全一致。
    操作列表元素为 (kind, 相对路径, 标注)。
    """
    plan = []

    if not src_dir.is_dir():
        return plan, "源头不存在"

    src_skills = sorted(p.name for p in src_dir.iterdir() if p.is_dir())
    if not src_skills:
        return plan, "源头没有任何技能目录"

    src_skill_set = set(src_skills)
    src_top_files = {p.name for p in src_dir.iterdir() if p.is_file()}

    # --- 1. 镜像顶层的孤儿条目：源头已无的技能目录 / 散落文件 ---
    if dest_dir.is_dir():
        for p in sorted(dest_dir.iterdir(), key=lambda x: x.name):
            if p.is_dir():
                if p.name not in src_skill_set:
                    plan.append((RMTREE, Path(p.name), "源头已无此技能目录"))
            elif p.is_file():
                if p.name not in src_top_files:
                    plan.append((UNLINK, Path(p.name), "源头已无"))

    # --- 2. 每个技能目录内部 ---
    for skill in src_skills:
        s_root = src_dir / skill
        d_root = dest_dir / skill

        # 2a. 镜像里源头没有的子目录：整体删除（含内部缓存）
        pruned = set()
        if d_root.is_dir():
            extra_dirs = sorted(
                rel_dir_set(d_root) - rel_dir_set(s_root),
                key=lambda r: len(r.parts),  # 浅的先处理，父目录删除后跳过子目录
            )
            for rel in extra_dirs:
                if any(anc == rel or anc in rel.parents for anc in pruned):
                    continue
                pruned.add(rel)
                plan.append((RMTREE, Path(skill) / rel, "源头已无此目录"))

        def is_pruned(rel: Path) -> bool:
            """该相对路径是否已被计划删除的目录覆盖。"""
            return any(anc == rel or anc in rel.parents for anc in pruned)

        # 2b. 文件级对比：新增 / 更新
        s_files = rel_file_set(s_root)
        d_files = rel_file_set(d_root)
        for rel in sorted(s_files):
            s = s_root / rel
            d = d_root / rel
            if is_pruned(rel):
                continue
            if not d.exists():
                plan.append((COPY, Path(skill) / rel, "新增"))
            elif not filecmp.cmp(s, d, shallow=False):
                plan.append((COPY, Path(skill) / rel, "更新"))

        # 2c. 镜像里源头没有的文件：删除（已随目录整体删除的跳过，避免重复报告）
        for rel in sorted(d_files - s_files):
            if is_pruned(rel):
                continue
            plan.append((UNLINK, Path(skill) / rel, "源头已无"))

        # 2d. 镜像里存活技能内部的本机缓存：删除
        #     这些条目被排除在比较集合之外，不主动清理就会永久残留
        for rel in sorted(ignored_entries(d_root)):
            if is_pruned(rel):
                continue
            kind = RMTREE if (d_root / rel).is_dir() else UNLINK
            plan.append((kind, Path(skill) / rel, "本机缓存，不属于镜像"))

    # 2e. 顶层散落文件的同步
    for name in sorted(src_top_files):
        s = src_dir / name
        d = dest_dir / name
        if not d.exists():
            plan.append((COPY, Path(name), "新增"))
        elif not filecmp.cmp(s, d, shallow=False):
            plan.append((COPY, Path(name), "更新"))

    return plan, ""


LABELS = {COPY: None, UNLINK: "删除", RMTREE: "删除目录"}


def apply_plan(src_dir: Path, dest_dir: Path, plan) -> int:
    """执行操作计划，返回改动数。"""
    if not plan:
        return 0
    dest_dir.mkdir(parents=True, exist_ok=True)
    for kind, rel, _note in plan:
        target = dest_dir / rel
        if kind == COPY:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_dir / rel, target)
        elif kind == UNLINK:
            if target.exists():
                target.unlink()
        elif kind == RMTREE:
            if target.is_dir():
                shutil.rmtree(target)
    return len(plan)


def report(plan) -> int:
    """打印计划内容，返回改动数。"""
    for kind, rel, note in plan:
        if kind == COPY:
            # 区分新增和更新：执行前目标是否存在
            print(f"  [{note}] {rel.as_posix()}")
        else:
            print(f"  [{LABELS[kind]}] {rel.as_posix()}  （{note}）")
    return len(plan)


def sync_one(src_dir: Path, dest_dir: Path, apply: bool) -> int:
    """把 src_dir 镜像到 dest_dir，返回改动数。"""
    print(f"--- {src_dir.relative_to(PROJECT_ROOT)}  ->  {dest_dir.relative_to(PROJECT_ROOT)} ---")

    plan, skip_reason = build_plan(src_dir, dest_dir)
    if skip_reason:
        print(f"  [跳过] {skip_reason}，不做任何删除")
        print()
        return 0

    if not plan:
        print("  （无改动，已一致）")
        print()
        return 0

    # 预览与执行共用同一份计划；执行前先打印，保证所见即所做
    n = report(plan)
    if apply:
        apply_plan(src_dir, dest_dir, plan)
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
