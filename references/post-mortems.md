# Post-mortems & open observations

Durable record of incidents, near-misses, and patterns under observation that
are not (yet) rules. A pattern graduates to a spec (C-series) only with enough
data and explicit user approval; until then, entries here are tracked, not
acted on.

---

## OBS-1 — Boundary-case entries drift away before fill (opened 2026-08-21)

**Observation:** both tight-stop boundary cases so far resolved *against*
entry before a fill could happen:

| Case | Date | Entry / ceiling | Stop | ATR multiple | Outcome |
|------|------|----------------|------|--------------|---------|
| S    | 2026-07-30 | 17.90 / 17.93 | 17.01 | 0.949 (but only 3¢ of ceiling room) | DAY limit expired unfilled; price drifted to 17.975 > ceiling next session → dead |
| RF   | 2026-08-21 | 30.22 / 30.53 | 29.89 | **0.626 — C4 boundary pass** (floor 0.6, cleared by 0.026 ≈ 1.4¢/share) | Ran to 30.65 > ceiling while report awaited approval, same afternoon; rr collapsed 6.82 → 2.40 at the close → report VOID |
| KGC  | 2026-09-02 | 30.00 / 30.20 | 29.11 | **0.632 at screen — band** (0.661 at live re-verify; 20¢ of ceiling room) | Approved + placed; DAY limit expired unfilled at the close; opened 9/3 at 30.72, through the ceiling — the S shape exactly. $0 cost |

RF is the purer example: it was the first C4-era approval and sat 0.026 above
the freshly shipped 0.6 floor. The market resolved it within ~3 hours.

**Tracking rule (user-directed 2026-08-21, NOT a gate):** for every future
run, record each technical survivor's `stop_atr_multiple` in the research log
(the report already states them). Tag any survivor with multiple < 0.65
(within ~0.05 of the C4 floor) as **BOUNDARY** in its log line. Track whether
BOUNDARY candidates resolve against entry (ceiling breach, unfilled drift,
post-report gate failure) more often than comfortable clearers.

**Trigger for action:** a third boundary case resolving against entry the same
way → spec a rule (candidate: raise the floor toward 0.65-0.70, or add a
ceiling-room minimum in ATR terms). **TRIGGER FIRED 2026-09-03 — KGC is the
third datapoint (in scope: cleared every gate, presented, approved, evaporated
unfilled). Spec offered to the user; NOT built pending explicit approval.**
Calibration facts on hand: a 0.65 floor would have rejected RF (0.626) and KGC
(0.632) at screen while keeping every historical approval (min real approval
0.702 CCL, next 0.813 F); ceiling room on the three failures was 3¢/31¢/20¢
(0.03/0.59/0.15 ATR) vs F's 35¢ (0.95 ATR) which filled instantly and worked.

**Boundary-band tally (user-directed 2026-09-03, tracking only, NO threshold
change):** boundary-band names (multiple 0.60-0.65 at screen) are **0-for-3 on
producing a trade**: RF 8/21 (0.626) drifted through its ceiling unfilled,
KGC 9/2 (0.632) drifted through its ceiling unfilled, HAL 8/25 (0.609) decayed
through the C4 floor in 26 minutes pre-presentation. ATR_FLOOR_MULT stays 0.6
— C4 was calibrated to reject fake ratios from noise-tight stops and does that
job well; it is not to be overloaded with a second job (user ruling 9/3).

**SCOPE — what counts, and what explicitly does not (user-directed 2026-08-24):**
OBS-1 measures ONE failure mode: a candidate that **cleared every gate and was
presented to the user**, then evaporated before it could be filled. A candidate
the gates REJECTED is not a datapoint here, however boundary-adjacent its
numbers looked — that is the system working, not the pattern failing, and
merging the two would obscure what OBS-1 is measuring. **KMI (2026-08-24) is
therefore EXCLUDED**: it was approved on pre-market levels, but the post-open
re-verify caught it as a falling knife (multiple 0.743 → 0.29) and it was never
presented. Its record lives in PROC-1, where the pre-market incident belongs.

