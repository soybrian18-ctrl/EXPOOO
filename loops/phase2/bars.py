"""Phase 2 B3 pulls, the pure half: what a pulled row means (spec 2 "bars.py" row, 3.1, 8 B3). No clock, file or network;
loops/phase2_pull.py (outside the package) fetches and stores. Nothing here evaluates a signal, a fill or an R, and
nothing aggregates over sessions (spec 3.7, the standing rule): the checks are per response and per row.

Bars are keyed by New York date. A bar is final only by its stamp (midnight Chicago); where a final and a provisional
candle share a date the final one is kept, and a date with only a provisional candle is not stored. A response is judged
on its final bars: none (EMPTY), one (TRUNCATED; B1: one candle, no history), a stale end (STALE) or a late start
(LATE_START). The runner asks those again a minute later and keeps one only when the answers agree.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Iterable, Optional

from phase2 import sample_bars as SB

OK, EMPTY, TRUNCATED, STALE, LATE_START, ERROR = "OK", "EMPTY", "TRUNCATED", "STALE", "LATE_START", "ERROR"
MISMATCH, NO_CIK, UNSETTLED, PENDING = "MISMATCH", "NO_CIK", "UNSETTLED", "PENDING"
AGREE = {EMPTY: 3, TRUNCATED: 3, STALE: 2, LATE_START: 2}     # equal answers needed before one is believed
# Directory exclusions universe.py rules on at B4 (K-1 test for MLPs, 814- for BDCs): B3 pulls those names.
FUND_MARK = re.compile(r"^(fund|closed-end fund)\b")
COMMON_UNITS = re.compile(r"\bcommon\s+units?\b", re.I)
ADR_NAME = re.compile(r"\bamerican\s+depositary\b|\bAD[RS]s?\b", re.I)
ITEM_202 = "results of operations and financial condition"
HEADER_FIRST = "2021-12-01"              # 2.02 headers from here: a month before the first signal session
ANNUAL = ("10-K", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A", "6-K", "10-Q")


def pull_list(rows: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """(names to pull, names left out with the reason). The sampler's directory rules, except that a name whose only
    objection is one B4 rules on (MLP, fund, common units, an ADR of preferred shares or units) is pulled, marked ``b4``."""
    rows = list(rows)
    keep, out = SB.universe_stand_in(rows)
    by = {}
    for r in rows:
        by.setdefault(r["symbol"], r)
    kept = [dict(symbol=r["symbol"], name=r["name"], source=r["source"], forms=r["forms"], note=r["note"], b4="")
            for r in keep]
    have, left = {r["symbol"] for r in kept}, []
    for x in out:
        why = x["reason"]
        ask = (why == "MLP" or FUND_MARK.match(why) or (why == "unit" and COMMON_UNITS.search(x["name"]))
               or (why in ("preferred", "unit") and ADR_NAME.search(x["name"])))
        if x["symbol"] not in have and ask:
            r = by[x["symbol"]]
            have.add(x["symbol"])
            kept.append(dict(symbol=r["symbol"], name=r["name"], source=r["source"], forms=SB.schwab_forms(r["symbol"]),
                             note="", b4=why))
        else:
            left.append(x)
    return sorted(kept, key=lambda r: r["symbol"]), left


def _good(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def impossible(c: dict) -> str:
    """Why a candle is impossible (3.1 "Data quality"), or ''."""
    if not all(_good(c.get(f)) for f in ("o", "h", "l", "c", "v")):
        return "not a number"
    if c["v"] <= 0:
        return "no volume"
    if c["l"] <= 0:
        return "low at or below zero"
    if c["l"] > c["h"]:
        return "low above high"
    if not c["l"] <= c["c"] <= c["h"]:
        return "close outside the range"
    return ""


def clean(raw: Iterable[dict]) -> tuple[list[dict], dict]:
    """(final bars oldest first, what was set aside). Each bar is {d,o,h,l,c,v,ms}. Impossible bars are dropped and
    listed; a date whose only candle is not final is listed, never stored; of two final candles for a date the last
    in the response is kept and the date is listed when they differ."""
    by, other, bad, dup = {}, set(), [], set()
    for k in raw:
        c = SB.candle_from_raw(k)
        if c["kind"] != "final":
            other.add(c["d"])
            continue
        prev = by.get(c["d"])
        if prev is not None and any(prev[f] != c[f] for f in "ohlcv"):
            dup.add(c["d"])
        by[c["d"]] = c
    bars = []
    for d in sorted(by):
        c = by[d]
        why = impossible(c)
        if why:
            bad.append([d, why])
        else:
            bars.append({f: c[f] for f in ("d", "o", "h", "l", "c", "v", "ms")})
    return bars, dict(not_final=sorted(other - set(by)), impossible=bad, duplicate=sorted(dup))


def response_class(bars: list[dict], start: str, last_session: str) -> str:
    """The class of a cleaned response (its final bars): EMPTY, TRUNCATED, STALE (ends before the batch's last
    session asked for), LATE_START (starts after ``start``, the first session asked for) or OK."""
    if not bars:
        return EMPTY
    if len(bars) == 1:
        return TRUNCATED
    if bars[-1]["d"] < last_session:
        return STALE
    return LATE_START if bars[0]["d"] > start else OK


# ---- splits -------------------------------------------------------------------------------------------------------

def yahoo_symbol(sym: str) -> str:
    return sym.replace(".", "-").replace("/", "-")


def split_rows(events: Iterable[tuple[dt.date, float]]) -> tuple[list[list], list[list]]:
    """(splits, flagged), each [[date, ratio]] oldest first; ratio > 1 is a forward split. A ratio that is not
    positive and finite, is exactly 1, or shares its date with another is flagged for B4, never used silently."""
    evs = sorted((d.isoformat(), float(r)) for d, r in events)
    count: dict[str, int] = {}
    for d, _ in evs:
        count[d] = count.get(d, 0) + 1
    good, flagged = [], []
    for d, r in evs:
        ok = math.isfinite(r) and r > 0 and r != 1.0 and count[d] == 1
        (good if ok else flagged).append([d, r if math.isfinite(r) else str(r)])
    return good, flagged


# ---- EDGAR --------------------------------------------------------------------------------------------------------

def cik_table(doc: dict, fallback: Optional[dict] = None) -> dict[str, int]:
    """Ticker -> CIK from company_tickers_exchange.json, then company_tickers.json for a ticker only it has;
    '-' class shares are read back as '.'."""
    f = doc["fields"]
    i, j = f.index("cik"), f.index("ticker")
    pairs = [(r[j], r[i]) for r in doc["data"]] + [(r["ticker"], r["cik_str"]) for r in (fallback or {}).values()]
    out: dict[str, int] = {}
    for tick, cik in pairs:
        if tick:
            out.setdefault(str(tick).upper().replace("-", "."), int(cik))
    return out


def _columns(block: dict) -> list[dict]:
    names = ("accessionNumber", "filingDate", "acceptanceDateTime", "form", "items", "fileNumber")
    n = len(block["accessionNumber"])
    cols = {k: block.get(k) or [""] * n for k in names}
    if any(len(v) != n for v in cols.values()):
        raise ValueError("submissions columns of unequal length")
    return [{k: cols[k][i] for k in names} for i in range(n)]


def older_files(doc: dict, since: str = HEADER_FIRST) -> list[str]:
    """Names of the older submissions files that reach ``since``."""
    return [f["name"] for f in doc["filings"].get("files", []) if f.get("filingTo", "9999") >= since]


def has_202(items: str) -> bool:
    return "2.02" in [x.strip() for x in (items or "").split(",")]


def submissions_record(doc: dict, older: Iterable[dict] = ()) -> dict:
    """One issuer: SIC, the 814- (BDC) file numbers seen, every date of each periodic form (the foreign private
    issuer test is point-in-time, B4), every 8-K or 8-K/A naming Item 2.02 since HEADER_FIRST, and what shows a
    predecessor CIK (the first filing date, former names, successor 8-K12 filings): the old CIK's 2.02s are not here."""
    rows = _columns(doc["filings"]["recent"])
    first = [f["filingFrom"] for f in doc["filings"].get("files", []) if f.get("filingFrom")]
    for block in older:
        rows += _columns(block)
    forms: dict[str, set] = {}
    bdc, acc, successor = set(), {}, set()
    for r in rows:
        if r["filingDate"]:
            first.append(r["filingDate"])
        if r["form"] in ANNUAL and r["filingDate"]:
            forms.setdefault(r["form"], set()).add(r["filingDate"])
        if str(r["fileNumber"] or "").startswith("814-"):
            bdc.add(r["fileNumber"])
        if r["form"].startswith(("8-K12", "8-K15")):
            successor.add((r["filingDate"], r["form"]))
        if r["form"] in ("8-K", "8-K/A") and has_202(r["items"]) and r["filingDate"] >= HEADER_FIRST:
            acc[r["accessionNumber"]] = dict(acc=r["accessionNumber"], form=r["form"], filed=r["filingDate"],
                                             json_accepted=r["acceptanceDateTime"])
    return dict(cik=int(doc["cik"]), name=doc.get("name", ""), sic=str(doc.get("sic") or ""),
                sic_text=doc.get("sicDescription", ""), entity_type=doc.get("entityType", ""),
                tickers=doc.get("tickers") or [], bdc_files=sorted(bdc),
                forms={k: sorted(v) for k, v in forms.items()}, first_filing=min(first) if first else "",
                former_names=doc.get("formerNames") or [], successor=[list(x) for x in sorted(successor)],
                earnings=sorted(acc.values(), key=lambda a: (a["filed"], a["acc"])))


