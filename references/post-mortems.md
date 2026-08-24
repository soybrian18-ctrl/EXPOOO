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
ceiling-room minimum in ATR terms). **Held at TWO datapoints as of 2026-08-24.**

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

**Why it matters:** a rising ATR multiple reads as improving quality and is
not, on its own, evidence of a better setup. The multiple is a ratio with entry
price in the numerator's path — it can be improved by deterioration in the
trade's economics. Any future rule that keys on the multiple (including a
higher C4 floor, per OBS-1) should be read alongside R:R and ceiling room, not
in isolation.

**Tracking:** record the multiple AND the R:R for boundary candidates that
survive to a later session, and note whether the multiple moved via the stop
(structure changed) or via the entry (price ran). No action from one case.

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