**Related history:** C4 lineage in `loops/technicals.py` (0.6 floor
calibration: approvals clustered 0.70-1.35, bad cluster ≤ 0.498); the S
no-chase precedent (2026-07-30/31); KEY (0.498, shelf broke in 2 sessions)
and HBAN (0.538, C4's first live catch, 8/21) as the sub-floor cohort.

---

## OBS-2 — How boundary cases resolve: worse entry, not better setup (opened 2026-08-24)

**Observation:** when a boundary pass stops being a boundary pass, the ATR
multiple improves for the wrong reason. RF is the first clean example:

| | Fri 2026-08-21 | Mon 2026-08-24 |
|---|---|---|
| Price | 30.22 (report entry) | 30.68 |
| Stop (same shelf, unbroken) | 29.89 | 29.90 |
| Risk/share | 0.33 | 0.78 |
| **ATR multiple** | **0.626 — boundary pass** | **1.537 — comfortable** |
| R:R to T1 32.47 | 6.82 | **2.295 — fails 3:1** |
| vs ceiling | at 30.53 ceiling | **30.68 > 30.54 — above** |

The structure never deteriorated: the shelf held, no knife, setup stayed valid.
The multiple more than doubled purely because the ENTRY got worse — price rose
away from a fixed stop. So a "healthier" stop distance was bought with exactly
the thing that kills the trade: a compressed ratio and a breached ceiling.

**Second case — TFC 2026-08-27 (same shape, 25 minutes):** screen 10:15 at
49.95, stop 49.20, risk 0.75, multiple **0.898**, rr 5.70 → re-verify 10:40 at
50.13, multiple **1.114**, rr 4.40 — and OUT of the $5-50 price band. The
multiple "improved" 24% purely through entry drift; the trade died of the same
drift. With KMI/HAL under OBS-3, **both directions of entry drift now have two
documented cases each**: price toward the stop (multiple falls through the
floor, R:R inflates — OBS-3) and price away from the stop (multiple rises,
R:R compresses, band/ceiling breached — OBS-2). A moving multiple with an
unmoved stop is entry drift, not setup change, in every observed case.

**Why it matters:** a rising ATR multiple reads as improving quality and is
not, on its own, evidence of a better setup. The multiple is a ratio with entry
price in the numerator's path — it can be improved by deterioration in the
trade's economics. Any future rule that keys on the multiple (including a
higher C4 floor, per OBS-1) should be read alongside R:R and ceiling room, not
in isolation.

**Tracking:** record the multiple AND the R:R for boundary candidates that
survive to a later session, and note whether the multiple moved via the stop
(structure changed) or via the entry (price ran). Two cases (RF 8/24, TFC 8/27), tracked only — no action.

---

## OBS-3 — Boundary-band approvals decay through the ATR floor intraday, pre-presentation (opened 2026-08-25)

**Distinct from OBS-1 and OBS-2.** OBS-1 measures candidates that were
PRESENTED and then evaporated. OBS-3 measures candidates that never reached
presentation: they cleared the prefilter in the 0.60-0.65 boundary band and
fell through the C4 floor within the hour, caught only by the post-run
re-verify. Two consecutive trading days, same signature:

| Case | Approved at | Re-verified at | Multiple | R:R | Elapsed |
|------|-------------|----------------|----------|-----|---------|
| KMI 2026-08-24 | 31.17, risk 0.554 | 30.68, risk 0.205 | **0.743 → 0.29** | 3.91 → **12.8** | ~80 min (incl. pre-market; see PROC-1) |
| HAL 2026-08-25 | 34.42, risk 0.550 | 34.19, risk 0.315 | **0.609 → 0.349** | 3.24 → **6.40** | **26 min, all regular-hours** |

**The signature:** price drifts DOWN toward a fixed stop → risk/share shrinks →
the ATR multiple falls through the floor → and the headline R:R *inflates*
because the denominator is collapsing. In both cases the arithmetic ratio got
more attractive precisely as the setup got worse. This is the same fake-ratio
mechanism as DVN/PFE, but arriving through decay-in-place rather than a knife.

