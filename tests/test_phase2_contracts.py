"""Package-level contracts for loops/phase2 (spec sections 2 and 3.7), no network.

  * No orders possible: nothing in the package references an order-placing call.
  * OOS seal: the two unseal names appear only where the spec allows.
  * fills.py is pure: it cannot reach a clock, a file or the network.

Run:  python -m unittest tests.test_phase2_contracts
"""

from __future__ import annotations

import ast
import io
import os
import re
import unicodedata
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "loops", "phase2")
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules"}
SKIP_PATHS = {os.path.join(".claude", "worktrees")}           # worktree copies of the repo itself
SCRIPT_EXTS = {".py", ".sh", ".bash", ".zsh", ".command", ".js", ".mjs", ".cjs", ".ts"}
MAX_SCAN_BYTES = 2_000_000
UNSEALS = ("UNSEALED_BY_PICK", "KNOWN_ANSWER_REPLAY")
# Names inside fills.py that would let a caller step around the seal.
PRIVATE = ("_check_seal", "_is_known_answer", "_entry_session", "_held_session", "_oos_window", "_Seal", "_SEALS",
           "_SPEC_OOS_WINDOW", "_KNOWN_ANSWER_RECORDS", "_REPLAY_TARGET_MULT")
TAMPERING = ("__kwdefaults__", "__defaults__", "object.__setattr__", "__globals__", "object.__getattribute__",
             "import_module", "attrgetter", "getmembers")
# Calls and attributes that look a module up by a computed name.
LOOKUPS = ("getattr", "vars", "hasattr", "setattr", "delattr")
MODULE_DICTS = ("__dict__", "__getattribute__")


def read(path: str) -> str:
    """File text, NFKC-normalized the way Python normalizes identifiers (so look-alike letters match)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return unicodedata.normalize("NFKC", fh.read())


def read_raw(path: str) -> str:
    """File text as written, for ast.parse: the parser normalizes identifiers itself, and NFKC would break a string
    literal that holds a full-width quote."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def package_modules() -> list[str]:
    return sorted(os.path.join(PKG, f) for f in os.listdir(PKG) if f.endswith(".py"))


def is_secrets_file(name: str) -> bool:
    """.env and .env.* hold the API keys and contacts. The scan never opens them; they are never scripts."""
    return name == ".env" or name.startswith(".env.")


def scanned_files() -> list[str]:
    """The repo's files with a code extension, and its extensionless files that start with #!, up to MAX_SCAN_BYTES
    each. A .env or .env.* file is never opened."""
    out = []
    for folder, dirs, files in os.walk(ROOT):
        here = os.path.relpath(folder, ROOT)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and os.path.normpath(os.path.join(here, d)) not in SKIP_PATHS]
        for f in files:
            if is_secrets_file(f):
                continue
            path = os.path.join(folder, f)
            if not os.path.isfile(path) or os.path.getsize(path) > MAX_SCAN_BYTES:
                continue
            ext = os.path.splitext(f)[1]
            if ext in SCRIPT_EXTS:
                out.append(path)
            elif ext == "":
                with open(path, "rb") as fh:
                    if fh.read(2) == b"#!":
                        out.append(path)
    return sorted(out)


def rel(path: str) -> str:
    return os.path.relpath(path, ROOT)


