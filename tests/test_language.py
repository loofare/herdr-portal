"""The English operator board translates UI copy, never agent-authored content."""

import importlib
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "board"))
import collect  # noqa: E402
import tui  # noqa: E402

HAN = re.compile(r"[\u4e00-\u9fff]")


class Screen:
    def __init__(self):
        self.text = []

    def getmaxyx(self):
        return 43, 129

    def erase(self):
        self.text.clear()

    def bkgd(self, *args):
        pass

    def addstr(self, y, x, text, attr):
        self.text.append(text)

    def refresh(self):
        pass


def render(locale):
    with patch.dict(os.environ, {"HERDR_PORTAL_LANG": locale}):
        importlib.reload(collect)
        importlib.reload(tui)
        screen = Screen()
        with patch.object(tui.curses, "color_pair", return_value=0):
            board = tui.Board(screen)
            board.pos["agents"] = [0, 0]
            board.snapshot = {
                "counts": {"agents": 1, "working": 1, "windows": 0},
                "columns": {
                    "blocked": [],
                    "working": [{"pane_id": "w1:p1", "title": "Worker", "workspace": "omhq",
                                 "activity_phase": collect.build_activity({}, "working", True, "Pi", "Pi")["phase"],
                                 "status_label": collect.STATUS_META["working"]["label"],
                                 "activity_title": "Testing", "last_output": "Agent-authored output"}],
                    "settled": [],
                },
            }
            board.draw()
            return "\n".join(screen.text), board, screen


class LanguageTest(unittest.TestCase):
    def test_english_operator_board_and_chinese_override(self):
        english, _, _ = render("en")
        self.assertFalse(HAN.search(english), english)
        self.assertIn("RUNNING / Running", english)
        self.assertIn("Q Quit", english)
        chinese, _, _ = render("zh")
        self.assertIn("执行中", chinese)

    def test_english_host_locale_needs_no_manual_setting(self):
        with patch.dict(os.environ, {"LANG": "en_US.UTF-8"}, clear=True):
            importlib.reload(collect)
            importlib.reload(tui)
            self.assertEqual(collect.STATUS_META["idle"]["label"], "Idle")
            self.assertIn("Q Quit", tui.HELP_AGENTS)

    def test_english_rename_and_reclaim_controls(self):
        _, board, screen = render("en")
        board.rename = {"pane_id": "w1:p1", "kind": "pane", "buffer": [], "cursor": 0}
        with patch.object(tui.curses, "color_pair", return_value=0):
            board.draw()
        self.assertFalse(HAN.search("\n".join(screen.text)), "rename dialog has Chinese UI")
        board.rename = None
        board.reclaim = {"idle": 300, "scan": {"candidates": [], "protected": []}, "chosen": set()}
        with patch.object(tui.curses, "color_pair", return_value=0):
            board.draw()
        self.assertFalse(HAN.search("\n".join(screen.text)), "reclaim dialog has Chinese UI")

    def test_rename_validation_and_update_tab_stay_english(self):
        render("en")
        with self.assertRaisesRegex(ValueError, "Tab name cannot be empty"):
            collect.rename_target("tab", "w1:t1", "")
        self.assertFalse(HAN.search(collect.update_plan()["label"]))
        self.assertEqual(collect.classify_window({"label": "vim"}), ("editor", "Editor"))

    def test_user_output_is_not_translated(self):
        _, board, screen = render("en")
        board.snapshot["columns"]["working"][0]["last_output"] = "用户输出"
        with patch.object(tui.curses, "color_pair", return_value=0):
            board.draw()
        self.assertIn("用户输出", "\n".join(screen.text))


if __name__ == "__main__":
    unittest.main()
