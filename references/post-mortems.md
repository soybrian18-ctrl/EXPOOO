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