_FIELD = re.compile(r"^\s*(?:<(ACCEPTANCE-DATETIME|TYPE|ITEMS|ACCESSION-NUMBER)>|"
                    r"(CONFORMED SUBMISSION TYPE|ACCESSION NUMBER|ITEM INFORMATION):)[ \t]*(.*?)\s*$", re.M)
_NAMES = {"CONFORMED SUBMISSION TYPE": "TYPE", "ACCESSION NUMBER": "ACCESSION-NUMBER", "ITEM INFORMATION": "ITEMS"}


def parse_header(text: str, acc: str) -> dict:
    """Acceptance time (Eastern, as the header prints it, 14 digits), form and items of one filing header, tag form
    or long form. Raises ValueError when the header is not the one asked for or has no readable time. ``match`` is
    whether it is an 8-K or 8-K/A with Item 2.02."""
    tags: dict[str, list[str]] = {}
    for m in _FIELD.finditer(text):
        tags.setdefault(m.group(1) or _NAMES[m.group(2)], []).append(m.group(3))
    stamp = tags.get("ACCEPTANCE-DATETIME", [""])[0]
    if not re.fullmatch(r"\d{14}", stamp):
        raise ValueError(f"{acc}: no acceptance time in the header")
    when = dt.datetime.strptime(stamp, "%Y%m%d%H%M%S")
    said = tags.get("ACCESSION-NUMBER", [])
    if (said and acc not in said) or (not said and acc not in text):
        raise ValueError(f"{acc}: the header is not for this filing")
    items = ["2.02" if i.lower() == ITEM_202 else i for i in tags.get("ITEMS", [])]
    form = tags.get("TYPE", [""])[0]
    return dict(acc=acc, accepted_et=when.isoformat(), type=form, items=items,
                match=form in ("8-K", "8-K/A") and "2.02" in items)


def header_url(cik: int, acc: str) -> str:
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", acc):
        raise ValueError(f"not an accession number: {acc!r}")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{acc}.hdr.sgml"
