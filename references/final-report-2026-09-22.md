# FINAL REPORT — speculative equity experiment (funded 2026-04-24, ended early 2026-09-22)

Source of truth: Schwab transaction history (47 transactions, account ****3908) and
order history, pulled 2026-09-22 10:56 ET after liquidation. Not the running logs.

## Headline
**Final value $697.40 vs actual funding $652.25 → +$45.15 (+6.92%) over 151 days.**
Final value = $696.32 withdrawn 9/22 + $1.08 residual. API verification at close:
zero positions, zero working orders, no strays.

Reconciliation: 652.25 funding + 44.41 trade P/L (fee-inclusive) + 0.60 WWW dividend
= 697.26 vs 697.40 actual → +$0.14 residual. A $2.00 "SMA_ADJUSTMENT" (5/1) is in the
ledger; if it were cash the gap would be −$1.86, so it is most likely margin
bookkeeping, not cash. Immaterial either way.

Ending detail: AR and RRC were NOT liquidated — both stopped out at the 9/21 open
(gap-downs through their stops, −22c and −38c slippage). VTRS was sold at market
9/22 10:54 ET (+$8.82, the only end-of-experiment liquidation).

## Every trade (19 round trips; P/L from transaction net amounts; R = P/L ÷ initial bracket risk)

| # | Sym | Who | Entry | Exit | Qty | Entry px | Exit px | P/L | Risk $ | R | Exit type |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | EVER | sys | 04-30 | 04-30 | 6 | 15.57 | 14.76 | −4.86 | 4.86 | −1.00 | stop-limit |
| 2 | MGNI | sys | 04-30 | 06-15 | 15 | 12.89 | 16.50 | +54.14 | 10.35 | +5.23 | TARGET 16.50 |
| 3 | WWW | OWN | 04-30 | 08-12 | 6 | 16.85 | 17.85 | +6.00 | 6.60 | +0.91 | raised stop (above entry) |
| 4 | TASK #1 | sys | 05-07 | 05-07 | 22 | 6.37 | 6.26 | −2.42 | 2.20 | −1.10 | stop |
| 5 | TASK #2 | sys | 05-08 | 05-08 | 22 | 6.31 | 6.21 | −2.20 | 2.42 | −0.91 | stop, gap open |
| 6 | APPN | sys | 05-11 | 05-13 | 5 | 21.34 | 19.50 | −9.20 | 9.20 | −1.00 | stop |
| 7 | CXM | sys | 06-09 | 06-18 | 26 | 5.33 | 4.96 | −9.63 | 8.58 | −1.12 | stop-limit, gap open |
| 8 | COLL | sys | 06-16 | 07-07 | 5 | 34.20 | 38.40 | +21.00 | 7.00 | +3.00 | TARGET 38.40 |
| 9 | TENB | sys | 06-18 | 06-29 | 6 | 26.50 | 30.90 | +26.40 | 7.80 | +3.38 | TARGET 30.90 |
| — | *gate stack live 2026-07-23* | | | | | | | | | | |
| 10 | FRO | sys | 07-30 | 08-11 | 5 | 38.60 | 37.355 | −6.22 | 6.30 | −0.99 | stop |
| 11 | AEO | sys | 07-31 | 08-12 | 11 | 17.075 | 16.56 | −5.67 | 5.77 | −0.98 | stop |
| 12 | CCL | sys | 08-11 | 08-19 | 7 | 27.665 | 26.95 | −5.01 | 5.00 | −1.00 | stop |
| 13 | ASO | sys | 08-14 | 08-17 | 4 | 47.91 | 46.555 | −5.42 | 5.72 | −0.95 | stop, gap open |
| 14 | RF | sys | 08-25 | 08-31 | 6 | 30.425 | 29.905 | −3.12 | 3.15 | −0.99 | stop |
| 15 | F | sys | 09-01 | 09-09 | 14 | 13.98 | 13.69 | −4.06 | 4.20 | −0.97 | stop |
| 16 | VTRS | sys | 09-10 | 09-22 | 12 | 16.355 | 17.0901 | +8.82 | 4.14 | +2.13 | LIQUIDATION (market) |
| 17 | CNK | sys | 09-10 | 09-15 | 5 | 35.00 | 34.06 | −4.70 | 4.75 | −0.99 | stop |
| 18 | AR | sys | 09-17 | 09-21 | 4 | 35.71 | 34.561 | −4.60 | 3.72 | −1.24 | stop, gap open (−22c) |
| 19 | RRC | OWN | 09-17 | 09-21 | 4 | 39.11 | 37.90 | −4.84 | 3.32 | −1.46 | stop, gap open (−38c); UNAPPROVED entry |

