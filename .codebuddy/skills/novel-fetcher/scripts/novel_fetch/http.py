# -*- coding: utf-8 -*-
"""零依赖 HTTP 客户端。

只用标准库 urllib，负责：编码自动识别、gzip/deflate 解压、每主机限速、
可重试状态码退避、Cookie 会话、公网地址校验。

不依赖 requests / httpx / bs4。
"""
from __future__ import annotations

import gzip
import io
import ipaddress
import json
import random
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field

__all__ = ["HttpClient", "HttpError", "Response", "FetchPolicy"]

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 各站点限速与重试策略：host -> (最小间隔秒数, 最大重试次数)
_HOST_POLICIES: dict[str, tuple[float, int]] = {
    "fanqienovel.com": (0.6, 3),
    "reading.snssdk.com": (0.6, 3),
    "linovelib.com": (1.2, 5),
    "bilinovel.com": (1.2, 5),
}
DEFAULT_HOST_POLICY = (0.35, 3)

RETRYABLE_STATUS = {403, 408, 425, 429, 500, 502, 503, 504}

_RATE_LOCK = threading.Lock()
_HOST_LAST_REQUEST: dict[str, float] = {}


@dataclass
class FetchPolicy:
    """单次请求的策略覆盖项。"""

    timeout: float = 25.0
    retries: int | None = None
    min_interval: float | None = None
    headers: dict[str, str] = field(default_factory=dict)
    allow_private_host: bool = False


class HttpError(RuntimeError):
    """网络层错误，message 面向用户。"""

    def __init__(self, message: str, *, status: int | None = None, url: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.url = url


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str]
    raw: bytes
    text: str

    def json(self) -> object:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise HttpError("响应不是有效 JSON") from exc


def _decode_charset(raw: bytes, declared: str | None, sniff: bytes = b"") -> str:
    """按声明 charset -> meta 探测 -> 常见中文编码 -> utf-8 顺序解码。"""
    candidates: list[str] = []
    if declared:
        candidates.append(declared.strip().strip("\"'"))
    if sniff:
        m = re.search(rb'charset=["\']?([\w-]+)', sniff[:4096], re.I)
        if m:
            candidates.append(m.group(1).decode("ascii", "ignore"))
    candidates += ["utf-8", "gb18030", "big5", "utf-16"]
    # 去重且保序
    seen: set[str] = set()
    ordered = []
    for c in candidates:
        key = c.lower().replace("_", "-")
        if key and key not in seen:
            seen.add(key)
            ordered.append(c)
    for enc in ordered:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        # gb18030 能解 utf-8 但会出乱码，优先检查是否含替换字符
        if "\ufffd" in text and enc.lower() not in {"utf-8"}:
            continue
        return text
    return raw.decode("utf-8", "ignore")


def _compress_body(raw: bytes, encoding: str) -> bytes:
    enc = (encoding or "").lower()
    if "gzip" in enc:
        try:
            return gzip.decompress(raw)
        except OSError:
            pass
    if "deflate" in enc:
        for wbits in (-zlib.MAX_WBITS, zlib.MAX_WBITS):
            try:
                return zlib.decompress(raw, wbits)
            except zlib.error:
                continue
    if "br" in enc:
        raise HttpError("服务器返回 brotli 压缩，当前环境不支持")
    return raw


def _resolve_host(host: str) -> tuple[bool, str]:
    """解析主机并判断是否公网。

    返回 (是否放行, 拒绝原因)。
    """
    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "metadata", "metadata.google.internal"}:
        return False, "该地址属于本机或云元数据服务，出于安全考虑不予访问"
    try:
        infos = socket.getaddrinfo(lowered, None)
    except socket.gaierror:
        return False, f"域名无法解析：{host}（请检查链接是否正确或站点是否可访问）"
    if not infos:
        return False, f"域名无法解析：{host}"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False, f"目标地址不是公网地址（{host} → {addr}），不予访问"
    return True, ""


def _throttle(host: str, min_interval: float) -> None:
    """同一主机两次请求之间保持最小间隔。"""
    if min_interval <= 0:
        return
    with _RATE_LOCK:
        now = time.monotonic()
        last = _HOST_LAST_REQUEST.get(host, 0.0)
        wait = min_interval - (now - last)
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _HOST_LAST_REQUEST[host] = now


