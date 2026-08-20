#!/usr/bin/env python3
"""Mission-control style curses dashboard for every live Herdr pane.

对齐网页版的设计：
- 待确认列动态出现（为空时不占位置）
- 窗口（SSH/Shell）在独立视图里，Tab 切换
- 卡片展示结构化进展：阶段 + 执行标题 + 工具
- 详情栏展示最近输出摘要
"""

from __future__ import annotations

import curses
import os
import re
import signal
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collect import (  # noqa: E402
    CLEANUP_THRESHOLD_LABELS,
    CLEANUP_THRESHOLDS,
    DEFAULT_CLEANUP_IDLE,
    RENAME_KINDS,
    RENAME_LABELS,
    RENAME_MAX,
    SPAWN_LABELS,
    cleanup_apply,
    cleanup_scan,
    collect_or_error,
    focus_target,
    launch_update,
    mo_clean,
    rename_target,
    spawn_pane,
    spawn_tab,
    start_version_check,
    update_plan,
    version_status,
)

AGENT_COLUMNS = (
    ("blocked", "ACTION", "待确认", "等待你确认 / 输入"),
    ("working", "RUNNING", "执行中", "正在运行"),
    ("settled", "SETTLED", "已就绪", "空闲 / 完成"),
)

HELP_AGENTS = "↑↓ 选择  ←→ 切列  Enter 跳转  N 新 Tab  s/S 新 Pane 右/下  E 重命名  X 释放闲置  U 更新  Q 退出"
HELP_WINDOWS = "↑↓←→ 选择  Enter 跳转  N 新 Tab  s/S 新 Pane 右/下  E 重命名  X 释放闲置  U 更新  Tab 返回  Q 退出"
HELP_RECLAIM = "↑↓ 移动  Space 选中  A 全选  N 清空  T 阈值  d/D 磁盘预览·清理  Enter 释放  Esc 返回"
HELP_RENAME = "输入新名称  Tab 切换对象  ←→ 移动光标  Ctrl+U 清空  Enter 保存  Esc 取消"
CARD_HEIGHT = 5
CARD_GAP = 1

# Color-pair IDs.
P_BLOCKED = 1
P_WORKING = 2
P_SETTLED = 3
P_WINDOW = 4
P_TEXT = 5
P_ACCENT = 6
P_MUTED = 7
P_BORDER = 8
P_BG = 9
P_CARD = 10
P_CARD_MUTED = 11
P_SELECT_BLOCKED = 12
P_SELECT_WORKING = 13
P_SELECT_SETTLED = 14
P_SELECT_WINDOW = 15
P_CARD_BLOCKED = 16
P_CARD_WORKING = 17
P_CARD_SETTLED = 18
P_CARD_WINDOW = 19
P_DETAIL = 20
P_LIVE = 21
P_SELECT_ACCENT = 22

COLUMN_PAIR = {
    "blocked": P_BLOCKED,
    "working": P_WORKING,
    "settled": P_SETTLED,
    "window": P_WINDOW,
}
SELECT_PAIR = {
    "blocked": P_SELECT_BLOCKED,
    "working": P_SELECT_WORKING,
    "settled": P_SELECT_SETTLED,
    "window": P_SELECT_WINDOW,
}
CARD_STATUS_PAIR = {
    "blocked": P_CARD_BLOCKED,
    "working": P_CARD_WORKING,
    "settled": P_CARD_SETTLED,
    "window": P_CARD_WINDOW,
}
KEY_TITLE = {key: title for key, _en, title, _hint in AGENT_COLUMNS}