def computed_fills_lookups(src: str) -> list[str]:
    """Places in ``src`` that reach into the fills module by a computed name: getattr, vars, hasattr, setattr or
    delattr applied to a name an import binds to it ('from phase2 import fills [as F]', 'from . import fills',
    'import phase2.fills [as F]'), a read of its __dict__ or __getattribute__, or a star import of it. It is
    conservative: any 'from X import fills' and any attribute named fills count as the fills module. A later
    alias (G = F), builtins.getattr, sys.modules and similar routes are not seen."""
    tree = ast.parse(src)
    aliases = set()
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            aliases |= {a.asname or a.name for a in node.names if a.name == "fills"}
            if (node.module or "").split(".")[-1] == "fills" and any(a.name == "*" for a in node.names):
                hits.append(f"line {node.lineno}: import *")
        elif isinstance(node, ast.Import):
            aliases |= {a.asname for a in node.names if a.asname and a.name.split(".")[-1] == "fills"}

    def is_fills(node: ast.AST) -> bool:
        return (isinstance(node, ast.Name) and node.id in aliases) or (isinstance(node, ast.Attribute)
                                                                       and node.attr == "fills")

    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in LOOKUPS
                and node.args and is_fills(node.args[0])):
            hits.append(f"line {node.lineno}: {node.func.id}")
        elif isinstance(node, ast.Attribute) and node.attr in MODULE_DICTS and is_fills(node.value):
            hits.append(f"line {node.lineno}: {node.attr}")
    return hits


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
    """3.7 step 2. The unseals are objects compared by identity, so a use has to reach them by name. This test
    pins every place a scanned repo file writes either name, file by file and count by count, and fails a
    lookup of the fills module by a computed name (getattr, vars, __dict__) outside fills.py. It cannot see code
    outside the repo, or every dynamic route inside it: for UNSEALED_BY_PICK the backtest runner's check of the
    committed pick is the real guard.

    When the backtest runner is written (B6) it joins USES with UNSEALED_BY_PICK only, in the same commit
    as the code that verifies the committed pick. A new test that uses an unseal updates its count here.
    """

    USES = {   # file -> (UNSEALED_BY_PICK, KNOWN_ANSWER_REPLAY)
        os.path.join("loops", "phase2", "fills.py"): (6, 6),
        os.path.join("tests", "test_phase2_fills.py"): (4, 7),
        os.path.join("tests", "test_phase2_known_answer.py"): (0, 7),
        os.path.join("tests", "test_phase2_contracts.py"): (4, 2),
    }

    def test_every_use_of_an_unseal_is_pinned(self):
        found = {}
        for path in scanned_files():
            text = read(path)
            counts = tuple(text.count(n) for n in UNSEALS)
            if any(counts):
                found[rel(path)] = counts
        self.assertEqual(found, self.USES)

    def test_nothing_outside_fills_reaches_around_the_seal(self):
        fills_path = os.path.join("loops", "phase2", "fills.py")
        this_file = os.path.join("tests", "test_phase2_contracts.py")
        offenders = []
        for path in scanned_files():
            if rel(path) in (fills_path, this_file):
                continue
            text = read(path)
            offenders += [f"{rel(path)}: {name}" for name in PRIVATE + TAMPERING
                          if re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", text)]
        self.assertEqual(offenders, [])

    def test_the_repo_has_no_symlinked_directories(self):
        links = []
        for folder, dirs, _ in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            links += [rel(os.path.join(folder, d)) for d in dirs if os.path.islink(os.path.join(folder, d))]
        self.assertEqual(links, [])

    def test_nothing_outside_fills_looks_the_fills_module_up_by_a_computed_name(self):
        """getattr(fills, 'UNSEALED' + '_BY_PICK') would reach an unseal without writing its name."""
        fills_path = os.path.join("loops", "phase2", "fills.py")
        offenders = []
        for path in scanned_files():
            if path.endswith(".py") and rel(path) != fills_path:
                offenders += [f"{rel(path)}: {hit}" for hit in computed_fills_lookups(read_raw(path))]
        self.assertEqual(offenders, [])

    def test_the_computed_lookup_scan_catches_the_plain_routes(self):
        name = "'UNSEALED' + '_BY_PICK'"
        caught = [f"from phase2 import fills as F\nS = getattr(F, {name})",
                  f"from phase2 import fills\nS = vars(fills)[{name}]",
                  f"from . import fills\nS = fills.__dict__[{name}]",
                  f"import phase2.fills as F\nok = hasattr(F, {name})",
                  f"import phase2.fills\nS = getattr(phase2.fills, {name})",
                  "from phase2.fills import *"]
        for src in caught:
            with self.subTest(src=src):
                self.assertTrue(computed_fills_lookups(src))
        plain = "from phase2 import fills as F\nF.step(o, s, b, breadth_ok=True, params=P)\nx = getattr(o, 'state')\n"
        self.assertEqual(computed_fills_lookups(plain), [])

    def test_the_scan_never_opens_a_secrets_file(self):
        """The scan reads the first bytes of extensionless files to find #! scripts. It never opens .env or a .env.*
        file and never scans one, even with a script's extension or a #! line. The walk is simulated, so no file
        named .env is created."""
        names = [".env", ".env.local", ".env.sh", ".env.py", "tool"]
        self.assertEqual([n for n in names if is_secrets_file(n)], names[:4])
        self.assertFalse([n for n in ("env.py", "dotenv.py", "x.env", "tool") if is_secrets_file(n)])
        opened = []

        def fake_open(path, *args, **kwargs):
            opened.append(os.path.basename(str(path)))
            return io.BytesIO(b"#!/bin/sh\n")

        with mock.patch("os.walk", return_value=[(ROOT, [], names)]), mock.patch("os.path.isfile", return_value=True), \
                mock.patch("os.path.getsize", return_value=10), mock.patch("builtins.open", fake_open):
            found = [os.path.basename(p) for p in scanned_files()]
        self.assertEqual((found, opened), (["tool"], ["tool"]))

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