**Note the symmetry with OBS-2:** OBS-2 is price moving AWAY from the stop
(multiple rises, R:R collapses, ceiling breached); OBS-3 is price moving TOWARD
the stop (multiple falls through the floor, R:R inflates). Both are the entry
moving, not the structure changing. Neither direction is good news, and in both
the R:R and the multiple move in OPPOSITE directions — which is exactly why
neither number can be read alone.

**Operational consequence (already in force):** the post-run re-verify is not
optional for boundary-band names. PROC-1 mandates it for pre-market runs; OBS-3
shows a 26-minute regular-hours gap was enough to flip HAL. **Re-verify every
boundary-band survivor immediately before presenting, regardless of when the
run started.**

**Trigger for action:** a third case → spec raising ATR_FLOOR_MULT (0.6 → 0.65+)
so the boundary band sits above the decay zone, and/or requiring a boundary-band
candidate to be re-verified stable across two reads before it can be presented.
Not before — two cases, tracked only.

---

## C5 STUDY (2026-09-03) — ceiling-room minimum gate: REJECTED BY THE DATA

**Proposed rule (user-directed spec):** separate gate requiring ceiling room
>= K x ATR14, where ceiling = (T1 + 3*stop)/4 and room = ceiling - entry.
Contract: reject the three drift-aways (S 7/30, RF 8/21, KGC 9/2) while
keeping F and every prior fill. ATR_FLOOR_MULT stays 0.6 regardless.

**Finding: the contract is UNSATISFIABLE.** Decision-time room/ATR across the
record (replay-verified rows + recorded live rows):

  FILLS:  TENB 0.035 (+3R WINNER) - AEO 0.061 - FRO 0.123 - ASO 0.136 -
          RF-8/25 0.162 - COLL 0.230 (+3R winner) - CCL 0.384 - F 0.955
  DRIFTS: S 0.037 - KGC 0.180 - RF-8/21 0.598

The classes fully interleave. Every K that rejects all 3 drifts (K >= 0.6)
flips 7 of 8 fills including BOTH 3R winners; even K = 0.05 flips TENB.
Root cause is algebraic, not empirical bad luck:

  room = risk x (rr - 3) / 4   =>   room/ATR = stop_atr_multiple x (rr-3) / 4

Ceiling room is not an independent dimension — it is a composite of the ATR
multiple and EXCESS R:R above the 3:1 gate. The system's normal approvals
enter near the 3:1 minimum (rr 3.1-3.7), so their room is structurally tiny
by construction. F (rr 7.7 -> room 0.95 ATR) is the outlier, not the standard.
"All three failures had room < 0.6 ATR" was true but incomplete: so did 7 of
8 fills. NO GATE SHIPPED; no gate at any threshold survives the regression
contract. C4 remains unchanged at 0.6.

**What actually separates fills from drift-aways in the record — placement
marketability, 7-for-7 vs 2-for-2:** every fill was placed with the live price
AT or BELOW the limit (marketable; CCL 27.665<27.70, RF-8/25 at-limit, F
13.91<13.98, ASO market order, etc.). Both placed-then-expired drifts were
RESTING BELOW MARKET at placement: KGC placed with price 30.07 vs a 30.00
limit; S's price had left its limit behind. (RF-8/21 never reached placement.)

**PROC-2 — ADOPTED 2026-09-03 (user-approved; process rule, no code):**
place the approved entry ONLY if the live price at placement is AT or BELOW
the approved limit (and below the ceiling). If price sits above the limit, do
NOT rest an order below the market — the approval lapses unfilled and the
name re-competes fresh on the next run. Enforced at the price-confirmation
step that precedes every manual placement.

