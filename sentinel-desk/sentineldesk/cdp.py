from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import socket
import struct
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class CDPError(RuntimeError):
    pass


@dataclass(frozen=True)
class CDPPage:
    id: str
    title: str
    url: str
    websocket_url: str


@dataclass(frozen=True)
class CDPCapture:
    html: str
    final_url: str
    screenshot: bytes | None = None


@dataclass(frozen=True)
class CDPSelector:
    url: str | None = None
    title: str | None = None
    page_id: str | None = None

    @property
    def is_empty(self) -> bool:
        return not any([self.url, self.title, self.page_id])

    def describe(self) -> str:
        parts = []
        if self.page_id:
            parts.append(f"id={self.page_id!r}")
        if self.url:
            parts.append(f"url={self.url!r}")
        if self.title:
            parts.append(f"title={self.title!r}")
        return ", ".join(parts) or "no selector"


def devtools_endpoint(address: str, port: int, path: str) -> str:
    return f"http://{address}:{port}{path}"


def parse_cdp_url(url: str) -> tuple[str, int, str | None]:
    address, port, selector = parse_cdp_selector(url)
    return address, port, selector.url


def parse_cdp_selector(url: str) -> tuple[str, int, CDPSelector]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "cdp":
        raise ValueError("CDP capture URL must use cdp://")
    query = urllib.parse.parse_qs(parsed.query)
    selector = CDPSelector(
        url=query.get("url", [None])[0],
        title=query.get("title", [None])[0],
        page_id=(query.get("id") or query.get("target_id") or [None])[0],
    )
    return parsed.hostname or "127.0.0.1", parsed.port or 9222, selector


def list_pages(address: str = "127.0.0.1", port: int = 9222, *, timeout: float = 5) -> list[CDPPage]:
    with urllib.request.urlopen(devtools_endpoint(address, port, "/json/list"), timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    pages = []
    for item in payload:
        websocket_url = item.get("webSocketDebuggerUrl")
        if item.get("type") == "page" and websocket_url:
            pages.append(
                CDPPage(
                    id=str(item.get("id", "")),
                    title=str(item.get("title", "")),
                    url=str(item.get("url", "")),
                    websocket_url=str(websocket_url),
                )
            )
    return pages


def page_summary(pages: list[CDPPage], limit: int = 8) -> str:
    if not pages:
        return "no pages"
    rows = []
    for page in pages[:limit]:
        title = page.title or "(untitled)"
        current_url = page.url or "(blank)"
        rows.append(f"id={page.id!r} title={title!r} url={current_url!r}")
    if len(pages) > limit:
        rows.append(f"... {len(pages) - limit} more")
    return "; ".join(rows)


def _matches_exact_or_contains(value: str, needle: str) -> tuple[bool, bool]:
    if value == needle:
        return True, True
    if needle in value:
        return False, True
    return False, False


def _filter_by_text(candidates: list[CDPPage], *, label: str, needle: str, getter: str) -> list[CDPPage]:
    exact_matches = []
    partial_matches = []
    for page in candidates:
        value = getattr(page, getter)
        exact, matched = _matches_exact_or_contains(value, needle)
        if exact:
            exact_matches.append(page)
        elif matched:
            partial_matches.append(page)
    matches = exact_matches or partial_matches
    if not matches:
        raise CDPError(f"No Chrome page matched {label}={needle!r}. Open pages: {page_summary(candidates)}")
    return matches


def pick_page(
    pages: list[CDPPage],
    match_url: str | None = None,
    *,
    title: str | None = None,
    page_id: str | None = None,
) -> CDPPage:
    if not pages:
        raise CDPError("No debuggable Chrome page found. Launch Chrome with sentineldesk chrome launch first.")
    selector = CDPSelector(url=match_url, title=title, page_id=page_id)
    if selector.is_empty:
        if len(pages) == 1:
            return pages[0]
        raise CDPError(
            "Multiple Chrome pages are open; pass a deterministic selector such as "
            "`?url=...`, `?title=...`, or `?id=...`. Open pages: " + page_summary(pages)
        )

    candidates = pages
    if page_id:
        candidates = [page for page in candidates if page.id == page_id]
        if not candidates:
            raise CDPError(f"No Chrome page matched id={page_id!r}. Open pages: {page_summary(pages)}")
    if match_url:
        candidates = _filter_by_text(candidates, label="url", needle=match_url, getter="url")
    if title:
        candidates = _filter_by_text(candidates, label="title", needle=title, getter="title")

    if len(candidates) == 1:
        return candidates[0]
    raise CDPError(
        "Ambiguous Chrome page selector "
        + selector.describe()
        + "; add a stricter selector such as `?id=<target-id>`. Candidates: "
        + page_summary(candidates)
    )


def _read_exact(sock: socket.socket, length: int) -> bytes:
    chunks = []
    remaining = length
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise CDPError("WebSocket closed while reading.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _open_websocket(ws_url: str, *, timeout: float = 5) -> socket.socket:
    parsed = urllib.parse.urlparse(ws_url)
    if parsed.scheme != "ws":
        raise CDPError(f"Only ws:// CDP endpoints are supported, got {parsed.scheme!r}.")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    sock = socket.create_connection((host, port), timeout=timeout)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(4096)
        if len(response) > 65536:
            raise CDPError("WebSocket handshake response was too large.")
    status = response.split(b"\r\n", 1)[0]
    accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest())
    if b" 101 " not in status or accept not in response:
        raise CDPError(f"WebSocket handshake failed: {status.decode('ascii', errors='replace')}")
    return sock


def _send_text(sock: socket.socket, payload: dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    header = bytearray([0x81])
    if len(data) < 126:
        header.append(0x80 | len(data))
    elif len(data) <= 0xFFFF:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", len(data)))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", len(data)))
    mask = os.urandom(4)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
    sock.sendall(bytes(header) + mask + masked)


