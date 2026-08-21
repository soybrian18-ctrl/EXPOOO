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
ceiling-room minimum in ATR terms). Two cases are not enough data to act on —
explicitly noted by the user. Do not build anything from this entry alone.

**Related history:** C4 lineage in `loops/technicals.py` (0.6 floor
calibration: approvals clustered 0.70-1.35, bad cluster ≤ 0.498); the S
no-chase precedent (2026-07-30/31); KEY (0.498, shelf broke in 2 sessions)
and HBAN (0.538, C4's first live catch, 8/21) as the sub-floor cohort.