class HttpClient:
    """带限速与重试的零依赖 HTTP 客户端。

    用法：
        with HttpClient() as client:
            resp = client.get("https://example.com/book/1")
            print(resp.text)

    也可用 client.get_text / client.get_json 便捷方法。
    """

    def __init__(self, *, user_agent: str = DEFAULT_UA) -> None:
        self._ua = user_agent
        self._cookies: dict[str, str] = {}
        self._lock = threading.Lock()
        self._opener = urllib.request.build_opener()
        self._ctx = ssl.create_default_context()

    # -- 生命周期 ---------------------------------------------------------
    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._opener.close()
        except Exception:
            pass

    def set_cookies(self, cookies: dict[str, str]) -> None:
        with self._lock:
            self._cookies.update(cookies)

    def cookies(self) -> dict[str, str]:
        with self._lock:
            return dict(self._cookies)

    # -- 请求 -------------------------------------------------------------
    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | str | None = None,
        policy: FetchPolicy | None = None,
    ) -> Response:
        pol = policy or FetchPolicy()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise HttpError(f"不支持的协议：{parsed.scheme or '空'}", url=url)
        if not parsed.hostname:
            raise HttpError("URL 缺少主机名", url=url)

        base_interval, base_retries = _HOST_POLICIES.get(
            parsed.hostname.lower(), DEFAULT_HOST_POLICY
        )
        interval = pol.min_interval if pol.min_interval is not None else base_interval
        retries = pol.retries if pol.retries is not None else base_retries

        if not pol.allow_private_host:
            allowed, reason = _resolve_host(parsed.hostname)
            if not allowed:
                raise HttpError(reason, url=url)

        body = data.encode("utf-8") if isinstance(data, str) else data
        headers = {
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            **pol.headers,
        }
        with self._lock:
            if self._cookies:
                headers["Cookie"] = "; ".join(
                    f"{k}={v}" for k, v in self._cookies.items()
                )

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            _throttle(parsed.hostname.lower(), interval)
            try:
                req = urllib.request.Request(url, headers=headers, data=body, method=method)
                with self._opener.open(req, timeout=pol.timeout) as resp:
                    raw = resp.read()
                    raw = _compress_body(raw, resp.headers.get("Content-Encoding", ""))
                    ctype = resp.headers.get("Content-Type", "")
                    m = re.search(r"charset=([\w-]+)", ctype, re.I)
                    declared = m.group(1) if m else None
                    text = _decode_charset(raw, declared, raw)
                    with self._lock:
                        self._absorb_set_cookie(resp.headers.get_all("Set-Cookie") or [])
                    return Response(
                        url=resp.geturl(),
                        status=resp.status,
                        headers=dict(resp.headers),
                        raw=raw,
                        text=text,
                    )
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in RETRYABLE_STATUS and attempt < retries:
                    self._backoff(attempt, interval)
                    continue
                raise HttpError(
                    self._describe_http_error(exc.code), status=exc.code, url=url
                ) from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < retries:
                    self._backoff(attempt, interval)
                    continue
                raise HttpError(f"网络请求失败：{exc.reason}", url=url) from exc
            except (TimeoutError, socket.timeout) as exc:
                last_error = exc
                if attempt < retries:
                    self._backoff(attempt, interval)
                    continue
                raise HttpError("网络请求超时", url=url) from exc

        raise HttpError(f"请求在多次重试后仍失败：{last_error}", url=url)

    @staticmethod
    def _describe_http_error(code: int) -> str:
        table = {
            401: "站点要求登录（401）",
            403: "站点拒绝访问（403），可能触发了反爬验证",
            404: "页面不存在（404）",
            429: "请求过于频繁（429），已被站点限流",
        }
        return table.get(code, f"站点返回错误状态码 {code}")

    @staticmethod
    def _backoff(attempt: int, interval: float) -> None:
        time.sleep(min(interval * (2 ** attempt) + random.uniform(0, 0.4), 8.0))

    def _absorb_set_cookie(self, values: list[str]) -> None:
        for item in values:
            pair = item.split(";", 1)[0].strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                self._cookies[k.strip()] = v.strip()

    # -- 便捷方法 ---------------------------------------------------------
    def get(self, url: str, *, policy: FetchPolicy | None = None) -> Response:
        return self.request(url, policy=policy)

    def post(
        self,
        url: str,
        *,
        data: bytes | str | None = None,
        policy: FetchPolicy | None = None,
    ) -> Response:
        return self.request(url, method="POST", data=data, policy=policy)

    def get_text(self, url: str, *, policy: FetchPolicy | None = None) -> str:
        return self.request(url, policy=policy).text

    def get_json(self, url: str, *, policy: FetchPolicy | None = None) -> object:
        return self.request(url, policy=policy).json()