Sum = +$44.41 (matches TRADE net exactly). R uses the initial bracket stop at entry
(WWW's and MGNI's stops were later raised; initial risk is what was planned).
Exit mix: 3 targets, 1 raised stop, 1 liquidation, 14 stops (5 of them gap-opens).

## Statistics — three ways, split at the gate stack (entries < 7/23 vs ≥ 7/29)

| Set | n | W–L | Win % | Avg win | Avg loss | Payoff | Net | ΣR | Avg R |
|---|---|---|---|---|---|---|---|---|---|
| **ALL trades** | 19 | 5–14 | 26.3% | +23.27 | −5.14 | 4.53 | **+44.41** | −0.05 | 0.00 |
|   pre-gate | 9 | 4–5 | 44.4% | +26.88 | −5.66 | 4.75 | +79.23 | +7.39 | +0.82 |
|   post-gate | 10 | 1–9 | 10.0% | +8.82 | −4.85 | 1.82 | −34.82 | −7.44 | −0.74 |
| **SYSTEM only** (excl WWW, RRC) | 17 | 4–13 | 23.5% | +27.59 | −5.16 | 5.34 | **+43.25** | +0.50 | +0.03 |
|   pre-gate | 8 | 3–5 | 37.5% | +33.85 | −5.66 | 5.98 | +73.23 | +6.48 | +0.81 |
|   post-gate | 9 | 1–8 | 11.1% | +8.82 | −4.85 | 1.82 | −29.98 | −5.98 | −0.66 |
| **SYSTEM excl MGNI** | 16 | 3–13 | 18.8% | +18.74 | −5.16 | 3.63 | **−10.89** | −4.73 | −0.30 |
|   pre-gate | 7 | 2–5 | 28.6% | +23.70 | −5.66 | 4.19 | +19.09 | +1.25 | +0.18 |
|   post-gate | 9 | 1–8 | 11.1% | +8.82 | −4.85 | 1.82 | −29.98 | −5.98 | −0.66 |

Own picks, reported separately: WWW +6.00 (+0.91R, plus $0.60 dividend); RRC −4.84 (−1.46R).

What the split shows, stated plainly:
- All realized profit came from three pre-gate target hits (MGNI +5.2R, COLL +3.0R, TENB +3.4R).
  Every post-gate entry that reached an exit on its own bracket was a stop (8 of 9 system
  entries); the one post-gate win was VTRS, sold at liquidation at +2.1R, never at target.
  Zero targets were hit after 2026-07-23.
- The gate stack changed WHICH entries were taken, not how much a loss cost: post-gate
  losses ran −0.95R to −1.24R (mean −1.02R), and none was a falling knife or a fake ratio —
  they were honest, tightly anchored stops that got hit. The specific failure modes the
  gates were built against (DVN/PFE fake ratios, KEY-style noise-stops, KMI knives,
  boundary decay) did not recur in the fills.
- Excluding MGNI, the system was net negative (−$10.89, −4.7R); the experiment's return
  rests on one 5R outlier and two 3R winners from the first seven weeks.
- n=9 post-gate is too small, and it overlaps the Aug 12 consumer-discretionary sweep and
  the Sep 21 gap-down that took AR/RRC; market regime and gate effect cannot be separated
  from this data. What can be said: loss containment worked; entry selection under the
  gates did not produce targets.

## Structural fixes — incident → rule → what it caught live

- **Falling-knife gate (2026-07-01, DVN/PFE).** Pre-fix mechanics printed 20.4:1 and 8.19:1
  from stops set inside fresh lows. Rule: support must be ≥5 sessions old; a fresh
  40-session low within 5 sessions is untradeable. Caught live: KMI 8/24 (multiple
  0.743→0.29 at the open), YOU 9/17 (fake rr 23.6), FHN 9/17 (6.77), CSX 9/17, GFS 9/17.
- **P1 aged-support anchor (2026-07-23).** The window-minimum stop formula inflated
  risk-per-share on healthy names. Rule: stop under the nearest tested shelf floor (or
  pivot) minus 0.2 ATR. Regression 16/16 hard rows; every post-7/23 fill stopped at its
  planned level (−0.95..−1.00R) except the two gap-opens.
