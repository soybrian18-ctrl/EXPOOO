#!/usr/bin/env python3
"""Phase 2 B3 pulls: the runner, OUTSIDE loops/phase2 (it builds the Schwab client and reads the SEC contact at run time).
READ-ONLY: quotes and daily bars from Schwab, the public symbol directory, Yahoo splits, SEC EDGAR. Writes only
logs/phase2/b3/<batch>/ (schwab-py rewrites the token file when it refreshes access, as always). Every step appends to its own file and resumes: a name already done is skipped. The parsing is in
phase2/bars.py.
Sealed-window bars are stored raw and never aggregated (spec 3.7); the summaries here count names, not sessions.

  .venv/bin/python -B loops/phase2_pull.py status
  .venv/bin/python -B loops/phase2_pull.py directory | quotes | bars | splits | submissions | headers   [--limit N] [--batch NAME]

A later full re-pull (spec 3.1 needs bars through 2026-12-30) takes a new --batch, so one batch has one end date and one
split basis. Run order: directory, quotes, bars, splits, submissions, headers. The Schwab steps stop by themselves before
08:30 ET on any day (Friday's night job pulls on Saturday morning) and after 16:45 ET on weekdays, share the night job's
limiter (spec 2), refuse a token with under params.token_min_hours left, and rebuild the client every 10 minutes and as
soon as the token changes, so a re-authentication is never reverted. EDGAR is paced at 5 requests a second (the SEC allows 10). The contact sent in the
SEC User-Agent comes from SEC_CONTACT_NAME and SEC_CONTACT_EMAIL in the settings file, is never printed or stored, and
goes to sec.gov only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "loops")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from phase2 import bars as B  # noqa: E402
from phase2 import sample_bars as SB  # noqa: E402
from phase2.params import PARAMS, params_hash  # noqa: E402

OUT = ROOT / "logs" / "phase2" / "b3"
EDGAR_HOSTS = ("https://www.sec.gov/", "https://data.sec.gov/")
EDGAR_SPACING, ROUNDS, ROUND_PAUSE, MAX_FAILS_IN_ROW, CLIENT_LIFE = 0.2, 3, 60.0, 20, 600.0
DONE = {"bars": (B.OK, B.EMPTY, B.TRUNCATED, B.STALE, B.LATE_START), "splits": (B.OK, B.EMPTY),
        "submissions": (B.OK,), "headers": (B.OK, B.MISMATCH)}
STREAK = (B.ERROR, B.EMPTY, B.TRUNCATED)                 # a run of these means the source is down, not the names


class Stop(RuntimeError):
    """A step stopped early; rerun it later and it resumes."""


def append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, separators=(",", ":")) + "\n")


def rows(path: Path) -> Iterable[dict]:
    """Stored rows; an unreadable line (a run cut off mid-write) is skipped, so its name is pulled again."""
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def heal(path: Path) -> None:
    """End a cut-off last line, so the next append starts its own line."""
    if path.exists() and path.stat().st_size:
        with open(path, "rb+") as fh:
            fh.seek(-1, 2)
            if fh.read(1) != b"\n":
                fh.write(b"\n")


def last_by(path: Path, key: str = "symbol") -> dict:
    """The classes only (bars files are large): the last row's class per key."""
    return {r[key]: r.get("cls") for r in rows(path) if key in r}


def schwab_open(now: dt.datetime) -> bool:
    return now.time() >= dt.time(8, 30) and (now.weekday() >= 5 or now.time() < dt.time(16, 45))


