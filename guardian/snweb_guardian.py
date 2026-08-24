#!/usr/bin/env python3
"""Stable local reverse-proxy/maintenance guardian for SNTalkBot Web Manager.

This process owns the public/local Web Manager listening socket while the FastAPI
application runs on a separate loopback backend port.  Web Manager upgrades may
restart the FastAPI service without making the outer reverse proxy see a raw 502.
"""
from __future__ import annotations

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import sys
from typing import Iterable

GUARDIAN_VERSION = "1.0.0"
PUBLIC_BIND = os.getenv("SNWEB_BIND", "127.0.0.1")
PUBLIC_PORT = int(os.getenv("SNWEB_PORT", "28765"))
BACKEND_BIND = os.getenv("SNWEB_APP_BIND", "127.0.0.1")
BACKEND_PORT = int(os.getenv("SNWEB_APP_PORT", "28766"))
MAX_BODY = int(os.getenv("SNWEB_GUARDIAN_MAX_BODY", str(16 * 1024 * 1024)))

HOP_BY_HOP = {
    "connection", "proxy-connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
}

MAINTENANCE_HTML = """<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="2"><title>SNTalkBot Web Manager กำลังเริ่มบริการ</title></head>
<body><main id="main-content"><h1>SNTalkBot Web Manager</h1>
<p role="status" aria-live="polite">กำลังเริ่มหรืออัปเดตบริการเว็บ กรุณารอสักครู่ หน้านี้จะลองเชื่อมต่อใหม่อัตโนมัติ</p>
<p>บอตและข้อมูลของคุณไม่ได้ถูกลบ การอัปเดตมี Guardian คอยรับคำขอแทนระหว่าง Web Manager เริ่ม process ใหม่</p>
</main></body></html>""".encode("utf-8")


def _filtered_headers(items: Iterable[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in items:
        if key.lower() in HOP_BY_HOP:
            continue
        out[key] = value
    return out


class GuardianHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SNTalkBotWebGuardian/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[guardian] " + (fmt % args) + "\n")

    def _guardian_health(self) -> None:
        body = json.dumps({
            "ok": True,
            "guardian_version": GUARDIAN_VERSION,
            "backend": f"{BACKEND_BIND}:{BACKEND_PORT}",
        }, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _maintenance(self, *, api_like: bool = False) -> None:
        accept = (self.headers.get("Accept") or "").lower()
        if api_like or "application/json" in accept or self.path.startswith("/healthz"):
            body = b'{"ok":false,"maintenance":true,"message":"Web Manager is restarting"}'
            content_type = "application/json; charset=utf-8"
        elif "text/event-stream" in accept:
            body = b""
            content_type = "text/plain; charset=utf-8"
        else:
            body = MAINTENANCE_HTML
            content_type = "text/html; charset=utf-8"
        self.send_response(503)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Retry-After", "2")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _read_body(self) -> bytes | None:
        transfer = (self.headers.get("Transfer-Encoding") or "").strip().lower()
        if transfer and transfer != "identity":
            self.send_error(501, "Chunked request bodies are not supported by the local guardian")
            return None
        raw_len = self.headers.get("Content-Length")
        if not raw_len:
            return b""
        try:
            length = int(raw_len)
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return None
        if length < 0 or length > MAX_BODY:
            self.send_error(413, "Request body too large")
            return None
        return self.rfile.read(length)

    def _proxy(self) -> None:
        if self.path == "/guardian-healthz":
            self._guardian_health()
            return
        body = self._read_body()
        if body is None:
            return
        headers = _filtered_headers(self.headers.items())
        headers["Host"] = self.headers.get("Host", f"{BACKEND_BIND}:{BACKEND_PORT}")
        if "X-Forwarded-For" not in headers:
            headers["X-Forwarded-For"] = self.client_address[0]
        headers["X-SNTalkBot-Web-Guardian"] = GUARDIAN_VERSION
        try:
            conn = http.client.HTTPConnection(BACKEND_BIND, BACKEND_PORT, timeout=3600)
            conn.request(self.command, self.path, body=body if body else None, headers=headers)
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException, socket.timeout):
            self._maintenance(api_like=self.command not in ("GET", "HEAD"))
            return

        response_headers = [(k, v) for k, v in resp.getheaders() if k.lower() not in HOP_BY_HOP]
        content_length = next((v for k, v in response_headers if k.lower() == "content-length"), None)
        self.send_response(resp.status, resp.reason)
        for key, value in response_headers:
            self.send_header(key, value)
        if content_length is None:
            # http.client de-chunks upstream responses. Close the client side at
            # EOF so streaming/SSE works without forwarding invalid chunk framing.
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command == "HEAD":
            conn.close()
            return
        try:
            # HTTPResponse.read(amt) may wait to accumulate ``amt`` bytes across
            # multiple HTTP chunks. That is wrong for SSE/job progress where tiny
            # events must reach the browser immediately. read1() returns data from
            # the next available buffered/chunk read without waiting for 64 KiB.
            read_chunk = getattr(resp, "read1", resp.read)
            while True:
                chunk = read_chunk(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            conn.close()

    do_GET = _proxy
    do_HEAD = _proxy
    do_POST = _proxy
    do_PUT = _proxy
    do_PATCH = _proxy
    do_DELETE = _proxy
    do_OPTIONS = _proxy


def main() -> int:
    if PUBLIC_BIND == BACKEND_BIND and PUBLIC_PORT == BACKEND_PORT:
        raise SystemExit("Guardian public socket and Web Manager backend socket must be different")
    server = ThreadingHTTPServer((PUBLIC_BIND, PUBLIC_PORT), GuardianHandler)
    server.daemon_threads = True
    print(
        f"SNTalkBot Web Guardian {GUARDIAN_VERSION}: "
        f"{PUBLIC_BIND}:{PUBLIC_PORT} -> {BACKEND_BIND}:{BACKEND_PORT}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
