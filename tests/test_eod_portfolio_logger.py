"""Regression test for the EOD portfolio logger's write-verification stage.

Run either of:

    python -m unittest tests.test_eod_portfolio_logger
    python tests/test_eod_portfolio_logger.py

No network or credentials required -- loop_common helpers are patched and the
history file is crafted on disk.

Covers the 2026-08-12 crash: Stage 4 seeks to a byte offset in
logs/portfolio_history.txt to read the tail, and that offset can land mid-way
through a multi-byte UTF-8 character (box-drawing output), which raised
UnicodeDecodeError in text mode. The read is now binary with errors="replace".
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "loops"))

import loop_common as lc  # noqa: E402
import eod_portfolio_logger as loop  # noqa: E402

# 200 box-drawing chars = 600 bytes of 3-byte UTF-8 sequences. Stage 4 seeks
# to size_before - 256, and 344 % 3 == 2, so the seek lands on a continuation
# byte -- the exact geometry that crashed a text-mode read on 2026-08-12.
_MULTIBYTE_HISTORY = "─" * 200


class EodLoggerVerifyTailTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.logs_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.log_lines = []

        patches = {
            "LOGS_DIR": self.logs_dir,
            "ensure_logs_dir": lambda: self.logs_dir,
            "append_log": lambda _f, msg: self.log_lines.append(msg),
            "notify": lambda *a, **k: True,
            "install_clean_exit": lambda _finalize: None,
            "resolve_token_path": lambda: Path("unused_token.json"),
            "validate_token": lambda *a, **k: lc.TokenCheck(True, lc.HEALTHY, 1.0, "ok"),
            "run_subprocess": lambda *a, **k: lc.SubprocessResult(
                0, "│ AAPL │ stub row │\n", "", False, 0.5
            ),
        }
        for name, value in patches.items():
            patcher = mock.patch.object(lc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.hist_path = self.logs_dir / loop.LOOP_CONFIG["HISTORY_FILE"]

    def test_verify_survives_seek_into_multibyte_character(self):
        self.hist_path.write_text(_MULTIBYTE_HISTORY, encoding="utf-8")
        seek_offset = self.hist_path.stat().st_size - 256
        self.assertNotEqual(seek_offset % 3, 0, "offset must land mid-character")

        exit_code = loop.main()

        self.assertEqual(exit_code, loop.EXIT_OK)
        self.assertTrue(
            any("result=snapshot_saved" in line for line in self.log_lines),
            f"expected snapshot_saved, got: {self.log_lines}",
        )
        tail = self.hist_path.read_text(encoding="utf-8")
        self.assertIn("===== END SNAPSHOT", tail)

    def test_verify_ok_on_empty_history(self):
        exit_code = loop.main()

        self.assertEqual(exit_code, loop.EXIT_OK)
        self.assertTrue(
            any("result=snapshot_saved" in line for line in self.log_lines),
            f"expected snapshot_saved, got: {self.log_lines}",
        )


if __name__ == "__main__":
    unittest.main()