def step(name: str, out: Path, todo: list, key: Callable, work: Callable, *, gate: Callable = lambda: None,
         log: Callable = print, sleep: Callable = time.sleep, limit: Optional[int] = None, every: int = 200,
         control: Callable = lambda: None) -> Counter:
    """Run ``work(item) -> row`` over the items not done yet, the never-tried ones first. An error, or an answer that
    may be a truncation block (B.AGREE), is asked again in later rounds at least ROUND_PAUSE apart; such an answer is
    believed only when that many answers agree, otherwise it is UNSETTLED and a rerun asks again. MAX_FAILS_IN_ROW
    never-tried names failing in a row stops the step: something is wrong with the source, not with a name. A name
    whose answer is not settled gets a PENDING row (the stopping run of failures excepted), so an interrupted run never
    makes it look never-tried. EMPTY and TRUNCATED are stored only after ``control`` finds a known-good name full."""
    path = out / f"{name}.jsonl"
    heal(path)
    past = last_by(path)
    done = {k for k, c in past.items() if c in DONE[name]}
    items = [x for x in todo if key(x) not in done]
    items = sorted(items, key=lambda x: key(x) in past)[:limit]          # stable: never-tried first
    log(f"{name}: {len(items)} to pull, {len(done)} done of {len(todo)}")
    tally: Counter = Counter()
    held: dict = {}
    empties: list = []                                       # settled EMPTY or TRUNCATED rows, waiting for the control
    streak: list = []                                        # never-tried names failing in a row, not yet marked

    def store(item, row: dict) -> None:
        row = {k: v for k, v in row.items() if k not in ("symbol", "sig")}
        append(path, dict(symbol=key(item), pulled=SB.iso(SB.now_et()), **row))
        tally[row["cls"]] += 1

    def settle(item, row: dict, final: bool) -> bool:
        k = key(item)
        if row["cls"] in B.AGREE:
            sig = (row["cls"], row.get("sig"))
            held.setdefault(k, []).append(sig)
            if held[k].count(sig) >= B.AGREE[row["cls"]]:
                if row["cls"] in (B.EMPTY, B.TRUNCATED):
                    empties.append((item, row))
                else:
                    store(item, row)
                return True
            if final:
                store(item, dict(row, cls=B.UNSETTLED, answer=row["cls"]))
            return False
        if row["cls"] == B.ERROR and not final:
            return False
        store(item, row)
        return True

    def mark(which: list) -> None:
        for item in which:
            append(path, dict(symbol=key(item), pulled=SB.iso(SB.now_et()), cls=B.PENDING))
        which.clear()

    todo_now = items
    down = False
    try:
        for rnd in range(1, ROUNDS + 1):
            again = []
            for n, item in enumerate(todo_now, 1):
                gate()
                try:
                    row = work(item)
                except Stop:
                    raise
                except Exception as e:                       # noqa: BLE001  one bad name never stops the step
                    row = dict(cls=B.ERROR, error=type(e).__name__ if name in ("submissions", "headers")
                               else f"{type(e).__name__}: {e}"[:160])
                settled = settle(item, row, rnd == ROUNDS)
                if not settled:
                    again.append(item)
                if rnd == 1 and key(item) not in past:
                    if row["cls"] in STREAK:
                        streak.append(item)
                        if len(streak) >= MAX_FAILS_IN_ROW:
                            down = True
                            raise Stop(f"{name}: {len(streak)} in a row failed or came back empty "
                                       f"({row.get('error') or row['cls']}); none of them is stored; rerun to resume")
                    else:
                        mark(streak)
                        if not settled:
                            mark([item])
                if n % every == 0:
                    log(f"  round {rnd}: {n} of {len(todo_now)} {dict(tally)}")
            mark(streak)
            if not again:
                break
            todo_now = again
            if rnd < ROUNDS:
                log(f"  {len(again)} to ask again in {ROUND_PAUSE:.0f} s")
                sleep(ROUND_PAUSE)
        if empties:
            control()
            for item, row in empties:
                store(item, row)
    finally:
        if not down:
            mark(streak)
    log(f"{name}: {dict(tally)}")
    return tally


# ---- Schwab and the directory -------------------------------------------------------------------------------------

def names(out: Path) -> list[dict]:
    p = out / "names.json"
    if not p.exists():
        raise Stop("run the directory step first")
    return json.loads(p.read_text())


