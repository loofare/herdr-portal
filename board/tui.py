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

from collect import collect_or_error, focus_target  # noqa: E402

AGENT_COLUMNS = (
    ("blocked", "ACTION", "待确认", "等待你确认 / 输入"),
    ("working", "RUNNING", "执行中", "正在运行"),
    ("settled", "SETTLED", "已就绪", "空闲 / 完成"),
)

HELP_AGENTS = "↑↓ 选择  ←→ 切列  Enter 跳转  Tab 窗口  R 刷新  Q 退出"
HELP_WINDOWS = "↑↓←→ 选择  Enter 跳转  Tab 返回  R 刷新  Q 退出"
CARD_HEIGHT = 6
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

    # ---------- 数据 ----------

    def column_items(self, key: str) -> list[dict]:
        return list((self.snapshot.get("columns") or {}).get(key) or [])

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

    def flash(self, message: str, duration: float = 2.2) -> None:
        self.message = message
        self.message_until = time.time() + duration

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

    # ---------- 绘制 ----------

    def draw_header(self, height: int, width: int) -> int:
        counts = self.snapshot.get("counts") or {}
        clock = self.snapshot.get("clock") or time.strftime("%H:%M:%S")
        margin = 2
        right_edge = width - margin

        _write(self.stdscr, 1, margin, "HERDR  /  MISSION CONTROL", attr=curses.color_pair(P_ACCENT) | curses.A_BOLD)
        view_name = "AGENT 看板" if self.view == "agents" else "窗口 / TERMINALS"
        _write(self.stdscr, 2, margin, f"全局智能体调度 · {view_name}", attr=curses.color_pair(P_TEXT) | curses.A_BOLD)
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

        # 行1：徽标 + 工作区
        badge = item.get("agent_label") or item.get("agent") or "?"
        workspace = item.get("workspace") or "—"
        marker = "◆" if selected else ("●" if item.get("focused") else "○")
        left = f" {marker} {badge} "
        _write(self.stdscr, y + 1, x + 1, left, width - 2, status_attr)
        workspace_room = width - 3 - _width(left)
        if workspace_room > 3:
            _write(
                self.stdscr,
                y + 1,
                x + width - 2 - _width(_fit(workspace, workspace_room)),
                _fit(workspace, workspace_room),
                attr=muted_attr,
            )

        # 行2：标题
        title = item.get("title") or item.get("pane_id") or "Untitled"
        _write(self.stdscr, y + 2, x + 2, title, width - 4, base_attr | curses.A_BOLD)

        # 行3：进展阶段 + 执行标题
        phase = item.get("activity_phase") or "当前进展"
        activity_title = item.get("activity_title") or ""
        line3 = f"▸ {phase} · {_plain(activity_title)}" if activity_title else f"▸ {phase}"
        _write(self.stdscr, y + 3, x + 2, line3, width - 4, status_attr)

        # 行4：状态/工具 + pane
        status = item.get("status_label") or ""
        age = item.get("last_active_label") or ""
        tool = item.get("activity_tool") or (item.get("family") or "")
        state_text = f"{status}{f' · {age}' if age else ''} · {tool.upper()}"
        _write(self.stdscr, y + 4, x + 2, state_text, width - 4, muted_attr)
        pane = item.get("pane_id") or ""
        pane_room = width - 5 - _width(_fit(state_text, width - 4))
        if pane_room > 4:
            _write(
                self.stdscr,
                y + 4,
                x + width - 2 - _width(_fit(pane, pane_room)),
                _fit(pane, pane_room),
                attr=muted_attr,
            )

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
        badge = item.get("agent_label") or "WINDOW"
        status = item.get("status_label") or ""
        _write(self.stdscr, y + 1, margin + 2, f"{badge}  /  {status}", panel_width - 4, curses.color_pair(COLUMN_PAIR[key]) | curses.A_BOLD)
        _write(self.stdscr, y + 2, margin + 2, item.get("title") or "", panel_width - 4, curses.color_pair(P_TEXT) | curses.A_BOLD)

        phase = item.get("activity_phase") or "当前进展"
        activity = item.get("activity_title") or ""
        progress = f"▸ {phase}{f' · {_plain(activity)}' if activity else ''}"
        _write(self.stdscr, y + 3, margin + 2, progress, panel_width - 4, curses.color_pair(COLUMN_PAIR[key]) | curses.A_BOLD)

        location = "  ›  ".join(
            part for part in (item.get("workspace"), item.get("tab"), item.get("pane_id")) if part
        )
        _write(self.stdscr, y + 4, margin + 2, location, panel_width - 4, curses.color_pair(P_MUTED))
        output = item.get("last_output") or item.get("terminal_title") or "暂无最近输出"
        preview = _fit(f"↳ {_plain(output)}", panel_width - 4)
        _write(self.stdscr, y + 5, margin + 2, preview, panel_width - 4, curses.color_pair(P_CARD_MUTED))

    def draw_footer(self, y: int, width: int) -> None:
        if time.time() < self.message_until and self.message:
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
        stdscr.bkgd(" ", curses.color_pair(P_BG))
        height, width = stdscr.getmaxyx()
        if height < 18 or width < 48:
            _write(stdscr, 1, 2, "HERDR MISSION CONTROL", width - 4, curses.color_pair(P_ACCENT) | curses.A_BOLD)
            _write(stdscr, 3, 2, "窗口太小，请放大 popup", width - 4, curses.color_pair(P_TEXT))
            _write(stdscr, height - 2, 2, "Q 退出", width - 4, curses.color_pair(P_MUTED))
            stdscr.refresh()
            return

        board_top = self.draw_header(height, width)
        detail_height = 7 if height >= 32 else 0
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
    }
    for pair_id, (foreground, background) in pairs.items():
        curses.init_pair(pair_id, foreground, background)


def main(stdscr: curses.window) -> None:
    _init_colors()
    stdscr.nodelay(True)
    stdscr.timeout(180)
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
        if key in ("q", "Q", "\x1b"):
            break
        if key in ("r", "R"):
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
        elif key == curses.KEY_RESIZE:
            pass


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(main)