Honesty note (user-directed): the separator is 7-for-7 on fills and 2-for-2
on drift-aways — a SMALL SAMPLE that could be coincidence. It is adopted
anyway because it changes no historical outcome and adds no risk: all 8
fills were already marketable at placement, and the two lapses (S, KGC)
produce the identical $0 result with no resting order in the book and no
overnight drift exposure. If a live case ever shows the rule costing a fill
that would have worked, log it here and revisit.

**Edge case #1 (2026-09-10, CNK):** the pre-placement confirm read 35.02 vs a
35.00 approved limit (2c over) -> rule said LAPSE. The user placed anyway and
the order FILLED AT THE EXACT LIMIT 45 seconds later — no chase, no rest, no
ceiling breach. The rule's letter produced a false negative on a 2c oscillation
that the drift cases (S 7c-plus, KGC 7c-then-$1, TFC band-crossers) never
resembled. One case, logged per this clause — possible refinement if a second
occurs: a small tolerance (e.g. price within 0.1 x ATR above the limit still
placeable, since the DAY limit itself caps the fill price) or a single re-poll
after 60s. NOT changed now.

---

## BACKLOG-1 — Rank technical survivors by R:R before gating (logged 2026-09-10, NOT built)

**Observation (user-directed):** the gate loop stops at the first full web-gate
pass, evaluating survivors in SCREEN order — additional technical survivors go
unevaluated. On 2026-09-01, BAX (rr 5.30) and TFC (rr 6.17) cleared the
prefilter and were never gated because F won the queue. The pool widening to
15-20 (2026-09-10) makes the gap larger.

**2026-09-10 — THE GAP CHANGED A LIVE DECISION.** The first wide-pool run
(19 screened) produced three survivors; the pipeline approved AMRX on queue
position alone (7th in screen order). User-directed catch-up gating found
VTRS a FULL PASSER that beat AMRX on insider signal (AMRX: $7.2M sold at the
entry zone, 0 buys; VTRS: CEO bought at $9-10, no 90d selling), R:R (4.95 vs
4.61), valuation (fwd P/E 6.5 vs 17.4), FCF ($1.96B vs $83M TTM), liquidity
and leverage — and the user chose VTRS over the pipeline's pick. (LUV, the
third survivor, failed the FCF gate.) Strongest possible argument for this
spec.

**Future spec candidate:** sort `survivors` by descending prefilter R:R before
the gate loop, so MAX_CANDIDATES budget is spent in R:R order — OR gate ALL
survivors and present a comparison when more than one passes (what the user
effectively did by hand on 9/10). Open design caution: OBS-2/OBS-3 show
inflated R:R accompanies deteriorating boundary setups — an rr-alone sort key
would prioritize exactly the fake-ratio profile C4 exists to catch; candidates:
sort only among atr_floor_ok survivors, cap the key, or gate-all-and-compare.
DO NOT BUILD without a spec + approval + regression.

## PROC-1 — Never run the research pipeline pre-market (opened 2026-08-24)

**Incident:** the 2026-08-24 run was launched at 08:14 ET, 76 minutes before
the open, so `technicals.py` computed every deterministic level from
pre-market quotes. KMI passed the full prefilter and the web gate on those
levels and came back as an approved candidate. Its full arc over 80 minutes:
08:15 pre-market 31.17, risk 0.554, multiple **0.743**, rr 3.91, valid setup →
approved; 08:48 pre-market 31.05, risk 0.428, multiple **0.574** → C4 fail;
09:37 post-open 30.68, risk 0.205, multiple **0.29**, **falling knife** (fresh
40-session low), fake rr 12.8 → rejected by three gates at once. Had the report
been presented and approved on pre-market numbers, the position would have been
a knife entry. (Deliberately NOT an OBS-1 datapoint — the gates caught it and
it was never presented; see the OBS-1 scope note.)

**Rule (process, not a code gate):** launch `/equity-research` only AFTER
09:30 ET. If a run is started earlier for any reason, re-run
`loops/technicals.py` on every survivor after the open and re-apply the
deterministic gates BEFORE presenting anything — pre-market levels are
report-invalid. The pre-market → post-open delta on 8/24 was large enough to
flip three separate gates on one name.