def directory(out: Path, fetch: Callable[[str], bytes] = SB.fetch_directory_http, log: Callable = print) -> None:
    if (out / "names.json").exists():
        log("directory: already stored (the name list is fixed for B3)")
        return
    folder, parsed = out / "directory", []
    folder.mkdir(parents=True, exist_ok=True)
    for name, url in SB.DIRECTORY.items():
        data = fetch(url)
        if not data.startswith((b"Symbol|", b"ACT Symbol|")):
            raise Stop(f"{name}: no directory header")
        if b"File Creation Time" not in data[-400:]:
            raise Stop(f"{name}: cut off (no footer)")
        (folder / name).write_bytes(data)
        parsed += SB.parse_directory(data.decode("utf-8", "replace"), name)
    keep, left = B.pull_list(parsed)
    SB.atomic_write_json(out / "left_out.json", left)
    SB.atomic_write_json(out / "names.json", keep)
    log(f"directory: {len(parsed)} rows, {len(keep)} to pull ({sum(bool(k['b4']) for k in keep)} for B4 to rule on), "
        f"{len(left)} left out")


def schwab_gate(hours: Callable, now: Callable = SB.now_et) -> Callable:
    def gate() -> None:
        if not schwab_open(now()):
            raise Stop("outside 08:30-16:45 ET on a weekday: left to the night job; rerun to resume")
        left, _ = hours()
        if left is None or left < PARAMS.token_min_hours:
            raise Stop("the Schwab token is unreadable or has too little life left")
    return gate


class FreshClient:
    """The read-only market data, rebuilt every CLIENT_LIFE seconds and as soon as the token's expiry moves, so a client
    built before a re-authentication never writes the old token back (schwab-py rewrites the file on each refresh)."""

    def __init__(self, build: Callable, hours: Callable, clock: Callable = time.monotonic, gate: Callable = lambda: None):
        self.build, self.hours, self.clock, self.gate = build, hours, clock, gate
        self.md, self.born, self.expiry = None, 0.0, None

    def get(self):
        self.gate()
        _, when = self.hours()
        if when is None:
            raise Stop("the Schwab token is unreadable just now; rerun to resume")
        expiry = dt.datetime.fromisoformat(when)
        moved = self.expiry is not None and abs((expiry - self.expiry).total_seconds()) > 60
        if self.md is None or moved or self.clock() - self.born > CLIENT_LIFE:
            self.md, self.born, self.expiry = self.build(), self.clock(), expiry
        return self.md

    def daily(self, *a):
        return self.get().daily(*a)

    def quotes(self, *a):
        return self.get().quotes(*a)


def quote_step(out: Path, quotes: Callable[[list], dict], log: Callable = print, sleep: Callable = time.sleep,
               chunk: int = 200) -> None:
    """One quote per name: the subtype, the CUSIP and description (3.1 identity), and which Schwab form answers. Names
    that never answer are listed, and a rerun never replaces a fuller file."""
    todo, found, path = names(out), {}, out / "quotes.jsonl"
    forms = {f: n["symbol"] for n in todo for f in n["forms"]}
    forms["SPY"] = "SPY"
    asked, dotted = list(forms), {f.replace("/", "."): s for f, s in forms.items()}
    retried = False
    chunks = [asked[i:i + chunk] for i in range(0, len(asked), chunk)]
    for i, part in enumerate(chunks):
        got = None
        for attempt in range(ROUNDS):
            try:
                got = quotes(part)
                break
            except Stop:
                raise
            except Exception as e:                           # noqa: BLE001
                log(f"  quotes chunk {i + 1}: {type(e).__name__}")
                if attempt < ROUNDS - 1:
                    sleep(ROUND_PAUSE)
        if got is None:
            raise Stop("a quotes chunk failed; nothing stored; rerun")
        for f, e in got.items():
            sym = forms.get(f) or dotted.get(f.replace("/", "."))
            if sym and sym not in found and isinstance(e, dict) and ("quote" in e or "reference" in e):
                ref = e.get("reference", {})
                found[sym] = dict(symbol=sym, form=f, sub=e.get("assetSubType"), main=e.get("assetMainType"),
                                  cusip=ref.get("cusip"), description=ref.get("description"),
                                  exchange=ref.get("exchangeName"), pulled=SB.iso(SB.now_et()))
        if i == len(chunks) - 1 and not retried:             # what never answered is asked once more
            retried, left = True, [f for f, sym in forms.items() if sym not in found]
            if left:
                sleep(ROUND_PAUSE)
                chunks += [left[k:k + chunk] for k in range(0, len(left), chunk)]
    had = len(list(rows(path)))
    if len(found) < had:
        raise Stop(f"quotes: only {len(found)} answered against {had} stored; the stored file is kept")
    missing = sorted({n["symbol"] for n in todo} - set(found))
    SB.atomic_write_json(out / "quotes_missing.json", missing)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(found[s]) + "\n" for s in sorted(found)))
    os.replace(tmp, path)
    log(f"quotes: {len(found)} answered, {len(missing)} names listed as missing")


