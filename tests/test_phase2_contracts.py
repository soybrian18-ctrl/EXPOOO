"""Package-level contracts for loops/phase2 (spec sections 2 and 3.7), no network.

  * No orders possible: nothing in the package references an order-placing call.
  * OOS seal: the two unseal names appear only where the spec allows.
  * fills.py is pure: it cannot reach a clock, a file or the network.

Run:  python -m unittest tests.test_phase2_contracts
"""

from __future__ import annotations

import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "loops", "phase2")
SKIP_DIRS = {".git", ".venv", "venv", ".claude", "__pycache__", "node_modules", "logs"}   # .claude can hold worktree copies
UNSEALS = ("UNSEALED_BY_PICK", "KNOWN_ANSWER_REPLAY")
UNSEAL_VALUES = ("unsealed_by_pick", "known_answer_replay")   # a literal value would unseal just as well


def read(path: str) -> str:
    with open(path) as fh:
        return fh.read()


def package_modules() -> list[str]:
    return sorted(os.path.join(PKG, f) for f in os.listdir(PKG) if f.endswith(".py"))


def repo_python_files() -> list[str]:
    out = []
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        out += [os.path.join(folder, f) for f in files if f.endswith(".py")]
    return sorted(out)


def rel(path: str) -> str:
    return os.path.relpath(path, ROOT)


class NoOrdersPossible(unittest.TestCase):
    """Section 2: 'A test fails if the package references place_order, replace_order, cancel_order or
    order_executor.'"""

    FORBIDDEN = ("place_order", "replace_order", "cancel_order", "order_executor")

    def test_the_package_exists_and_is_scanned(self):
        self.assertIn(os.path.join(PKG, "fills.py"), package_modules())

    def test_the_package_never_references_an_order_placing_call(self):
        for path in package_modules():
            text = read(path)
            for word in self.FORBIDDEN:
                self.assertNotIn(word, text, f"{rel(path)} references {word}")


class OosSealContract(unittest.TestCase):
    """3.7 step 2. An unseal is a name a caller has to write down, so every use shows up here.

    When the backtest runner is written (B6) it joins NON_TEST_USERS with UNSEALED_BY_PICK only, in
    the same commit as the code that verifies the committed pick.
    """

    NON_TEST_USERS = {os.path.join("loops", "phase2", "fills.py"): set(UNSEALS)}     # where the names are defined
    TEST_USERS = {
        os.path.join("tests", "test_phase2_fills.py"): set(UNSEALS),                 # tests that the seal works
        os.path.join("tests", "test_phase2_known_answer.py"): {"KNOWN_ANSWER_REPLAY"},   # the one exemption
        os.path.join("tests", "test_phase2_contracts.py"): set(UNSEALS),             # this file
    }

    def test_unseal_names_appear_only_where_the_spec_allows(self):
        allowed = {**self.NON_TEST_USERS, **self.TEST_USERS}
        found = {}
        for path in repo_python_files():
            names = {n for n in UNSEALS if n in read(path)}
            if names:
                found[rel(path)] = names
        self.assertEqual(found, allowed)

    def test_unseal_values_appear_only_where_they_are_defined(self):
        found = sorted(rel(p) for p in repo_python_files() if any(v in read(p) for v in UNSEAL_VALUES))
        self.assertEqual(found, [os.path.join("loops", "phase2", "fills.py"), os.path.join("tests", "test_phase2_contracts.py")])

    def test_the_seal_is_the_default(self):
        tree = ast.parse(read(os.path.join(PKG, "fills.py")))
        defaults = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in ("step", "run", "evaluate_at_cutoff", "close_at_mark"):
                kw = dict(zip((a.arg for a in node.args.kwonlyargs), node.args.kw_defaults))
                defaults[node.name] = kw["seal"].id if isinstance(kw.get("seal"), ast.Name) else None
        self.assertEqual(defaults, {"step": "SEALED", "run": "SEALED", "evaluate_at_cutoff": "SEALED",
                                    "close_at_mark": "SEALED"})


class FillsIsPure(unittest.TestCase):
    """Section 2: everything that decides a fill or an exit is a pure function."""

    ALLOWED_IMPORTS = {"__future__", "datetime", "functools", "math", "dataclasses", "typing", "params", "known_answer"}

    def setUp(self):
        self.tree = ast.parse(read(os.path.join(PKG, "fills.py")))

    def test_the_known_answer_table_is_plain_data(self):
        tree = ast.parse(read(os.path.join(PKG, "known_answer.py")))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, {"__future__", "datetime", "typing"})
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)])       # a table, no logic

    def test_fills_imports_nothing_that_reaches_a_clock_a_file_or_the_network(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, self.ALLOWED_IMPORTS)
        self.assertIn("params", imported)

    def test_fills_never_reads_the_clock_or_touches_a_file(self):
        called = {n.func.id for n in ast.walk(self.tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        attributes = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(called & {"open", "print", "input", "exec", "eval", "__import__"})
        self.assertFalse(attributes & {"now", "today", "utcnow", "time", "environ"})


if __name__ == "__main__":
    unittest.main()
