#!/usr/bin/env python3
"""Render a three-column prose revision comparison as a static HTML file."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def block(value: object) -> str:
    return esc(value).replace("\n", "<br>\n")


def rich_block(value: object) -> str:
    """Escape text, then allow a tiny safe subset used by model summaries."""
    rendered = block(value)
    replacements = {
        "&lt;br&gt;": "<br>",
        "&lt;br/&gt;": "<br>",
        "&lt;br /&gt;": "<br>",
        "&lt;strong&gt;": "<strong>",
        "&lt;/strong&gt;": "</strong>",
        "&lt;b&gt;": "<strong>",
        "&lt;/b&gt;": "</strong>",
    }
    for old, new in replacements.items():
        rendered = rendered.replace(old, new)
    return rendered


import re


def count_words(text: str) -> int:
    """统计中文字数（含中文标点），排除空格/英文/数字/Markdown符号。
    与 fanqie-long-zhengwen/count_chinese_words.py 逻辑一致。"""
    t = re.sub(r'\s+', '', text)
    t = re.sub(r'[a-zA-Z0-9]+', '', t)
    t = re.sub(r'[#*_`\[\]\(\)]+', '', t)
    return len(t)


def render(data: dict) -> str:
    title = data.get("title") or "润色结果预览页"
    source = data.get("source") or ""
    function = data.get("function") or ""
    recommendation = data.get("recommendation") or ""
    versions = data.get("versions") or []
    while len(versions) < 3:
        versions.append({"name": f"版本{len(versions) + 1}", "text": ""})


    source_card = f"""          <article class="version source-version">
            <h3>原文 <span class="wordcount">{count_words(source)} 字</span></h3>
            <div class="text">{block(source)}</div>
          </article>"""
    version_cards = []
    for item in versions[:3]:
        version_cards.append(
            f"""          <article class="version">
            <h3>{esc(item.get("name", ""))} <span class="wordcount">{count_words(item.get("text", ""))} 字</span></h3>
            <div class="text">{block(item.get("text", ""))}</div>
          </article>"""
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    :root {{
      --bg: #f6f3ee;
      --paper: #fffdf8;
      --ink: #1f252b;
      --muted: #65717d;
      --line: #ded7cc;
      --accent: #2f6f73;
      --accent-soft: #dceeed;
      --shadow: 0 10px 30px rgba(31, 37, 43, .08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: linear-gradient(180deg, rgba(47,111,115,.08), transparent 320px), var(--bg);
      font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", system-ui, sans-serif;
      line-height: 1.78;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      border-bottom: 1px solid var(--line);
      background: rgba(246, 243, 238, .92);
      backdrop-filter: blur(12px);
    }}
    .bar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
      width: min(100%, 1920px);
      margin: 0 auto;
      padding: 18px 16px;
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      font-weight: 800;
      letter-spacing: 0;
    }}
    .hint {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      white-space: nowrap;
    }}
    main {{
      width: min(100%, 1920px);
      margin: 0 auto;
      padding: 16px;
    }}
    section {{ margin-bottom: 26px; }}
    .panel, .version {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--paper);
      box-shadow: var(--shadow);
    }}
    .section-head {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 20px 0;
    }}
    h2 {{ margin: 0; font-size: 18px; }}
    .tag {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 3px 10px;
      border-radius: 999px;
      color: var(--accent);
      background: var(--accent-soft);
      font-size: 13px;
      font-weight: 700;
    }}
    .body {{ padding: 16px 20px 20px; }}
    .prose {{
      max-width: 980px;
      white-space: normal;
      font-size: 16px;
    }}
    .compare-wrap {{
      overflow-x: auto;
      padding-bottom: 12px;
    }}
    .compare {{
      display: grid;
      grid-template-columns: repeat(4, minmax(360px, 1fr));
      gap: 16px;
      width: 100%;
      min-width: 1504px;
    }}
    .version {{
      display: flex;
      min-height: 720px;
      flex-direction: column;
      overflow: hidden;
    }}
    .version h3 {{
      margin: 0;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: #fbf8f1;
      font-size: 17px;
    }}
    .wordcount {{
      float: right;
      font-weight: 500;
      font-size: 13px;
      color: var(--muted);
    }}
    .text {{
      padding: 16px;
      font-size: 16px;
    }}
    .recommend {{ border-left: 5px solid var(--accent); }}
    .recommend strong {{ color: var(--accent); }}
    .small {{ color: var(--muted); font-size: 13px; }}
    @media (max-width: 860px) {{
      .bar {{ align-items: flex-start; flex-direction: column; padding: 16px; }}
      .hint {{ white-space: normal; }}
      main {{ padding: 16px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <h1>{esc(title)}</h1>
      <p class="hint">电脑端建议全屏查看；四列区域可横向滚动。</p>
    </div>
  </header>
  <main>
    <section class="panel">
      <div class="section-head">
        <h2>原版剧情功能</h2>
        <span class="tag">诊断</span>
      </div>
      <div class="body"><div class="prose">{block(function)}</div></div>
    </section>

    <section>
      <div class="compare-wrap">
        <div class="compare">
{source_card}
{chr(10).join(version_cards)}
        </div>
      </div>
    </section>

    <section class="panel recommend">
      <div class="section-head">
        <h2>推荐</h2>
        <span class="tag">建议采用</span>
      </div>
      <div class="body"><div class="prose">{rich_block(recommendation)}</div></div>
    </section>

    <p class="small">由 writing-optimization 技能生成。</p>
  </main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="JSON file containing comparison data")
    source.add_argument("--json", help="JSON string containing comparison data")
    source.add_argument("--stdin", action="store_true", help="Read comparison JSON from stdin")
    parser.add_argument("--output", required=True, help="HTML output path")
    args = parser.parse_args()

    output_path = Path(args.output)
    if args.stdin:
        raw_json = sys.stdin.read()
    elif args.json is not None:
        raw_json = args.json
    else:
        raw_json = Path(args.input).read_text(encoding="utf-8-sig")

    data = json.loads(raw_json.lstrip("\ufeff"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render(data), encoding="utf-8")
    print(output_path.resolve())


if __name__ == "__main__":
    main()