def bar_work(daily: Callable, forms: dict[str, list], start: dt.datetime, end: str, now: Callable = SB.now_et) -> Callable:
    """Final bars from ``start`` through ``end`` (the batch's last session); later bars are cut, so every run of a batch
    stores the same end."""
    first = start.date().isoformat()

    def work(sym: str) -> dict:
        best, errors = None, []
        for form in forms[sym]:
            try:
                raw = daily(form, start, now())
            except Stop:
                raise
            except Exception as e:                           # noqa: BLE001  a class share's other form may answer
                errors.append(e)
                continue
            bars, aside = B.clean(raw or [])
            bars = [b for b in bars if b["d"] <= end]
            aside = {k: [x for x in v if (x if isinstance(x, str) else x[0]) <= end] for k, v in aside.items()}
            if best is None or len(bars) > len(best[1]):
                best = (form, bars, aside)
            if len(bars) > 1:
                break
        if best is None or (errors and not best[1]):
            raise errors[0]
        form, bars, aside = best
        ends = dict(first=bars[0]["d"], last=bars[-1]["d"], n=len(bars)) if bars else dict(first="", last="", n=0)
        return dict(cls=B.response_class(bars, first, end), form=form, sig=tuple(ends.values()), **ends,
                    bars=[[b[f] for f in ("d", "o", "h", "l", "c", "v", "ms")] for b in bars], **aside)
    return work


def batch_end(out: Path, now: Callable = SB.now_et) -> str:
    """The batch's last session, fixed by its first bars run: the last session dated before that day (today's bar is
    final only around midnight, so the clock's "completed" session is not enough)."""
    p = out / "end.json"
    if not p.exists():
        SB.atomic_write_json(p, dict(end=SB.previous_session(now().date()).isoformat()))
    return json.loads(p.read_text())["end"]


def bar_names(out: Path) -> dict[str, list]:
    """The names to pull bars for, SPY with them; the Schwab form that answered the quote comes first."""
    got = {r["symbol"]: r["form"] for r in rows(out / "quotes.jsonl")}
    if not got:
        raise Stop("run the quotes step first")
    forms = {n["symbol"]: sorted(n["forms"], key=lambda f, s=n["symbol"]: f != got.get(s)) for n in names(out)}
    forms["SPY"] = ["SPY"]
    return forms


# ---- Yahoo ----------------------------------------------------------------------------------------------------------

def yahoo_history(sym: str) -> tuple[list, dict]:
    import yfinance                                          # approved D6; only this step needs it
    h = yfinance.Ticker(B.yahoo_symbol(sym)).history(start=PARAMS.bars_start, interval="1d", actions=True,
                                                     auto_adjust=False, raise_errors=True)
    if h is None or not len(h):
        return [], dict(n=0, first="", last="")
    days = [i.date() for i in h.index]
    return ([(d, float(v)) for d, v in zip(days, h["Stock Splits"]) if v],
            dict(n=len(days), first=days[0].isoformat(), last=days[-1].isoformat()))


