#!/usr/bin/env python3
"""C6 selection regression -- offline replay of the gate-selection sort over
every historical survivor set (Python replica; research_workflow.js is
authoritative, same pattern as the C1 sector regression).

C6 (2026-09-11) retired first-pass-wins: ALL survivors are gated, bounded by
MAX_CANDIDATES = 5, selected when >5 by min(rr, SELECTION_RR_CAP=6.0) desc,
then stop_atr_multiple desc, then screen order. See the SELECTION_RR_CAP
lineage comment in research_workflow.js for the empirical basis of the cap.

CONTRACT:
  part-b1 (hard): with the historical maximum of 4 survivors per run, the
          top-5 selection must include EVERY survivor of EVERY run -- zero
          historical exclusions.
  part-b2 (hard): the key's ordering on the documented post-C4 sets matches
          the hand-computed expectations below (locks the arithmetic; order
          affected no historical outcome because all survivors were gated).
  part-c  (documented, NOT asserted): outcome audit of the three runs where
          first-pass-wins skipped survivors. NOTE ON BAX (2026-09-01): its
          web-gate outcome is UNKNOWABLE OFFLINE -- web gates are not
          replayable (same scope note as regression_gates.py) and BAX was
          never gated live before leaving the pool. It is deliberately
          recorded as UNKNOWABLE, not as a pass or a fail; do not "resolve"
          this row without a contemporaneous live evaluation.
"""

from __future__ import annotations

SELECTION_RR_CAP = 6.0
MAX_CANDIDATES = 5


def order(survivors: list[dict]) -> list[str]:
    """Replica of the C6 selection sort (JS authoritative)."""
    key = lambda s: (-min(s.get("rr") or 0, SELECTION_RR_CAP),
                     -(s.get("atr_mult") or 0),
                     s["idx"])
    return [s["ticker"] for s in sorted(survivors, key=key)][:MAX_CANDIDATES]


# Every pipeline run's survivor set (from logs/research_loop.txt + run journals).
# idx = position in screen/pool order among survivors' pool. atr_mult is None
# for pre-C4 runs (field did not exist live); the tie-break treats None as 0,
# which only matters inside a capped-rr tie -- none exists in pre-C4 sets.
RUNS = [
    ("2026-08-11", [{"ticker": "CCL",  "rr": 5.187,  "atr_mult": None,  "idx": 0}]),
    ("2026-08-12", []),
    ("2026-08-14", [{"ticker": "M",    "rr": 4.356,  "atr_mult": None,  "idx": 0}]),
    ("2026-08-19", [{"ticker": "KEY",  "rr": 8.395,  "atr_mult": None,  "idx": 0},
                    {"ticker": "HBAN", "rr": 4.509,  "atr_mult": None,  "idx": 1}]),
    ("2026-08-21", [{"ticker": "RF",   "rr": 6.818,  "atr_mult": 0.626, "idx": 0}]),
    ("2026-08-24", [{"ticker": "KMI",  "rr": 3.906,  "atr_mult": 0.743, "idx": 0}]),
    ("2026-08-25", [{"ticker": "RF",   "rr": 3.868,  "atr_mult": 1.005, "idx": 0}]),
    ("2026-08-26", []),
    ("2026-08-27", [{"ticker": "GIII", "rr": 7.702,  "atr_mult": 0.693, "idx": 0},
                    {"ticker": "TFC",  "rr": 5.695,  "atr_mult": 0.898, "idx": 1}]),
    ("2026-09-01", [{"ticker": "F",    "rr": 6.457,  "atr_mult": 0.948, "idx": 0},
                    {"ticker": "BAX",  "rr": 5.302,  "atr_mult": 1.101, "idx": 1},
                    {"ticker": "TFC",  "rr": 6.171,  "atr_mult": 0.801, "idx": 2}]),
    ("2026-09-02", [{"ticker": "KGC",  "rr": 4.141,  "atr_mult": 0.632, "idx": 0}]),
    ("2026-09-03am", []),
    ("2026-09-03pm", [{"ticker": "WY", "rr": 5.093,  "atr_mult": 1.010, "idx": 0}]),
    ("2026-09-08", []),
    ("2026-09-10am", [{"ticker": "AMRX", "rr": 5.334, "atr_mult": 0.915, "idx": 0},
                      {"ticker": "VTRS", "rr": 4.651, "atr_mult": 1.025, "idx": 1},
                      {"ticker": "LUV",  "rr": 12.859, "atr_mult": 0.905, "idx": 2}]),
    ("2026-09-10pm", [{"ticker": "TFC", "rr": 4.110,  "atr_mult": 1.150, "idx": 0},
                      {"ticker": "CNK", "rr": 4.135,  "atr_mult": 0.810, "idx": 1},
                      {"ticker": "LNC", "rr": 4.653,  "atr_mult": 0.743, "idx": 2},
                      {"ticker": "GEN", "rr": 3.257,  "atr_mult": 0.615, "idx": 3}]),
]

