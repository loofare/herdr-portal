#!/usr/bin/env python3
"""Manage the portal server as a terminal-independent local daemon."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "server.py"
RUNTIME = Path(os.environ.get("HERDR_PORTAL_RUNTIME", Path.home() / ".local/state/herdr-portal"))
PID_FILE = RUNTIME / "server.pid"
LOG_FILE = RUNTIME / "server.log"
HOST = os.environ.get("HERDR_PORTAL_HOST", "127.0.0.1")
PORT = int(os.environ.get("HERDR_PORTAL_PORT", "8787"))
URL = f"http://{HOST}:{PORT}/api/snapshot"


def read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def healthy(timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and isinstance(payload, dict)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False


def start() -> int:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    pid = read_pid()
    if process_alive(pid) and healthy():
        print(f"running {pid} http://{HOST}:{PORT}/")
        return 0
    if pid and not process_alive(pid):
        PID_FILE.unlink(missing_ok=True)
    if healthy():
        print(f"running external http://{HOST}:{PORT}/")
        return 0

    env = os.environ.copy()
    env["HERDR_PORTAL_HOST"] = HOST
    env["HERDR_PORTAL_PORT"] = str(PORT)
    log = LOG_FILE.open("ab", buffering=0)
    try:
        process = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT.parent),
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log.close()
    PID_FILE.write_text(f"{process.pid}\n")

    for _ in range(30):
        if healthy():
            print(f"started {process.pid} http://{HOST}:{PORT}/")
            return 0
        if process.poll() is not None:
            break
        time.sleep(0.1)
    tail = ""
    try:
        tail = "\n".join(LOG_FILE.read_text(errors="replace").splitlines()[-12:])
    except OSError:
        pass
    print(f"failed to start portal server\n{tail}", file=sys.stderr)
    return 1


def stop() -> int:
    pid = read_pid()
    if not process_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        print("stopped")
        return 0
    assert pid is not None
    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        if not process_alive(pid):
            break
        time.sleep(0.1)
    if process_alive(pid):
        os.kill(pid, signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)
    print("stopped")
    return 0


def status() -> int:
    pid = read_pid()
    ok = process_alive(pid) and healthy()
    print(json.dumps({"running": ok, "pid": pid, "url": f"http://{HOST}:{PORT}/"}))
    return 0 if ok else 1


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    if action == "start":
        return start()
    if action == "stop":
        return stop()
    if action == "restart":
        stop()
        return start()
    if action == "status":
        return status()
    print("usage: daemon.py start|stop|restart|status", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
