"""Package-level contracts for loops/phase2 (spec sections 2 and 3.7), no network.

  * No orders possible: nothing in the package references an order-capable call (schwab-py's order verbs, its
    private write requests and a client's raw HTTP session, Alpaca's TradingClient, its order verbs and the module
    that builds it, the September executor), and no other script-like file in the repo does either, outside the
    files pinned here with a count per name (review S1, S2). A new runner outside the package is covered without
    editing a list, for the names listed here.
  * Only a wrapped client: no module in the package references config, build_client or load_settings, can
    construct a Schwab or Alpaca client, imports anything outside an allowlist (the standard-library modules it
    uses, phase2, technicals for compute_levels and three constants, httpx for the symbol directory's one GET),
    names a reader of the token or of .env, imports by a computed name, runs another program, looks an attribute
    up by name outside the pinned places, or reaches into a function's closure, code or globals or into a caller's
    frame (MarketData's three functions are closures over the runner's client). Runners outside the package build
    the client and pass in the wrapper (review S3, S4, S5). The package scans include subfolders.
  * OOS seal: the two unseal names appear only where the spec allows, in every script-like file of the repo
    (notebooks, makefiles and launchd plists included); inside fills.py, by the AST, only in their own
    assignments, the seal registry and _check_seal. No public fills function names one, only step reaches the
    bar-reading transitions, and only the transitions (and Bar itself) read a bar's prices (review S7).
  * fills.py is pure: it cannot reach a clock, a file or the network.

Run:  python -m unittest tests.test_phase2_contracts
"""

from __future__ import annotations

import ast
import collections
import io
import os
import re
import tempfile
import unicodedata
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "loops", "phase2")
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules"}
SKIP_PATHS = {os.path.join(".claude", "worktrees")}           # worktree copies of the repo itself
# Script-like files, matched whatever the case (macOS file systems ignore case). Notebooks, makefiles and launchd
# plists run code too (review S7). There is no size limit: a large notebook is scanned like any other file.
SCRIPT_EXTS = {".py", ".sh", ".bash", ".zsh", ".command", ".js", ".mjs", ".cjs", ".ts", ".ipynb", ".mk", ".plist"}
SCRIPT_NAMES = {"makefile", "gnumakefile"}                    # Makefile, makefile, GNUmakefile
UNSEALS = ("UNSEALED_BY_PICK", "KNOWN_ANSWER_REPLAY")
SEAL_REGISTRY = "_SEALS"                                      # fills.py's tuple of the three seals
# Names inside fills.py that would let a caller step around the seal.
PRIVATE = ("_check_seal", "_is_known_answer", "_entry_session", "_held_session", "_oos_window", "_Seal", "_SEALS",
           "_SPEC_OOS_WINDOW", "_KNOWN_ANSWER_RECORDS", "_REPLAY_TARGET_MULT")
TAMPERING = ("__kwdefaults__", "__defaults__", "object.__setattr__")
# Calls and attributes that look a module up by a computed name.
LOOKUPS = ("getattr", "vars", "hasattr", "setattr", "delattr")
MODULE_DICTS = ("__dict__", "__getattribute__")


