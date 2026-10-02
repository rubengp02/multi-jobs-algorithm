#!/usr/bin/env python3
"""Inspect non-sensitive LinkedIn DOM counters through local Chromium CDP.

Used only while ``LINKEDIN_CHROMIUM_DEBUG_PORT`` is explicitly enabled on the
Raspberry Pi. It deliberately returns structure and counters, never cookies,
credentials, or page text.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import urllib.parse
import urllib.request


def _read_exact(connection: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    while length:
        chunk = connection.recv(length)
        if not chunk:
            raise ConnectionError("Chromium closed the DevTools connection")
        chunks.append(chunk)
        length -= len(chunk)
    return b"".join(chunks)


def _connect_websocket(url: str) -> socket.socket:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1":
        raise ValueError("The DevTools endpoint must be local ws://127.0.0.1")
    connection = socket.create_connection(
        (parsed.hostname, parsed.port or 80), timeout=10
    )
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {parsed.path} HTTP/1.1\r\n"
        f"Host: {parsed.netloc}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    connection.sendall(request.encode("ascii"))
    response = connection.recv(4096).decode("iso-8859-1")
    if " 101 " not in response:
        raise ConnectionError(
            f"DevTools WebSocket handshake failed: {response.splitlines()[0]}"
        )
    expected = base64.b64encode(
        hashlib.sha1(
            f"{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11".encode("ascii")
        ).digest()
    ).decode("ascii")
    if f"Sec-WebSocket-Accept: {expected}" not in response:
        raise ConnectionError("DevTools WebSocket rejected its handshake")
    return connection


def _send_json(connection: socket.socket, payload: dict[str, object]) -> None:
    data = json.dumps(payload).encode("utf-8")
    length = len(data)
    header = bytearray([0x81])
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.extend([0x80 | 126, *struct.pack("!H", length)])
    else:
        header.extend([0x80 | 127, *struct.pack("!Q", length)])
    mask = os.urandom(4)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
    connection.sendall(bytes(header) + mask + masked)


def _receive_json(connection: socket.socket) -> dict[str, object]:
    first, second = _read_exact(connection, 2)
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(connection, 8))[0]
    if second & 0x80:
        mask = _read_exact(connection, 4)
        raw = bytes(
            value ^ mask[index % 4]
            for index, value in enumerate(_read_exact(connection, length))
        )
    else:
        raw = _read_exact(connection, length)
    if opcode == 8:
        raise ConnectionError("DevTools closed the WebSocket")
    if opcode == 9:
        connection.sendall(b"\x8a" + bytes([len(raw)]) + raw)
        return _receive_json(connection)
    return json.loads(raw.decode("utf-8"))


def main() -> None:
    with urllib.request.urlopen(
        "http://127.0.0.1:9222/json/list", timeout=10
    ) as response:
        targets = json.load(response)
    target = next(
        (
            item
            for item in targets
            if item.get("type") == "page" and "/jobs/search/" in item.get("url", "")
        ),
        None,
    )
    if target is None:
        raise SystemExit("No active LinkedIn job-search tab found")
    expression = """(() => {
      const count = (selector) => document.querySelectorAll(selector).length;
      const classes = [...document.querySelectorAll('[class]')]
        .map((element) => String(element.className || ''))
        .filter((value) => /job|search|scaffold/i.test(value))
        .slice(0, 40);
      return {
        title: document.title,
        url: location.href,
        readyState: document.readyState,
        occludableCards: count('[data-occludable-job-id]'),
        jobCardContainers: count('.job-card-container'),
        resultListItems: count('.jobs-search-results__list-item'),
        jobLinks: count('a[href*="/jobs/view/"]'),
        resultContainers: count('.scaffold-layout__list-container, .jobs-search-results-list, .jobs-search-results-list__list'),
        bodyTextLength: (document.body?.innerText || '').length,
        relevantClasses: classes
      };
    })()"""
    connection = _connect_websocket(str(target["webSocketDebuggerUrl"]))
    try:
        _send_json(
            connection,
            {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": expression, "returnByValue": True},
            },
        )
        while True:
            result = _receive_json(connection)
            if result.get("id") == 1:
                print(json.dumps(result, ensure_ascii=False, indent=2))
                break
    finally:
        connection.close()


if __name__ == "__main__":
    main()
