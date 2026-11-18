"""The B2 freeze (spec 3.7 step 1; ruled by the owner 2026-11-18), no network.

The spec and the params must match the last entry of specs/phase2_freeze.json, so an edit after the freeze fails
here until it is logged as a re-freeze (allowed only before the first IS number) or handled as a non-bug change
under spec 3.7 step 7. The code-tree hash is recorded, not tested here: `loops/phase2_freeze.py check` recomputes
it (it needs git).

Run:  python -m unittest tests.test_phase2_freeze
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "loops"))

from phase2.params import PARAMS, params_hash, unset  # noqa: E402

RECORD = ROOT / "specs" / "phase2_freeze.json"
FIELDS = {"label", "ruled", "reason", "written", "spec_sha256", "params_file_sha256", "params_hash",
          "code_tree_sha256", "code_tree_files"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Freeze(unittest.TestCase):
    def setUp(self):
        self.entries = json.loads(RECORD.read_text())

    def test_the_record_is_well_formed(self):
        self.assertIsInstance(self.entries, list)
        self.assertGreaterEqual(len(self.entries), 1)
        self.assertEqual(self.entries[0]["label"], "B2")
        self.assertEqual(self.entries[0]["ruled"], "2026-11-18")
        for e in self.entries:
            self.assertEqual(set(e), FIELDS)
            for k in ("spec_sha256", "params_file_sha256", "code_tree_sha256"):
                self.assertRegex(e[k], r"^[0-9a-f]{64}$", k)
            self.assertRegex(e["params_hash"], r"^[0-9a-f]{16}$")
            self.assertGreater(e["code_tree_files"], 50)
            self.assertTrue(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-0[45]:00$", e["written"]), e["written"])

    def test_the_spec_matches_the_last_entry(self):
        self.assertEqual(sha(ROOT / "specs" / "phase2_spec.md"), self.entries[-1]["spec_sha256"],
                         "the spec changed after the freeze: log a re-freeze (before any IS number) or treat it "
                         "as a non-bug change (spec 3.7 step 7)")

    def test_the_params_match_the_last_entry(self):
        self.assertEqual(params_hash(PARAMS), self.entries[-1]["params_hash"])
        self.assertEqual(sha(ROOT / "loops" / "phase2" / "params.py"), self.entries[-1]["params_file_sha256"],
                         "params.py changed after the freeze: log a re-freeze (before any IS number) or treat it "
                         "as a non-bug change (spec 3.7 step 7)")

    def test_nothing_was_frozen_while_a_value_awaited_a_ruling(self):
        self.assertEqual(unset(PARAMS), [])


if __name__ == "__main__":
    unittest.main()