def _recv_text(sock: socket.socket) -> dict[str, Any]:
    first, second = _read_exact(sock, 2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(sock, 8))[0]
    mask = _read_exact(sock, 4) if masked else b""
    payload = _read_exact(sock, length)
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    if opcode == 0x8:
        raise CDPError("WebSocket closed by Chrome.")
    if opcode not in {0x1, 0x2}:
        return {}
    return json.loads(payload.decode("utf-8", errors="replace"))


def cdp_command(ws_url: str, method: str, params: dict[str, Any] | None = None, *, timeout: float = 5) -> dict[str, Any]:
    sock = _open_websocket(ws_url, timeout=timeout)
    try:
        command_id = 1
        _send_text(sock, {"id": command_id, "method": method, "params": params or {}})
        while True:
            message = _recv_text(sock)
            if message.get("id") == command_id:
                if "error" in message:
                    raise CDPError(str(message["error"]))
                return message.get("result", {})
    finally:
        sock.close()


def evaluate(ws_url: str, expression: str, *, timeout: float = 5) -> Any:
    result = cdp_command(
        ws_url,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": False},
        timeout=timeout,
    )
    remote = result.get("result", {})
    return remote.get("value")


def screenshot_bytes_from_result(result: dict[str, Any]) -> bytes | None:
    data = result.get("data")
    if not isinstance(data, str) or not data.strip():
        return None
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise CDPError("Chrome screenshot payload was not valid base64.") from error


def capture_screenshot(ws_url: str, *, timeout: float = 5) -> bytes | None:
    result = cdp_command(
        ws_url,
        "Page.captureScreenshot",
        {"format": "png", "captureBeyondViewport": False, "fromSurface": True},
        timeout=timeout,
    )
    return screenshot_bytes_from_result(result)


def capture_page(
    address: str = "127.0.0.1",
    port: int = 9222,
    *,
    match_url: str | None = None,
    title: str | None = None,
    page_id: str | None = None,
    timeout: float = 5,
) -> CDPCapture:
    page = pick_page(list_pages(address, port, timeout=timeout), match_url, title=title, page_id=page_id)
    html = evaluate(page.websocket_url, "document.documentElement.outerHTML", timeout=timeout)
    final_url = evaluate(page.websocket_url, "location.href", timeout=timeout) or page.url
    if not isinstance(html, str) or not html.strip():
        raise CDPError("Chrome page did not return HTML.")
    try:
        screenshot = capture_screenshot(page.websocket_url, timeout=timeout)
    except CDPError:
        screenshot = None
    return CDPCapture(html=html, final_url=str(final_url), screenshot=screenshot)


def capture_from_url(url: str, *, timeout: float = 5) -> CDPCapture:
    address, port, selector = parse_cdp_selector(url)
    return capture_page(address, port, match_url=selector.url, title=selector.title, page_id=selector.page_id, timeout=timeout)
