# -*- coding: utf-8 -*-
"""零依赖 HTML 解析工具。

标准库没有 BeautifulSoup，这里用 html.parser 实现一个够用的 DOM：
- 容错解析（自动闭合、忽略注释与脚本内容）
- 类 CSS 的简化选择器（标签/类/ID/属性/后代组合）
- 正文抽取启发式

不追求完整 CSS 规范，只覆盖小说站点解析需要的能力。
"""
from __future__ import annotations

import html as html_mod
import re
from html.parser import HTMLParser

__all__ = ["Node", "parse_html", "html_to_text", "NodeList", "select"]

# 不会产生文本内容的标签
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
# 解析时跳过其内容的标签（注意不含 head：meta/title/link 需要保留）
SKIP_CONTENT = {"script", "style", "noscript", "template", "svg"}


class Node:
    """极简 DOM 节点。"""

    __slots__ = ("tag", "attrs", "children", "parent", "text_parts")

    def __init__(self, tag: str, attrs: dict[str, str] | None = None,
                 parent: "Node | None" = None) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Node] = []
        self.parent = parent
        self.text_parts: list[str] = []

    # -- 属性访问 ---------------------------------------------------------
    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    @property
    def classes(self) -> list[str]:
        return self.attrs.get("class", "").split()

    @property
    def classes_set(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    @property
    def id(self) -> str:
        return self.attrs.get("id", "")

    def has_class(self, name: str) -> bool:
        return name in self.classes_set

    # -- 文本 -------------------------------------------------------------
    @property
    def text(self) -> str:
        """自身直接文本（不含后代）。"""
        return "".join(self.text_parts)

    def all_text(self, separator: str = "") -> str:
        """本级与全部后代的文本。"""
        parts: list[str] = []
        self._collect_text(parts)
        raw = "".join(parts)
        if separator:
            return separator.join(p for p in (s.strip() for s in parts) if p)
        return raw

    def _collect_text(self, out: list[str]) -> None:
        out.extend(self.text_parts)
        for child in self.children:
            child._collect_text(out)

    # -- 遍历 -------------------------------------------------------------
    def iter(self):
        yield self
        for child in self.children:
            yield from child.iter()

    def find(self, selector: str) -> "Node | None":
        found = self.select(selector, limit=1)
        return found[0] if found else None

    def select(self, selector: str, *, limit: int = 0) -> "NodeList":
        return select(self, selector, limit=limit)

    def __repr__(self) -> str:
        cls = ".".join(self.classes)
        ident = f"#{self.id}" if self.id else ""
        return f"<Node {self.tag}{ident}{'.' + cls if cls else ''}>"


class NodeList(list):
    """节点列表，支持链式取文本。"""

    def all_text(self, separator: str = "") -> list[str]:
        return [n.all_text(separator) for n in self]

    def texts(self, separator: str = "") -> list[str]:
        return [n.all_text(separator).strip() for n in self]

    def first(self) -> Node | None:
        return self[0] if self else None

    def attr(self, name: str) -> list[str]:
        return [n.get(name) for n in self]


class _DomBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack: list[Node] = [self.root]
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v if v is not None else "") for k, v in attrs}
        if self._skip_depth:
            if tag in SKIP_CONTENT:
                self._skip_depth += 1
            return
        if tag in SKIP_CONTENT:
            self._skip_depth = 1
            return
        node = Node(tag, attr_map, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth:
            return
        if tag in SKIP_CONTENT:
            return
        attr_map = {k: (v if v is not None else "") for k, v in attrs}
        node = Node(tag, attr_map, parent=self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag in SKIP_CONTENT:
                self._skip_depth -= 1
            return
        # 向上找到匹配的开标签
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data:
            self.stack[-1].text_parts.append(data)


def parse_html(markup: str) -> Node:
    """把 HTML 文本解析成 DOM，根节点为 #document。"""
    builder = _DomBuilder()
    try:
        builder.feed(markup)
        builder.close()
    except Exception:
        pass
    return builder.root


# --------------------------------------------------------------------------
# 选择器
# --------------------------------------------------------------------------

_SIMPLE_RE = re.compile(
    r"^(?P<tag>[a-zA-Z][\w-]*|\*)?"
    r"(?P<id>#[\w-]+)?"
    r"(?P<classes>(?:\.[\w-]+)*)"
    r"(?P<attrs>(?:\[[^\]]+\])*)$"
)
_ATTR_RE = re.compile(r"\[([\w-]+)(?:([~^$*|]?=)[\"']?([^\"'\]]*)[\"']?)?\]")


class _SimpleSelector:
    __slots__ = ("tag", "id_", "classes", "attrs")

    def __init__(self, chunk: str) -> None:
        m = _SIMPLE_RE.match(chunk.strip())
        if not m:
            raise ValueError(f"不支持的选择器片段：{chunk}")
        self.tag = (m.group("tag") or "*").lower()
        self.id_ = (m.group("id") or "")[1:]
        self.classes = [c for c in (m.group("classes") or "").split(".") if c]
        self.attrs: list[tuple[str, str, str]] = []
        for name, op, value in _ATTR_RE.findall(m.group("attrs") or ""):
            self.attrs.append((name, op, value))

    def matches(self, node: Node) -> bool:
        if node.tag == "#document":
            return False
        if self.tag != "*" and node.tag != self.tag:
            return False
        if self.id_ and node.id != self.id_:
            return False
        if self.classes:
            own = node.classes_set
            if not all(c in own for c in self.classes):
                return False
        for name, op, value in self.attrs:
            actual = node.attrs.get(name)
            if actual is None:
                return False
            if not op:
                continue
            if op == "=" and actual != value:
                return False
            if op == "*=" and value not in actual:
                return False
            if op == "^=" and not actual.startswith(value):
                return False
            if op == "$=" and not actual.endswith(value):
                return False
            if op == "~=" and value not in actual.split():
                return False
            if op == "|=" and not (actual == value or actual.startswith(value + "-")):
                return False
        return True


def _split_groups(selector: str) -> list[str]:
    """按逗号拆分选择器组，忽略括号内的逗号。"""
    groups: list[str] = []
    depth = 0
    current = []
    for ch in selector:
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == "," and depth == 0:
            groups.append("".join(current))
            current = []
        else:
            current.append(ch)
    groups.append("".join(current))
    return [g for g in (g.strip() for g in groups) if g]


def _parse_chain(group: str) -> list[tuple[str, _SimpleSelector]]:
    """把 'div.a > p.b span' 拆成 [(组合符, 选择器)]。"""
    tokens = re.split(r"\s*([>+~])\s*|\s+", group.strip())
    chain: list[tuple[str, _SimpleSelector]] = []
    combinator = " "
    for tok in tokens:
        if tok is None or tok == "":
            continue
        if tok in {">", "+", "~"}:
            combinator = tok
            continue
        chain.append((combinator, _SimpleSelector(tok)))
        combinator = " "
    return chain


def _matches_chain(node: Node, chain: list[tuple[str, _SimpleSelector]]) -> bool:
    """自右向左回溯匹配整条链。"""
    if not chain:
        return False
    combinator, selector = chain[-1]
    if not selector.matches(node):
        return False
    rest = chain[:-1]
    if not rest:
        return True
    prev_combinator, _ = chain[-1]
    if prev_combinator == " ":
        parent = node.parent
        while parent is not None and parent.tag != "#document":
            if _matches_chain(parent, rest):
                return True
            parent = parent.parent
        return False
    if prev_combinator == ">":
        parent = node.parent
        return parent is not None and _matches_chain(parent, rest)
    if prev_combinator == "+":
        prev = _previous_sibling(node)
        return prev is not None and _matches_chain(prev, rest)
    if prev_combinator == "~":
        sib = _previous_sibling(node)
        while sib is not None:
            if _matches_chain(sib, rest):
                return True
            sib = _previous_sibling(sib)
        return False
    return False


def _previous_sibling(node: Node) -> Node | None:
    parent = node.parent
    if parent is None:
        return None
    try:
        idx = parent.children.index(node)
    except ValueError:
        return None
    return parent.children[idx - 1] if idx > 0 else None


def select(root: Node, selector: str, *, limit: int = 0) -> NodeList:
    """在 root 子树内按选择器查找节点。

    支持：标签、#id、.class、[attr]、[attr=value]、[attr*=value]，
    以及后代（空格）、子代（>）、相邻（+）、兄弟（~）组合，逗号分组。
    """
    results = NodeList()
    chains = [_parse_chain(g) for g in _split_groups(selector)]
    chains = [c for c in chains if c]
    if not chains:
        return results
    for node in root.iter():
        if node is root:
            continue
        for chain in chains:
            if _matches_chain(node, chain):
                results.append(node)
                break
        if limit and len(results) >= limit:
            break
    return results


# --------------------------------------------------------------------------
# 文本转换
# --------------------------------------------------------------------------

_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "blockquote", "pre", "hr",
}


def html_to_text(markup: str) -> str:
    """把 HTML 转成保留段落结构的纯文本。"""
    normalized = re.sub(
        r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?\s*>", "\n", markup, flags=re.I
    )
    normalized = re.sub(r"<[^>]+>", "", normalized)
    text = html_mod.unescape(normalized)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def extract_text(node: Node, *, block_separator: str = "\n") -> str:
    """从节点抽取文本，块级标签之间加换行。"""
    parts: list[str] = []

    def walk(n: Node) -> None:
        if n is not node and n.tag in _BLOCK_TAGS:
            parts.append(block_separator)
        parts.extend(n.text_parts)
        if n.tag in {"br"}:
            parts.append(block_separator)
        for child in n.children:
            walk(child)
        if n is not node and n.tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            parts.append(block_separator)

    walk(node)
    text = html_mod.unescape("".join(parts))
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)