def read(path: str) -> str:
    """File text, NFKC-normalized the way Python normalizes identifiers (so look-alike letters match)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return unicodedata.normalize("NFKC", fh.read())


def package_files(pkg: str = PKG) -> list[str]:
    """Every file under the package, subfolders included, caches skipped (integration check, gap C: a module in
    loops/phase2/sub/ must not escape the scans)."""
    out = []
    for folder, dirs, files in os.walk(pkg):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        out += [os.path.join(folder, f) for f in files]
    return sorted(out)


def package_modules(pkg: str = PKG) -> list[str]:
    return [p for p in package_files(pkg) if p.endswith(".py")]


def is_secrets_file(name: str) -> bool:
    """.env and .env.* hold the API keys and contacts. The scan never opens them; they are never scripts."""
    return name == ".env" or name.startswith(".env.")


def scanned_files(root: str = ROOT) -> list[str]:
    """Every script-like file under ``root``: code by extension, a makefile by name, or any other extensionless
    file that starts with #!. A secrets file is never opened."""
    out = []
    for folder, dirs, files in os.walk(root):
        here = os.path.relpath(folder, root)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and os.path.normpath(os.path.join(here, d)) not in SKIP_PATHS]
        for f in files:
            if is_secrets_file(f):
                continue
            path = os.path.join(folder, f)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext in SCRIPT_EXTS or f.lower() in SCRIPT_NAMES:
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
    delattr applied to a name bound to it ('from phase2 import fills [as F]', 'from . import fills',
    'import phase2.fills [as F]', or the attribute phase2.fills), a read of its __dict__ or __getattribute__, or
    a star import of it."""
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


def word(name: str) -> str:
    """A regex for ``name`` as a whole identifier."""
    return r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])"


class NoOrdersPossible(unittest.TestCase):
    """Section 2: 'A test fails if the package references place_order, replace_order, cancel_order or
    order_executor.' The list also carries what that sentence misses (review S2): Alpaca's TradingClient, its order
    verbs and alpaca_account, which builds it, and schwab-py's private write requests and a client's raw HTTP
    session, which a client reached through a closure could use. The repo-wide scan (review S1) reads every
    script-like file, so a runner outside the package (B5's nightly, a bars.py builder) is covered without anyone
    editing a list, for the names listed here."""

    FORBIDDEN = ("place_order", "replace_order", "cancel_order", "order_executor",              # schwab-py; executor
                 "submit_order", "close_position", "close_all_positions", "exercise_options_position",
                 "alpaca_account", "TradingClient",                                              # Alpaca
                 "_post_request", "_put_request", "_delete_request",                             # schwab-py, private
                 ".session.")                                    # a schwab-py client's raw HTTP session (review S4)
    # The only files that may carry one of the FORBIDDEN names, each name's count pinned like the seal pins
    # (substring counts, so place_order also counts inside replace_order), with the reason. A new file, or a
    # changed count, fails. The package is never pinned.
    REPO_PINS = {
        os.path.join("loops", "order_executor.py"): (
            {"order_executor": 2, "submit_order": 1, "alpaca_account": 1},
            "the September experiment's Alpaca PAPER order executor, pre-Phase 2 code in the repo since HEAD"),
        os.path.join("loops", "alpaca_account.py"): (
            {"alpaca_account": 1, "TradingClient": 3},
            "the September experiment's Alpaca paper-account reader, which builds that executor's TradingClient"),
        os.path.join("tests", "test_phase2_contracts.py"): (
            {"place_order": 8, "replace_order": 4, "cancel_order": 3, "order_executor": 6, "submit_order": 3,
             "close_position": 2, "close_all_positions": 2, "exercise_options_position": 2, "alpaca_account": 8,
             "TradingClient": 6, "_post_request": 2, "_put_request": 2, "_delete_request": 2, ".session.": 2},
            "this file: the banned names, these pins and the scans' own test cases"),
    }

    def test_the_package_exists_and_is_scanned(self):
        self.assertIn(os.path.join(PKG, "fills.py"), package_modules())

    def test_the_scan_reaches_subfolders_and_every_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("top.py", os.path.join("sub", "evil.py"), os.path.join("sub", "deeper", "run.sh"),
                         os.path.join("__pycache__", "top.cpython-314.pyc")):
                os.makedirs(os.path.dirname(os.path.join(tmp, name)) or tmp, exist_ok=True)
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                    fh.write("import config\n")
            self.assertEqual([os.path.relpath(p, tmp) for p in package_files(tmp)],
                             [os.path.join("sub", "deeper", "run.sh"), os.path.join("sub", "evil.py"), "top.py"])
            self.assertEqual([os.path.relpath(p, tmp) for p in package_modules(tmp)],
                             [os.path.join("sub", "evil.py"), "top.py"])

    def test_the_package_never_references_an_order_placing_call(self):
        for path in package_files():
            text = read(path)
            for name in self.FORBIDDEN:
                self.assertNotIn(name, text, f"{rel(path)} references {name}")

    def test_no_script_in_the_repo_names_an_order_call_outside_its_pin(self):
        """Review S1: under the D7 pattern the full client lives in runners outside the package, so the ban
        covers the whole repo, and the few files that carry a name are pinned by count."""
        found = {}
        for path in scanned_files():
            text = read(path)
            hits = {name: text.count(name) for name in self.FORBIDDEN if name in text}
            if hits:
                found[rel(path)] = hits
        self.assertEqual(found, {path: counts for path, (counts, _reason) in self.REPO_PINS.items()})
        self.assertFalse([p for p in self.REPO_PINS if p.startswith(os.path.join("loops", "phase2") + os.sep)])
        self.assertTrue(all(reason and "\n" not in reason for _counts, reason in self.REPO_PINS.values()))


class OnlyAWrappedClient(unittest.TestCase):
    """Section 2: 'phase2 code sees only a wrapped client.' No module under loops/phase2 may import config, name
    build_client or load_settings, or construct a Schwab or Alpaca client; a runner outside the package (the
    sampler's is loops/phase2_sample.py) builds the client, wraps it read-only and passes in only the wrapper.
    The package imports only from an allowlist, so it cannot reuse a repo helper that builds a client (review S3),
    and it can neither read the token nor reach the client inside MarketData's closures (review S4, S5)."""

    NAMES = ("config", "build_client", "load_settings")
    CONSTRUCTORS = ("client_from_token_file", "client_from_login_flow", "client_from_manual_flow",
                    "client_from_access_functions", "easy_client")
    CLIENT_MODULES = ("schwab", "config", "alpaca", "alpaca_account", "order_executor")        # review S2
    # Review S3: render.py imports config at module level and daily_briefing.py builds a client, so a package
    # module may import only the standard-library modules the package uses, its own modules (phase2), technicals
    # (compute_levels) and httpx (the public symbol directory: its one import and its one GET are pinned by
    # test_httpx_is_used_only_for_the_symbol_directory). Relative imports are allowed inside the package.
    ALLOWED_IMPORTS = {"__future__", "argparse", "collections", "dataclasses", "datetime", "decimal", "fcntl",
                       "fractions", "functools", "hashlib", "json", "math", "os", "pathlib", "re", "sys", "time",
                       "typing", "zoneinfo",
                       "phase2", "technicals", "httpx"}
    # technicals.levels_for and technicals.main import config, and main builds a client: allowlisting the module
    # must not open that route, so the package takes only these from it.
    TECHNICALS_USED = {"compute_levels", "KNIFE_LOOKBACK", "MIN_SUPPORT_AGE", "ATR_FLOOR_MULT"}
    # Review S5: the runner reads the token and the settings and hands the package a reader (token_hours), so the
    # package names none of the readers. Substrings; environ, getenv and .env as whole words (fills.py's
    # docstring says 'environment').
    TOKEN_READERS = ("loop_common", "dotenv", "load_dotenv", "resolve_token_path", "token_age_days")
    SETTINGS_PATTERNS = (word("environ"), word("getenv"), r"\.env(?![A-Za-z0-9_])")

    def test_no_package_module_references_config_build_client_or_load_settings(self):
        offenders = []
        for path in package_files():
            text = read(path)
            offenders += [f"{rel(path)}: {name}" for name in self.NAMES if re.search(word(name), text)]
        self.assertEqual(offenders, [])

    def test_no_package_module_can_construct_a_schwab_or_alpaca_client(self):
        offenders = []
        for path in package_modules():
            text = read(path)
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Import):
                    offenders += [f"{rel(path)}: import {a.name}" for a in node.names
                                  if a.name.split(".")[0] in self.CLIENT_MODULES]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and \
                        (node.module or "").split(".")[0] in self.CLIENT_MODULES:
                    offenders.append(f"{rel(path)}: from {node.module} import")
            offenders += [f"{rel(path)}: {name}" for name in self.CONSTRUCTORS if re.search(word(name), text)]
        self.assertEqual(offenders, [])

    def test_every_package_import_is_allowlisted(self):
        """Review S3: every import statement, at module or function level, names an allowlisted module, and the
        allowlist holds only modules the package imports (an unused entry is removed, not kept in reserve)."""
        offenders, used = [], set()
        for path in package_modules():
            below = os.path.relpath(os.path.dirname(path), PKG)
            depth = 0 if below == "." else len(below.split(os.sep))
            tree = ast.parse(read(path))
            offenders += [f"{rel(path)}: {hit}" for hit in unlisted_imports(tree, self.ALLOWED_IMPORTS, depth)]
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    used |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    used.add((node.module or "").split(".")[0])
        self.assertEqual(offenders, [])
        self.assertEqual(sorted(self.ALLOWED_IMPORTS - used), [])

    def test_the_import_allowlist_catches_the_reviewers_routes(self):
        for line in ("import daily_briefing", "import render", "from alpaca_account import get_trading_client",
                     "import alpaca.trading.client", "def f():\n    import loop_common", "from dotenv import x",
                     "import gc", "import traceback", "from .. import render", "from ..loops import x"):
            self.assertTrue(unlisted_imports(ast.parse(line), self.ALLOWED_IMPORTS), line)
        self.assertTrue(unlisted_imports(ast.parse("from ... import render"), self.ALLOWED_IMPORTS, depth=1))
        for line in ("from . import fills", "from .params import Params", "import datetime as dt",
                     "from phase2 import sample_bars", "import technicals", "def f():\n    import httpx"):
            self.assertEqual(unlisted_imports(ast.parse(line), self.ALLOWED_IMPORTS), [], line)
        self.assertEqual(unlisted_imports(ast.parse("from .. import fills"), self.ALLOWED_IMPORTS, depth=1), [])

    def test_the_package_takes_only_compute_levels_and_three_constants_from_technicals(self):
        offenders = []
        for path in package_modules():
            tree = ast.parse(read(path))
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    offenders += [f"{rel(path)}: import {a.name}{' as ' + a.asname if a.asname else ''}"
                                  for a in node.names if a.name.split(".")[0] == "technicals"
                                  and (a.name != "technicals" or a.asname)]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and \
                        (node.module or "").split(".")[0] == "technicals":
                    offenders += [f"{rel(path)}: from {node.module} import {a.name}" for a in node.names
                                  if node.module != "technicals" or a.name not in self.TECHNICALS_USED]
                elif isinstance(node, ast.Name) and node.id == "technicals":
                    up = parents.get(node)
                    if not (isinstance(up, ast.Attribute) and up.value is node and up.attr in self.TECHNICALS_USED):
                        offenders.append(f"{rel(path)}:{node.lineno}: technicals"
                                         + (f".{up.attr}" if isinstance(up, ast.Attribute) else " as a value"))
        self.assertEqual(offenders, [])

    def test_no_package_module_reads_the_token_or_the_settings(self):
        offenders = []
        for path in package_files():
            text = read(path)
            offenders += [f"{rel(path)}: {name}" for name in self.TOKEN_READERS if name in text]
            offenders += [f"{rel(path)}: {pattern}" for pattern in self.SETTINGS_PATTERNS if re.search(pattern, text)]
        self.assertEqual(offenders, [])

    def test_no_package_module_imports_by_a_computed_name(self):
        """Integration check, gap C: the tests above read names and import statements, so a module that imports
        by a computed name (getattr(__import__('con' + 'fig'), ...)) or reads one from sys.modules would pass
        them. No package module may do either, and none may reach into a function's closure, code or globals or
        into a caller's frame (review S4: MarketData's functions close over the runner's client, and the
        limiter's wait() runs inside them). A static scan cannot see every disguise; this closes the plain
        routes, and the runner is still the only place that builds a client."""
        offenders = []
        for path in package_modules():
            offenders += [f"{rel(path)}: {hit}" for hit in computed_imports(ast.parse(read(path)))]
        self.assertEqual(offenders, [])

    def test_the_computed_name_scan_catches_the_plain_forms(self):
        for line in ("getattr(__import__('con' + 'fig'), 'build_' + 'client')", "import importlib",
                     "from importlib import import_module", "x = sys.modules['con' + 'fig']",
                     "exec('import con' + 'fig')", "eval('1')", "compile('1', 'f', 'eval')", "import builtins",
                     "__builtins__['__import__']('x')", "import runpy", "pkgutil = 1; from pkgutil import iter_modules",
                     # review S4: the client inside MarketData's closures, and the frames that hold it
                     "c = md.daily.__closure__[0].cell_contents", "md.daily.__code__.co_freevars",
                     "md.daily.__globals__['x']", "import gc; gc.get_referents(md.daily)", "import inspect",
                     "from inspect import getclosurevars", "sys._getframe(1).f_locals['client']",
                     "f.f_back.f_globals", "e.__traceback__.tb_next.tb_frame", "getattr(md.daily, '__closure__')",
                     "vars(fn)['__globals__']",
                     # review safety F3: running another program steps around the import allowlist
                     "os.system('x')", "os.popen('x')", "os.execv(a, b)", "os.posix_spawn(a, b, c)", "os.fork()",
                     "os.spawnlp(os.P_WAIT, 'x', 'x')", "getattr(os, 'execvpe')", "from os import system"):
            self.assertTrue(computed_imports(ast.parse(line)), line)
        self.assertEqual(computed_imports(ast.parse("import re\nre.compile('x')\ngetattr(md, 'daily', None)\n"
                                                    "os.replace(a, b)\nos.path.join('systems', 'x')")), [])

    def test_httpx_is_used_only_for_the_symbol_directory(self):
        """Review safety F2: httpx is allowlisted for the public symbol directory, and nothing else constrains what
        it is used for. By the AST, every reference to it in the package is inside sample_bars.fetch_directory_http
        and is its import or httpx.get (which refuses any URL but the two directory files)."""
        found = sorted((rel(path), place, form) for path in package_modules()
                       for place, form in httpx_references(ast.parse(read(path))))
        sb = os.path.join("loops", "phase2", "sample_bars.py")
        self.assertEqual(found, [(sb, "fetch_directory_http", "httpx.get"), (sb, "fetch_directory_http", "import httpx")])
        for src, want in (("def f(u):\n    import httpx as h\n    return h.get(u)", [("f", "import httpx as h")]),
                          ("import httpx\n", [("module", "import httpx")]),
                          ("def fetch_directory_http(u):\n    import httpx\n    return httpx.post(u)",
                           [("fetch_directory_http", "import httpx"), ("fetch_directory_http", "httpx.post")]),
                          ("def f():\n    from httpx import Client", [("f", "from httpx import Client")]),
                          ("def f():\n    import httpx\n    c = httpx\n", [("f", "import httpx"), ("f", "httpx as a value")]),
                          ("x = 'httpx'", [("x", "'httpx'")])):
            self.assertEqual(httpx_references(ast.parse(src)), want, src)

    def test_every_dynamic_attribute_lookup_in_the_package_is_pinned(self):
        """Review safety F6: a package helper handed a full client could reach any method by a computed attribute
        name without naming it. Every lookup by name (getattr, hasattr, setattr, delattr, vars, __dict__,
        __getattribute__) in the package is pinned by module and place; a new one fails until it is reviewed."""
        names = {"getattr", "hasattr", "setattr", "delattr", "vars", "__dict__", "__getattribute__"}
        found = {}
        for path in package_modules():
            places = name_places(ast.parse(read(path)), names)
            if places:
                found[rel(path)] = places
        p = os.path.join("loops", "phase2")
        self.assertEqual(found, {
            os.path.join(p, "compare_bars.py"): {("getattr", "_order_module"): 1, ("hasattr", "_order_module"): 1},
            os.path.join(p, "orders.py"): {("getattr", "Bracket"): 1},
            os.path.join(p, "params.py"): {("getattr", "unset"): 1},
            os.path.join(p, "sample_bars.py"): {("getattr", "require_market_data"): 1}})


DYNAMIC_CALLS = ("__import__", "exec", "eval", "compile")
DYNAMIC_MODULES = ("importlib", "runpy", "imp", "pkgutil", "zipimport", "builtins", "gc", "inspect")
DYNAMIC_ATTRIBUTES = ("import_module", "__import__", "modules",
                      # review S4: a function's cells, code and globals, and the frames of its callers
                      "__closure__", "cell_contents", "__code__", "__globals__", "co_freevars",
                      "_getframe", "_current_frames", "f_back", "f_locals", "f_globals", "f_builtins",
                      "tb_frame", "__traceback__", "gi_frame", "cr_frame", "ag_frame")
DYNAMIC_NAMES = ("__builtins__", "__loader__", "__spec__")
# Review safety F3: os is allowlisted, and running another program (a shell, a fork) would step around the import
# allowlist and every text ban. subprocess, pty and multiprocessing are refused by the allowlist already.
SPAWN = ("system", "popen", "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
         "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
         "posix_spawn", "posix_spawnp", "fork", "forkpty")


def computed_imports(tree: ast.AST) -> list[str]:
    """Every plain route to importing by a computed name: the dynamic builtins called by name (re.compile, an
    attribute call, is not one), the import machinery's modules, sys.modules, and the module's own loader; every
    plain route into a function's closure, code or globals or a caller's frame; and every route to running
    another program (SPAWN: os.system, os.popen, the exec and spawn families, fork). Each as an attribute, as an
    imported name (from os import system) or as a string that is exactly one of those names
    (getattr(f, '__closure__'), getattr(os, 'fork'))."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in DYNAMIC_CALLS:
            hits.append(f"{node.func.id}()")
        elif isinstance(node, ast.Import):
            hits += [f"import {a.name}" for a in node.names if a.name.split(".")[0] in DYNAMIC_MODULES]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in DYNAMIC_MODULES:
            hits.append(f"from {node.module} import")
        elif isinstance(node, ast.ImportFrom):
            hits += [f"from {node.module} import {a.name}" for a in node.names if a.name in SPAWN]
        elif isinstance(node, ast.Attribute) and node.attr in DYNAMIC_ATTRIBUTES + SPAWN:
            hits.append(f".{node.attr}")
        elif isinstance(node, ast.Name) and node.id in DYNAMIC_NAMES:
            hits.append(node.id)
        elif isinstance(node, ast.Constant) and node.value in DYNAMIC_ATTRIBUTES + DYNAMIC_NAMES + SPAWN:
            hits.append(repr(node.value))
    return hits


def httpx_references(tree: ast.Module) -> list[tuple[str, str]]:
    """(place, form) of every reference to httpx in a module, in order: its import (with any alias), a from-import,
    an attribute of it (httpx.get), the name used as a value, or the string 'httpx'. The place is the top-level
    def or class around it, or the one name a plain assignment binds, else 'module'."""
    out = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            place = stmt.name
        elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            place = stmt.targets[0].id
        else:
            place = "module"
        parents = {child: node for node in ast.walk(stmt) for child in ast.iter_child_nodes(node)}
        hits = []
        for node in ast.walk(stmt):
            if isinstance(node, ast.Import):
                hits += [(node, "import " + a.name + (f" as {a.asname}" if a.asname else "")) for a in node.names
                         if a.name.split(".")[0] == "httpx"]
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "httpx":
                hits.append((node, f"from {node.module} import " + ", ".join(a.name for a in node.names)))
            elif isinstance(node, ast.Name) and node.id == "httpx":
                up = parents.get(node)
                hits.append((node, f"httpx.{up.attr}" if isinstance(up, ast.Attribute) and up.value is node
                             else "httpx as a value"))
            elif isinstance(node, ast.Constant) and node.value == "httpx":
                hits.append((node, "'httpx'"))
        out += [(place, form) for node, form in sorted(hits, key=lambda h: (h[0].lineno, h[0].col_offset))]
    return out


def unlisted_imports(tree: ast.AST, allowed, depth: int = 0) -> list[str]:
    """Every import statement, at module or function level, whose top-level module is not in ``allowed``, and
    every relative import that climbs out of loops/phase2 (``depth``: the module's folder levels below it)."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [f"import {a.name}" for a in node.names if a.name.split(".")[0] not in allowed]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and (node.module or "").split(".")[0] not in allowed:
                hits.append(f"from {node.module} import")
            elif node.level > depth + 1:
                hits.append(f"from {'.' * node.level}{node.module or ''} import")
    return hits


def identifiers(node: ast.AST) -> list[str]:
    """The names a node reads or binds: a name, an attribute, an imported name or its alias, a global or nonlocal
    declaration, a parameter, a keyword argument, a def or a class, or a string (a string matches a name only when
    it is exactly that name, as in globals()['X']; a docstring or a message never does)."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.alias):
        return [node.name.rsplit(".", 1)[-1]] + ([node.asname] if node.asname else [])
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return list(node.names)
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.keyword):
        return [node.arg] if node.arg else []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return []


def name_places(tree: ast.Module, names) -> dict:
    """{(name, place): count} for every reference to one of ``names`` in a module's code. The place is what the
    top-level statement around it defines: a function's or a class's name, or the one name a plain assignment
    binds; any other statement is 'module'."""
    out = collections.Counter()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            place = stmt.name
        elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            place = stmt.targets[0].id
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            place = stmt.target.id
        else:
            place = "module"
        for node in ast.walk(stmt):
            for ident in identifiers(node):
                if ident in names:
                    out[(ident, place)] += 1
    return dict(out)


class OosSealContract(unittest.TestCase):
    """3.7 step 2. The unseals are objects compared by identity, so a use has to reach them by name. This test
    pins every place a repo script writes either name, file by file and count by count, in every script-like
    file (notebooks, makefiles and launchd plists included), pins fills.py's own uses by the AST, and fails a
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

    def setUp(self):
        self.fills = ast.parse(read(os.path.join(PKG, "fills.py")))

    def test_every_use_of_an_unseal_is_pinned(self):
        found = {}
        for path in scanned_files():
            text = read(path)
            counts = tuple(text.count(n) for n in UNSEALS)
            if any(counts):
                found[rel(path)] = counts
        self.assertEqual(found, self.USES)

    def test_the_scans_reach_notebooks_makefiles_plists_and_large_files(self):
        """Review S7: a notebook or a makefile that used an unseal was invisible to the scans."""
        scanned = ["run.py", os.path.join("research", "oos_peek.ipynb"), os.path.join("tools", "replay.mk"),
                   os.path.join("deploy", "job.plist"), "Makefile", os.path.join("a", "makefile"),
                   os.path.join("b", "GNUmakefile"), os.path.join("c", "MAKEFILE"), "UPPER.PY", "tool", "big.ipynb"]
        ignored = ["notes.txt", "README.md", "data", os.path.join(".venv", "lib.py"),
                   os.path.join(".claude", "worktrees", "copy", "run.py"), os.path.join("__pycache__", "x.py")]
        with tempfile.TemporaryDirectory() as tmp:
            for name in scanned + ignored:
                os.makedirs(os.path.dirname(os.path.join(tmp, name)) or tmp, exist_ok=True)
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                    fh.write("#!/bin/sh\n" if name == "tool" else "#" * 2_100_000 if name == "big.ipynb" else "x\n")
            self.assertEqual(sorted(os.path.relpath(p, tmp) for p in scanned_files(tmp)), sorted(scanned))

    def test_nothing_outside_fills_reaches_around_the_seal(self):
        fills_path = os.path.join("loops", "phase2", "fills.py")
        this_file = os.path.join("tests", "test_phase2_contracts.py")
        offenders = []
        for path in scanned_files():
            if rel(path) in (fills_path, this_file):
                continue
            text = read(path)
            offenders += [f"{rel(path)}: {name}" for name in PRIVATE + TAMPERING if re.search(word(name), text)]
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
                offenders += [f"{rel(path)}: {hit}" for hit in computed_fills_lookups(read(path))]
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
                mock.patch("builtins.open", fake_open):
            found = [os.path.basename(p) for p in scanned_files()]
        self.assertEqual((found, opened), (["tool"], ["tool"]))

    def test_the_seal_is_the_default(self):
        defaults = {}
        for node in ast.walk(self.fills):
            if isinstance(node, ast.FunctionDef) and node.name in ("step", "run", "evaluate_at_cutoff", "close_at_mark"):
                kw = dict(zip((a.arg for a in node.args.kwonlyargs), node.args.kw_defaults))
                defaults[node.name] = kw["seal"].id if isinstance(kw.get("seal"), ast.Name) else None
        self.assertEqual(defaults, {"step": "SEALED", "run": "SEALED", "evaluate_at_cutoff": "SEALED",
                                    "close_at_mark": "SEALED"})

    def test_fills_names_an_unseal_only_in_its_assignment_the_registry_and_check_seal(self):
        """Review S7: a text count cannot tell a docstring from code, so a refactor could move a docstring mention
        into a new helper and keep the count. By the AST, each unseal is named only in its own assignment, in the
        registry _SEALS and in _check_seal, and the registry only there too (else _SEALS[1] would stand in for an
        unseal). fills.py looks nothing up by a string either."""
        pick, replay = UNSEALS
        self.assertEqual(name_places(self.fills, set(UNSEALS) | {SEAL_REGISTRY}), {
            (pick, pick): 1, (pick, SEAL_REGISTRY): 1, (pick, "_check_seal"): 1,
            (replay, replay): 1, (replay, SEAL_REGISTRY): 1, (replay, "_check_seal"): 2,
            (SEAL_REGISTRY, SEAL_REGISTRY): 1, (SEAL_REGISTRY, "_check_seal"): 1})
        lookups = {"globals", "vars", "locals", "getattr", "setattr", "delattr", "__dict__", "modules",
                   "astuple", "asdict"}                                # a seal or a bar's fields read wholesale
        self.assertEqual(sorted({i for n in ast.walk(self.fills) for i in identifiers(n)} & lookups), [])

    def test_no_public_fills_function_names_or_defaults_to_an_unseal(self):
        """Review S7: a public helper that passes an unseal (run_oos) would let any caller unseal without naming
        one. No function or method whose name has no leading underscore names an unseal or the registry, in its
        parameters' defaults or anywhere in its body."""
        watched = set(UNSEALS) | {SEAL_REGISTRY}
        offenders = []
        for fn in ast.walk(self.fills):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and not fn.name.startswith("_"):
                defaults = fn.args.defaults + [d for d in fn.args.kw_defaults if d is not None]
                for label, parts in (("default", defaults), ("body", fn.body + fn.decorator_list)):
                    offenders += [f"{fn.name} ({label}): {i}" for part in parts for n in ast.walk(part)
                                  for i in identifiers(n) if i in watched]
        self.assertEqual(offenders, [])

    def test_the_fills_pins_catch_a_public_unseal(self):
        pick = UNSEALS[0]
        for extra in (f"def run_oos(o, s, *, params):\n    return run(o, s, params=params, seal={pick})\n",
                      f"def run_oos(o, s, *, params, seal={pick}):\n    return run(o, s, params=params, seal=seal)\n",
                      f"def run_oos(o, s, *, params):\n    return run(o, s, params=params, seal={SEAL_REGISTRY}[1])\n",
                      f"def run_oos(o, s, *, params):\n    return run(o, s, params=params, seal=globals()['{pick}'])\n",
                      f"run_oos = functools.partial(run, seal={pick})\n"):
            tree = ast.parse(read(os.path.join(PKG, "fills.py")) + "\n\n" + extra)
            self.assertIn("run_oos", {place for _name, place in name_places(tree, set(UNSEALS) | {SEAL_REGISTRY})},
                          extra)

    def test_only_step_reaches_a_bar_and_each_entry_point_checks_the_seal_first(self):
        """Review S7, the other half: a public function that steps a bar without _check_seal would need no unseal
        at all. The two bar-reading transitions are reached only from step, and step, evaluate_at_cutoff and
        close_at_mark open with the seal check on their own seal argument (run goes through step)."""
        self.assertEqual(name_places(self.fills, {"_entry_session", "_held_session", "_check_seal"}), {
            ("_entry_session", "_entry_session"): 1, ("_entry_session", "step"): 1,
            ("_held_session", "_held_session"): 1, ("_held_session", "step"): 1,
            ("_check_seal", "_check_seal"): 1, ("_check_seal", "step"): 1,
            ("_check_seal", "evaluate_at_cutoff"): 1, ("_check_seal", "close_at_mark"): 1})
        first = {}
        for node in self.fills.body:
            if isinstance(node, ast.FunctionDef) and node.name in ("step", "evaluate_at_cutoff", "close_at_mark"):
                body = node.body[1:] if ast.get_docstring(node) is not None else node.body
                first[node.name] = ast.unparse(body[0])
        self.assertEqual(first, {"step": "_check_seal(order, session, seal, params)",
                                 "evaluate_at_cutoff": "_check_seal(order, cutoff, seal, params)",
                                 "close_at_mark": "_check_seal(order, cutoff, seal, params)"})

    # Every place fills.py names a bar's price fields, and the fill and exit helpers, by the AST (attributes,
    # parameters, keywords and exact strings), computed from fills.py as it stands.
    BAR_PRICES = {("open", "Bar"): 3, ("open", "ENTRY_OPEN"): 1, ("open", "_entry_session"): 3,
                  ("open", "_held_session"): 4, ("open", "_intraday_stop"): 1,
                  ("high", "Bar"): 3, ("high", "_entry_session"): 2, ("high", "_held_session"): 1,
                  ("low", "Bar"): 4, ("low", "_entry_session"): 2, ("low", "_held_session"): 1,
                  ("low", "_intraday_stop"): 2,
                  ("close", "Bar"): 3, ("close", "_check_mark"): 5, ("close", "_entry_session"): 1,
                  ("close", "step"): 1}
    TRANSITION_HELPERS = {("_fill", "_fill"): 1, ("_fill", "_entry_session"): 1,
                          ("_exit", "_exit"): 1, ("_exit", "_entry_session"): 2, ("_exit", "_held_session"): 5,
                          ("_intraday_stop", "_intraday_stop"): 1, ("_intraday_stop", "_entry_session"): 1,
                          ("_intraday_stop", "_held_session"): 1}

    def test_only_the_transitions_read_a_bars_prices(self):
        """Review safety F4: a public fills function that read a bar and filled an order inline, never calling
        _check_seal, passed every test above (through _fill, or with dataclasses.replace and no helper at all). So
        every place that names a bar's open, high, low or close (Bar itself, the transitions, the mark check and
        step's own close) is pinned, and so is every place that names _fill, _exit or _intraday_stop. A new place
        fails until it is reviewed; step remains the only way to a transition, and it checks the seal first."""
        self.assertEqual(name_places(self.fills, {"open", "high", "low", "close"}), self.BAR_PRICES)
        self.assertEqual(name_places(self.fills, {"_fill", "_exit", "_intraday_stop"}), self.TRANSITION_HELPERS)
        peek = ("\n\ndef peek_fill(order, session, bar):\n    if order.trigger <= bar.open <= order.ceiling:\n"
                "        return replace(order, state=OPEN, entry_date=session, entry_raw=bar.open)\n    return order\n")
        tree = ast.parse(read(os.path.join(PKG, "fills.py")) + peek)
        self.assertNotEqual(name_places(tree, {"open", "high", "low", "close"}), self.BAR_PRICES)   # the pin's own case


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