def split_work(history: Callable = yahoo_history, sleep: Callable = time.sleep) -> Callable:
    """Splits with the coverage they rest on: "no splits" means something only where Yahoo has the history (B4 compares
    it with the Schwab bars)."""
    def work(sym: str) -> dict:
        sleep(0.5)
        events, ends = history(sym)
        good, flagged = B.split_rows(events)
        return dict(cls=B.OK if ends["n"] else B.EMPTY, splits=good, flagged=flagged, sig=tuple(ends.values()), **ends)
    return work


# ---- EDGAR ----------------------------------------------------------------------------------------------------------

def edgar_client(sleep: Callable = time.sleep, clock: Callable = time.monotonic) -> Callable[[str], str]:
    import httpx
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    who, mail = os.environ.get("SEC_CONTACT_NAME", "").strip(), os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if not who or not mail:
        raise Stop("SEC_CONTACT_NAME or SEC_CONTACT_EMAIL is not set")
    web = httpx.Client(headers={"User-Agent": f"{who} {mail}"}, timeout=30, follow_redirects=False)
    last = [0.0]

    def get(url: str) -> str:
        if not url.startswith(EDGAR_HOSTS):
            raise ValueError("not an SEC address")
        wait = EDGAR_SPACING - (clock() - last[0])
        if wait > 0:
            sleep(wait)
        last[0] = clock()
        r = web.get(url)
        if r.status_code in (403, 429):
            raise Stop(f"SEC answered {r.status_code}: stopped so the limit is not pushed; wait 10 minutes and rerun")
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.text
    return get


def submissions_work(get: Callable[[str], str], ciks: dict[str, int]) -> Callable:
    def work(sym: str) -> dict:
        cik = ciks.get(sym)
        if cik is None:
            return dict(cls=B.NO_CIK)
        doc = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
        older = [json.loads(get("https://data.sec.gov/submissions/" + f)) for f in B.older_files(doc)]
        rec = B.submissions_record(doc, older)
        if rec["cik"] != cik:
            raise ValueError("another issuer's submissions")
        listed = [t.upper().replace("-", ".") for t in rec["tickers"]]
        return dict(cls=B.OK, ticker_listed=sym in listed, **rec)
    return work


def header_list(out: Path) -> list[tuple[int, str]]:
    seen, todo = set(), []
    for r in rows(out / "submissions.jsonl"):
        for a in r.get("earnings", []) if r.get("cls") == B.OK else []:
            if a["acc"] not in seen:
                seen.add(a["acc"])
                todo.append((r["cik"], a["acc"]))
    if not todo:
        raise Stop("run the submissions step first")
    return todo


def header_work(get: Callable[[str], str]) -> Callable:
    def work(item: tuple) -> dict:
        cik, acc = item
        h = B.parse_header(get(B.header_url(cik, acc)), acc)
        return dict(cls=B.OK if h["match"] else B.MISMATCH, cik=cik, **h)
    return work


def canary(out: Path, get: Callable[[str], str]) -> None:
    """Spec 3.2, M2 item 1: a check on known filings before any header is stored. Apple's results come out at 16:30
    ET, so the headers of its four oldest stored earnings 8-Ks must read 16:25-16:45 Eastern, 8-K, Item 2.02."""
    known = next((r for r in rows(out / "submissions.jsonl") if r["symbol"] == "AAPL" and r.get("cls") == B.OK), None)
    if known is None or len(known["earnings"]) < 4:
        raise Stop("canary: no AAPL filings stored")
    for a in known["earnings"][:4]:
        h = B.parse_header(get(B.header_url(known["cik"], a["acc"])), a["acc"])
        if not h["match"] or not "16:25" <= h["accepted_et"][11:16] <= "16:45":
            raise Stop(f"canary: {a['acc']} reads {h['accepted_et']} {h['type']} {h['items']}; nothing stored")


# ---- command line -----------------------------------------------------------------------------------------------------

