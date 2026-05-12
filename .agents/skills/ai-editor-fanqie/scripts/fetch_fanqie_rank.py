#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch Fanqie web rank data for market checks.

This script uses Fanqie Novel's public web rank page to obtain rankVersion
and category IDs, then calls the web rank JSON endpoint. It is intended for
editorial market analysis, not bulk scraping.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


RANK_PAGE = "https://fanqienovel.com/rank"
API_URL = "https://fanqienovel.com/api/rank/category/list"
APP_ID = "2503"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

GENDER_MAP = {
    "male": "1",
    "female": "0",
}

RANK_MOLD_MAP = {
    "read": "2",
    "new": "1",
}

DEFAULT_CACHE_DAYS = 30


def safe_slug(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"[\\/:*?\"<>|\s]+", "_", text)
    return text.strip("._") or "default"


def default_cache_dir() -> Path:
    return Path.cwd() / "AI 责编" / "榜单缓存"


def cache_key(args: argparse.Namespace) -> str:
    if args.list_categories:
        return "categories_all"
    if args.scan:
        max_part = args.max_categories if args.max_categories > 0 else "all"
        return (
            f"scan_{args.gender}_{args.rank_type}_"
            f"per{args.per_category}_max{max_part}"
        )
    category = args.category or "都市高武"
    return (
        f"category_{safe_slug(category)}_{args.gender}_"
        f"{args.rank_type}_limit{args.limit}"
    )


def cache_path(args: argparse.Namespace) -> Path:
    return Path(args.cache_dir) / f"{cache_key(args)}.json"


def parse_iso_datetime(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def cache_age_days(result: dict[str, Any], path: Path) -> float:
    fetched_at = parse_iso_datetime(str(result.get("fetched_at", "")))
    if fetched_at is None:
        fetched_at = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)
    return max((now - fetched_at).total_seconds() / 86400, 0)


def load_fresh_cache(path: Path, max_age_days: int) -> dict[str, Any] | None:
    if max_age_days <= 0 or not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if cache_age_days(result, path) > max_age_days:
        return None
    result.setdefault("cache", {})
    result["cache"].update({
        "hit": True,
        "path": str(path),
        "max_age_days": max_age_days,
        "age_days": round(cache_age_days(result, path), 2),
    })
    return result


def save_cache(path: Path, result: dict[str, Any], max_age_days: int) -> None:
    if max_age_days <= 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    cached = dict(result)
    cached.setdefault("cache", {})
    cached["cache"].update({
        "hit": False,
        "path": str(path),
        "max_age_days": max_age_days,
    })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cached, f, ensure_ascii=False, indent=2)


def http_get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": RANK_PAGE,
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def extract_initial_state(html: str) -> dict[str, Any]:
    marker = "__INITIAL_STATE__="
    idx = html.find(marker)
    if idx < 0:
        raise RuntimeError("Cannot find __INITIAL_STATE__ in Fanqie rank page")
    start = idx + len(marker)
    end = html.find("</script>", start)
    if end < 0:
        raise RuntimeError("Cannot find script end after __INITIAL_STATE__")
    raw = html[start:end].strip().rstrip(";").strip()
    raw = re.sub(r"\bundefined\b", "null", raw)
    return json.JSONDecoder().raw_decode(raw)[0]


def get_meta() -> dict[str, Any]:
    html = http_get(RANK_PAGE)
    state = extract_initial_state(html)
    rank = state.get("rank", {}) or {}
    return {
        "rank_version": rank.get("rankVersion", ""),
        "categories": rank.get("rankCategoryTypeList", {}) or {},
        "initial_books": rank.get("book_list", []) or [],
    }


def pua_ratio(text: str) -> float:
    if not text:
        return 0.0
    pua = sum(1 for ch in text if 0xE000 <= ord(ch) <= 0xF8FF)
    return pua / max(len(text), 1)


def normalize_book(item: dict[str, Any], rank: int, sub_category: str = "") -> dict[str, Any]:
    word_number = item.get("wordNumber", 0)
    read_count = item.get("read_count", 0)
    try:
        word_number = int(word_number)
    except (TypeError, ValueError):
        word_number = 0
    try:
        read_count = int(read_count)
    except (TypeError, ValueError):
        read_count = 0

    title = str(item.get("bookName", "") or "")
    intro = str(item.get("abstract", "") or "")
    author = str(item.get("author", "") or "")
    book_id = str(item.get("bookId", "") or "")
    category = str(item.get("categoryV2", "") or item.get("category", "") or "")

    return {
        "rank": rank,
        "book_id": book_id,
        "title": title,
        "author": author,
        "intro": intro[:300],
        "word_number": word_number,
        "read_count": read_count,
        "category": category,
        "sub_category": sub_category,
        "url": f"https://fanqienovel.com/page/{book_id}" if book_id else "",
        "has_pua_text": any(pua_ratio(v) > 0 for v in [title, intro, author, category]),
    }


