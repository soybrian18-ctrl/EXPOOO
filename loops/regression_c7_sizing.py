#!/usr/bin/env python3
"""C7 sizing regression -- offline replay of the %-of-NL position sizing
(POSITION_FLOOR_PCT=18 / POSITION_CAP_PCT=25) over every historical FILL,
plus book-capacity feasibility. Python replica; research_workflow.js is
authoritative (same pattern as the C1/C6 harnesses).

CONTRACT:
  part-a (hard): every historical fill still sizes to >= MIN_SHARES (3) and
         >= the 18% floor under the 25% cap -- ZERO flips. Share counts may
         differ from the fixed-$ rule; counts are reported, not asserted.
  part-b (hard): the floor <= 0.75 x cap invariant holds (18/25 = 0.72).
         This is WHY no waiver logic exists: the high-price conflict window
         (cap-bound 3-share position of a near-$50 name stranded below the
         floor -- ASO's exact profile) exists iff floor > 0.75 x cap. A band
         change that breaks the ratio silently reintroduces the window.
  part-c (hard): 3-position book feasibility at NL 650/700/750
         (cap+cap+floor <= 70% deployment cap), and 4-position INFEASIBILITY
         (4 x 18 = 72 > 70) -- the rules' position count is 3 by design.
  NOT RETROACTIVE: the 2026-09-11 two-position book (VTRS 27.9% + CNK 24.9%,
  sized under the old $-rule) stays at 2 -- headroom 17.1% < the 18% floor.
  C7 prevents recurrence; it does not unlock current headroom.
"""

from __future__ import annotations

FLOOR_PCT, CAP_PCT, MIN_SHARES, DEPLOY_CAP = 18.0, 25.0, 3, 70.0

# (ticker, old_shares, entry, NL at decision) -- all ten fills of the experiment.
FILLS = [
    ("COLL", 5, 34.20, 692.00), ("TENB", 7, 26.57, 680.50),
    ("FRO",  5, 38.60, 747.50), ("AEO", 11, 17.18, 747.00),
    ("CCL",  7, 27.70, 731.50), ("ASO",  4, 48.05, 725.37),
    ("RF",   6, 30.46, 710.00), ("F",   14, 13.98, 706.78),
    ("VTRS", 12, 16.41, 702.48), ("CNK",  5, 35.00, 702.57),
]


def size(entry: float, nl: float) -> tuple[int, float, bool]:
    cap_d, floor_d = CAP_PCT / 100 * nl, FLOOR_PCT / 100 * nl
    buyable = int(cap_d // entry)
    value = buyable * entry
    return buyable, value, buyable >= MIN_SHARES and value >= floor_d


def main() -> int:
    ok = True
    print(f"C7 SIZING REGRESSION (floor {FLOOR_PCT}% / cap {CAP_PCT}% of NL):")
    print("part-a FILLS REPLAY (verdicts must hold; share counts informational):")
    for tkr, old_sh, entry, nl in FILLS:
        sh, val, good = size(entry, nl)
        ok = ok and good
        print(f"  {tkr:5} old {old_sh:>2}sh -> new {sh:>2}sh (${val:6.2f} = {100*val/nl:4.1f}% of NL {nl:.0f}) "
              f"{'MATCH' if good else 'FLIP -- SIZING FAIL'}")
    inv = FLOOR_PCT <= 0.75 * CAP_PCT
    ok = ok and inv
    print(f"\npart-b INVARIANT floor <= 0.75 x cap: {FLOOR_PCT} <= {0.75*CAP_PCT:.2f} "
          f"{'MATCH (no conflict window at any NL/price)' if inv else 'BROKEN -- conflict window reintroduced'}")
    print("\npart-c CAPACITY:")
    for nl in (650.0, 700.0, 750.0):
        three = 2 * CAP_PCT + FLOOR_PCT <= DEPLOY_CAP
        four = 4 * FLOOR_PCT <= DEPLOY_CAP
        ok = ok and three and not four
        print(f"  NL {nl:.0f}: 3-position book (25+25+18={2*CAP_PCT+FLOOR_PCT:.0f}%) "
              f"{'FEASIBLE' if three else 'INFEASIBLE -- BROKEN'}; "
              f"4-position (4x18={4*FLOOR_PCT:.0f}%) "
              f"{'infeasible BY DESIGN (position count = 3)' if not four else 'FEASIBLE -- UNEXPECTED'}")
    print("\nNOT RETROACTIVE: 9/11 book (VTRS 27.9% + CNK 24.9% = 52.9% deployed, "
          "headroom 17.1% < 18% floor) stays at 2 positions until an exit or NL growth.")
    print(f"\nC7 SIZING: {'ALL HARD CHECKS PASS (zero fill flips)' if ok else 'MISMATCH -- investigate'}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