def _plain(text: str | None) -> str:
    """去掉 Markdown 标记，转成单行纯文本。"""
    text = text or ""
    text = re.sub(r"(\*\*|__|`|~~)", "", text)
    text = re.sub(r"^\s*(?:#{1,6}|[-*+>]|\d+[.)])\s*", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


def _char_width(char: str) -> int:
    if not char or unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def _width(text: str) -> int:
    return sum(_char_width(char) for char in text)


def _fit(text: str, width: int, pad: bool = False) -> str:
    if width <= 0:
        return ""
    text = str(text or "")
    used = 0
    out: list[str] = []
    clipped = False
    for char in text:
        char_width = _char_width(char)
        if used + char_width > width:
            clipped = True
            break
        out.append(char)
        used += char_width
    if clipped and width > 0:
        while out and used + 1 > width:
            used -= _char_width(out.pop())
        if used < width:
            out.append("…")
            used += 1
    if pad and used < width:
        out.append(" " * (width - used))
    return "".join(out)


def _write(
    stdscr: curses.window,
    y: int,
    x: int,
    text: str,
    width: int | None = None,
    attr: int = 0,
    pad: bool = False,
) -> None:
    height, screen_width = stdscr.getmaxyx()
    if y < 0 or y >= height or x < 0 or x >= screen_width:
        return
    room = max(0, screen_width - x - 1)
    if width is not None:
        room = min(room, max(0, width))
    if room <= 0:
        return
    try:
        stdscr.addstr(y, x, _fit(text, room, pad=pad), attr)
    except curses.error:
        pass


def _right(stdscr: curses.window, y: int, right_x: int, text: str, attr: int = 0) -> None:
    text = _fit(text, max(0, right_x))
    _write(stdscr, y, max(0, right_x - _width(text)), text, attr=attr)


def _box(
    stdscr: curses.window,
    y: int,
    x: int,
    height: int,
    width: int,
    attr: int,
    heavy: bool = False,
) -> None:
    if height < 2 or width < 2:
        return
    if heavy:
        tl, tr, bl, br, hz, vt = "┏", "┓", "┗", "┛", "━", "┃"
    else:
        tl, tr, bl, br, hz, vt = "╭", "╮", "╰", "╯", "─", "│"
    _write(stdscr, y, x, tl + hz * (width - 2) + tr, width, attr)
    for row in range(y + 1, y + height - 1):
        _write(stdscr, row, x, vt, 1, attr)
        _write(stdscr, row, x + width - 1, vt, 1, attr)
    _write(stdscr, y + height - 1, x, bl + hz * (width - 2) + br, width, attr)


def _column_key(item: dict) -> str:
    column = item.get("column") or item.get("status") or "window"
    if column in {"idle", "done"}:
        return "settled"
    return column if column in COLUMN_PAIR else "window"


def _scrollbar_geometry(track_top: int, track_bottom: int, visible: int, total: int, start: int) -> tuple[int, int]:
    track = max(1, track_bottom - track_top + 1)
    thumb = max(1, round(track * visible / total))
    max_start = max(0, total - visible)
    frac = start / max_start if max_start else 0.0
    thumb_start = track_top + round((track - thumb) * frac)
    return thumb, thumb_start


class Board:
    def __init__(self, stdscr: curses.window) -> None:
        self.stdscr = stdscr
        self.snapshot: dict = {}
        self.view = "agents"  # "agents" | "windows"
        self.pos = {"agents": [1, 0], "windows": [0, 0]}
        self.selected_id: str | None = None
        self.message = ""
        self.message_until = 0.0
        self.last_refresh = 0.0
        self.error = ""
        # 鼠标命中区：draw() 每帧重建，(top, bottom, left, right, …)
        self.hit_cards: list[tuple[int, int, int, int, int, int]] = []
        self.hit_panels: list[tuple[int, int, int, int, int]] = []
        self.hit_buttons: list[tuple[int, int, int, int, str]] = []
        self.hit_rows: list[tuple[int, int, int, int, int]] = []
        # 回收面板：None 表示未打开
        self.reclaim: dict | None = None
        # 重命名面板：None 表示未打开
        self.rename: dict | None = None
        self.last_click = (0.0, -1, -1)
        # 版本检查：只读缓存，后台线程负责刷新
        self.version = version_status()
        self.version_read = 0.0
        self.update_armed_until = 0.0

    # ---------- 数据 ----------

    def column_items(self, key: str) -> list[dict]:
        return list((self.snapshot.get("columns") or {}).get(key) or [])

    def find_item(self, pane_id: str | None) -> dict | None:
        if not pane_id:
            return None
        for items in self.view_items():
            for item in items:
                if item.get("pane_id") == pane_id:
                    return item
        return None

    def window_items(self) -> list[dict]:
        return self.column_items("window")

    def visible_agent_keys(self) -> list[str]:
        keys: list[str] = []
        if self.column_items("blocked"):
            keys.append("blocked")
        keys.extend(["working", "settled"])
        return keys

    def view_items(self) -> list[list[dict]]:
        if self.view == "windows":
            return [self.window_items()]
        return [self.column_items(key) for key in self.visible_agent_keys()]

    def selected_item(self) -> dict | None:
        columns = self.view_items()
        col, row = self.pos[self.view]
        col = max(0, min(col, len(columns) - 1)) if columns else 0
        items = columns[col] if columns else []
        if not items:
            self.selected_id = None
            return None
        row = max(0, min(row, len(items) - 1))
        self.pos[self.view] = [col, row]
        item = items[row]
        self.selected_id = item.get("pane_id")
        return item

    def _locate(self, pane_id: str | None) -> bool:
        if pane_id:
            for col, items in enumerate(self.view_items()):
                for row, item in enumerate(items):
                    if item.get("pane_id") == pane_id:
                        self.pos[self.view] = [col, row]
                        self.selected_id = pane_id
                        return True
        for col, items in enumerate(self.view_items()):
            if items:
                self.pos[self.view] = [col, 0]
                self.selected_id = items[0].get("pane_id")
                return True
        self.pos[self.view] = [0, 0]
        self.selected_id = None
        return False

    def refresh(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self.last_refresh < 1.0:
            return
        previous_id = self.selected_id
        next_snapshot = collect_or_error()
        if next_snapshot.get("ok"):
            self.snapshot = next_snapshot
            self.error = ""
            self._locate(previous_id)
        else:
            self.error = next_snapshot.get("error", "采集失败")
            if not self.snapshot:
                self.snapshot = next_snapshot
        self.last_refresh = now
        if now - self.version_read > 5.0:
            # 只读那份 JSON 缓存（后台线程写），所以每 5 秒扫一次足够便宜
            self.version = version_status()
            self.version_read = now

    def flash(self, message: str, duration: float = 2.2) -> None:
        self.message = message
        self.message_until = time.time() + duration

    # ---------- 版本检查 / 更新 ----------

    def check_update(self) -> bool:
        """U：查版本 → 有新版就上膛 → 再按一次在新标签页跑更新命令。"""
        status = self.version
        if status["state"] == "unknown" or status["stale"]:
            self.flash("正在查最新版本…", 8.0)
            self.draw()
            status = self.version = version_status(refresh=True)
            self.version_read = time.time()
        current = status["current"] or "?"
        if status["state"] == "current":
            self.flash(f"已是最新 · v{current}", 3.0)
            return False
        if status["state"] != "outdated":
            self.flash(f"查不到最新版本 · {status['error'] or '未知原因'}", 4.0)
            return False
        plan = update_plan()
        if time.time() > self.update_armed_until:
            self.update_armed_until = time.time() + 6.0
            self.flash(f"发现新版 v{status['latest']}（当前 v{current}）· 再按一次 U 执行 {plan['hint']}", 6.0)
            return False
        self.update_armed_until = 0.0
        try:
            result = launch_update()
        except Exception as exc:  # noqa: BLE001
            self.flash(f"更新启动失败 · {exc}", 4.0)
            return False
        try:
            focus_target(result["pane_id"])
            return True
        except Exception:  # noqa: BLE001 - 命令已经在新标签页跑起来了
            self.refresh(force=True)
            self.flash(f"已在新标签页执行 {result['hint']}", 4.0)
            return False

    def jump(self) -> bool:
        """跳转到对应 Pane；成功返回 True（调用方关闭面板）。"""
        item = self.selected_item()
        if not item:
            self.flash("当前没有可选项目")
            return False
        try:
            focus_target(item["pane_id"])
            return True
        except Exception as exc:  # noqa: BLE001
            self.flash(f"跳转失败 · {exc}", 3.5)
            return False

    def move(self, dcol: int = 0, drow: int = 0) -> None:
        columns = self.view_items()
        if not columns or not any(columns):
            return
        col, row = self.pos[self.view]
        if dcol:
            nxt = col + dcol
            for _ in range(len(columns)):
                idx = nxt % len(columns)
                if columns[idx]:
                    col = idx
                    break
                nxt += dcol
        if drow:
            items = columns[col]
            if items:
                row = (row + drow) % len(items)
        self.pos[self.view] = [col, min(row, max(0, len(columns[col]) - 1))]
        self.selected_item()

    def choose_column(self, index: int) -> None:
        columns = self.view_items()
        if not columns or not any(columns):
            return
        self.pos[self.view] = [min(index, len(columns) - 1), 0]
        self.selected_item()

    def toggle_view(self) -> None:
        self.view = "windows" if self.view == "agents" else "agents"
        self._locate(self.selected_id)

    # ---------- 新开 Tab / Pane ----------

    def spawn(self, kind: str, direction: str = "right") -> bool:
        """以看板为起点开一个新 Tab / Pane：继承选中卡片的 workspace 和目录。

        跳过去之后返回 True（调用方关闭面板），和 Enter 跳转的手感一致。
        """
        item = self.selected_item()
        cwd = (item or {}).get("cwd") or None
        try:
            if kind == "tab":
                result = spawn_tab(workspace_id=(item or {}).get("workspace_id"), cwd=cwd)
            else:
                if not item:
                    self.flash("先选中一个 pane 再拆分")
                    return False
                result = spawn_pane(item["pane_id"], direction=direction, cwd=cwd)
        except Exception as exc:  # noqa: BLE001
            self.flash(f"新开 {SPAWN_LABELS[kind]} 失败 · {exc}", 3.5)
            return False
        try:
            focus_target(result["pane_id"])
            return True
        except Exception:  # noqa: BLE001 - 已经建出来了，跳转失败不算致命
            self.refresh(force=True)
            self._locate(result["pane_id"])
            self.flash(f"已新开 {SPAWN_LABELS[kind]} {result['pane_id']}，但跳转失败", 4.0)
            return False

    # ---------- 重命名 ----------

    def _rename_current(self, kind: str, item: dict) -> str:
        if kind == "pane":
            return item.get("pane_label") or ""
        if kind == "tab":
            return item.get("tab") or ""
        return item.get("workspace") or ""

    def open_rename(self, kind: str = "pane") -> None:
        item = self.selected_item()
        if not item:
            self.flash("当前没有可重命名的项目")
            return
        text = self._rename_current(kind, item)
        self.rename = {
            "pane_id": item.get("pane_id"),
            "kind": kind,
            "buffer": list(text),
            "cursor": len(text),
            "note": "",
        }

    def close_rename(self) -> None:
        self.rename = None

    def rename_switch(self, kind: str | None = None) -> None:
        """切换重命名对象（Pane / Tab / Workspace），并载入该对象的当前名字。"""
        if self.rename is None:
            return
        item = self.find_item(self.rename["pane_id"])
        if item is None:
            self.close_rename()
            return
        if kind is None:
            kinds = list(RENAME_KINDS)
            kind = kinds[(kinds.index(self.rename["kind"]) + 1) % len(kinds)]
        text = self._rename_current(kind, item)
        self.rename.update({"kind": kind, "buffer": list(text), "cursor": len(text), "note": ""})

    def rename_edit(self, key) -> None:
        """极简行编辑：插入 / 退格 / 删除 / 光标移动 / 清空。"""
        state = self.rename
        if state is None:
            return
        buffer: list[str] = state["buffer"]
        cursor: int = state["cursor"]
        if key in (curses.KEY_BACKSPACE, "\x7f", "\b", "\x08"):
            if cursor > 0:
                del buffer[cursor - 1]
                state["cursor"] = cursor - 1
        elif key == curses.KEY_DC:
            if cursor < len(buffer):
                del buffer[cursor]
        elif key == "\x15":  # Ctrl+U
            buffer.clear()
            state["cursor"] = 0
        elif key in (curses.KEY_LEFT,):
            state["cursor"] = max(0, cursor - 1)
        elif key in (curses.KEY_RIGHT,):
            state["cursor"] = min(len(buffer), cursor + 1)
        elif key in (curses.KEY_HOME, "\x01"):
            state["cursor"] = 0
        elif key in (curses.KEY_END, "\x05"):
            state["cursor"] = len(buffer)
        elif isinstance(key, str) and key >= " " and key != "\x7f":
            if len(buffer) < RENAME_MAX:
                buffer.insert(cursor, key)
                state["cursor"] = cursor + 1
        state["note"] = ""

    def rename_commit(self) -> None:
        state = self.rename
        if state is None:
            return
        item = self.find_item(state["pane_id"])
        if item is None:
            self.close_rename()
            self.flash("该 Pane 已经不存在了", 3.0)
            return
        kind = state["kind"]
        target_id = {"pane": "pane_id", "tab": "tab_id", "workspace": "workspace_id"}[kind]
        text = "".join(state["buffer"])
        try:
            result = rename_target(kind, item.get(target_id) or "", text)
        except Exception as exc:  # noqa: BLE001 - 重命名失败留在面板里，方便改
            state["note"] = f"失败 · {exc}"
            return
        synced = ""
        if kind == "tab":
            # 卡片标题优先用 pane label：只改 Tab 会在同一张卡上留下两个名字，
            # 所以把这次改名同步写到当前 Pane 的标题上（同一个 Tab 里的其他 Pane 不动）。
            try:
                rename_target("pane", item.get("pane_id") or "", result["label"])
                synced = " · 当前 Pane 标题同步"
            except Exception as exc:  # noqa: BLE001 - Tab 已经改好了，只报告没跟上的那一半
                synced = f" · Pane 标题没跟上（{exc}）"
        self.close_rename()
        self.refresh(force=True)
        self._locate(item.get("pane_id"))
        label = RENAME_LABELS[kind]
        done = f"{label} 已清除" if result["cleared"] else f"{label} 已改为「{result['label']}」"
        self.flash(f"{done}{synced}", 3.0)

    # ---------- 闲置回收 ----------

    def open_reclaim(self) -> None:
        """扫描可回收的 pane 并打开确认面板（扫描是只读的）。"""
        self.flash("正在扫描闲置 pane…", 6.0)
        self.draw()
        idle = self.reclaim.get("idle") if self.reclaim else DEFAULT_CLEANUP_IDLE
        self.reclaim = {"idle": idle, "row": 0, "start": 0, "armed": False, "note": "", "scan": None}
        self.rescan_reclaim()

    def rescan_reclaim(self) -> None:
        if self.reclaim is None:
            return
        try:
            scan = cleanup_scan(self.reclaim["idle"])
        except Exception as exc:  # noqa: BLE001 - 扫描失败不能让看板崩掉
            self.reclaim = None
            self.flash(f"扫描失败 · {exc}", 4.0)
            return
        self.reclaim["scan"] = scan
        self.reclaim["chosen"] = {
            entry["pane_id"] for entry in scan["candidates"] if entry["preselect"]
        }
        self.reclaim["row"] = min(self.reclaim.get("row", 0), max(0, len(scan["candidates"]) - 1))
        self.reclaim["armed"] = False
        self.message = ""
        self.message_until = 0.0

    def close_reclaim(self) -> None:
        self.reclaim = None

    def reclaim_candidates(self) -> list[dict]:
        return ((self.reclaim or {}).get("scan") or {}).get("candidates") or []

    def reclaim_move(self, delta: int) -> None:
        items = self.reclaim_candidates()
        if not items or self.reclaim is None:
            return
        self.reclaim["row"] = (self.reclaim["row"] + delta) % len(items)
        self.reclaim["armed"] = False

    def reclaim_toggle(self, index: int | None = None) -> None:
        items = self.reclaim_candidates()
        if not items or self.reclaim is None:
            return
        index = self.reclaim["row"] if index is None else index
        if not 0 <= index < len(items):
            return
        pane_id = items[index]["pane_id"]
        chosen: set[str] = self.reclaim["chosen"]
        if pane_id in chosen:
            chosen.discard(pane_id)
        else:
            chosen.add(pane_id)
        self.reclaim["row"] = index
        self.reclaim["armed"] = False

    def reclaim_select_all(self, select: bool) -> None:
        if self.reclaim is None:
            return
        self.reclaim["chosen"] = {entry["pane_id"] for entry in self.reclaim_candidates()} if select else set()
        self.reclaim["armed"] = False

    def reclaim_cycle_threshold(self) -> None:
        if self.reclaim is None:
            return
        thresholds = list(CLEANUP_THRESHOLDS)
        current = self.reclaim["idle"]
        index = thresholds.index(current) if current in thresholds else 0
        self.reclaim["idle"] = thresholds[(index + 1) % len(thresholds)]
        self.rescan_reclaim()

    def reclaim_confirm(self) -> None:
        """第一次 Enter 只是「上膛」，第二次才真正关闭 pane。"""
        if self.reclaim is None:
            return
        chosen = sorted(self.reclaim["chosen"])
        if not chosen:
            self.reclaim["note"] = "没有选中任何 pane"
            return
        if not self.reclaim["armed"]:
            self.reclaim["armed"] = True
            self.reclaim["note"] = f"再按一次 Enter 释放 {len(chosen)} 项"
            return
        self.reclaim["note"] = "正在释放…"
        self.draw()
        try:
            result = cleanup_apply(chosen, self.reclaim["idle"])
        except Exception as exc:  # noqa: BLE001
            self.reclaim["armed"] = False
            self.reclaim["note"] = f"释放失败 · {exc}"
            return
        freed = result.get("freed") or {}
        parts = [f"已释放 {freed.get('panes', 0)} 个 pane"]
        if freed.get("workspaces"):
            parts.append(f"回收 {freed['workspaces']} 个 workspace")
        if result.get("skipped"):
            parts.append(f"{len(result['skipped'])} 项已变活跃 · 跳过")
        if result.get("failed"):
            parts.append(f"{len(result['failed'])} 项失败 · {result['failed'][0].get('error', '')}")
        self.close_reclaim()
        self.refresh(force=True)
        self._locate(self.selected_id)
        self.flash(" · ".join(parts), 4.0)

    def launch_mo(self, dry_run: bool) -> bool:
        """全局磁盘清理交给 Mole：新开标签页跑 mo clean，跳过去并关掉看板。

        mo 是交互式工具（可能要 sudo、自带全屏 UI），必须待在真正的终端里，
        看板只负责把它开出来并把你送过去。返回 True 表示调用方关闭面板。
        """
        state = self.reclaim
        try:
            result = mo_clean(dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001
            if state is not None:
                state["note"] = str(exc)
            else:
                self.flash(str(exc), 4.0)
            return False
        try:
            focus_target(result["pane_id"])
        except Exception:  # noqa: BLE001 - 标签页已经起来了，跳转失败不算致命
            self.close_reclaim()
            self.refresh(force=True)
            self.flash(f"已在新标签页启动 {result['command']}", 4.0)
            return False
        return True

    # ---------- 鼠标 ----------

    def _card_at(self, my: int, mx: int) -> tuple[int, int] | None:
        for top, bottom, left, right, col, row in self.hit_cards:
            if top <= my <= bottom and left <= mx <= right:
                return col, row
        return None

    def _panel_at(self, my: int, mx: int) -> int | None:
        for top, bottom, left, right, col in self.hit_panels:
            if top <= my <= bottom and left <= mx <= right:
                return col
        return None

    def _button_at(self, my: int, mx: int) -> str | None:
        for top, bottom, left, right, name in self.hit_buttons:
            if top <= my <= bottom and left <= mx <= right:
                return name
        return None

    def _row_at(self, my: int, mx: int) -> int | None:
        for top, bottom, left, right, index in self.hit_rows:
            if top <= my <= bottom and left <= mx <= right:
                return index
        return None

    def click(self, my: int, mx: int, double: bool = False) -> bool:
        """单击选中、双击（或再点已选中的卡片）跳转；返回 True 表示调用方关闭面板。"""
        button = self._button_at(my, mx)
        if self.rename is not None:
            if button == "rename-save":
                self.rename_commit()
            elif button == "rename-cancel":
                self.close_rename()
            elif button and button.startswith("rename-"):
                self.rename_switch(button.removeprefix("rename-"))
            return False
        if button == "rename":
            self.open_rename()
            return False
        if button == "spawn-tab":
            return self.spawn("tab")
        if button == "spawn-pane":
            return self.spawn("pane")
        if button == "update":
            return self.check_update()
        if button == "reclaim":
            self.open_reclaim()
            return False
        if self.reclaim is not None:
            if button == "reclaim-apply":
                self.reclaim_confirm()
            elif button == "reclaim-cancel":
                self.close_reclaim()
            elif button == "reclaim-threshold":
                self.reclaim_cycle_threshold()
            elif button == "reclaim-all":
                self.reclaim_select_all(True)
            elif button == "reclaim-none":
                self.reclaim_select_all(False)
            elif button == "reclaim-mo-dry":
                return self.launch_mo(dry_run=True)
            elif button == "reclaim-mo-run":
                return self.launch_mo(dry_run=False)
            else:
                row = self._row_at(my, mx)
                if row is not None:
                    self.reclaim_toggle(row)
            return False
        target = self._card_at(my, mx)
        if target is None:
            column = self._panel_at(my, mx)
            if column is not None:
                self.choose_column(column)
            return False
        col, row = target
        now = time.time()
        repeat = self.last_click[1:] == (col, row) and now - self.last_click[0] <= 0.45
        already = list(self.pos[self.view]) == [col, row]
        self.last_click = (now, col, row)
        self.pos[self.view] = [col, row]
        self.selected_item()
        if double or repeat or already:
            return self.jump()
        return False

    # ---------- 绘制 ----------

    def draw_header(self, height: int, width: int) -> int:
        counts = self.snapshot.get("counts") or {}
        clock = self.snapshot.get("clock") or time.strftime("%H:%M:%S")
        margin = 2
        right_edge = width - margin

        _write(self.stdscr, 1, margin, "HERDR  /  MISSION CONTROL", attr=curses.color_pair(P_ACCENT) | curses.A_BOLD)
        view_name = "AGENT 看板" if self.view == "agents" else "窗口 / TERMINALS"
        subtitle = f"全局智能体调度 · {view_name}"
        current = self.version.get("current")
        if current:
            subtitle += f" · v{current}"
        _write(self.stdscr, 2, margin, subtitle, attr=curses.color_pair(P_TEXT) | curses.A_BOLD)
        live_text = f"● LIVE   {clock}"
        _right(self.stdscr, 1, right_edge, live_text, curses.color_pair(P_LIVE) | curses.A_BOLD)
        total_text = f"{counts.get('agents', 0)} AGENTS  ·  {counts.get('windows', 0)} WINDOWS"
        _right(self.stdscr, 2, right_edge, total_text, curses.color_pair(P_MUTED))

        stats = (
            ("blocked", counts.get("blocked", 0), "待确认"),
            ("working", counts.get("working", 0), "执行中"),
            ("settled", counts.get("idle", 0), "空闲"),
            ("window", counts.get("done", 0), "完成"),
            ("window", counts.get("windows", 0), "窗口"),
        )
        x = margin
        if width >= 78:
            for key, value, label in stats:
                pill = f" {int(value):02d}  {label} "
                _write(self.stdscr, 4, x, pill, attr=curses.color_pair(SELECT_PAIR[key]) | curses.A_BOLD)
                x += _width(pill) + 2
        else:
            summary = "  ".join(f"{label} {value}" for _, value, label in stats)
            _write(self.stdscr, 4, margin, summary, width - margin * 2, curses.color_pair(P_MUTED))

        # 行4 右侧：常驻动作按钮（鼠标可点，标签末尾是等效快捷键）
        buttons: list[tuple[str, str, int]] = [
            (" ⌫  释放闲置  X ", "reclaim", P_SELECT_ACCENT),
            (" ✎  重命名  E ", "rename", P_SELECT_ACCENT),
            (" ⬓  新 Pane  S ", "spawn-pane", P_SELECT_ACCENT),
            (" ＋  新 Tab  N ", "spawn-tab", P_SELECT_ACCENT),
        ]
        if self.version.get("state") == "outdated":
            # 有新版时最右边多一颗醒目的更新按钮，其余按钮整体左移
            buttons.insert(0, (f" ⬆  更新 v{self.version['latest']}  U ", "update", P_SELECT_WORKING))
        for label, name, pair in buttons:
            button_x = right_edge - _width(label)
            if button_x <= x + 2:
                break
            _write(self.stdscr, 4, button_x, label, attr=curses.color_pair(pair) | curses.A_BOLD)
            self.hit_buttons.append((4, 4, button_x, button_x + _width(label) - 1, name))
            right_edge = button_x - 2

        if self.error:
            message = f" 连接暂时中断 · 保留上次数据 · {self.error} "
            _right(self.stdscr, 4, right_edge, message, curses.color_pair(P_SELECT_BLOCKED) | curses.A_BOLD)

        _write(self.stdscr, 6, margin, "─" * max(0, width - margin * 2), width - margin * 2, curses.color_pair(P_BORDER))
        return 7

    def draw_panel(
        self,
        key: str,
        index: int,
        y: int,
        x: int,
        height: int,
        width: int,
        items: list[dict],
    ) -> None:
        if key == "window":
            english, chinese, hint = "TERMINALS", "窗口", "普通终端"
        else:
            _, english, chinese, hint = next(col for col in AGENT_COLUMNS if col[0] == key)
        active = index == self.pos[self.view][0] and self.view == "agents" or (
            self.view == "windows" and index == self.pos["windows"][0]
        )
        pair = COLUMN_PAIR[key]
        border_attr = curses.color_pair(pair if active else P_BORDER) | (curses.A_BOLD if active else 0)
        _box(self.stdscr, y, x, height, width, border_attr, heavy=active)
        self.hit_panels.append((y, y + height - 1, x, x + width - 1, index))

        number = f" {index + 1:02d} " if self.view == "agents" else " 00 "
        label = f"{number} {english} / {chinese} "
        label_attr = curses.color_pair(SELECT_PAIR[key]) | curses.A_BOLD if active else curses.color_pair(pair) | curses.A_BOLD
        _write(self.stdscr, y, x + 2, label, min(_width(label), width - 8), label_attr)
        count = f" {len(items):02d} "
        _write(self.stdscr, y, x + width - _width(count) - 2, count, attr=curses.color_pair(pair) | curses.A_BOLD)
        _write(self.stdscr, y + 1, x + 2, hint, width - 4, curses.color_pair(P_MUTED))

        cards_top = y + 3
        max_cards = max(1, (height - 5) // (CARD_HEIGHT + CARD_GAP))
        col, row = self.pos[self.view]
        start = 0
        if active and row >= max_cards:
            start = row - max_cards + 1
        visible = items[start : start + max_cards]
        has_scrollbar = len(items) > max_cards
        card_width = width - 5 if has_scrollbar else width - 4

        if not items:
            empty = "·  当前没有项目  ·"
            empty_y = min(y + height - 2, y + 5)
            empty_x = x + max(2, (width - _width(empty)) // 2)
            _write(self.stdscr, empty_y, empty_x, empty, width - 4, curses.color_pair(P_MUTED) | curses.A_DIM)
            return

        for offset, item in enumerate(visible):
            row_index = start + offset
            selected = active and row_index == row
            card_y = cards_top + offset * (CARD_HEIGHT + CARD_GAP)
            if card_y + CARD_HEIGHT >= y + height:
                break
            self.draw_card(item, card_y, x + 2, CARD_HEIGHT, card_width, selected)
            self.hit_cards.append(
                (card_y, card_y + CARD_HEIGHT - 1, x + 2, x + 1 + card_width, index, row_index)
            )

        if has_scrollbar:
            track_top = cards_top
            track_bottom = min(
                y + height - 2,
                cards_top + max_cards * (CARD_HEIGHT + CARD_GAP) - 1,
            )
            scroll_x = x + width - 2
            for ty in range(track_top, track_bottom + 1):
                _write(self.stdscr, ty, scroll_x, "│", 1, curses.color_pair(P_BORDER) | curses.A_DIM)
            thumb, thumb_start = _scrollbar_geometry(track_top, track_bottom, max_cards, len(items), start)
            for ty in range(thumb_start, thumb_start + thumb):
                _write(self.stdscr, ty, scroll_x, "┃", 1, curses.color_pair(pair) | curses.A_BOLD)

        if len(items) > max_cards:
            page = f" {start + 1}-{min(len(items), start + max_cards)} / {len(items)} "
            _write(self.stdscr, y + height - 1, x + width - _width(page) - 3, page, attr=curses.color_pair(pair))

    def draw_card(self, item: dict, y: int, x: int, height: int, width: int, selected: bool) -> None:
        key = _column_key(item)
        base_pair = SELECT_PAIR[key] if selected else P_CARD
        base_attr = curses.color_pair(base_pair)
        status_attr = curses.color_pair(SELECT_PAIR[key] if selected else CARD_STATUS_PAIR[key]) | curses.A_BOLD
        muted_attr = curses.color_pair(base_pair if selected else P_CARD_MUTED)

        for row in range(y, y + height):
            _write(self.stdscr, row, x, "", width, base_attr, pad=True)

        tl, tr, bl, br, hz, vt = ("┏", "┓", "┗", "┛", "━", "┃") if selected else ("╭", "╮", "╰", "╯", "─", "│")
        _write(self.stdscr, y, x, tl + hz * (width - 2) + tr, width, base_attr)
        for row in range(y + 1, y + height - 1):
            _write(self.stdscr, row, x, vt, 1, base_attr)
            _write(self.stdscr, row, x + width - 1, vt, 1, base_attr)
        _write(self.stdscr, y + height - 1, x, bl + hz * (width - 2) + br, width, base_attr)

        # 顶边角标：驱动框架（OMP / PI / …）弱化成边框上的小写标签
        badge = str(item.get("agent_label") or item.get("agent") or "").strip().lower()
        if badge and width >= 24:
            tag = f" {_fit(badge, max(4, width // 3))} "
            tag_x = x + width - 2 - _width(tag)
            if tag_x > x + 4:
                _write(self.stdscr, y, tag_x, tag, attr=muted_attr | (0 if selected else curses.A_DIM))

        # 行1：标题（卡片主角）+ 右侧工作区
        marker = "◆" if selected else ("●" if item.get("focused") else "○")
        workspace = item.get("workspace") or ""
        workspace = "" if workspace in {"—", "-"} else _fit(workspace, max(0, (width - 14) // 2))
        title_room = width - 6 - (_width(workspace) + 2 if workspace else 0)
        _write(self.stdscr, y + 1, x + 2, marker, 1, status_attr)
        _write(
            self.stdscr,
            y + 1,
            x + 4,
            item.get("title") or item.get("pane_id") or "Untitled",
            max(0, title_room),
            base_attr | curses.A_BOLD,
        )
        if workspace:
            _write(self.stdscr, y + 1, x + width - 2 - _width(workspace), workspace, attr=muted_attr)

        # 行2：进展阶段 + 执行标题
        phase = item.get("activity_phase") or "当前进展"
        activity_title = item.get("activity_title") or ""
        line2 = f"▸ {phase} · {_plain(activity_title)}" if activity_title else f"▸ {phase}"
        _write(self.stdscr, y + 2, x + 2, line2, width - 4, status_attr)

        # 行3：状态 / 工具 + pane
        status = item.get("status_label") or ""
        age = item.get("last_active_label") or item.get("quiet_label") or ""
        tool = item.get("activity_tool") or (item.get("family") or "")
        state_text = f"{status}{f' · {age}' if age else ''} · {tool.upper()}"
        _write(self.stdscr, y + 3, x + 2, state_text, width - 4, muted_attr)
        pane = item.get("pane_id") or ""
        pane_room = width - 5 - _width(_fit(state_text, width - 4))
        if pane_room > 4:
            _write(
                self.stdscr,
                y + 3,
                x + width - 2 - _width(_fit(pane, pane_room)),
                _fit(pane, pane_room),
                attr=muted_attr,
            )

    def draw_rename(self, height: int, width: int) -> None:
        """重命名面板：Pane 标题 / Tab 名称 / Workspace 名称，就地改，Esc 走人。"""
        state = self.rename
        if state is None:
            return
        item = self.find_item(state["pane_id"])
        if item is None:
            self.close_rename()
            return

        box_width = max(44, min(88, width - 6))
        box_height = 9
        x = max(1, (width - box_width) // 2)
        y = max(1, (height - box_height) // 2)
        base = curses.color_pair(P_CARD)
        muted = curses.color_pair(P_CARD_MUTED)
        accent = curses.color_pair(P_ACCENT) | curses.A_BOLD

        for row in range(y, y + box_height):
            _write(self.stdscr, row, x, "", box_width, base, pad=True)
        _box(self.stdscr, y, x, box_height, box_width, accent, heavy=True)
        _write(self.stdscr, y, x + 2, " RENAME  /  重命名 ", attr=accent)

        # 对象切换：三个可点的胶囊
        cursor_x = x + 2
        for kind in RENAME_KINDS:
            chip = f" {RENAME_LABELS[kind]} "
            on = kind == state["kind"]
            chip_attr = curses.color_pair(P_SELECT_ACCENT if on else P_CARD_MUTED) | curses.A_BOLD
            _write(self.stdscr, y + 1, cursor_x, chip, attr=chip_attr)
            self.hit_buttons.append((y + 1, y + 1, cursor_x, cursor_x + _width(chip) - 1, f"rename-{kind}"))
            cursor_x += _width(chip) + 1

        location = f"{item.get('workspace') or '—'}  ›  {item.get('tab') or '—'}  ›  {item.get('pane_id')}"
        _write(self.stdscr, y + 2, x + 2, location, box_width - 4, muted)

        # 输入框：光标处反显，长文本按光标位置右移窗口
        field_y = y + 4
        field_width = box_width - 6
        text = "".join(state["buffer"])
        cursor = state["cursor"]
        head = text[:cursor]
        while _width(head) > field_width - 1:
            head = head[1:]
        offset = cursor - len(head)
        shown = _fit(text[offset:], field_width)
        _write(self.stdscr, field_y, x + 2, " " * field_width, field_width, curses.color_pair(P_DETAIL))
        _write(self.stdscr, field_y, x + 3, shown, field_width - 1, curses.color_pair(P_DETAIL) | curses.A_BOLD)
        caret_x = x + 3 + _width(text[offset:cursor])
        caret_char = text[cursor] if cursor < len(text) else " "
        _write(self.stdscr, field_y, caret_x, caret_char, 2, curses.color_pair(P_DETAIL) | curses.A_REVERSE)

        if state["kind"] == "pane":
            hint = "留空保存 = 清除自定义标题，回落到终端标题"
        elif state["kind"] == "tab":
            hint = "保存时把当前 Pane 标题一起改成同名 · 名称不能为空"
        else:
            hint = "Workspace 名称不能为空"
        _write(self.stdscr, field_y + 1, x + 2, hint, box_width - 4, muted | curses.A_DIM)

        button_y = y + box_height - 2
        cancel = " 取消 Esc "
        cancel_x = x + box_width - 2 - _width(cancel)
        _write(self.stdscr, button_y, cancel_x, cancel, attr=curses.color_pair(P_CARD_MUTED) | curses.A_BOLD)
        self.hit_buttons.append((button_y, button_y, cancel_x, cancel_x + _width(cancel) - 1, "rename-cancel"))
        save = " 保存 ⏎ "
        save_x = cancel_x - 2 - _width(save)
        _write(self.stdscr, button_y, save_x, save, attr=curses.color_pair(P_SELECT_ACCENT) | curses.A_BOLD)
        self.hit_buttons.append((button_y, button_y, save_x, save_x + _width(save) - 1, "rename-save"))
        note = state.get("note") or ""
        if note:
            _write(self.stdscr, button_y, x + 2, note, max(0, save_x - x - 4), curses.color_pair(P_CARD_BLOCKED) | curses.A_BOLD)

    def draw_reclaim(self, height: int, width: int) -> None:
        """闲置回收确认面板：叠加在看板上方，不改变原有布局。"""
        state = self.reclaim
        if state is None:
            return
        scan = state.get("scan") or {}
        items = scan.get("candidates") or []
        protected = scan.get("protected") or []
        chosen: set[str] = state.get("chosen") or set()

        box_width = max(46, min(104, width - 6))
        box_height = max(12, min(height - 4, len(items) + 9))
        x = max(1, (width - box_width) // 2)
        y = max(1, (height - box_height) // 2)
        base = curses.color_pair(P_CARD)
        muted = curses.color_pair(P_CARD_MUTED)
        accent = curses.color_pair(P_ACCENT) | curses.A_BOLD

        for row in range(y, y + box_height):
            _write(self.stdscr, row, x, "", box_width, base, pad=True)
        _box(self.stdscr, y, x, box_height, box_width, accent, heavy=True)
        _write(self.stdscr, y, x + 2, " RECLAIM  /  释放闲置 ", attr=accent)

        idle = state["idle"]
        idle_label = CLEANUP_THRESHOLD_LABELS.get(idle, f"{idle // 60}m")
        chip = f" 预选 ≥ {idle_label}   T "
        chip_x = x + box_width - 2 - _width(chip)
        _write(self.stdscr, y + 1, chip_x, chip, attr=curses.color_pair(P_SELECT_WINDOW) | curses.A_BOLD)
        self.hit_buttons.append((y + 1, y + 1, chip_x, chip_x + _width(chip) - 1, "reclaim-threshold"))
        summary = f"候选 {len(items)}  ·  已选 {len(chosen)}  ·  受保护 {len(protected)}"
        _write(self.stdscr, y + 1, x + 2, summary, max(0, chip_x - x - 3), base | curses.A_BOLD)

        list_top = y + 3
        list_bottom = y + box_height - 5
        visible = max(1, list_bottom - list_top + 1)
        row_index = min(state.get("row", 0), max(0, len(items) - 1))
        start = state.get("start", 0)
        start = min(start, row_index)
        if row_index >= start + visible:
            start = row_index - visible + 1
        start = max(0, min(start, max(0, len(items) - visible)))
        state["start"] = start

        for offset, entry in enumerate(items[start : start + visible]):
            index = start + offset
            ry = list_top + offset
            active = index == row_index
            checked = entry["pane_id"] in chosen
            row_attr = curses.color_pair(P_SELECT_ACCENT) | curses.A_BOLD if active else base
            mark_attr = row_attr if active else curses.color_pair(P_CARD_SETTLED if checked else P_CARD_MUTED)
            meta_attr = row_attr if active else muted
            _write(self.stdscr, ry, x + 1, "", box_width - 2, row_attr, pad=True)
            _write(self.stdscr, ry, x + 1, "▸" if active else " ", 1, row_attr | curses.A_BOLD)
            _write(self.stdscr, ry, x + 3, "[✓]" if checked else "[ ]", 3, mark_attr | curses.A_BOLD)
            meta = f"{entry.get('workspace') or '—'} · {entry['pane_id']} · 静默 {entry.get('quiet_label') or '刚刚'}"
            meta = _fit(meta, max(0, box_width - 24))
            title_room = box_width - 11 - _width(meta)
            title = entry.get("title") or entry["pane_id"]
            if entry.get("risk") == "agent":
                title = f"⚠ {title}"
            _write(self.stdscr, ry, x + 7, title, max(0, title_room), row_attr | curses.A_BOLD)
            _write(self.stdscr, ry, x + box_width - 2 - _width(meta), meta, attr=meta_attr)
            self.hit_rows.append((ry, ry, x + 1, x + box_width - 2, index))

        if len(items) > visible:
            page = f" {start + 1}-{min(len(items), start + visible)} / {len(items)} "
            _write(self.stdscr, list_bottom + 1, x + box_width - _width(page) - 3, page, attr=muted)

        # 高亮行的解释：为什么可回收、关掉之后会连带释放什么
        detail_y = y + box_height - 4
        if items:
            entry = items[row_index]
            bits = [entry.get("reason") or "", entry.get("process") or ""]
            if entry.get("risk") == "agent":
                bits.append("会关闭该 Agent 会话")
            if entry.get("in_focused_tab"):
                bits.append("在当前标签页")
            if entry.get("last_in_workspace"):
                bits.append(f"连带释放 workspace「{entry.get('workspace')}」")
            elif entry.get("last_in_tab"):
                bits.append(f"连带释放标签页「{entry.get('tab')}」")
            detail = "↳ " + "  ·  ".join(bit for bit in bits if bit)
            _write(self.stdscr, detail_y, x + 2, detail, box_width - 4, curses.color_pair(P_CARD_WORKING))
        else:
            _write(
                self.stdscr,
                detail_y,
                x + 2,
                "没有可回收的 pane：活跃 Agent、当前聚焦 pane 和看板自身都会被保护。",
                box_width - 4,
                muted,
            )
        note = state.get("note") or ""
        if note:
            _write(self.stdscr, detail_y + 1, x + 2, note, box_width - 4, curses.color_pair(P_CARD_BLOCKED) | curses.A_BOLD)
        elif protected:
            summary_protected = "受保护 " + "  ·  ".join(
                f"{entry.get('title') or entry['pane_id']}（{entry.get('reason')}）" for entry in protected[:3]
            )
            if len(protected) > 3:
                summary_protected += f"  ·  +{len(protected) - 3}"
            _write(self.stdscr, detail_y + 1, x + 2, summary_protected, box_width - 4, muted | curses.A_DIM)

        # 底部按钮行
        button_y = y + box_height - 2
        cursor = x + 2
        mo_buttons = (
            (" 磁盘预览 d ", "reclaim-mo-dry", P_SELECT_SETTLED),
            (" 磁盘清理 D ", "reclaim-mo-run", P_SELECT_WINDOW),
        )
        buttons = [(" 全选 A ", "reclaim-all", P_SELECT_WINDOW), (" 清空 N ", "reclaim-none", P_SELECT_WINDOW)]
        if box_width >= 84:
            buttons += list(mo_buttons)
        for label, name, pair in buttons:
            _write(self.stdscr, button_y, cursor, label, attr=curses.color_pair(pair) | curses.A_BOLD)
            self.hit_buttons.append((button_y, button_y, cursor, cursor + _width(label) - 1, name))
            cursor += _width(label) + 2

        cancel = " 取消 Esc "
        cancel_x = x + box_width - 2 - _width(cancel)
        _write(self.stdscr, button_y, cancel_x, cancel, attr=curses.color_pair(P_CARD_MUTED) | curses.A_BOLD)
        self.hit_buttons.append((button_y, button_y, cancel_x, cancel_x + _width(cancel) - 1, "reclaim-cancel"))

        armed = bool(state.get("armed"))
        apply_label = f" 确认释放 {len(chosen)} 项 ⏎ " if armed else f" 释放选中 {len(chosen)} ⏎ "
        apply_attr = curses.color_pair(P_SELECT_BLOCKED if armed else P_SELECT_ACCENT) | curses.A_BOLD
        apply_x = cancel_x - 2 - _width(apply_label)
        if apply_x > cursor:
            _write(self.stdscr, button_y, apply_x, apply_label, attr=apply_attr)
            self.hit_buttons.append((button_y, button_y, apply_x, apply_x + _width(apply_label) - 1, "reclaim-apply"))

    def draw_detail(self, y: int, width: int, height: int) -> None:
        if height < 6:
            return
        margin = 2
        panel_width = width - margin * 2
        item = self.selected_item()
        _box(self.stdscr, y, margin, height, panel_width, curses.color_pair(P_BORDER))
        _write(self.stdscr, y, margin + 2, " SELECTED / 当前选中 ", attr=curses.color_pair(P_ACCENT) | curses.A_BOLD)
        if not item:
            _write(self.stdscr, y + 2, margin + 2, "当前没有项目", panel_width - 4, curses.color_pair(P_MUTED))
            return

        key = _column_key(item)
        status = item.get("status_label") or ""
        badge = str(item.get("agent_label") or "").strip().lower()
        tag = f"{badge}  ·  " if badge else ""
        status_x = margin + panel_width - 2 - _width(status)
        _write(self.stdscr, y + 1, status_x, status, attr=curses.color_pair(COLUMN_PAIR[key]) | curses.A_BOLD)
        if tag:
            _write(self.stdscr, y + 1, status_x - _width(tag), tag, attr=curses.color_pair(P_MUTED))
        title_room = max(0, status_x - _width(tag) - margin - 4)
        _write(
            self.stdscr,
            y + 1,
            margin + 2,
            item.get("title") or "",
            title_room,
            curses.color_pair(P_TEXT) | curses.A_BOLD,
        )

        phase = item.get("activity_phase") or "当前进展"
        activity = item.get("activity_title") or ""
        progress = f"▸ {phase}{f' · {_plain(activity)}' if activity else ''}"
        _write(self.stdscr, y + 2, margin + 2, progress, panel_width - 4, curses.color_pair(COLUMN_PAIR[key]) | curses.A_BOLD)

        location = "  ›  ".join(
            part for part in (item.get("workspace"), item.get("tab"), item.get("pane_id")) if part
        )
        quiet = item.get("quiet_label") or ""
        if quiet:
            location = f"{location}  ›  静默 {quiet}"
        _write(self.stdscr, y + 3, margin + 2, location, panel_width - 4, curses.color_pair(P_MUTED))
        output = item.get("last_output") or item.get("terminal_title") or "暂无最近输出"
        preview = _fit(f"↳ {_plain(output)}", panel_width - 4)
        _write(self.stdscr, y + 4, margin + 2, preview, panel_width - 4, curses.color_pair(P_CARD_MUTED))

    def draw_footer(self, y: int, width: int) -> None:
        if self.rename is not None:
            left = HELP_RENAME
            left_attr = curses.color_pair(P_ACCENT) | curses.A_BOLD
        elif self.reclaim is not None:
            left = HELP_RECLAIM
            left_attr = curses.color_pair(P_ACCENT) | curses.A_BOLD
        elif time.time() < self.message_until and self.message:
            left = self.message
            left_attr = curses.color_pair(P_ACCENT) | curses.A_BOLD
        else:
            left = HELP_AGENTS if self.view == "agents" else HELP_WINDOWS
            left_attr = curses.color_pair(P_MUTED)
        _write(self.stdscr, y, 2, left, width - 4, left_attr)
        right = "AUTO REFRESH  1s"
        _right(self.stdscr, y, width - 2, right, curses.color_pair(P_LIVE) | curses.A_BOLD)

    def draw(self) -> None:
        stdscr = self.stdscr
        stdscr.erase()
        self.hit_cards.clear()
        self.hit_panels.clear()
        self.hit_buttons.clear()
        self.hit_rows.clear()
        stdscr.bkgd(" ", curses.color_pair(P_BG))
        height, width = stdscr.getmaxyx()
        if height < 18 or width < 48:
            _write(stdscr, 1, 2, "HERDR MISSION CONTROL", width - 4, curses.color_pair(P_ACCENT) | curses.A_BOLD)
            _write(stdscr, 3, 2, "窗口太小，请放大 popup", width - 4, curses.color_pair(P_TEXT))
            _write(stdscr, height - 2, 2, "Q 退出", width - 4, curses.color_pair(P_MUTED))
            stdscr.refresh()
            return

        board_top = self.draw_header(height, width)
        detail_height = 6 if height >= 32 else 0
        footer_y = height - 2
        detail_y = footer_y - detail_height
        board_bottom = detail_y - 1 if detail_height else footer_y - 1
        panel_height = max(8, board_bottom - board_top)

        content_width = width - 4
        if self.view == "agents":
            keys = self.visible_agent_keys()
            visible = [(index, key, self.column_items(key)) for index, key in enumerate(keys)]
        else:
            visible = [(0, "window", self.window_items())]

        gap = 2
        count = len(visible)
        column_width = (content_width - gap * (count - 1)) // count
        for position, (index, key, items) in enumerate(visible):
            x = 2 + position * (column_width + gap)
            actual_width = column_width if position < count - 1 else width - 2 - x
            self.draw_panel(key, index, board_top, x, panel_height, actual_width, items)

        if detail_height:
            self.draw_detail(detail_y, width, detail_height)
        if self.reclaim is not None:
            self.draw_reclaim(height, width)
        if self.rename is not None:
            self.draw_rename(height, width)
        self.draw_footer(footer_y, width)
        stdscr.refresh()


def _init_colors() -> None:
    curses.curs_set(0)
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass

    rich = curses.COLORS >= 256
    bg = 235 if rich else -1
    card_bg = 237 if rich else -1
    blocked = 203 if rich else curses.COLOR_RED
    working = 221 if rich else curses.COLOR_YELLOW
    settled = 150 if rich else curses.COLOR_GREEN
    window = 117 if rich else curses.COLOR_CYAN
    text = 253 if rich else curses.COLOR_WHITE
    accent = 183 if rich else curses.COLOR_MAGENTA
    muted = 244 if rich else curses.COLOR_WHITE
    border = 239 if rich else curses.COLOR_WHITE
    dark = 235 if rich else curses.COLOR_BLACK

    pairs = {
        P_BLOCKED: (blocked, bg),
        P_WORKING: (working, bg),
        P_SETTLED: (settled, bg),
        P_WINDOW: (window, bg),
        P_TEXT: (text, bg),
        P_ACCENT: (accent, bg),
        P_MUTED: (muted, bg),
        P_BORDER: (border, bg),
        P_BG: (text, bg),
        P_CARD: (text, card_bg),
        P_CARD_MUTED: (muted, card_bg),
        P_SELECT_BLOCKED: (dark, blocked),
        P_SELECT_WORKING: (dark, working),
        P_SELECT_SETTLED: (dark, settled),
        P_SELECT_WINDOW: (dark, window),
        P_CARD_BLOCKED: (blocked, card_bg),
        P_CARD_WORKING: (working, card_bg),
        P_CARD_SETTLED: (settled, card_bg),
        P_CARD_WINDOW: (window, card_bg),
        P_DETAIL: (text, card_bg),
        P_LIVE: (settled, bg),
        P_SELECT_ACCENT: (dark, accent),
    }
    for pair_id, (foreground, background) in pairs.items():
        curses.init_pair(pair_id, foreground, background)


_CLICK_MASK = (
    curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED
)
_DOUBLE_CLICK = curses.BUTTON1_DOUBLE_CLICKED


def _enable_mouse() -> None:
    """开启左键上报；终端或 ncurses 不支持时静默降级为纯键盘操作。

    只开 ALL_MOUSE_EVENTS，由 ncurses 自己决定 X10 还是 SGR 上报协议：
    手动写 ESC[?1006h 会让 macOS 自带的 ncurses 5.7 收到自己读不懂的
    SGR 序列，鼠标反而彻底失灵。滚轮同理不做处理——5.7 没有 BUTTON5，
    下滚与鼠标移动共用同一个 bit，无法区分。
    """
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.mouseinterval(150)
    except curses.error:
        pass


def _handle_reclaim_key(board: Board, key) -> bool:
    """回收面板打开时接管键盘；返回 True 表示退出看板。Esc 返回后一切照旧。"""
    if key in ("\x1b", "q", "Q"):
        board.close_reclaim()
    elif key in ("\n", "\r"):
        board.reclaim_confirm()
    elif key in (" ", "x", "X"):
        board.reclaim_toggle()
    elif key in ("a", "A"):
        board.reclaim_select_all(True)
    elif key in ("n", "N"):
        board.reclaim_select_all(False)
    elif key in ("t", "T"):
        board.reclaim_cycle_threshold()
    elif key in ("r", "R"):
        board.rescan_reclaim()
    elif key == "d":
        return board.launch_mo(dry_run=True)
    elif key == "D":
        return board.launch_mo(dry_run=False)
    elif key in (curses.KEY_UP, "k"):
        board.reclaim_move(-1)
    elif key in (curses.KEY_DOWN, "j"):
        board.reclaim_move(1)
    elif key == curses.KEY_MOUSE:
        try:
            _, mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return False
        if bstate & _CLICK_MASK:
            return board.click(my, mx, double=bool(bstate & _DOUBLE_CLICK))
    return False


def _handle_rename_key(board: Board, key) -> None:
    """重命名面板打开时接管键盘：普通字符进输入框，Esc 取消，Enter 保存。"""
    if key == "\x1b":
        board.close_rename()
    elif key in ("\n", "\r"):
        board.rename_commit()
    elif key == "\t":
        board.rename_switch()
    elif key == curses.KEY_BTAB:
        board.rename_switch()
    elif key == curses.KEY_MOUSE:
        try:
            _, mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return
        if bstate & _CLICK_MASK:
            board.click(my, mx, double=bool(bstate & _DOUBLE_CLICK))
    else:
        board.rename_edit(key)


def main(stdscr: curses.window) -> None:
    _init_colors()
    _enable_mouse()
    stdscr.nodelay(True)
    stdscr.timeout(180)
    start_version_check()  # 缓存过期时后台查一次，第一帧不等网络
    board = Board(stdscr)
    board.refresh(force=True)
    board.selected_item()
    while True:
        board.refresh()
        board.draw()
        try:
            key = stdscr.get_wch()
        except curses.error:
            continue
        if board.reclaim is not None:
            if _handle_reclaim_key(board, key):
                break
            continue
        if board.rename is not None:
            _handle_rename_key(board, key)
            continue
        if key in ("q", "Q", "\x1b"):
            break
        if key in ("x", "X"):
            board.open_reclaim()
        elif key in ("e", "E"):
            board.open_rename()
        elif key in ("n", "N"):
            if board.spawn("tab"):
                break
        elif key == "s":
            if board.spawn("pane", direction="right"):
                break
        elif key == "S":
            if board.spawn("pane", direction="down"):
                break
        elif key in ("u", "U"):
            if board.check_update():
                break
        elif key in ("r", "R"):
            board.refresh(force=True)
            board.flash("数据已刷新")
        elif key in ("\n", "\r"):
            if board.jump():
                break
        elif key == "\t" or key == "v":
            board.toggle_view()
        elif key in (curses.KEY_LEFT, "h"):
            board.move(dcol=-1)
        elif key in (curses.KEY_RIGHT, "l"):
            board.move(dcol=1)
        elif key in (curses.KEY_UP, "k"):
            board.move(drow=-1)
        elif key in (curses.KEY_DOWN, "j"):
            board.move(drow=1)
        elif key in ("1", "2", "3", "4"):
            board.choose_column(int(key) - 1)
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except curses.error:
                continue
            if bstate & _CLICK_MASK:
                if board.click(my, mx, double=bool(bstate & _DOUBLE_CLICK)):
                    break
        elif key == curses.KEY_RESIZE:
            pass


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(main)
