#!/usr/bin/env python3
"""Generate chapter summaries for the book-analysis skill.

The script is deliberately limited to deterministic preparation work:
encoding detection, chapter extraction, resumable API summarization, and
writing the intermediate 1_故事梗概.md file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


PROMPT_VERSION = "book-analysis-summary-v2"
SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown"}

HEADING_CORE = (
    r"(?:"
    r"第[零〇一二三四五六七八九十百千万两\d]{1,12}[章回节](?:[ \t:：._-]+[^\r\n]{0,80})?"
    r"|Chapter[ \t]*\d+(?:[ \t:：._-]+[^\r\n]{0,80})?"
    r"|(?:序章|楔子|引子|尾声|终章|番外|前言|后记)(?:[ \t:：._-]+[^\r\n]{0,80})?"
    r"|[0-9]{1,5}[、.．][ \t]*[^\r\n]{1,80}"
    r")"
)

STRICT_HEADING_RE = re.compile(
    rf"^[ \t]*(?:#{{1,6}}[ \t]+)?(?P<title>{HEADING_CORE})[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

LOOSE_HEADING_RE = re.compile(
    rf"^[ \t]*(?:#{{1,6}}[ \t]+)?(?P<title>(?:{HEADING_CORE}|[0-9]{{1,5}}[ \t]+[^\r\n]{{1,80}}))[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def skill_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def default_workspace_root() -> Path:
    # scripts -> book-analysis -> skills -> .agents -> workspace root
    return Path(__file__).resolve().parents[4]


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and os.getenv(key) is None:
                os.environ[key] = value
    except OSError:
        return


def write_env_template(path: Path) -> None:
    if path.exists():
        return
    path.write_text(
        "# 样板书梗概脚本 API 配置\n"
        "NOVEL_API_KEY=\n"
        "NOVEL_API_BASE=https://api.openai.com/v1\n"
        "NOVEL_API_MODEL=gpt-4o\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="为样板书拆解生成章节梗概")
    parser.add_argument("novel_path", type=Path, help="样板书 TXT/MD 文件路径")
    parser.add_argument("--workspace-root", type=Path, default=default_workspace_root())
    parser.add_argument("--output-dir", type=Path, help="输出目录；相对路径按项目根解析")
    parser.add_argument("--title", help="覆盖输出目录使用的书名")
    parser.add_argument("--encoding", help="指定编码；默认自动尝试 utf-8-sig、gb18030、big5")
    parser.add_argument("--loose-headings", action="store_true", help="额外识别“1 标题”形式的章节标题")
    parser.add_argument("--inspect", action="store_true", help="只检查编码和章节，不调用 API")
    parser.add_argument("--start", type=int, default=1, help="从识别出的第几章开始，默认 1")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少章，0 表示不限制")
    parser.add_argument("--batch-size", type=int, default=5, help="每批最多多少章")
    parser.add_argument("--max-input-chars", type=int, default=24000, help="每批正文最多字符数")
    parser.add_argument("--workers", type=int, default=3, help="并行请求数")
    parser.add_argument("--retries", type=int, default=3, help="单批失败后的重试次数")
    parser.add_argument("--timeout", type=float, default=90, help="单次 API 请求超时秒数")
    parser.add_argument("--refresh", action="store_true", help="忽略已有缓存并重新生成")
    return parser.parse_args()


def read_source(path: Path, requested_encoding: str | None) -> tuple[str, str, str]:
    raw = path.read_bytes()
    candidates = [requested_encoding] if requested_encoding else ["utf-8-sig", "gb18030", "big5"]
    errors: list[str] = []
    for encoding in candidates:
        if not encoding:
            continue
        try:
            text = raw.decode(encoding)
            if "\x00" in text:
                raise UnicodeError("检测到 NUL 字节，疑似不是文本文件")
            digest = hashlib.sha256(raw).hexdigest()
            return text, encoding, digest
        except (UnicodeDecodeError, UnicodeError) as exc:
            errors.append(f"{encoding}: {exc}")
    raise UnicodeError("无法识别文件编码；请使用 --encoding 指定。\n" + "\n".join(errors))


def extract_chapters(text: str, loose_headings: bool = False) -> list[dict[str, Any]]:
    pattern = LOOSE_HEADING_RE if loose_headings else STRICT_HEADING_RE
    matches = list(pattern.finditer(text))
    chapters: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chapters.append(
            {
                "index": index + 1,
                "title": match.group("title").strip(),
                "content": text[match.end() : end].strip(),
            }
        )
    return chapters


def safe_title(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", value).strip(" .")
    return cleaned or "未命名样板书"


def print_inspection(path: Path, encoding: str, text: str, chapters: list[dict[str, Any]]) -> None:
    payload = {
        "path": str(path),
        "encoding": encoding,
        "characters": len(text),
        "chapters": len(chapters),
        "first_chapters": [c["title"] for c in chapters[:5]],
        "last_chapters": [c["title"] for c in chapters[-3:]],
        "empty_chapters": [c["index"] for c in chapters if not c["content"]],
        "chapter_sizes": {
            "max": max((len(c["content"]) for c in chapters), default=0),
            "average": round(
                sum(len(c["content"]) for c in chapters) / len(chapters), 1
            )
            if chapters
            else 0,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def select_chapters(chapters: list[dict[str, Any]], start: int, limit: int) -> list[dict[str, Any]]:
    if start < 1:
        raise ValueError("--start 必须大于等于 1")
    selected = chapters[start - 1 :]
    return selected[:limit] if limit > 0 else selected


def build_batches(
    chapters: list[dict[str, Any]], batch_size: int, max_input_chars: int
) -> list[dict[str, Any]]:
    if batch_size < 1 or max_input_chars < 1:
        raise ValueError("--batch-size 和 --max-input-chars 必须大于 0")
    batches: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for chapter in chapters:
        size = len(chapter["content"])
        if size > max_input_chars:
            raise ValueError(
                f"第 {chapter['index']} 章正文 {size} 字，超过 --max-input-chars={max_input_chars}；"
                "请提高上限或先拆分该章节。"
            )
        if current and (len(current) >= batch_size or current_chars + size > max_input_chars):
            batches.append({"chapters": current})
            current = []
            current_chars = 0
        current.append(chapter)
        current_chars += size
    if current:
        batches.append({"chapters": current})
    for batch in batches:
        first = batch["chapters"][0]["index"]
        last = batch["chapters"][-1]["index"]
        batch["id"] = f"batch_{first:04d}_{last:04d}"
    return batches


def cache_key(batch: dict[str, Any], source_digest: str, model: str, base_url: str) -> str:
    payload = {
        "prompt": PROMPT_VERSION,
        "source": source_digest,
        "model": model,
        "base_url": base_url,
        "chapters": [
            {
                "index": c["index"],
                "title": c["title"],
                "content": hashlib.sha256(c["content"].encode("utf-8")).hexdigest(),
            }
            for c in batch["chapters"]
        ],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def validate_summary(content: str, expected_count: int) -> None:
    sections = list(re.finditer(r"^##\s+.+$", content, re.MULTILINE))
    if len(sections) != expected_count:
        raise ValueError(f"模型返回 {len(sections)} 个章节，预期 {expected_count} 个")
    for index, match in enumerate(sections):
        end = sections[index + 1].start() if index + 1 < len(sections) else len(content)
        body = content[match.end() : end].strip(" -\n")
        if len(body) < 15:
            raise ValueError(f"第 {index + 1} 个章节梗概过短")


def get_client(api_key: str, base_url: str, timeout: float) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("未安装 openai 库，请先安装后再运行梗概脚本。") from exc
    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)


def generate_summary(client: Any, model: str, batch: dict[str, Any], retries: int) -> str:
    chapters = batch["chapters"]
    titles = "、".join(c["title"] for c in chapters)
    body = "\n\n".join(
        f"===== {chapter['title']} =====\n{chapter['content']}" for chapter in chapters
    )
    messages = [
        {
            "role": "system",
            "content": "你是网文资料整理助手。只输出简体中文 Markdown 章节梗概，不评价作品，不补写原文没有的剧情。",
        },
        {
            "role": "user",
            "content": (
                f"请为以下 {len(chapters)} 个章节分别写 50-100 字梗概。\n"
                f"章节顺序：{titles}\n"
                "每章必须单独输出，标题必须使用原始章节标题，格式只能是：\n"
                "## 原始章节标题\n梗概正文\n\n"
                "重点记录核心行动、冲突变化、结果和新悬念，不要写空泛评价。\n\n"
                f"正文：\n{body}"
            ),
        },
    ]
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=max(1200, len(chapters) * 350),
            )
            result = response.choices[0].message.content or ""
            validate_summary(result, len(chapters))
            return result.strip()
        except Exception as exc:  # API-compatible clients expose different exception classes.
            last_error = exc
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"批次 {batch['id']} 失败：{last_error}")


def atomic_write(path: Path, content: str) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def main() -> int:
    args = parse_args()
    novel_path = args.novel_path.expanduser().resolve()
    if not novel_path.is_file():
        print(f"错误：文件不存在：{novel_path}", file=sys.stderr)
        return 2
    if novel_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        print(f"错误：只支持 TXT、MD、Markdown 文件：{novel_path}", file=sys.stderr)
        return 2

    try:
        text, encoding, source_digest = read_source(novel_path, args.encoding)
        chapters = extract_chapters(text, args.loose_headings)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if not chapters:
        print(
            "未识别到章节标题。请检查文件格式，或在确认标题格式后使用 --loose-headings。",
            file=sys.stderr,
        )
        return 2
    if args.inspect:
        print_inspection(novel_path, encoding, text, chapters)
        return 0

    try:
        selected = select_chapters(chapters, args.start, args.limit)
        batches = build_batches(selected, args.batch_size, args.max_input_chars)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if not selected:
        print("错误：指定范围内没有章节。", file=sys.stderr)
        return 2

    load_dotenv(skill_dir() / ".env")
    api_key = os.getenv("NOVEL_API_KEY", "")
    if not api_key:
        env_path = skill_dir() / ".env"
        try:
            write_env_template(env_path)
        except OSError as exc:
            print(f"错误：无法创建配置模板：{exc}", file=sys.stderr)
            return 2
        print(f"未配置 NOVEL_API_KEY，已准备模板：{env_path}", file=sys.stderr)
        return 2

    workspace_root = args.workspace_root.expanduser().resolve()
    title = safe_title(args.title or novel_path.stem)
    output_dir = args.output_dir or (workspace_root / "样板书拆解" / title)
    if not output_dir.is_absolute():
        output_dir = workspace_root / output_dir
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / ".summary_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "1_故事梗概.md"

    base_url = os.getenv("NOVEL_API_BASE", "https://api.openai.com/v1")
    model = os.getenv("NOVEL_API_MODEL", "gpt-4o")
    try:
        client = get_client(api_key, base_url, args.timeout)
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    pending: list[tuple[dict[str, Any], Path]] = []
    results: dict[str, str] = {}

    for batch in batches:
        key = cache_key(batch, source_digest, model, base_url)
        cache_path = cache_dir / f"{batch['id']}_{key}.md"
        if not args.refresh and cache_path.is_file():
            cached = cache_path.read_text(encoding="utf-8")
            try:
                validate_summary(cached, len(batch["chapters"]))
                results[batch["id"]] = cached.strip()
                continue
            except ValueError:
                pass
        pending.append((batch, cache_path))

    print(f"识别 {len(chapters)} 章，选取 {len(selected)} 章，分为 {len(batches)} 批。")
    print(f"缓存命中 {len(results)} 批，待处理 {len(pending)} 批。")
    failures: list[str] = []
    workers = max(1, min(args.workers, len(pending) or 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(generate_summary, client, model, batch, args.retries): (batch, cache_path)
            for batch, cache_path in pending
        }
        for future in as_completed(futures):
            batch, cache_path = futures[future]
            try:
                summary = future.result()
                atomic_write(cache_path, summary + "\n")
                results[batch["id"]] = summary
                print(f"完成 {batch['id']}")
            except Exception as exc:
                failures.append(f"{batch['id']}: {exc}")

    if failures:
        print("梗概未完成，未覆盖最终文件。失败批次：", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    header = (
        f"# 《{title}》全书故事梗概\n\n"
        f"> 来源：{novel_path.name}；编码：{encoding}；章节：{len(selected)}；模型：{model}\n\n"
    )
    final_content = header + "\n\n".join(results[batch["id"]] for batch in batches) + "\n"
    atomic_write(output_file, final_content)
    print(f"已生成：{output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