def status(out: Path, log: Callable = print) -> None:
    log(f"params {params_hash(PARAMS)}; {out}")
    n = len(names(out)) if (out / "names.json").exists() else 0
    subs = last_by(out / "submissions.jsonl")
    want = dict(bars=n + 1, splits=n, submissions=n, headers="?")
    if subs:
        want["headers"] = len({a["acc"] for r in rows(out / "submissions.jsonl") for a in r.get("earnings", [])})
    for name in ("bars", "splits", "submissions", "headers"):
        c = Counter(last_by(out / f"{name}.jsonl").values())
        done = sum(v for k, v in c.items() if k in DONE[name])
        log(f"  {name}: {done} of {want[name]} done {dict(c)}")
    if subs and sum(v in DONE["submissions"] for v in subs.values()) < n:
        log("  (the header count is a floor: submissions are not complete)")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 2 B3 pulls (read-only, resumable)")
    ap.add_argument("what", choices=("status", "directory", "quotes", "bars", "splits", "submissions", "headers"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--batch", default="batch1")
    a = ap.parse_args(argv)
    if not a.batch.isalnum():
        ap.error("--batch takes letters and digits only")
    out = OUT / a.batch
    try:
        if a.what == "status":
            status(out)
            return 0
        out.mkdir(parents=True, exist_ok=True)
        source = {"quotes": "schwab", "bars": "schwab", "submissions": "edgar", "headers": "edgar"}.get(a.what, a.what)
        with open(OUT / f".{source}.lock", "w") as lock:     # one run per source, across batches
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise Stop(f"another {source} run is going") from None
            subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            run(a.what, out, a.limit)
    except Stop as e:
        print(f"STOPPED: {e}")
        return 1
    except Exception as e:                                   # noqa: BLE001  type only: no address or header text
        print(f"STOPPED: {type(e).__name__} outside the per-name work; rerun to resume")
        return 1
    return 0


def control_ok(name: str, row: dict, want: str) -> None:
    if row["cls"] != want:
        raise Stop(f"{name}: the control name answers {row['cls']}, so the source is doubtful; no empty answer is stored")


def run(what: str, out: Path, limit: Optional[int]) -> None:
    if what == "directory":
        directory(out)
    elif what in ("quotes", "bars"):
        import phase2_sample as R                            # the client is built there, read-only, rate-limited
        md = FreshClient(R.schwab_market_data, R.token_hours_left, gate=schwab_gate(R.token_hours_left))
        if what == "quotes":
            quote_step(out, md.quotes)
        else:
            forms = bar_names(out)
            start = dt.datetime.combine(dt.date.fromisoformat(PARAMS.bars_start), dt.time(0), SB.NY)
            work = bar_work(md.daily, forms, start, batch_end(out))
            step("bars", out, sorted(forms), str, work, limit=limit, control=lambda: control_ok("bars", work("SPY"), B.OK))
    elif what == "splits":
        try:
            import yfinance                                  # noqa: F401
        except ImportError:
            raise Stop("yfinance is not installed (approved D6; the install waits for the owner's word)") from None
        work = split_work()
        step("splits", out, [n["symbol"] for n in names(out)], str, work, limit=limit,
             control=lambda: control_ok("splits", work("AAPL"), B.OK))
    elif what == "submissions":
        get, docs = edgar_client(), []
        for f in ("company_tickers_exchange.json", "company_tickers.json"):
            if not (out / f).exists():                       # one table per batch
                SB.atomic_write_json(out / f, json.loads(get("https://www.sec.gov/files/" + f)))
            docs.append(json.loads((out / f).read_text()))
        step("submissions", out, [n["symbol"] for n in names(out)], str,
             submissions_work(get, B.cik_table(*docs)), limit=limit)
    else:
        todo, get = header_list(out), edgar_client()
        canary(out, get)
        step("headers", out, todo, lambda x: x[1], header_work(get), limit=limit, every=1000)


if __name__ == "__main__":
    sys.exit(main())