def find_category(categories: dict[str, Any], category: str, gender: str | None) -> tuple[str, str, str]:
    if not category:
        raise ValueError("category is required")
    search_genders = [gender] if gender in ("male", "female") else ["male", "female"]
    for gender_key in search_genders:
        for cat in categories.get(gender_key, []) or []:
            cat_id = str(cat.get("id", ""))
            cat_name = str(cat.get("name", ""))
            if category in {cat_id, cat_name}:
                return cat_id, cat_name, GENDER_MAP[gender_key]
    # Allow raw category ID fallback, defaulting to male.
    return category, category, GENDER_MAP.get(gender or "male", "1")


def api_call(
    rank_version: str,
    category_id: str,
    gender_code: str,
    rank_type: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    params = {
        "app_id": APP_ID,
        "rank_list_type": "3",
        "offset": str(offset),
        "limit": str(limit),
        "category_id": category_id,
        "rank_version": rank_version,
        "gender": gender_code,
        "rankMold": RANK_MOLD_MAP.get(rank_type, "2"),
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    text = http_get(url)
    data = json.loads(text)
    if data.get("code") != 0:
        raise RuntimeError(f"Fanqie API error: code={data.get('code')} msg={data.get('msg')}")
    return data


def fetch_category_rank(
    meta: dict[str, Any],
    category: str,
    gender: str | None,
    rank_type: str,
    limit: int,
) -> dict[str, Any]:
    cat_id, cat_name, gender_code = find_category(meta["categories"], category, gender)
    books: list[dict[str, Any]] = []
    for offset in range(0, limit, 10):
        page_limit = min(10, limit - offset)
        data = api_call(meta["rank_version"], cat_id, gender_code, rank_type, offset, page_limit)
        book_list = data.get("data", {}).get("book_list", []) or []
        for item in book_list:
            books.append(normalize_book(item, len(books) + 1, cat_name))
        if len(book_list) < page_limit:
            break
    return make_result(f"番茄小说 {cat_name} {rank_label(rank_type)}", rank_type, books, meta, category=cat_name)


def fetch_gender_scan(
    meta: dict[str, Any],
    gender: str,
    rank_type: str,
    per_category: int,
    max_categories: int | None = None,
) -> dict[str, Any]:
    books: list[dict[str, Any]] = []
    categories = meta["categories"].get(gender, []) or []
    if max_categories is not None and max_categories > 0:
        categories = categories[:max_categories]
    gender_code = GENDER_MAP[gender]
    for cat in categories:
        cat_id = str(cat.get("id", ""))
        cat_name = str(cat.get("name", ""))
        if not cat_id:
            continue
        try:
            data = api_call(meta["rank_version"], cat_id, gender_code, rank_type, 0, per_category)
        except Exception as exc:
            print(f"warn: failed category {cat_name}({cat_id}): {exc}", file=sys.stderr)
            continue
        for item in data.get("data", {}).get("book_list", []) or []:
            books.append(normalize_book(item, len(books) + 1, cat_name))
    return make_result(f"番茄小说 {gender_label(gender)}全分类扫描 {rank_label(rank_type)}", rank_type, books, meta)


def rank_label(rank_type: str) -> str:
    return "在读榜" if rank_type == "read" else "新书榜"


def gender_label(gender: str) -> str:
    return "男频" if gender == "male" else "女频"


def make_result(
    title: str,
    rank_type: str,
    books: list[dict[str, Any]],
    meta: dict[str, Any],
    category: str = "",
) -> dict[str, Any]:
    category_stats: dict[str, dict[str, Any]] = {}
    for book in books:
        cat = book.get("sub_category") or book.get("category") or "未分类"
        stat = category_stats.setdefault(cat, {"book_count": 0, "total_read_count": 0, "top_rank": None})
        stat["book_count"] += 1
        stat["total_read_count"] += int(book.get("read_count") or 0)
        rank = int(book.get("rank") or 0)
        if stat["top_rank"] is None or rank < stat["top_rank"]:
            stat["top_rank"] = rank
    for stat in category_stats.values():
        count = stat["book_count"] or 1
        stat["avg_read_count"] = stat["total_read_count"] // count

    return {
        "source": "fanqienovel.com web rank API",
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "title": title,
        "rank_type": rank_type,
        "category": category,
        "rank_version": meta.get("rank_version", ""),
        "note": (
            "Text fields may contain PUA private-use characters due to Fanqie web font obfuscation. "
            "Category IDs, ranks, URLs, word counts, and read counts remain useful for market analysis."
        ),
        "category_stats": sorted(
            category_stats.items(),
            key=lambda kv: (kv[1]["total_read_count"], kv[1]["book_count"]),
            reverse=True,
        ),
        "books": books,
    }


def list_categories(meta: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for gender_key in ["male", "female"]:
        for cat in meta["categories"].get(gender_key, []) or []:
            rows.append({
                "gender": gender_key,
                "gender_label": gender_label(gender_key),
                "id": cat.get("id", ""),
                "name": cat.get("name", ""),
            })
    return {
        "source": "fanqienovel.com/rank __INITIAL_STATE__",
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rank_version": meta.get("rank_version", ""),
        "categories": rows,
    }


def print_summary(result: dict[str, Any]) -> None:
    cache = result.get("cache") or {}
    if cache.get("hit"):
        print(
            f"[cache hit] {cache.get('path')} | "
            f"age={cache.get('age_days')}d max_age={cache.get('max_age_days')}d"
        )
    elif cache.get("path"):
        print(f"[cache saved] {cache.get('path')}")

    if "categories" in result:
        print(f"Fanqie categories | rank_version={result.get('rank_version')}")
        for cat in result.get("categories", []):
            print(f"- {cat.get('gender_label')} {cat.get('id')} {cat.get('name')}")
        return

    print(f"{result.get('title', 'Fanqie rank')} | rank_version={result.get('rank_version')}")
    print(result.get("note", ""))
    stats = result.get("category_stats", [])
    if stats:
        print("\nCategory stats:")
        for cat, stat in stats[:20]:
            print(
                f"- {cat}: books={stat['book_count']} "
                f"total_read={stat['total_read_count']} avg_read={stat['avg_read_count']}"
            )
    books = result.get("books", [])
    if books:
        print("\nTop books:")
        for book in books[:30]:
            print(
                f"{book['rank']:>3}. [{book.get('sub_category') or book.get('category')}] "
                f"{book.get('title')} | read={book.get('read_count')} | {book.get('url')}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Fanqie Novel web rank data")
    parser.add_argument("--list-categories", action="store_true", help="List Fanqie rank categories")
    parser.add_argument("--scan", action="store_true", help="Scan all categories for a gender")
    parser.add_argument("--category", default="", help="Category name or ID, e.g. 都市高武 or 1014")
    parser.add_argument("--gender", choices=["male", "female"], default="male")
    parser.add_argument("--rank-type", choices=["read", "new"], default="read")
    parser.add_argument("--limit", type=int, default=30, help="Books to fetch for category mode")
    parser.add_argument("--per-category", type=int, default=10, help="Books per category for scan mode")
    parser.add_argument("--max-categories", type=int, default=0, help="Max categories for scan mode; 0 means all")
    parser.add_argument("--output", default="", help="Write JSON to this path")
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary")
    parser.add_argument("--cache-dir", default=str(default_cache_dir()), help="Directory for local rank cache")
    parser.add_argument("--cache-days", type=int, default=DEFAULT_CACHE_DAYS, help="Reuse cached rank data within this many days; 0 disables cache")
    parser.add_argument("--refresh", action="store_true", help="Ignore cache and fetch fresh data")
    args = parser.parse_args()

    cpath = cache_path(args)
    if not args.refresh:
        cached_result = load_fresh_cache(cpath, args.cache_days)
        if cached_result is not None:
            text = json.dumps(cached_result, ensure_ascii=False, indent=2)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(text)
            if args.summary:
                print_summary(cached_result)
            else:
                print(text)
            return 0

    meta = get_meta()
    if args.list_categories:
        result = list_categories(meta)
    elif args.scan:
        max_categories = args.max_categories if args.max_categories > 0 else None
        result = fetch_gender_scan(meta, args.gender, args.rank_type, args.per_category, max_categories)
    else:
        category = args.category or "都市高武"
        result = fetch_category_rank(meta, category, args.gender, args.rank_type, args.limit)

    result.setdefault("cache", {})
    result["cache"].update({
        "hit": False,
        "path": str(cpath),
        "max_age_days": args.cache_days,
    })
    save_cache(cpath, result, args.cache_days)

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    if args.summary:
        print_summary(result)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
