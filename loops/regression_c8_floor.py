#!/usr/bin/env python3
"""C8 floor regression -- offline assertion of the ATR-floor raise (0.6 -> 0.65)
against every historical fill, the four boundary failures, KEY, and the C6
survivor sets. Multiples below are the AUTHORITATIVE decision-time values
established by the C8 spec study (c8_floor_sweep_study.py, 2026-09-17):
documented/logged value where one exists, candle replay otherwise; on a
replay/record conflict the RECORD wins (KEY standard -- candle replay can
anchor a different shelf than the live call did).

CONTRACT:
  part-a (hard): all TEN fills pass the raised floor -- ZERO flips. CCL 0.702
         is the minimum and the BINDING CONSTRAINT on any future raise
         (0.71+ flips it; 0.70 leaves 0.002).
  part-b (hard): all four boundary failures (the 0-for-4 tally) reject at
         screen under the raised floor. The zone between the worst failure
         (0.635) and the min fill (0.702) is EMPTY in the record and only
         0.067 wide.
  part-c (hard): KEY 8/19 (0.498, the C4 motivating row) still rejects.
  part-d (hard): C6 interaction -- removing sub-floor members from the
         recorded survivor sets changes NO historical outcome: the two sets
         that empty (RF 8/21, KGC 9/2) produced no trade anyway, and the
         9/10pm set's dropped member (GEN 0.615) failed its web gate live.
         Recomputed selections are asserted.
  RF DISCREPANCY (reported here per user directive 2026-09-17, not only in
  the spec): RF 8/25 fill is RECORDED at 1.537 (OBS-2 table, from live 8/25
  data) but candle-replays at 1.081 (recorded-stop view 1.100). The gap is
  unexplained in the record; the RECORD is used per the KEY standard. Either
  value clears any candidate floor by >0.38, so calibration is unaffected --
  but the inconsistency itself is real and stays visible in this output.
"""

from __future__ import annotations

FLOOR = 0.65          # must equal technicals.ATR_FLOOR_MULT (asserted below)
OLD_FLOOR = 0.6

# (ticker, decision date, authoritative multiple, source)
FILLS = [
    ("COLL", "2026-06-15", 1.102, "recorded stop 32.80 / replay ATR 1.2703 (pre-C4, computed 9/17)"),
    ("TENB", "2026-06-18", 0.877, "C4 expansion note; replay 0.877 confirms"),
    ("FRO",  "2026-07-29", 0.909, "EXPECTATIONS note; replay confirms"),
    ("AEO",  "2026-07-31", 0.874, "EXPECTATIONS note; replay confirms"),
    ("CCL",  "2026-08-11", 0.702, "EXPECTATIONS note -- MINIMUM, binding constraint"),
    ("ASO",  "2026-08-14", 0.897, "EXPECTATIONS note; replay confirms"),
    ("RF",   "2026-08-25", 1.537, "OBS-2 record -- REPLAY DISCREPANCY, see header"),
    ("F",    "2026-09-01", 0.813, "research log; replay 0.865/0.786 brackets it"),
    ("VTRS", "2026-09-10", 0.950, "research log '~0.95'; replay 0.941 / recorded-stop 0.918"),
    ("CNK",  "2026-09-10", 0.802, "first computed 9/17: (35.00-34.05)/1.1845; replay agrees exactly"),
]

BOUNDARY_FAILURES = [
    ("HAL", "2026-08-25", 0.609, "decayed 0.609 -> 0.349 in 26 min pre-presentation (OBS-3 #2)"),
    ("RF",  "2026-08-21", 0.626, "drifted through ceiling unfilled, report VOID"),
    ("KGC", "2026-09-02", 0.632, "approved, evaporated unfilled"),
    ("RSI", "2026-09-17", 0.635, "decayed 0.635 -> 0.542 in ~35 RTH min, rr 9.65 -> 11.47 (OBS-3 #3, trigger)"),
]

KEY_ROW = ("KEY", "2026-08-19", 0.498, "C4 motivating row (recorded live inputs)")