- **C1 sector cap (2026-08-12).** One consumer-discretionary move stopped WWW and AEO
  16 minutes apart and put CCL within 3% the same session. Rule: max two open positions
  per GICS sector; a 2nd-in-sector is flagged. Enforced deterministically via
  held_sectors on every run; CCL's own approval retro-fails in regression (FAIL-INTENDED).
  No third-in-sector candidate arose live; the AR+RRC Energy pair on 9/17 was the flag case.
- **C4 ATR stop floor 0.6 (2026-08-21, KEY).** KEY passed the shelf detector at 0.498×ATR
  with rr 8.40 and broke within two sessions. Rule: risk/share ≥ 0.6×ATR14, pure reject
  (deepen-anchor alternative rejected — it would have approved KEY at 21.6). Caught live:
  CDE 0.435 (9/16), CNX 0.591 (9/16), SM 0.585/0.47 (9/17), CSX 0.201; plus HAL and RSI
  via the re-verify.
- **C6 gate-all-and-compare (2026-09-11).** First-pass-wins changed three live outcomes on
  9/10 (VTRS chosen over the pipeline's AMRX; LNC's 4.65 rr died on FCF; CNK surfaced
  4th in queue). Rule: gate every survivor (top-5 by min(rr,6) → multiple → screen
  order), dossier every passer, user picks. Caught live: 9/16 SBLK (higher rr) failed on
  catalyst while HL passed; 9/17 four passers compared head-to-head.
- **C7 percentage sizing 18–25% (2026-09-14).** The $150–200 rule jammed the book at two
  positions with $120 of headroom. Rule: 18–25% of net liq, floor ≤ 0.75×cap so a
  3-share $48 name cannot strand below the floor; capacity 3 by design; not retroactive.
  Live: HL 9 sh, AR 4 sh, DVN 3 sh all sized cleanly.
- **C8 ATR floor raised to 0.65 (2026-09-17).** Screen multiples 0.60–0.65 went 0-for-4
  on producing a trade (HAL, RF, KGC, RSI); RSI decayed 0.635→0.542 in 35 minutes.
  Calibration on all ten fills: CCL 0.702 is the binding minimum, the empty zone is 0.067
  wide, historical fill cost zero. Caught live within hours: CMG rejected at screen at
  0.634 (rr 7.17).
- **PROC-1 (2026-08-24).** A pre-market launch approved KMI on pre-market levels; it was a
  knife at the open. Rule: never launch before 9:31 ET; re-verify every passer live
  immediately before presenting. Caught: HAL 8/25 (0.609→0.349 in 26 min), RSI 9/17 —
  3-for-3 with KMI.
- **PROC-2 (2026-09-03).** Three approved names (S, RF, KGC) evaporated while resting
  limits sat below market; fills were 7-for-7 marketable, lapses 2-for-2 drifts. Rule:
  place only if live price ≤ approved limit, never rest. Edge case #1 CNK (2¢ over,
  filled at the limit 45 s later). Deviation 9/17: AR entered before the approval word and
  rested 33 minutes — the PROC-3 candidate (no entry before "approved"; bracket template
  verified) was noted, not built.
- **Negative results kept out of the stack:** P2 breakout mode retired (20% hit rate ≈
  breakeven); C5 ceiling-room gate proven uncalibratable (room/ATR = multiple×(rr−3)/4
  flips every 3R winner); two-read stability rule declined (re-verify owns the job).

## Process incidents on the record
- Platform qty-100 default: three REJECTED stop legs at qty 100 (AEO, RF; ASO stop at 59.5)
  — every one caught by the API 8-check; clean from F onward.
- 9/17: AR and an unapproved RRC entered 2½ hours before "approved"; AR's first bracket was
  a TRIGGER chain with a SELL_SHORT stop (no active protection for ~2 hours); fixed and
  re-verified 8/8. RRC held out-of-system by user decision; both gapped through their stops
  on 9/21.
- Three refresh-token deaths (7-day TTL), each caught by the monitor + live probe.
- One silent no-op file edit (9/10) whose commit message claimed a section it lacked;
  fixed with an honest follow-up commit.

## Automation
launchd agents com.stockmonitor.{dailybriefing, eodportfolio, morningstopcheck,
tokenrefresh} were booted out and DISABLED on 2026-09-22 so they do not fire against an
empty account (or reload at next login). Plists kept in ~/Library/LaunchAgents. Reload:
`launchctl enable gui/$(id -u)/<label> && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist`.
com.lisb.nightlybriefing (different project prefix) was left untouched.
