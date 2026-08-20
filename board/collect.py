#!/usr/bin/env python3
"""Collect a live, UI-ready snapshot of every Herdr pane and agent."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERDR_BIN = os.environ.get("HERDR_BIN_PATH", "herdr")

STATUS_ORDER = ("blocked", "working", "idle", "done", "unknown")

STATUS_META = {
    "blocked": {"label": "待确认", "short": "BLOCKED", "tone": "blocked"},
    "working": {"label": "执行中", "short": "WORKING", "tone": "working"},
    "idle": {"label": "空闲", "short": "IDLE", "tone": "idle"},
    "done": {"label": "已完成", "short": "DONE", "tone": "done"},
    "unknown": {"label": "未知", "short": "UNKNOWN", "tone": "unknown"},
}

AGENT_META = {
    "pi": {"label": "PI", "family": "pi"},
    "omp": {"label": "OMP", "family": "omp"},
    "opencode": {"label": "OpenCode", "family": "opencode"},
    "claude": {"label": "Claude", "family": "claude"},
    "codex": {"label": "Codex", "family": "codex"},
    "gemini": {"label": "Gemini", "family": "gemini"},
    "cursor": {"label": "Cursor", "family": "cursor"},
    "grok": {"label": "Grok", "family": "grok"},
    "kimi": {"label": "Kimi", "family": "kimi"},
    "copilot": {"label": "Copilot", "family": "copilot"},
    "droid": {"label": "Droid", "family": "droid"},
    "amp": {"label": "Amp", "family": "amp"},
    "devin": {"label": "Devin", "family": "devin"},
    "cline": {"label": "Cline", "family": "cline"},
    "kiro": {"label": "Kiro", "family": "kiro"},
    "hermes": {"label": "Hermes", "family": "hermes"},
    "kilo": {"label": "Kilo", "family": "kilo"},
    "qodercli": {"label": "Qoder", "family": "qoder"},
    "qoder": {"label": "Qoder", "family": "qoder"},
    "maki": {"label": "Maki", "family": "maki"},
    "agy": {"label": "Agy", "family": "agy"},
    "mastracode": {"label": "Mastra", "family": "mastra"},
}

SPINNER_RE = re.compile(r"[\u2800-\u28FF⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏◐◓◑◒●○•]+")
PREFIX_RE = re.compile(r"^(?:[π•·>›\-—]\s*)+")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9:_-]+$")

_session_cache: dict[str, tuple[float, dict[str, Any]]] = {}

# ---------- 闲置回收（Reclaim） ----------

# 只有前台进程全是这些「静止 shell」的窗口 pane 才可能被回收。
SHELL_NAMES = frozenset(
    {"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "nu", "xonsh", "elvish", "login"}
)
# 看板自身所在的 pane 永远不回收（否则会把自己关掉）。
PORTAL_MARKERS = ("board/tui.py", "board/server.py", "board/daemon.py")
# 阈值档位：0 = 不限，其余为「静默秒数」。TUI / 网页共用同一组档位。
CLEANUP_THRESHOLDS = (0, 300, 1800, 7200)
CLEANUP_THRESHOLD_LABELS = {0: "不限", 300: "5m", 1800: "30m", 7200: "2h"}
DEFAULT_CLEANUP_IDLE = 1800

_activity: dict[str, dict[str, Any]] = {}
_activity_loaded = False
_activity_saved_at = 0.0


def run_herdr(*args: str, timeout: float = 4.0, allow_empty: bool = False) -> dict[str, Any]:
    """跑一条 herdr CLI 命令并解析 JSON。

    `allow_empty` 给那些成功时静默（例如 `pane run`）的子命令用：
    退出码为 0 且没有输出时返回空字典，而不是当成失败。
    """
    completed = subprocess.run(
        [HERDR_BIN, *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    raw = completed.stdout.strip() or completed.stderr.strip()
    if not raw:
        if allow_empty and completed.returncode == 0:
            return {}
        raise RuntimeError(f"herdr {' '.join(args)} returned no output (exit {completed.returncode})")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"herdr {' '.join(args)} returned non-JSON") from exc
    if completed.returncode != 0 and "error" in payload:
        raise RuntimeError(payload["error"].get("message", raw[:200]))
    return payload


def clean_title(value: str | None) -> str:
    if not value:
        return ""
    text = SPINNER_RE.sub("", value)
    text = PREFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" -·|:：")
    return text


def project_name(cwd: str | None) -> str:
    if not cwd:
        return ""
    return Path(cwd.rstrip("/")).name


def relative_home(path: str | None) -> str:
    if not path:
        return ""
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path


def parse_iso(stamp: str | None) -> float | None:
    if not stamp or not isinstance(stamp, str):
        return None
    text = stamp.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def human_age(ts: float | None, now: float | None = None) -> str:
    if not ts:
        return ""
    now = now or time.time()
    delta = max(0, int(now - ts))
    if delta < 10:
        return "刚刚"
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


def _tail_bytes(path: Path, size: int = 128_000) -> str:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        handle.seek(max(0, end - size))
        return handle.read().decode("utf-8", errors="replace")


def _head_lines(path: Path, limit: int = 8) -> list[str]:
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for _ in range(limit):
            line = handle.readline()
            if not line:
                break
            lines.append(line)
    return lines


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return " ".join(
        str(part["text"])
        for part in content
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
    ).strip()


def _headline(text: str | None, limit: int = 92) -> str:
    if not text:
        return ""
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines:
        return ""
    line = lines[0]
    line = re.sub(r"^(?:#{1,6}|[-*+]>?|\d+[.)])\s*", "", line)
    line = line.replace("**", "").replace("__", "").replace("`", "")
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) > limit:
        sentence = re.split(r"(?<=[。！？.!?])\s*", line, maxsplit=1)[0]
        line = sentence if 8 <= len(sentence) <= limit else line[: limit - 1].rstrip() + "…"
    return line


TOOL_PHASES = {
    "bash": "执行命令",
    "eval": "运行代码",
    "read": "读取文件",
    "write": "写入文件",
    "edit": "修改代码",
    "grep": "检索代码",
    "find": "查找文件",
    "ls": "浏览目录",
    "web_search": "联网检索",
    "fetch_content": "读取网页",
    "source_check": "核验信息",
    "subagent": "调度 Agent",
    "hub": "调度任务",
    "ask": "等待确认",
}


def _humanize_activity_title(title: str) -> str:
    patterns = (
        (r"^Waiting for (?:the )?(.+?) to finish$", r"等待 \1 完成"),
        (r"^Continuing to wait for (?:the )?(.+)$", r"继续等待 \1"),
        (r"^Wait for (?:the )?(.+)$", r"等待 \1"),
        (r"^Read (.+)$", r"读取 \1"),
        (r"^Test (.+)$", r"测试 \1"),
    )
    for pattern, replacement in patterns:
        if re.match(pattern, title, flags=re.IGNORECASE):
            return re.sub(pattern, replacement, title, flags=re.IGNORECASE)
    return title


def _tool_activity(tool: dict[str, Any], fallback: str = "") -> dict[str, Any]:
    name = str(tool.get("name") or tool.get("toolName") or "tool")
    args = tool.get("arguments") or tool.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    intent = (
        tool.get("intent")
        or args.get("i")
        or args.get("title")
        or args.get("intent")
        or args.get("description")
        or args.get("reason")
    )
    op = str(args.get("op") or "").lower()
    phase = TOOL_PHASES.get(name, "调用工具")
    intent_text = str(intent or "")
    if name == "hub" and (op == "wait" or re.match(r"^(?:Waiting|Continuing to wait|Wait)\b", intent_text, re.IGNORECASE)):
        phase = "等待子任务"
    elif name == "hub":
        phase = "调度子任务"
    elif name == "subagent":
        phase = "调度 Agent"

    title = _headline(str(intent) if intent else "")
    if not title and name in {"read", "write", "edit"} and args.get("path"):
        action = {"read": "读取", "write": "写入", "edit": "更新"}[name]
        title = f"{action} {Path(str(args['path'])).name}"
    if not title and fallback:
        title = _headline(fallback)
    if not title and name == "bash" and args.get("command"):
        command = re.sub(r"\s+", " ", str(args["command"])).strip()
        title = _headline(command, 76)
    if not title:
        title = f"正在使用 {name}"
    title = _humanize_activity_title(title)
    return {"tool": name, "phase": phase, "title": title}


def read_session_extra(session_path: str | None) -> dict[str, Any]:
    if not session_path:
        return {}
    path = Path(session_path)
    try:
        stat = path.stat()
    except OSError:
        return {}

    cached = _session_cache.get(session_path)
    if cached and cached[0] == stat.st_mtime:
        return cached[1]

    extra: dict[str, Any] = {
        "session_title": "",
        "preview": "",
        "headline": "",
        "last_output": "",
        "last_output_at": None,
        "tool": "",
        "tool_phase": "",
        "tool_title": "",
        "tool_pending": False,
        "last_event_kind": "",
        "last_active": stat.st_mtime,
        "session_started": None,
    }
    try:
        fallback_title = ""
        for line in _head_lines(path):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "session":
                fallback_title = event.get("title") or fallback_title
                started = event.get("timestamp")
                if isinstance(started, str):
                    extra["session_started"] = started
            elif kind == "title" and event.get("title"):
                extra["session_title"] = event["title"]
        extra["session_title"] = extra["session_title"] or fallback_title
        tail = _tail_bytes(path)
        last_assistant_text = ""
        latest_tool: dict[str, Any] = {}
        latest_tool_at = 0.0
        latest_result_at = 0.0
        last_event_kind = ""
        for raw in tail.splitlines():
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            parsed = parse_iso(event.get("timestamp") or event.get("updatedAt")) or 0.0
            if parsed:
                extra["last_active"] = parsed
            event_type = event.get("type")
            if event_type == "title" and event.get("title"):
                extra["session_title"] = event["title"]
                continue
            if event_type == "custom" and event.get("customType") == "tool_execution_start":
                data = event.get("data") or {}
                latest_tool = _tool_activity(data, last_assistant_text)
                latest_tool_at = parse_iso(data.get("startedAt")) or parsed or latest_tool_at
                last_event_kind = "tool"
                continue
            if event_type != "message":
                continue
            message = event.get("message") or {}
            role = message.get("role")
            content = message.get("content")
            if role == "assistant":
                text = _extract_text(content)
                if text:
                    last_assistant_text = text
                    extra["headline"] = _headline(text)
                    extra["last_output"] = text[:1500]
                    extra["last_output_at"] = parsed or None
                    last_event_kind = "assistant"
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "toolCall":
                            latest_tool = _tool_activity(part, last_assistant_text)
                            latest_tool_at = parsed or latest_tool_at
                            last_event_kind = "tool"
            elif role == "toolResult":
                latest_result_at = parsed or latest_result_at
                last_event_kind = "result"

        extra["preview"] = extra["headline"]
        extra["tool"] = latest_tool.get("tool", "")
        extra["tool_phase"] = latest_tool.get("phase", "")
        extra["tool_title"] = latest_tool.get("title", "")
        extra["tool_pending"] = bool(latest_tool and latest_tool_at >= latest_result_at)
        extra["last_event_kind"] = last_event_kind
    except OSError:
        pass

    _session_cache[session_path] = (stat.st_mtime, extra)
    if len(_session_cache) > 64:  # 简单 FIFO 上限，防止会话路径累积
        _session_cache.pop(next(iter(_session_cache)), None)
    return extra


def classify_window(pane: dict[str, Any]) -> tuple[str, str]:
    title = (pane.get("terminal_title_stripped") or pane.get("terminal_title") or "").lower()
    label = (pane.get("label") or "").lower()
    blob = f"{title} {label}"
    if "ssh " in blob or blob.startswith("ssh"):
        return "ssh", "SSH"
    if any(token in blob for token in ("vim", "nvim", "helix", "emacs")):
        return "editor", "编辑器"
    if any(token in blob for token in ("git", "lazygit", "tig")):
        return "git", "Git"
    return "shell", "窗口"


def build_activity(
    extra: dict[str, Any],
    status: str,
    is_agent: bool,
    fallback_title: str,
    terminal_title: str,
) -> dict[str, Any]:
    if not is_agent:
        return {
            "phase": "窗口活动",
            "title": terminal_title or fallback_title,
            "tool": "terminal",
            "active": False,
            "tone": "window",
        }

    tool_title = extra.get("tool_title") or ""
    headline = extra.get("headline") or ""
    session_title = extra.get("session_title") or ""
    if status == "blocked":
        phase = "等待确认"
        title = headline or tool_title or "等待你的输入或授权"
        active = True
    elif status == "working" and extra.get("tool_pending"):
        phase = extra.get("tool_phase") or "正在执行"
        title = tool_title or headline or session_title or fallback_title
        active = True
    elif status == "working" and extra.get("last_event_kind") == "result":
        phase = "整理执行结果"
        title = tool_title or headline or session_title or fallback_title
        active = True
    elif status == "working":
        phase = "生成回复"
        title = headline or tool_title or session_title or fallback_title
        active = True
    else:
        phase = "最近完成" if status == "done" else "最近活动"
        title = headline or tool_title or session_title or fallback_title
        active = False

    return {
        "phase": phase,
        "title": _headline(title) or fallback_title,
        "tool": extra.get("tool") or "agent",
        "active": active,
        "tone": status if status in STATUS_META else "unknown",
    }


def normalize_item(
    pane: dict[str, Any],
    workspaces: dict[str, dict[str, Any]],
    tabs: dict[str, dict[str, Any]],
    now: float,
) -> dict[str, Any]:
    agent = pane.get("agent")
    status = pane.get("agent_status") or "unknown"
    session = pane.get("agent_session") or {}
    session_path = session.get("value") if session.get("kind") == "path" else None
    extra = read_session_extra(session_path) if session_path else {}
    workspace = workspaces.get(pane.get("workspace_id") or "", {})
    tab = tabs.get(pane.get("tab_id") or "", {})
    is_agent = bool(agent)
    if not is_agent:
        window_kind, window_label = classify_window(pane)
        agent_label = window_label
        family = window_kind
        column = "window"
        status_label = "窗口"
    else:
        meta = AGENT_META.get(agent, {"label": str(agent).upper(), "family": "other"})
        agent_label = meta["label"]
        family = meta["family"]
        column = status if status in STATUS_META else "unknown"
        status_label = STATUS_META.get(status, STATUS_META["unknown"])["label"]

    pane_title = str(pane.get("label") or "").strip()
    session_title = str(extra.get("session_title") or "").strip()
    terminal_title_raw = pane.get("terminal_title_stripped") or pane.get("terminal_title") or ""
    terminal_title = clean_title(terminal_title_raw)
    title = (
        pane_title
        or session_title
        or terminal_title
        or tab.get("label")
        or workspace.get("label")
        or pane.get("pane_id")
    )
    secondary_title = ""
    for candidate in (session_title, terminal_title):
        if candidate and candidate.casefold() != str(title).casefold():
            secondary_title = candidate
            break
    activity = build_activity(extra, status, is_agent, title, terminal_title)
    last_active = extra.get("last_active")
    return {
        "id": pane.get("pane_id"),
        "kind": "agent" if is_agent else "window",
        "agent": agent or family,
        "agent_label": agent_label,
        "family": family,
        "status": status if is_agent else "window",
        "status_label": status_label,
        "column": column if is_agent else "window",
        "workspace_id": pane.get("workspace_id"),
        "workspace": workspace.get("label") or pane.get("workspace_id") or "—",
        "tab_id": pane.get("tab_id"),
        "tab": tab.get("label") or pane.get("tab_id") or "—",
        "pane_id": pane.get("pane_id"),
        "pane_label": pane_title,
        "pane_title": pane_title,
        "session_title": session_title,
        "terminal_title": terminal_title,
        "title": title,
        "secondary_title": secondary_title,
        "activity_phase": activity["phase"],
        "activity_title": activity["title"],
        "activity_tool": activity["tool"],
        "activity_active": activity["active"],
        "activity_tone": activity["tone"],
        "cwd": pane.get("cwd") or pane.get("foreground_cwd") or "",
        "cwd_short": relative_home(pane.get("cwd") or pane.get("foreground_cwd")),
        "project": project_name(pane.get("cwd") or pane.get("foreground_cwd")),
        "focused": bool(pane.get("focused")),
        "session_id": session.get("value") if session.get("kind") == "id" else Path(session_path).stem if session_path else "",
        "session_path": session_path or "",
        "last_active": last_active,
        "last_active_label": human_age(last_active, now),
        "preview": extra.get("preview") or "",
        "last_output": extra.get("last_output") or "",
        "last_output_at": extra.get("last_output_at"),
        "last_output_label": human_age(extra.get("last_output_at"), now),
        "terminal_title_raw": terminal_title_raw,
        "revision": pane.get("revision"),
    }


def _fingerprint(snapshot: dict[str, Any]) -> str:
    items = [
        {
            "pane_id": item.get("pane_id"),
            "kind": item.get("kind"),
            "agent": item.get("agent"),
            "status": item.get("status"),
            "column": item.get("column"),
            "workspace_id": item.get("workspace_id"),
            "tab_id": item.get("tab_id"),
            "title": item.get("title"),
            "secondary_title": item.get("secondary_title"),
            "activity_phase": item.get("activity_phase"),
            "activity_title": item.get("activity_title"),
            "activity_tool": item.get("activity_tool"),
            "activity_active": item.get("activity_active"),
            "focused": item.get("focused"),
            "last_output": item.get("last_output"),
            "last_output_at": item.get("last_output_at"),
            "revision": item.get("revision"),
        }
        for item in snapshot.get("items") or []
    ]
    payload = json.dumps(
        {"items": items, "counts": snapshot.get("counts"), "focused": snapshot.get("focused")},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def collect() -> dict[str, Any]:
    now = time.time()
    payload = run_herdr("api", "snapshot")
    snapshot = (payload.get("result") or {}).get("snapshot") or {}
    workspaces = {item["workspace_id"]: item for item in snapshot.get("workspaces") or [] if item.get("workspace_id")}
    tabs = {item["tab_id"]: item for item in snapshot.get("tabs") or [] if item.get("tab_id")}
    panes = snapshot.get("panes") or []
    items = [normalize_item(pane, workspaces, tabs, now) for pane in panes]
    track_pane_activity(panes, now)
    for item in items:
        since = (_activity.get(item.get("pane_id")) or {}).get("since")
        item["quiet_since"] = since
        item["quiet_seconds"] = int(max(0.0, now - since)) if since else 0
        item["quiet_label"] = human_age(since, now)
    counts = {
        "blocked": 0,
        "working": 0,
        "idle": 0,
        "done": 0,
        "unknown": 0,
        "windows": 0,
        "agents": 0,
        "total": len(items),
    }
    for item in items:
        if item["kind"] == "window":
            counts["windows"] += 1
        else:
            counts["agents"] += 1
            if item["status"] in counts:
                counts[item["status"]] += 1
    columns = {
        "blocked": [item for item in items if item["column"] == "blocked"],
        "working": [item for item in items if item["column"] == "working"],
        "settled": [item for item in items if item["column"] in {"idle", "done"}],
        "window": [item for item in items if item["column"] == "window"],
    }
    spaces: dict[str, dict[str, Any]] = {}
    for workspace in snapshot.get("workspaces") or []:
        wid = workspace.get("workspace_id")
        spaces[wid] = {
            "workspace_id": wid,
            "label": workspace.get("label") or wid,
            "focused": bool(workspace.get("focused")),
            "agent_status": workspace.get("agent_status"),
            "items": [],
        }
    for item in items:
        bucket = spaces.setdefault(
            item["workspace_id"],
            {
                "workspace_id": item["workspace_id"],
                "label": item["workspace"],
                "focused": False,
                "agent_status": None,
                "items": [],
            },
        )
        bucket["items"].append(item)

    return {
        "ok": True,
        "fingerprint": _fingerprint({"items": items, "counts": counts, "focused": {
            "workspace_id": snapshot.get("focused_workspace_id"),
            "tab_id": snapshot.get("focused_tab_id"),
            "pane_id": snapshot.get("focused_pane_id"),
        }}),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "clock": time.strftime("%H:%M:%S"),
        "version": snapshot.get("version") or "",
        "focused": {
            "workspace_id": snapshot.get("focused_workspace_id"),
            "tab_id": snapshot.get("focused_tab_id"),
            "pane_id": snapshot.get("focused_pane_id"),
        },
        "counts": counts,
        "items": items,
        "columns": columns,
        "spaces": list(spaces.values()),
        "workspaces": snapshot.get("workspaces") or [],
        "tabs": snapshot.get("tabs") or [],
    }


def collect_or_error() -> dict[str, Any]:
    try:
        return collect()
    except Exception as exc:  # noqa: BLE001 - surface any collector failure to UI
        return {
            "ok": False,
            "error": str(exc),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "clock": time.strftime("%H:%M:%S"),
            "counts": {
                "blocked": 0,
                "working": 0,
                "idle": 0,
                "done": 0,
                "unknown": 0,
                "windows": 0,
                "agents": 0,
                "total": 0,
            },
            "items": [],
            "columns": {"blocked": [], "working": [], "settled": [], "window": []},
            "spaces": [],
            "focused": {},
        }


def send_text(pane_id: str, text: str) -> dict[str, Any]:
    """Deliver text from the web portal into an agent pane.

    Settled agents (blocked/idle/done) get a proper prompt submission;
    working agents get literal typed input so a reply reaches them
    mid-stream without double-delivery risk.
    """
    if not pane_id or not SAFE_ID_RE.match(pane_id):
        raise ValueError(f"invalid pane id: {pane_id}")
    message = "".join(
        char for char in str(text or "")
        if char in "\n\t" or ord(char) >= 32
    ).strip()
    if not message:
        raise ValueError("消息内容为空")
    if len(message) > 20_000:
        raise ValueError("消息过长（上限 20000 字符）")

    snapshot = collect()
    item = next((entry for entry in snapshot["items"] if entry["pane_id"] == pane_id), None)
    if not item:
        raise RuntimeError(f"pane 不存在: {pane_id}")
    if item["kind"] != "agent":
        raise RuntimeError("该 Pane 不是 Agent，网页端暂只支持向 Agent 发送文字")

    if item["status"] in {"blocked", "idle", "done"}:
        run_herdr("agent", "prompt", pane_id, message, timeout=20)
        return {"path": "prompt", "agent": item["agent_label"], "title": item["title"]}

    run_herdr("pane", "send-text", pane_id, message, timeout=10)
    run_herdr("pane", "send-keys", pane_id, "enter", timeout=10)
    return {"path": "keys", "agent": item["agent_label"], "title": item["title"]}


TERMINAL_APPS = {
    "ghostty": "Ghostty",
    "iterm2": "iTerm",
    "iterm": "iTerm",
    "terminal": "Terminal",
    "kitty": "kitty",
    "alacritty": "Alacritty",
    "wezterm-gui": "WezTerm",
    "wezterm": "WezTerm",
    "warp": "Warp",
    "hyper": "Hyper",
    "tabby": "Tabby",
}


def _process_table() -> dict[int, tuple[int, str]]:
    table: dict[int, tuple[int, str]] = {}
    try:
        raw = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,comm="],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return table
    for line in raw.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            table[int(parts[0])] = (int(parts[1]), parts[2].strip())
        except ValueError:
            continue
    return table


def _find_terminal_app() -> tuple[str, int] | None:
    """找到承载 Herdr 的终端 App（通过 herdr 进程的祖先链）。"""
    table = _process_table()
    if not table:
        return None
    herdr_pids = [
        pid
        for pid, (_, comm) in table.items()
        if comm == "herdr" or comm.lower().endswith("/herdr")
    ]
    seen_chains: set[int] = set()
    for pid in herdr_pids:
        current = pid
        for _ in range(10):
            if current in seen_chains:
                break
            seen_chains.add(current)
            row = table.get(current)
            if not row:
                break
            ppid, comm = row
            base = comm.rsplit("/", 1)[-1].lower()
            app = TERMINAL_APPS.get(base)
            if app:
                return app, current
            current = ppid
            if current <= 1:
                break
    return None


def bring_herdr_to_front() -> bool:
    """把承载 Herdr 的终端窗口带到前台。"""
    if os.environ.get("HERDR_PORTAL_NO_FRONT") == "1":
        return False
    found = _find_terminal_app()
    if not found:
        return False
    app, app_pid = found
    try:
        subprocess.run(
            ["open", "-a", app],
            check=True,
            capture_output=True,
            timeout=6,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        script = (
            "tell application \"System Events\" to set frontmost of "
            f"first application process whose unix id is {app_pid} to true"
        )
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            timeout=6,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def focus_target(pane_id: str) -> dict[str, Any]:
    if not pane_id or not SAFE_ID_RE.match(pane_id):
        raise ValueError(f"invalid pane id: {pane_id}")
    snapshot = collect()
    item = next((entry for entry in snapshot["items"] if entry["pane_id"] == pane_id), None)
    if not item:
        raise RuntimeError(f"pane not found: {pane_id}")
    if item["kind"] == "agent":
        result = run_herdr("agent", "focus", pane_id)
        bring_herdr_to_front()
        return result
    if item.get("workspace_id"):
        run_herdr("workspace", "focus", item["workspace_id"])
    if item.get("tab_id"):
        run_herdr("tab", "focus", item["tab_id"])
    subprocess.run(
        [HERDR_BIN, "pane", "zoom", pane_id, "--on"],
        check=False,
        capture_output=True,
        text=True,
        timeout=3,
    )
    result = run_herdr("pane", "zoom", pane_id, "--off")
    bring_herdr_to_front()
    return result


def _state_dir() -> Path:
    base = os.environ.get("HERDR_PORTAL_STATE_DIR")
    if base:
        return Path(base)
    return Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "herdr-portal"


def _activity_path() -> Path:
    return _state_dir() / "activity.json"


def _load_activity() -> None:
    """进程内只读一次磁盘；之后以内存镜像为准（多个看板同时跑时各自收敛）。"""
    global _activity_loaded
    if _activity_loaded:
        return
    _activity_loaded = True
    try:
        raw = json.loads(_activity_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(raw, dict):
        for pane_id, record in raw.items():
            if isinstance(record, dict) and isinstance(record.get("since"), (int, float)):
                _activity[str(pane_id)] = {
                    "revision": record.get("revision"),
                    "title": record.get("title") or "",
                    "since": float(record["since"]),
                }


def _save_activity(now: float) -> None:
    global _activity_saved_at
    if now - _activity_saved_at < 5.0:
        return
    _activity_saved_at = now
    path = _activity_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_activity, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def track_pane_activity(panes: list[dict[str, Any]], now: float) -> None:
    """记录每个 pane「终端内容最后一次变化」的时刻，用于判断静默时长。

    revision 是 herdr 的终端内容版本号：agent 跑动或用户敲字都会推进它，
    静止的 shell 则一直不变。看板每秒采集一次，所以这份记录足够精确。
    """
    _load_activity()
    dirty = False
    live: set[str] = set()
    for pane in panes:
        pane_id = pane.get("pane_id")
        if not pane_id:
            continue
        live.add(pane_id)
        revision = pane.get("revision")
        title = pane.get("terminal_title_stripped") or pane.get("terminal_title") or ""
        record = _activity.get(pane_id)
        if record and record.get("revision") == revision and record.get("title") == title:
            continue
        _activity[pane_id] = {"revision": revision, "title": title, "since": now}
        dirty = True
    for pane_id in [pane_id for pane_id in _activity if pane_id not in live]:
        del _activity[pane_id]
        dirty = True
    if dirty:
        _save_activity(now)


def _process_info(pane_id: str) -> dict[str, Any] | None:
    try:
        payload = run_herdr("pane", "process-info", "--pane", pane_id, timeout=3.0)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return None
    info = (payload.get("result") or {}).get("process_info")
    return info if isinstance(info, dict) else None


def _process_info_map(pane_ids: list[str]) -> dict[str, dict[str, Any] | None]:
    if not pane_ids:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(pane_ids))) as pool:
        return dict(zip(pane_ids, pool.map(_process_info, pane_ids)))


def _foreground_summary(info: dict[str, Any] | None) -> tuple[list[str], str, bool]:
    """返回 (进程名列表, 展示用标签, 是否只剩静止 shell)。"""
    processes = (info or {}).get("foreground_processes") or []
    names: list[str] = []
    for process in processes:
        name = str(process.get("argv0") or process.get("name") or "").rsplit("/", 1)[-1]
        if name.startswith("-"):
            name = name[1:]
        if name:
            names.append(name)
    shell_only = bool(names) and all(name in SHELL_NAMES for name in names)
    label = " · ".join(dict.fromkeys(names)) if names else "无前台进程"
    return names, label, shell_only


def _is_portal_pane(info: dict[str, Any] | None) -> bool:
    for process in (info or {}).get("foreground_processes") or []:
        blob = " ".join(
            str(part)
            for part in (process.get("cmdline"), process.get("argv0"), *(process.get("argv") or []))
            if part
        )
        if any(marker in blob for marker in PORTAL_MARKERS):
            return True
    return False


def _reclaim_verdict(
    item: dict[str, Any],
    info: dict[str, Any] | None,
    focused_pane_id: str | None,
) -> tuple[str, str, str, str]:
    """(verdict, risk, reason, process_label)；verdict 为 candidate / protected。"""
    _, process_label, shell_only = _foreground_summary(info)
    if item.get("focused") or item.get("pane_id") == focused_pane_id:
        return "protected", "", "当前聚焦", process_label
    if info is None:
        return "protected", "", "进程信息不可用", process_label
    if _is_portal_pane(info):
        return "protected", "", "看板自身", process_label
    if item.get("kind") == "agent":
        if item.get("status") in {"working", "blocked"}:
            return "protected", "", "Agent 运行中", process_label
        return "candidate", "agent", "空闲 Agent", process_label
    if not shell_only:
        return "protected", "", f"运行中 · {process_label}", process_label
    return "candidate", "shell", "静止 Shell", process_label


def cleanup_scan(idle_seconds: int = DEFAULT_CLEANUP_IDLE) -> dict[str, Any]:
    """列出可以安全回收的 pane。只读，不做任何关闭动作。"""
    idle_seconds = max(0, int(idle_seconds))
    snapshot = collect()
    items = snapshot.get("items") or []
    focused_pane_id = (snapshot.get("focused") or {}).get("pane_id")
    focused_tab_id = (snapshot.get("focused") or {}).get("tab_id")
    infos = _process_info_map([item["pane_id"] for item in items if item.get("pane_id")])

    tab_total: dict[str, int] = {}
    workspace_total: dict[str, int] = {}
    for item in items:
        tab_total[item.get("tab_id")] = tab_total.get(item.get("tab_id"), 0) + 1
        workspace_total[item.get("workspace_id")] = workspace_total.get(item.get("workspace_id"), 0) + 1

    candidates: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    for item in items:
        pane_id = item.get("pane_id")
        info = infos.get(pane_id)
        verdict, risk, reason, process_label = _reclaim_verdict(item, info, focused_pane_id)
        quiet_seconds = float(item.get("quiet_seconds") or 0.0)
        entry = {
            "pane_id": pane_id,
            "kind": item.get("kind"),
            "agent_label": item.get("agent_label"),
            "title": item.get("title"),
            "workspace": item.get("workspace"),
            "workspace_id": item.get("workspace_id"),
            "tab": item.get("tab"),
            "tab_id": item.get("tab_id"),
            "status_label": item.get("status_label"),
            "reason": reason,
            "process": process_label,
            "quiet_seconds": int(quiet_seconds),
            "quiet_label": item.get("quiet_label") or "",
        }
        if verdict == "protected":
            protected.append(entry)
            continue
        entry.update(
            {
                "risk": risk,
                "idle_ok": quiet_seconds >= idle_seconds,
                "in_focused_tab": bool(focused_tab_id) and item.get("tab_id") == focused_tab_id,
                "last_in_tab": tab_total.get(item.get("tab_id"), 0) <= 1,
                "last_in_workspace": workspace_total.get(item.get("workspace_id"), 0) <= 1,
            }
        )
        # 默认只勾选「静止 shell + 已超过阈值 + 不在当前标签页」，Agent 一律交给人确认。
        entry["preselect"] = bool(
            risk == "shell" and entry["idle_ok"] and not entry["in_focused_tab"]
        )
        candidates.append(entry)

    candidates.sort(key=lambda entry: (-entry["quiet_seconds"], entry["pane_id"] or ""))
    return {
        "ok": True,
        "idle_seconds": idle_seconds,
        "idle_label": CLEANUP_THRESHOLD_LABELS.get(idle_seconds, f"{idle_seconds // 60}m"),
        "clock": time.strftime("%H:%M:%S"),
        "candidates": candidates,
        "protected": protected,
        "counts": {
            "candidates": len(candidates),
            "preselected": sum(1 for entry in candidates if entry["preselect"]),
            "protected": len(protected),
            "panes": len(items),
            "workspaces": len(workspace_total),
        },
    }


def cleanup_apply(pane_ids: list[str], idle_seconds: int = DEFAULT_CLEANUP_IDLE) -> dict[str, Any]:
    """关闭选中的 pane。只会关闭「本次重新扫描仍然是候选」的 pane。

    herdr 会级联回收：关掉标签页里最后一个 pane 会连标签页一起收，
    关掉工作区里最后一个标签页会连工作区一起收，所以只需要 pane close。
    """
    requested = [str(pane_id) for pane_id in pane_ids or [] if str(pane_id).strip()]
    invalid = [pane_id for pane_id in requested if not SAFE_ID_RE.match(pane_id)]
    if invalid:
        raise ValueError(f"invalid pane id: {invalid[0]}")
    if not requested:
        raise ValueError("没有选中任何 pane")

    scan = cleanup_scan(idle_seconds)
    allowed = {entry["pane_id"] for entry in scan["candidates"]}
    before_workspaces = {entry["workspace_id"] for entry in scan["candidates"] + scan["protected"]}
    targets = [pane_id for pane_id in requested if pane_id in allowed]
    skipped = [pane_id for pane_id in requested if pane_id not in allowed]

    closed: list[str] = []
    failed: list[dict[str, str]] = []
    for pane_id in targets:
        try:
            run_herdr("pane", "close", pane_id, timeout=6.0)
            closed.append(pane_id)
        except Exception as exc:  # noqa: BLE001 - 单个 pane 失败不影响其余
            failed.append({"pane_id": pane_id, "error": str(exc)})
    for pane_id in closed:
        _activity.pop(pane_id, None)

    after = collect_or_error()
    after_items = after.get("items") or []
    after_workspaces = {item.get("workspace_id") for item in after_items}
    return {
        "ok": not failed,
        "closed": closed,
        "failed": failed,
        "skipped": skipped,
        "freed": {
            "panes": len(closed),
            "workspaces": len(before_workspaces - after_workspaces),
        },
        "remaining": {
            "panes": len(after_items),
            "workspaces": len(after_workspaces),
        },
    }


# ---------- 重命名 ----------

RENAME_KINDS = ("pane", "tab", "workspace")
RENAME_LABELS = {"pane": "Pane 标题", "tab": "Tab 名称", "workspace": "Workspace 名称"}
RENAME_MAX = 80


def clean_label(text: str | None) -> str:
    """去掉控制字符并压平空白；herdr 的 label 是单行展示用文本。"""
    text = "".join(char for char in str(text or "") if ord(char) >= 32 and char != "\x7f")
    return re.sub(r"\s+", " ", text).strip()[:RENAME_MAX]


def rename_target(kind: str, target_id: str, label: str) -> dict[str, Any]:
    """重命名 pane / tab / workspace；pane 传空字符串表示清除自定义标题。"""
    if kind not in RENAME_KINDS:
        raise ValueError(f"unsupported rename kind: {kind}")
    target_id = str(target_id or "")
    if not target_id or not SAFE_ID_RE.match(target_id):
        raise ValueError(f"invalid {kind} id: {target_id}")
    label = clean_label(label)
    if not label:
        if kind != "pane":
            raise ValueError(f"{RENAME_LABELS[kind]}不能为空")
        run_herdr("pane", "rename", target_id, "--clear")
        return {"kind": kind, "target_id": target_id, "label": "", "cleared": True}
    run_herdr(kind, "rename", target_id, label)
    return {"kind": kind, "target_id": target_id, "label": label, "cleared": False}


# ---------- 新开 Tab / Pane ----------

SPAWN_DIRECTIONS = ("right", "down")
SPAWN_LABELS = {"tab": "Tab", "pane": "Pane"}


def spawn_tab(
    workspace_id: str | None = None,
    cwd: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """新开一个标签页，返回它的根 pane。

    默认不抢焦点：看板负责建，跳不跳由调用方决定（失败时不留下半个焦点）。
    """
    args = ["tab", "create", "--no-focus"]
    if workspace_id:
        if not SAFE_ID_RE.match(workspace_id):
            raise ValueError(f"invalid workspace id: {workspace_id}")
        args += ["--workspace", workspace_id]
    if cwd:
        args += ["--cwd", cwd]
    label = clean_label(label)
    if label:
        args += ["--label", label]
    result = run_herdr(*args, timeout=10.0).get("result") or {}
    pane_id = (result.get("root_pane") or {}).get("pane_id")
    if not pane_id:
        raise RuntimeError("herdr 没有返回新建的 pane")
    return {"kind": "tab", "pane_id": pane_id, "tab_id": (result.get("tab") or {}).get("tab_id")}


def spawn_pane(pane_id: str, direction: str = "right", cwd: str | None = None) -> dict[str, Any]:
    """在指定 pane 旁边切一个新 pane，返回新 pane。"""
    pane_id = str(pane_id or "")
    if not pane_id or not SAFE_ID_RE.match(pane_id):
        raise ValueError(f"invalid pane id: {pane_id}")
    if direction not in SPAWN_DIRECTIONS:
        raise ValueError(f"unsupported split direction: {direction}")
    args = ["pane", "split", pane_id, "--direction", direction, "--no-focus"]
    if cwd:
        args += ["--cwd", cwd]
    result = run_herdr(*args, timeout=10.0).get("result") or {}
    new_id = (result.get("pane") or {}).get("pane_id")
    if not new_id:
        raise RuntimeError("herdr 没有返回新建的 pane")
    return {"kind": "pane", "pane_id": new_id, "direction": direction, "source_pane_id": pane_id}


# ---------- 全局资源清理（Mole / mo clean） ----------

MO_BIN = os.environ.get("HERDR_PORTAL_MO_BIN", "mo")


def mo_available() -> bool:
    return shutil.which(MO_BIN) is not None


def launch_task(command: list[str], label: str, cwd: str | None = None) -> dict[str, Any]:
    """新开一个 herdr 标签页并在里面跑命令，返回新 pane。

    交互式工具（sudo 提示、全屏 UI）必须待在真正的终端里，所以看板只负责
    起一个标签页把它交出去，不去代管它的输入输出。
    """
    if not command:
        raise ValueError("命令为空")
    spawned = spawn_tab(cwd=cwd, label=clean_label(label) or "task")
    pane_id = spawned["pane_id"]
    try:
        run_herdr("pane", "run", pane_id, *command, timeout=10.0, allow_empty=True)
    except Exception:
        # 命令没起来就别留下一个空标签页
        try:
            run_herdr("pane", "close", pane_id, timeout=6.0)
        except Exception:  # noqa: BLE001
            pass
        raise
    return {"pane_id": pane_id, "tab_id": spawned["tab_id"], "command": " ".join(command)}


def mo_clean(dry_run: bool = True) -> dict[str, Any]:
    """把全局磁盘清理交给 Mole（mo clean），在新标签页里跑。"""
    if not mo_available():
        raise RuntimeError(f"未找到 {MO_BIN}（Mole）· https://mole.fit")
    command = [MO_BIN, "clean"] + (["--dry-run"] if dry_run else [])
    label = "mo clean · 预览" if dry_run else "mo clean"
    result = launch_task(command, label, cwd=str(Path.home()))
    result["dry_run"] = dry_run
    return result


# ---------- 版本检查 / 更新引导 ----------

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PLUGIN_ROOT / "herdr-plugin.toml"
VERSION_REPO = os.environ.get("HERDR_PORTAL_REPO", "loofare/herdr-portal")
VERSION_BRANCH = os.environ.get("HERDR_PORTAL_BRANCH", "main")
VERSION_TTL = float(os.environ.get("HERDR_PORTAL_VERSION_TTL") or 6 * 3600)
VERSION_TIMEOUT = 6.0
VERSION_RE = re.compile(r'(?m)^\s*version\s*=\s*"([^"]+)"')
_version_worker: threading.Thread | None = None


def _manifest_version(text: str) -> str:
    match = VERSION_RE.search(text or "")
    return match.group(1).strip() if match else ""


def local_version() -> str:
    try:
        return _manifest_version(MANIFEST_PATH.read_text(encoding="utf-8"))
    except OSError:
        return ""


def _version_key(version: str) -> tuple[int, int, int, int]:
    """把 1.2.10 变成能比大小的定长元组。

    定长很重要：补零后 `1.2.0` 和 `1.2.0-rc1` 相等，预发布版本不会被当成更新。
    """
    key = [0, 0, 0, 0]
    for index, part in enumerate(re.split(r"[.\-+_]", str(version or "").lstrip("vV"))[:4]):
        digits = re.match(r"\d+", part)
        key[index] = int(digits.group()) if digits else 0
    return tuple(key)  # type: ignore[return-value]


def _version_cache_path() -> Path:
    return _state_dir() / "version.json"


def _read_version_cache() -> dict[str, Any]:
    try:
        raw = json.loads(_version_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def fetch_latest_version() -> dict[str, Any]:
    """读一次上游 manifest 的版本号并落缓存；离线 / 限流都只记成「查不到」。"""
    url = f"https://raw.githubusercontent.com/{VERSION_REPO}/{VERSION_BRANCH}/herdr-plugin.toml"
    record: dict[str, Any] = {"checked_at": time.time(), "source": url}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "herdr-portal"})
        with urllib.request.urlopen(request, timeout=VERSION_TIMEOUT) as response:
            body = response.read(200_000).decode("utf-8", "replace")
        latest = _manifest_version(body)
        if not latest:
            raise ValueError("上游 manifest 没有 version 字段")
        record["latest"] = latest
    except Exception as exc:  # noqa: BLE001 - 查版本失败绝不该影响看板
        record["error"] = str(exc)
    path = _version_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass
    return record


def version_status(refresh: bool = False) -> dict[str, Any]:
    """当前版本 vs 上游最新版本。默认只读缓存（不碰网络，不阻塞渲染）。"""
    current = local_version()
    record = fetch_latest_version() if refresh else _read_version_cache()
    latest = str(record.get("latest") or "")
    checked_at = record.get("checked_at")
    if latest and current:
        state = "outdated" if _version_key(latest) > _version_key(current) else "current"
    else:
        state = "unknown"
    return {
        "current": current,
        "latest": latest,
        "state": state,
        "error": str(record.get("error") or ""),
        "checked_at": checked_at,
        "stale": not checked_at or (time.time() - float(checked_at)) > VERSION_TTL,
        "source": str(record.get("source") or ""),
    }


def start_version_check() -> None:
    """缓存过期时后台查一次；看板第一帧不等网络。"""
    global _version_worker
    if _version_worker is not None and _version_worker.is_alive():
        return
    if not version_status()["stale"]:
        return
    _version_worker = threading.Thread(target=fetch_latest_version, name="portal-version", daemon=True)
    _version_worker.start()


def update_plan() -> dict[str, Any]:
    """怎么更新这份插件：git 克隆的走 git pull，GitHub 装的走 plugin install。"""
    if (PLUGIN_ROOT / ".git").exists():
        return {
            "mode": "git",
            "command": ["git", "-C", str(PLUGIN_ROOT), "pull", "--ff-only"],
            "label": "portal 更新 · git pull",
            "hint": f"git pull --ff-only · {PLUGIN_ROOT}",
        }
    return {
        "mode": "plugin",
        "command": [HERDR_BIN, "plugin", "install", f"github:{VERSION_REPO}"],
        "label": "portal 更新 · plugin install",
        "hint": f"herdr plugin install github:{VERSION_REPO}",
    }


def launch_update() -> dict[str, Any]:
    """在新标签页里跑更新命令：输出看得见、冲突能自己处理，看板不代管。"""
    plan = update_plan()
    result = launch_task(plan["command"], plan["label"], cwd=str(PLUGIN_ROOT))
    result.update({"mode": plan["mode"], "hint": plan["hint"]})
    return result


if __name__ == "__main__":
    print(json.dumps(collect_or_error(), ensure_ascii=False, indent=2))
