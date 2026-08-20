#!/usr/bin/env python3
"""Tiny local HTTP server for the Herdr portal dashboard."""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collect import (  # noqa: E402
    DEFAULT_CLEANUP_IDLE,
    cleanup_apply,
    cleanup_scan,
    collect_or_error,
    focus_target,
    send_text,
)

HOST = os.environ.get("HERDR_PORTAL_HOST", "127.0.0.1")
PORT = int(os.environ.get("HERDR_PORTAL_PORT", "8787"))
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".ico": "image/x-icon",
}


class PortalServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = "HerdrPortal/1.0"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_file(WEB / "index.html")
            return
        if parsed.path == "/api/snapshot":
            self._json(200, collect_or_error())
            return
        if parsed.path == "/api/cleanup":
            try:
                idle = DEFAULT_CLEANUP_IDLE
                values = parse_qs(parsed.query).get("idle")
                if values:
                    try:
                        idle = max(0, int(values[0]))
                    except (TypeError, ValueError):
                        idle = DEFAULT_CLEANUP_IDLE
                self._json(200, cleanup_scan(idle))
            except Exception as exc:  # noqa: BLE001
                self._json(400, {"ok": False, "error": str(exc)})
            return
        if parsed.path.startswith("/"):
            rel = parsed.path.lstrip("/")
            target = (WEB / rel).resolve()
            if WEB.resolve() in target.parents or target == WEB.resolve():
                if target.is_file():
                    self._send_file(target)
                    return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/focus", "/api/send", "/api/cleanup"}:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = parse_qs(raw.decode("utf-8"))
        pane_id = payload.get("pane_id") if isinstance(payload, dict) else None
        if isinstance(pane_id, list):
            pane_id = pane_id[0]
        try:
            if parsed.path == "/api/cleanup":
                pane_ids = payload.get("pane_ids") if isinstance(payload, dict) else None
                if isinstance(pane_ids, list) and pane_ids and isinstance(pane_ids[0], list):
                    pane_ids = pane_ids[0]
                idle_seconds = payload.get("idle_seconds") if isinstance(payload, dict) else None
                try:
                    idle_seconds = max(0, int(idle_seconds if idle_seconds is not None else DEFAULT_CLEANUP_IDLE))
                except (TypeError, ValueError):
                    idle_seconds = DEFAULT_CLEANUP_IDLE
                result = cleanup_apply(pane_ids or [], idle_seconds)
                self._json(200, {"ok": True, "result": result})
                return
            if parsed.path == "/api/send":
                text = payload.get("text") if isinstance(payload, dict) else None
                if isinstance(text, list):
                    text = text[0]
                result = send_text(str(pane_id or ""), str(text or ""))
            else:
                result = focus_target(str(pane_id or ""))
            self._json(200, {"ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001
            self._json(400, {"ok": False, "error": str(exc)})

    def _send_file(self, path: Path) -> None:
        data = path.read_bytes()
        self._send(200, data, MIME.get(path.suffix, "application/octet-stream"))


def main() -> None:
    httpd = PortalServer((HOST, PORT), Handler)
    print(f"herdr portal http://{HOST}:{PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