# part-b2 ordering expectations (hand-computed; post-C4 documented sets only).
# 9/01: F cap 6.0 > TFC cap 6.0 (tie -> multiple 0.948 vs 0.801 -> F first)
#       > BAX 5.302.
# 9/10am: LUV caps 12.859->6.0 (highest) > AMRX 5.334 > VTRS 4.651. Order had
#       no outcome effect (all 3 gated); recorded honestly: the key would gate
#       LUV first, and LUV FAILED its gate (FCF) -- gate-all is what protects
#       the outcome, not the ordering.
# 9/10pm: LNC 4.653 > CNK 4.135 > TFC 4.110 > GEN 3.257.
ORDERING = {
    "2026-09-01":   ["F", "TFC", "BAX"],
    "2026-09-10am": ["LUV", "AMRX", "VTRS"],
    "2026-09-10pm": ["LNC", "CNK", "TFC", "GEN"],
}

# part-c outcome audit (documented, not asserted).
OUTCOME_AUDIT = [
    ("2026-09-01",   "F approved first-pass; BAX + TFC skipped. Under C6 all three gate. "
                     "TFC: WOULD HAVE PASSED (stable fundamentals; passed identical gates "
                     "8/27 and 9/10). BAX: **UNKNOWABLE OFFLINE** -- never gated live, web "
                     "gates not replayable; deliberately NOT a pass and NOT a fail."),
    ("2026-09-10am", "AMRX approved first-pass; VTRS + LUV skipped. Replayed LIVE same day "
                     "(user-directed): VTRS PASSED and was chosen over AMRX; LUV FAILED "
                     "(FCF negative both legs). OUTCOME CHANGED."),
    ("2026-09-10pm", "TFC approved first-pass; CNK + LNC + GEN skipped. Replayed LIVE same "
                     "day: LNC FAILED (FCF), GEN FAILED (window by 1 day), CNK PASSED and "
                     "was ultimately taken after TFC voided out of band. OUTCOME CHANGED."),
]


def main() -> int:
    ok = True
    print("C6 SELECTION REGRESSION (offline replay of every historical survivor set):")
    for date, survivors in RUNS:
        sel = order(survivors)
        missing = [s["ticker"] for s in survivors if s["ticker"] not in sel]
        match = not missing
        ok = ok and match
        print(f"  {date:14} survivors={len(survivors)} gated={sel or '[]'} "
              f"{'MATCH (all selected)' if match else 'EXCLUDED: ' + str(missing)}")
    print("\npart-b2 ORDERING (documented post-C4 sets):")
    for date, expect in ORDERING.items():
        got = order(dict(RUNS)[date])
        match = got == expect
        ok = ok and match
        print(f"  {date:14} got={got} expected={expect} {'MATCH' if match else 'MISMATCH'}")
    print("\npart-c OUTCOME AUDIT (documented, not asserted):")
    for date, note in OUTCOME_AUDIT:
        print(f"  {date}: {note}")
    print(f"\nC6 SELECTION: {'ALL HARD CHECKS PASS (zero historical exclusions)' if ok else 'MISMATCH -- investigate'}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