# C6 survivor sets holding members in [OLD_FLOOR, FLOOR) -- from
# regression_c6_selection.RUNS -- with the historical outcome of each.
C6_INTERACTION = [
    ("2026-08-21", [("RF", 6.818, 0.626, 0)], [],
     "set EMPTIES; historically RF drifted through its ceiling unfilled -- no trade either way"),
    ("2026-09-02", [("KGC", 4.141, 0.632, 0)], [],
     "set EMPTIES; historically KGC was approved and evaporated unfilled -- no trade either way"),
    ("2026-09-10pm",
     [("TFC", 4.110, 1.150, 0), ("CNK", 4.135, 0.810, 1),
      ("LNC", 4.653, 0.743, 2), ("GEN", 3.257, 0.615, 3)],
     ["LNC", "CNK", "TFC"],
     "GEN (0.615) drops; it FAILED its web gate live anyway (catalyst 61d). "
     "LNC/CNK/TFC all still gate (<=5); CNK still the sole passer -- outcome unchanged"),
]


def c6_order(survivors):
    key = lambda s: (-min(s[1], 6.0), -s[2], s[3])
    return [s[0] for s in sorted(survivors, key=key)][:5]


def main() -> int:
    from technicals import ATR_FLOOR_MULT
    ok = ATR_FLOOR_MULT == FLOOR
    print(f"C8 FLOOR REGRESSION (floor {FLOOR}, was {OLD_FLOOR}):")
    print(f"  live constant check: technicals.ATR_FLOOR_MULT == {ATR_FLOOR_MULT} "
          f"{'MATCH' if ok else 'MISMATCH -- harness and code disagree'}")

    print("\npart-a FILLS (all must pass; CCL is the binding minimum):")
    for tkr, date, mult, src in FILLS:
        good = mult >= FLOOR
        ok = ok and good
        print(f"  {tkr:5} {date}  {mult:.3f}  margin {mult - FLOOR:+.3f}  "
              f"{'PASS' if good else 'FLIP -- FLOOR TOO HIGH'}  ({src})")
    min_tkr, min_date, min_mult, _ = min(FILLS, key=lambda r: r[2])
    ok = ok and (min_tkr, min_mult) == ("CCL", 0.702)
    print(f"  MIN: {min_tkr} {min_mult} -- 0.71+ flips it; 0.70 leaves 0.002. BINDING CONSTRAINT.")
    print("  RF DISCREPANCY: recorded 1.537 vs candle-replay 1.081 (recorded-stop view 1.100) --")
    print("  unexplained gap in the record; RECORD used per KEY standard; >0.38 above floor either way.")

    print("\npart-b BOUNDARY FAILURES (all must now reject at screen):")
    for tkr, date, mult, note in BOUNDARY_FAILURES:
        good = mult < FLOOR
        ok = ok and good
        print(f"  {tkr:5} {date}  {mult:.3f}  {'REJECTED' if good else 'ADMITTED -- FLOOR TOO LOW'}  ({note})")
    worst = max(m for _, _, m, _ in BOUNDARY_FAILURES)
    print(f"  clearance above worst failure ({worst}): {FLOOR - worst:.3f}; "
          f"empty-zone width ({worst} .. {min_mult}): {min_mult - worst:.3f}")

    print("\npart-c KEY (C4 motivating row):")
    good = KEY_ROW[2] < FLOOR
    ok = ok and good
    print(f"  {KEY_ROW[0]} {KEY_ROW[1]}  {KEY_ROW[2]}  {'REJECTED' if good else 'ADMITTED -- BROKEN'}")

    print("\npart-d C6 INTERACTION (sub-floor members removed from recorded survivor sets):")
    for date, survivors, expected_sel, note in C6_INTERACTION:
        kept = [s for s in survivors if s[2] >= FLOOR]
        sel = c6_order(kept)
        good = sel == expected_sel
        ok = ok and good
        print(f"  {date:12} {len(survivors)} -> {len(kept)} survivors; selection {sel or '[]'} "
              f"{'MATCH' if good else f'MISMATCH (expected {expected_sel})'}")
        print(f"    {note}")
    print("  (pre-C4 sets carry no recorded multiples: CCL 8/11 known 0.702 passes; M 8/14 "
          "UNKNOWABLE offline -- documented, not asserted, per the BAX standard)")

    print(f"\nC8 FLOOR: {'ALL HARD CHECKS PASS (zero fill flips, all failures rejected, no outcome changes)' if ok else 'MISMATCH -- investigate'}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
