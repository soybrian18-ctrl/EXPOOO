# Phase 2 spec: backtest, nightly forward test, paper verification, January decision

Status: **APPROVED 2026-11-10 (v3)**, with your changes: a 17.5% position cap,
GICS sectors, the random-entry test as a pass rule, and the fixed Method 2
extension. Section 9 records the approvals. Uncommitted until you give the
word. The build has started with the read-only data checks (section 8, B1).

There is no live trading in Phase 2. The only orders are paperMoney orders you
place yourself, and nothing in Phase 2 code can place an order (section 2).

How this draft was checked:
- a research pass (Schwab API, SEC EDGAR, spreads, PEAD/breadth evidence,
  thinkorswim mechanics);
- a five-lens adversarial review: look-ahead, fills/costs, statistics,
  fidelity to your instructions, and operations. It produced 59 findings
  (4 critical). The accepted ones are folded into the text below.
  The additions to your fixed pass rules are in 3.8, as you approved them.

Calendar (NYSE sessions, pinned in params):
- **Forward logging go-live:** target Mon 2026-11-23. That leaves 37 sessions
  to 2027-01-15, and each week of slip costs about 5 of them.
- **IS pick committed:** early December.
- **Sealed OOS run:** after the 2026-12-30 close. That session is the time
  exit for the last possible OOS fill (2026-10-30), so every OOS trade is
  closed when it runs.
- **Decision report:** Fri 2027-01-15, after the close (Mon 01-18 is a
  holiday).
- **Funding:** late January, yours, only if section 6 holds.
- **Method 2 extension (fixed 2026-11-10):** if M2 has not reached the minimum
  forward trade count by 01-15, its forward test runs through Q4 earnings
  season, to the close of Fri 2027-03-12, and it is decided then. The minimum
  is never lowered (section 6).

---------------------------------------------------------------------------

## 1. Rules reconciliation (binding rules vs Phase 2)

`references/trading-rules.md` is binding and still describes the September
account. Every conflict with your Phase 2 instructions:

| Topic | trading-rules.md | Phase 2 | Approved (D1) |
|---|---|---|---|
| Risk per trade | 2% of account value | 1% of a fixed $1,500 basis = $15 | supersede |
| Max positions | 3 | 4 | supersede |
| Position size | 18-25% of net liq | risk-sized; 25% cap; 3-share minimum | supersede, with the cap at **17.5% ($262.50)**. Your fix: under the 70% deployment cap a 25% cap left the fourth slot unfillable; 4 x 17.5% = 70% fits exactly |
| Deployment | 60-70%; >=30% cash; never fully deployed | not stated | **70% cap kept ($1,050)**. With four positions capped at 17.5% it can't bind on its own; it stays as a guard |
| Price band | prefer $5-50 | $5-100 | supersede. **Checked against the 3-share minimum at the 17.5% cap:** 3 shares fit only up to a ceiling price of **$87.50** (3 x $87.50 = $262.50), and only when risk per share (ceiling - stop) is **<= $5.00**. Names above that stay in the universe, breadth and every-signal statistics but are skipped for paper as unsizable; rule A4 tests the tradeable subset |
| Liquidity | 300k shares ADV30 | 500k shares | supersede (stricter) |
| Sector cap | <=2 per GICS sector, 2nd flagged | <=2 per sector | same rule, same meaning: SEC industry (SIC) codes are **mapped to the 11 GICS sectors** (section 4, sector map), so the C1 cap keeps its meaning |
| Target | >=3:1 "at real price levels" | not stated | fixed 3R target (D3); the 3:1 minimum is kept |
| Stop anchor | support >=5 sessions old; "a low set within the last 5 sessions is not support" | M2: stop below the gap-day low | **M2 violates the anchor rule by construction** (the gap-day low is 0 sessions old): explicit M2 exception |
| Min stop distance | 0.65 x ATR (C8) | stops >=1.0 ATR | subsumed |
| Falling knife | never enter | not stated | applies to both methods |
| Web gates | live pipeline | "technical rules only" | dropped for Phase 2, so what is paper-traded is what is tested |
| 9-section report + "approved" gate | before every trade | paper orders come from a nightly job | paper tickets carry no 9-section report or "approved". Each ticket shows the sizing math, deployment and cash after, positions after, and any 2nd-in-sector flag (the behavioral standards). The funded-account procedure is decided in January |
| Margin | none | none | the deployment cap makes margin impossible. **paperMoney is set to Cash (done 2026-11-10)**, so a short-sale construction error is rejected visibly. Note: the live account reports as a MARGIN account, where the same error would open a short instead |
| Paper account size | n/a | paperMoney's lowest cash setting is $100,000 | the paper account stays at $100,000 and its buying power is ignored. **Every paper trade is sized and tracked on the fixed $1,500 basis** in the ledger. The 8-check fails any quantity that doesn't match that sizing (section 5, item 1) |

These rows are written into trading-rules.md as a separate "Phase 2" block. It
supersedes the September rules for the paper phase, and the September block
stays, marked historical.

---------------------------------------------------------------------------

## 2. Architecture and hard contracts

**One signal path.** Everything that decides a signal, an order, a fill or an
exit is a pure function in `loops/phase2/`, called by both the backtester and
the nightly job. (The package is named "phase2" rather than "p2" because P2 is
the retired breakout mode in technicals.py.)

| Module | Role |
|---|---|
| `params.py` | every number in this spec plus the NYSE calendar (holidays and 13:00 closes, 2021-2027); hash printed in every report and log line |
| `bars.py` | Schwab daily candles. Explicit America/New_York date conversion, never machine-local time and never Central. B1 found older bars stamped 06:00 UTC and today's bar stamped 05:00 UTC; only New York time dates both correctly. Bars are keyed by that date, not by the raw timestamp. endDate=now and needExtendedHoursData=false on every call (the flag changed nothing in the B1 sample). A completed-session guard (section 4). Throttled to <=100 requests/minute under one shared lock (the app has about 120/min across all jobs) |
| `universe.py` | symbol list plus security type, point-in-time eligibility, split factors for as-traded tests |
| `events.py` | M2 earnings events (EDGAR header acceptance times, or the price/volume fallback) |
| `signals.py` | M1/M2 tests, breadth, bracket construction. Calls `technicals.compute_levels` **unchanged** |
| `fills.py` | the order state machine and pessimistic fill model (3.4). Used by the backtest, the forward tracker and the portfolio simulations |
| `backtest.py` / `nightly.py` / `paper.py` | runners and the paper ledger |

Contracts, each enforced by a test:
- **Parity:** `nightly.py --as-of DATE` on stored bars reproduces the
  backtest's signals, orders and order states for DATE exactly, all 12
  variants. Dates are drawn from the IS and from post-go-live sessions only
  (OOS seal, 3.7).
- **Window invariance:** `compute_levels` on the full history equals
  `compute_levels` on the trailing 120 bars, which both paths pass.
- **One cutoff evaluation:** the forward window and every analog band window
  evaluate trades open at their cutoff through the same `fills` function.
- **Known-answer fills:** run at B1, before the freeze (3.4). The model must
  never be more optimistic than Schwab's real fills on the experiment's 14
  stop-outs.
- **No orders possible:** phase2 code sees only a wrapped client exposing
  price history, quotes, instruments, account numbers and order *reads*. A
  test fails if the package references place_order, replace_order,
  cancel_order or order_executor.
- **Existing harnesses** (gates, C6, C7, C8, the 28 unit tests) stay green;
  technicals.py is untouched.

What the existing harness contributes: `breakout_replay.py` supplies the
pattern (as-of truncation, `compute_levels` as the pure core, stop-first when
both levels print in one bar). It is not used for fills. It enters at the
signal close (not executable after the close), fills stops at the stop price on
gap-throughs, charges no costs, and covers 43 hand-picked names. All four are
fixed in the new harness, and the file stays as it is. (P2 was retired on that
harness's 20% hit rate; under pessimistic fills that can only get worse, so the
retirement stands.)

---------------------------------------------------------------------------

## 3. Part 1: backtest

### 3.1 Data and universe

**Window and bars**
- Signals 2022-01-03 to 2026-10-30. Bars from 2021-01-04 for warm-up, through
  the 2026-12-30 close for the sealed OOS run.
- Schwab pricehistory, one request per symbol, about 5,600 requests, roughly an
  hour.
- SPY is pulled for the M2 fallback filter and for reporting.

**Symbols.** Nasdaq Trader `nasdaqlisted.txt` + `otherlisted.txt` (about 5,600
names after the filters below). Columns are parsed by header name, and names
are not filtered by exchange code (Texas exchange listings carry undocumented
codes).
- Security type uses Schwab's `assetSubType` where it is present: drop ETF,
  ETN, CEF, PRF, WAR, RGT and UIT. B1 showed it is incomplete. It is empty for
  some real common stocks (the REIT O) and for royalty trusts (PBT), and it
  labels MLPs (EPD) as common stock. So it can exclude a name but can never be
  the only test.
- Every remaining name must also pass the directory rules: Test Issue = N,
  ETF = N, the NASDAQ-symbol suffix rules (`- + = ^ # $ * % ~`), a descriptor
  rule on the security name, and a name rule for ETNs flagged ETF = N.
- Excluded by name (approved D6): MLP units and royalty trusts (they issue
  K-1 tax forms) and SPAC shares ("Acquisition Corp").
- Every excluded symbol is logged with its reason.

**As-traded eligibility on day t** (critical review finding)
- Rules: as-traded close(t) between $5 and $100; as-traded average volume over
  the 30 sessions ending t-1 >= 500,000; bars present for >=58 of the prior 60
  sessions; >=60 sessions of history.
- **B1 confirmed that Schwab back-adjusts both price and volume for splits:**
  - NVDA's 2024-06-07 bar reads $120.89 on 412M shares; it traded at $1,208.88
    on about 41M.
  - CMG's 2024-06-25 bar reads $65.66 on 24M shares; it traded near $3,283 on
    about 480k.
  - AMC's bars before its 2023 1:10 reverse split read $19-40; it traded at
    $2-4.
- Adjusted prices would therefore admit names that later forward-split during
  their run-ups, and pre-reverse-split losers at inflated prices.
- So eligibility, and the share counts in the portfolio simulations, use
  as-traded values: adjusted price x the cumulative split factor after t, and
  adjusted volume / that factor.
- The split table comes from Yahoo split events via yfinance (approved D6).
  It is validated against the Schwab series at every split date; the three
  splits above are the first test cases.
- Signals, ATR and R stay on the adjusted series, since they are scale-free.

**Data quality.** This is a trailing, point-in-time rule (the >=58-of-60 bar
test), never a whole-symbol drop based on future data.
- Impossible bars are dropped: low > high, close outside the range, or zero
  volume.
- A missing bar during a pending or open trade means no fill that session; the
  next bar goes through the normal rules, so it fills at the open if that open
  is through the stop.
- Trades that span a gap in the bars are listed.

**Survivorship.**
- **B1 confirmed delisted names are missing.** SIVB, SIVBQ, FRC, BBBY and
  BBBYQ all return an empty history and no instrument record. Only FRCB, First
  Republic's over-the-counter successor, returns bars, from 2023-01-03.
- Tickers also get reused, so any symbol's identity is checked by CUSIP and
  description before its history is trusted.
- Every report page carries the survivorship flag with its likely direction:
  **optimistic for M1** (probably for M2 too), concentrated in 2022-2023. A
  name that collapsed and delisted spent its above-$5 decline inside the
  universe, offering pullback entries that failed, and those trades are
  missing.
- The report counts delisted issuers from EDGAR Form 25 / 25-NSE filings and
  adds a report-only stress row (missing trades at -1R).

**Corporate actions.**
- Dividends are not credited, which is slightly conservative.
- Schwab may lower GTC stop and limit prices by the dividend on ex-dates
  (FINRA 5330). The forward checks treat a level lowered by exactly the
  dividend as expected.

### 3.2 Signals

Common to both methods:
- Inputs are bars through the close of day t only.
- Each variant runs its own per-ticker state machine: one pending or open trade
  per ticker per variant. A new signal replaces an unfilled pending order and
  starts its own window; with an open position, a new signal is ignored.
- Eligibility is tested on the signal day.
- Both methods enter on a **buy stop 1 cent above the signal day's high**. The
  methods differ only in what qualifies the signal day, and exits are identical
  (3.4).
- ATR = ATR14 exactly as `compute_levels` computes it, at the signal close.

**M1: pullback to an aged shelf (current technical rules + a touch rule)**

`L = compute_levels(bars[t-119..t], last = T)`, with T = high(t) + $0.01.
Day t qualifies if:
1. `L.valid_setup` (no knife; aged shelf/pivot >=5 sessions old; support held);
2. `L.atr_floor_ok` (structural risk >= 0.65 ATR, C8);
3. `L.rr_to_resistance >= 3.0` against the structural stop (the current rule,
   so the setup filter is unchanged);
4. **touch:** low(t) <= support_anchor + 0.25 x ATR. The live system relied on
   the LLM screen to find names near support; a mechanical test needs this
   rule;
5. eligible(t).

S0 = `L.suggested_stop` (shelf floor - 0.2 ATR). Window: sessions t+1 to t+3.
The order is canceled at any close below the shelf floor.

**M2: post-earnings gap continuation.** Day t qualifies if:
1. **Earnings event** (D5):
   - **EDGAR mode** (US filers): an 8-K or 8-K/A with Item 2.02 whose
     acceptance time is after 16:00 ET on the prior session and no later than
     16:00 ET on t. The time is read from the filing's SGML header in Eastern
     time, because the submissions-JSON timestamps have been unreliable since
     October 2026, with a canary check on a known filing. A US filer with no
     match is not an event; those gaps are counted to measure recall.
   - **Fallback mode:** foreign private issuers (20-F/40-F/6-K filers, whose
     6-Ks carry no item codes).
2. **Gap:** open(t) - close(t-1) >= max(3% of close(t-1), 1.0 x ATR at t-1).
3. **Volume:** volume(t) >= 3.0 x the 30-session average ending t-1.
4. **Held:** low(t) > close(t-1), and close(t) at or above the midpoint of
   day t's range.
5. **Falling-knife rule** on bars through t.
6. **Fallback mode only:** SPY's own gap < +1.0%, and no "detected event" (a
   day meeting items 2-4 plus the SPY test) for the ticker in the prior 40
   sessions.
7. eligible(t).

S0 = low(t) - 0.2 ATR. Window: sessions t+1 to t+5. The order is canceled at
any close below low(t). M2 results are reported split by detector source.

### 3.3 Breadth filter

- B(t) = the share of eligible(t) names with close(t) strictly above the
  50-session simple average (closes t-49 through t).
- **Breadth on:** a signal on a day with B(t) < 50% is blocked: it is logged,
  with no order and no paper ticket. Any pending order is canceled at the close
  of any day with B < 50%, so every fill on day d has B(d-1) >= 50%. The
  nightly scan does the same.
- **Breadth off:** the filter is ignored.

### 3.4 Order state machine, fills and costs

**Order** (cents; rounding always conservative):
- trigger **T** = high(t) + 0.01;
- ceiling **C** = floor(T + 0.25 ATR);
- stop **S** = floor(min(S0, T - k x ATR)) (D2);
- target **P** = ceil(T + 3(T - S)) (D3);
- planned risk per share = T - S.
- Paper tickets specify trigger activation on the last trade (STD), so live
  triggers match the daily-bar rule.

**Entry session d** (inside the window, not canceled, breadth-gated):

| Case | Result |
|---|---|
| T <= open <= C | filled at the **open** (opening fill) |
| open < T <= high | filled at **T** (intraday trigger) |
| open > C | triggered: the order is now a resting limit at C. Filled at **C** if the low trades through C (low <= C - 0.01). Otherwise **canceled after the close**, and the nightly prints CANCEL "triggered-unfilled" before the next open. A gap above the ceiling is a missed trade |
| otherwise | no fill |

**Exits on the entry session** (the OCO is live from the fill):
- **Stop:** low <= S means stopped at S. After an opening fill or a fill at C,
  the low necessarily came after the fill; after an intraday trigger, assuming
  so is the pessimistic choice.
- **Target:** high >= P + 0.01 means target at P, credited only on the
  opening-fill and intraday-trigger paths (the high necessarily came after the
  fill). On the fill-at-C path the high may have printed before the fill, so
  credit only if close >= P + 0.01.
- If both, the stop wins.

**Later sessions,** in order:
1. open <= S: stopped at the **open** (gap-through);
2. open >= P: target at P (no gap bonus);
3. low <= S: stopped at S;
4. high >= P + 0.01: target at P.

Resting limits need a 1-cent trade-through; stops and triggers fire on a touch.

**Time exit.** The fill session is session 0. Full sessions start the next
session, and half days count. A trade still open after session 40 is sold at
the open of session 41, with the OCO rules applied first, so the 3R cap is
exact.

**Costs** (every trade pays both legs; prices come from SEC 2022-2023 effective
spread data, taken toward the upper end of each range):
- **Half-spread** h = max(tier x price, $0.005). The tier is set by average
  dollar volume over the 30 sessions ending t-1 and fixed at the signal:

  | Average dollar volume | Half-spread |
  |---|---|
  | >= $100M | 5 bps |
  | $25-100M | 10 bps |
  | $5-25M | 20 bps |
  | < $5M | 40 bps |

- **Opening fills pay 2h:** gap-up entries, gap-through stops and time exits,
  because spreads are widest at the open.
- **Limit-price fills** (C, P) also pay h. This is deliberately conservative.
- Commissions are $0; SEC/TAF fees are ignored (about $0.01 per trade in the
  ledger).
- **Open-fill slippage g x ATR,** calibrated at B1 before the freeze (D7): g is
  the smallest multiple of 0.05 that makes the model non-optimistic on every
  one of the experiment's 14 real stop-outs. Exits are classified as gap or
  intraday from the bars, not from report labels; ASO's "gap open" actually
  filled at 10:05. If g = 0, "at the open" holds literally.

**Sensitivity rows (report-only):**
- costs x 2;
- a crash-bar bound: on stop sessions with open > S and low < S - 1 ATR, fill
  at the low, which bounds intraday halts and limit-down pauses.

### 3.5 R and wins

R = (net exit - net entry) / (T - S), where net entry = raw fill + cost and net
exit = raw fill - cost. A fill above T or a gap through S shows up as a loss
worse than -1R. Win = R > 0; loss = R <= 0.

Unit-test anchor, a $20 stock in the $5-25M tier (h = 20 bps):
- T 20.00, S 19.00, intraday trigger, intraday stop:
  R = (19.00 - 0.038 - 20.04) / 1.00 = **-1.078**;
- the same trade with a gap-through open at 18.80:
  R = (18.80 - 0.0752 - 20.04) / 1.00 = **-1.3152**.

### 3.6 Variants

M1/M2 x k in {1.0, 1.5, 2.0} x breadth on/off = 12 variants. The default (paper
tickets) is k = 1.5 with breadth on.

Entry filters don't depend on k, but exits do. Re-entries after an exit can
therefore differ by k, so the trade sets are *nearly*, not exactly, the same
across stop widths. The report shows the overlap.

### 3.7 Protocol: picked on 2022-2024, confirmed on 2025-2026 without changes

1. **Freeze.** The spec, params.py and the full code-tree hash are committed
   after B1 calibration and before any IS number exists. Re-freezing (new
   hash, logged) is allowed only before the first IS number.
2. **OOS seal in code.** Until a committed `pick.json` exists, signals.py and
   fills.py refuse to evaluate any session from 2025-01-02 to 2026-10-30.
   Those bars may be read only as look-back for post-go-live sessions. The
   forward tracker starts empty at go-live.
3. **IS** = fills dated 2022-01-03 to 2024-12-31. For the pick, IS trades still
   open at the 2024-12-31 close are marked there, net of exit cost, so 2025
   prices can't inform the pick. They are followed to completion only in the IS
   report written after the pick commit.
4. **Pick eligibility.** A variant is eligible only if, in the IS, it has:
   - >= 187 fills (300 x 753/1,212, rounded up);
   - average R >= +0.20;
   - average R > 0 with its 3 best trades removed, and with its 3 best
     calendar months removed (P4);
   - an average R that beats at least 95% of 1,000 random-entry runs (P5).

   The pick is the eligible variant with the highest IS average R. Ties (|difference| < 0.005R) go to breadth on, then
   k = 1.5, 1.0, 2.0. If none is eligible, the method fails Part 1 there and no
   OOS is spent.
5. **Pick commit** (pick + code hash) in early December, shown to you before any
   OOS number exists.
6. **Sealed OOS** = fills dated 2025-01-02 to 2026-10-30, run once from the
   pick commit after the 2026-12-30 close. Every trade is closed by then, so
   there are no marks in the pass statistics.
7. **Changes after the freeze.**
   - A **bug** is output that contradicts this spec's text or params.py,
     demonstrated by a failing test written from the spec text before the fix.
   - Any edit to the spec or params is a non-bug change.
   - After IS numbers exist, a non-bug change needs your approval, with the IS
     numbers shown before and after.
   - After the OOS run, a non-bug change **spends the OOS**.
   - Post-OOS bug fixes are reported as: sealed first-run figure, then every
     fix, then the post-fix figure. "Passed after fix" counts only if you rule
     on it with both numbers in view.

### 3.8 Pass rules (approved 2026-11-10)

All are computed on the every-signal list of filled trades, never on the
portfolio simulation. A method passes Part 1 only if its pick meets every rule.
A rule that can't be computed counts as failed.

**Your four rules, made exact:**
- **P1:** >= 300 trades, IS + OOS.
- **P2:** average R after costs >= +0.20 in IS **and** in OOS.
- **P3:** the OOS was evaluated on the frozen pick (attested by commit hashes).
- **P4:** full-window average R > 0 with the 3 highest-R trades removed.

**Rules you added on approval:**
- **P4, binding form (A1).** Full-window average R > 0 with the **3 best
  calendar months** removed (months ranked by total R, grouped by fill month).
  P4 as first written can't fail under a 3R cap; this form can.
- **P5, beat random entries (A5, made a pass rule).** The pick's average R must
  beat at least **95% of 1,000 random-entry runs** that use the same dates,
  universe and exits.
  - **One run:** for every trade of the pick, take its signal date t and draw a
    random eligible(t) ticker that did not signal for that variant on t.
  - **Same order construction:** trigger 1 cent above that ticker's high(t);
    ceiling +0.25 ATR; a stop the same number of ATRs below the trigger as the
    real trade's; a 3R target; the same entry window, breadth gate, exits and
    costs. A random order has no shelf or gap low, so it is canceled only by
    window expiry, a triggered-unfilled session, or breadth.
  - **Same trade count:** a draw that doesn't fill is redrawn, up to 20 times,
    so each run has as many filled trades as the pick.
  - **The bar:** 1,000 seeded runs. P5 passes if the pick's average R is above
    the 95th percentile of the runs' average R.
  - **Where it applies:** like P2, in the IS **and** in the OOS. The IS test is
    part of pick eligibility (3.7), so a drift-only variant never spends the
    OOS. The full-window figure is reported. (Two-period reading confirmed by
    you, 2026-11-10.)
  - **Reporting:** for every variant and each period, the report shows where
    its average R lands in the 1,000-run distribution: its percentile, with
    the runs' mean and 5th, 50th and 95th percentiles. Not only pass or fail.
  - **Why:** the test period is mostly a rising market, so random long entries
    earn positive R from drift alone. A method that can't beat them adds
    nothing over an index fund.
- **A2.** "Confirmed" requires >= 100 OOS trades.
- **A3 (M1 only).** P2-OOS must also hold with 2026-04-24 to 2026-09-22
  excluded. M1's rules were shaped by live trades in that slice, which is
  reported separately.
- **A4 (the funded variant).** P2 must also hold on the **sizable subset**:
  signals where floor(min(15/(C-S), 262.50/C)) >= 3 on as-traded prices, i.e.
  trades a $1,500 account can actually hold.
- **A6.** If by the decision date the measured regular-hours median half-spread
  exceeds the model by more than 50% in any tier (>= 30 observations), Check 1
  is judged on the costs x 2 row.

Report-only: the OOS with its top 3 trades removed, a 90% bootstrap interval
(3-month blocks), and the costs x 2 and crash-bar rows.

### 3.9 Report contents

**Per variant, for IS, OOS and the full window:**
- trades, win %, average R, average win and loss R, payoff;
- **longest losing streak** (ordered by exit date, then fill date, then ticker);
- **max drawdown at 1% risk:**
  - every-signal curve: daily sums of R by exit date, peak to trough, x 1%.
    This includes positions the account could never hold concurrently, so it
    reads worse than reality;
  - per-variant portfolio simulation (described below);
- **results by year:** 2022 to 2026, by fill year;
- exit mix, holding sessions, fill rate, cost drag in R, the sizable-subset
  rows, the trade overlap across k, how often the sector cap binds, and what
  the breadth filter removes (trades, drawdown, streaks);
- for every variant, its place in the P5 random-entry distribution
  (percentile, with the runs' 5th, 50th and 95th percentiles), the sensitivity
  rows, the M1 OOS slices, the M2 detector
  split, and the survivorship stress row.

**Portfolio simulations:**
- **Per variant:** one method, 4 slots.
- **Combined paper book:** the M1 and M2 default configurations, 2 slots each,
  sharing the sector, ticker, deployment and risk rules. This is the
  **realistic number**.
- Common rules:
  - fixed $15 risk / $262.50 cap sizing on as-traded prices;
  - equity = $1,500 + realized + unrealized P&L at each close; drawdown as a %
    of the running peak;
  - open risk = N x (C - S) while pending, N x (fill - S) once filled;
  - a slot freed intraday is available to that night's orders;
  - same-day ties broken by dollar volume, plus 200 random tie orders (median
    and 5th percentile reported).

### 3.10 Limits and priors, stated plainly

**Priors from the literature (research pass):**
- Post-earnings drift has largely disappeared for US stocks above microcap size
  since about 2006, and the price-reaction form is only marginal today.
- High-turnover pullbacks in liquid names tend to keep going rather than bounce.
- No rigorous evidence exists for either entry or for the 50%-breadth filter.
- Both methods start from **low priors**, and +0.20R after realistic costs is a
  demanding bar. A fail is a likely and legitimate outcome.

**Limits:**
- Survivorship (3.1).
- The LLM screen and the web gates are excluded, so the M1 tested here covers
  a wider population than the live M1 ever saw.
- Daily bars can't order intraday events; every unknowable ordering is resolved
  pessimistically.
- The spread model is an assumption until Part 2 measures it.
- Picking the best of six variants biases the IS (the sealed OOS and the
  forward test are the guards).
- Trades overlap, so 300 trades are not 300 independent observations.
- M1 can hold through an earnings release, because forward earnings dates
  aren't available. The gap-through rule prices that risk.

---------------------------------------------------------------------------

## 4. Part 2: nightly forward test

**Schedule.** A launchd agent runs on weekdays at 17:30 ET, wrapped in
caffeinate.
- Retry slots at 19:30, 21:00 and 06:30. Each is a no-op once the session is
  complete.
- **Completed-session guard:** only sessions whose bar is final are processed;
  later candles are dropped. B1 found that an hour after the close the day's
  bar is not yet the official close (AAPL at 16:58: bar close 348.562, official
  close 348.51). The cutoff, and whether the close must be cross-checked
  against the quote's regular-session last price, is set from the finality
  samples (17:35, 18:35, 20:20 and the next morning) before the freeze. The
  17:30 start time is provisional until then.
- **Completeness gate:** SPY and at least 99% of the prior session's eligible
  names must have a bar for today. Otherwise the run is INCOMPLETE: notify,
  retry, and never log "no session" on a calendar session.
- Optionally, you can set a Mac wake schedule (`pmset`). That is a system
  setting, so you would run it; I can't.

**Each run:**
1. **Token check:** fail closed unless the token has at least 3 hours of life
   left. Every notification states the token's expiry and escalates to
   "re-auth tonight" when needed.
2. **Refresh bars** from each symbol's last cached date, with a 15-session
   overlap.
   - **Basis-change detection:** a uniform ratio other than 1 across the overlap
     means a split. The full history is re-pulled, the levels and share counts
     of open forward and paper trades are rescaled, CORP-ACTION is logged, and
     a cancel-and-replace ticket is printed.
   - A tracked symbol with no bar for 2 sessions gets a CUSIP lookup. A rename
     continues under the new symbol; otherwise the trade is closed at its last
     print, labeled DELISTED, and kept in the statistics.
   - The directory files are archived nightly (the forward universe is truly
     point-in-time).
3. **Pull the session's 8-K Item 2.02 filings** with header acceptance times
   (EDGAR, approved D5).
4. **Signals for all 12 variants,** with breadth-blocked and unsizable signals
   logged too.
5. **Forward tracker:** advance every forward trade with `fills.py`.
   - Idempotent, keyed by session.
   - Report-only: a 1-minute-bar audit of each fill and exit session.
   - Report-only: regular-hours bid/ask snapshots for signaled, pending and
     open names, to check the spread model. These need the Mac awake during
     market hours.
6. **Paper book update and tickets** (below).
7. **Self-parity:** re-derive the night's outputs from the decision snapshot
   with `--as-of` and diff them against what the run produced. Any difference
   sends an alert.
8. **Notify:** "Phase 2: N new tickets, M cancels, X exits, Y confirmations
   needed; token expires ...".

**Paper book:**
- **The paperMoney balance stays at $100,000** (its lowest cash setting) and
  is never used for sizing. Every share count, cap, risk figure, deployment
  figure and dollar P&L is computed on the fixed **$1,500 basis** in the
  ledger. paperMoney's buying power would accept an oversized order that the
  live account would reject, so quantity is a pass/fail 8-check item
  (section 5).
- **The ledger is the source of truth.** A fill or exit predicted by the
  tracker but not yet confirmed by you keeps its slot and risk occupied
  (fail closed), and the ticket file asks for confirmation.
- **Nightly order of operations:**
  1. process exits and cancels;
  2. free slots;
  3. pool both methods' candidates, sorted by dollar volume;
  4. apply, in order:
     - the per-method cap (2 + 2);
     - one position per ticker;
     - the sector cap (2; unknown sector = ineligible);
     - deployment, N x C pending plus N x fill open, <= $1,050 (with four
       positions capped at $262.50 this can't bind on its own; a guard);
     - risk <= $60 (this can't bind at 4 x <=1% and is kept as a guard);
     - shares = floor(min(15/(C-S), 262.50/C)) >= 3. Under 3 shares the
       signal is skipped and logged as unsizable: its ceiling is above
       $87.50, or its risk per share is above $5.00.
- **Cap versus risk.** At the 17.5% cap, the cap sets the size whenever the
  stop plus ceiling slippage is closer than 5.7% of price, and such trades risk
  less than 1%. A $40 name with a 3.5% stop gets 6 shares and risks $8.40, or
  0.56% of the basis.
- **Every ticket** is headed "PAPERMONEY (D-...) ONLY. NOT THE LIVE ACCOUNT"
  and printed exactly as entered:

      BUY +N SYM STP <T> LMT <C> GTC  (trigger: STD)
         1st trgs OCO:  SELL -N SYM LMT <P> GTC  /  SELL -N SYM STP <S> GTC

  It shows the sizing math, deployment and cash after, positions after, and any
  2nd-in-sector flag.
- **CANCEL, TIME-EXIT and REPLACE instructions** carry a hard deadline
  ("before 09:25 ET Fri 12-04") and the exact sequence: cancel the whole group,
  confirm it is gone, then act. Never edit an order in place.
- **Live-account alarm:** every night, read-only, the live account must have no
  working orders and no positions; anything there triggers an urgent
  notification. If the API can see paperMoney, the account is selected by its
  D- number, never by list position.
- **Live balance watch:** the same read records the live liquidation value.
  The baseline is $1.01 (2026-11-10). If it drops below that before January,
  the transactions are pulled and reported. The earlier 7-cent change is not
  traced (your call).

**Sector map (approved D9): SIC codes to the 11 GICS sectors.**
- Each issuer's SEC industry (SIC) code is mapped to one of the 11 GICS
  sectors: Energy, Materials, Industrials, Consumer Discretionary, Consumer
  Staples, Health Care, Financials, Information Technology, Communication
  Services, Utilities, Real Estate. The cap of 2 per sector then means what it
  meant in September.
- The table is a checked-in file of SIC ranges plus explicit overrides where
  SIC and GICS disagree:
  - REITs (6798) to Real Estate;
  - 7370-7379 split between Information Technology and Communication Services;
  - homebuilders (1531) and autos (3711) to Consumer Discretionary;
  - pipelines (4922) to Energy, gas utilities (4924) to Utilities;
  - general-merchandise and grocery retail to Consumer Staples;
  - pharma, devices and research labs (2830-2836, 3840-3851, 8731) to Health
    Care;
  - metal mining (1000-1499) to Materials.
- **Validation before it is frozen:** the map is checked against known GICS
  sectors for the S&P 500 constituents and for every name this project has
  already classified (the September positions and gate logs). Target: at least
  90% agreement, with every disagreement listed. A validation-set name that
  disagrees gets a per-ticker override; the range rules change only for a
  systematic miss.
- SIC codes are each issuer's current code. That is exact for the forward test
  and a mild look-ahead in the backtest's portfolio simulations (stated).
- A name with no SIC code, or a code the table doesn't cover, is ineligible for
  paper (fail closed, logged). The report shows how often the cap binds.

**Logs** (`logs/phase2/`):
- append-only;
- recomputes go to separate versioned files;
- a nightly SHA-256 manifest of signals, trades and ledger is kept outside
  `logs/` and backed up, and committed at milestones (diff first).

---------------------------------------------------------------------------

## 5. Part 3: paper verification

**Step 0: DONE 2026-11-10, 13:29 ET.** A live `get_account_numbers` call
after the re-auth lists exactly one account: ****3908, MARGIN type, with 0
positions and 0 working orders. **No D- paperMoney account is visible to the
API.** This matches what QuantConnect, schwab-py and Schwab support (as relayed
in forums) say: the Trader API reaches live accounts only.

**Part 3 therefore runs on screenshots.** The API path described below is kept
only in case paperMoney ever becomes visible.

**Golden probe** (B1, not counted toward Check 3): in paperMoney, place a
correct "1st trgs OCO", a "1st trgs Seq" and a "1st trgs All" on a cheap name,
then screenshot all three in "More fields" mode before canceling. This records
the exact icons and status strings the check reads. Seq and All are the two
known wrong structures (AR 9/17 was the Seq error).

**Screenshot requirements:**
- Monitor > Activity and Positions > Working Orders, in "More fields" mode,
  with the group expanded;
- Order ID and Time Placed visible;
- the full working list (several images are fine if taken before any change);
- the paperMoney badge / D- account visible.

**Placement 8-check** (precondition: the account is paperMoney D-):
1. **Quantity matches the $1,500 sizing:** the entry is +N and both exits are
   -N, where N is the ticket's share count, floor(min($15/(C-S), $262.50/C)).
   Any other quantity on any leg fails. That includes the platform's 100-share
   default and any oversized order that paperMoney's $100,000 buying power
   would accept but the live account would reject.
2. BUY STP LMT on the correct symbol: stop T, limit C, trigger STD.
3. Structure: a key icon on the BUY parent only, and the two exits joined by a
   link icon (1st trgs OCO). Not Seq or All.
4. Both exits SELL TO CLOSE, never SELL SHORT / TO OPEN. With the paper
   account set to Cash, a short-sale leg should show REJECTED.
5. Target LMT at P and stop STP at S, exactly.
6. All three legs GTC.
7. Status: parent WORKING or QUEUED, both children WAIT TRG (API:
   AWAITING_PARENT_ORDER, correct only while the BUY parent is unfilled), and
   no leg REJECTED.
8. No working orders beyond the ledger's expected set.

**Activation check** (after the entry fills; this is the original 8-check):
- the position quantity is N, the $1,500-basis count;
- the fill is <= C;
- both exits are WORKING and linked as an OCO, at the exact levels, -N, GTC;
- no live entry; no strays.

A partial fill by paperMoney is logged as an incident for your judgment; it is
not scored as a construction error.

**First-try pass**, the unit for Check 3:
- A **placement** is one bracket from one ticket line. A replacement is a new
  placement.
- It passes if its first legible capture shows all eight items correct, you
  attest it wasn't edited before the capture, and, if the entry fills before
  01-15, the activation check passes with no fix.
- An unreadable image is re-requested and counts neither way.
- New order IDs on a resend mean the order was re-placed, which is a fail.
- If the entry has already triggered at capture, item 7 accepts "FILLED +N at a
  price <= C with both exits WORKING and linked". Item 1 still applies: the
  filled quantity must be the $1,500-basis N.

**Exits and reconciliation:**
- When the tracker predicts a fill or exit, the ticket file asks for a Filled
  Orders screenshot or a typed confirmation.
- Paper R uses paperMoney's fills. paperMoney's fill model is unpublished and
  reportedly optimistic, so paper R is informational; the forward log is the
  truth for Check 2.
- A Friday reconciliation compares Positions + Working Orders + Filled Orders
  with the ledger.
- **Process deviations,** reported separately and tallied next to Check 3:
  entries placed after 09:30 on their first window session, fills after a
  cancel deadline, and missed cancels.

**Ledger fields** (`paper_ledger.jsonl`): id, order IDs, method, ticker, N,
T/C/S/P, sector, captures, the eight item results, first-try pass, activation
result, fixes, deviations, paperMoney fills, exit type, R, and the
simulator-vs-paperMoney fill difference.

---------------------------------------------------------------------------

## 6. Part 4: decision (Fri 2027-01-15, after the close)

**Funding rule.** Funding requires Check 3 **and** at least one method for which
Checks 1 and 2 both hold. Only those methods are funded, trading the variant
evaluated in Check 2. A check that can't be computed counts as not holding.

**Check 1:** the method passes Part 1 (3.8).

**Check 2: the forward log lands inside the backtest's range.** This is
evaluated per method, on the pick's forward log: fills from go-live through the
decision date, evaluated at that close (closed R, or open trades marked net of
exit cost).

The reference uses **analog windows** (critical review finding). Every forward
trade shares one market path, so a band built from independent draws would be
too narrow. The review's simulation put the false-fail rate of such a band at
13-32% instead of 5%.
- L = the number of sessions from go-live to the decision date, frozen at
  go-live (37 for 01-15 with a Nov 23 go-live).
- For every start session s in the backtest signal period where the window fits
  inside the period, re-simulate the pick from an empty book.
- Evaluate every trade filled in [s, s+L-1] at the window's last close, and
  record the window mean and the fill count.
- The band is the 5th to 95th percentile of the window means.
- **Inside** = the forward mean is inside the band **and** the forward fill
  count is >= max(10, the 5th percentile of the window counts). That is the
  minimum forward trade count.
- A result above the band is reported as an anomaly for your judgment.
- The band width is published with the Part 1 report, so you can see how much
  one window can tell us.
- **Trades still open at the cutoff are treated identically in the historical
  band windows and in the forward window** (your instruction, 2026-11-10). One
  function in `fills.py` evaluates a trade at a cutoff close, and both sides
  call it:
  - closed by then: its realized R;
  - filled and still open: marked at that close, net of the exit half-spread;
  - an order not yet filled: not a trade, excluded.

**Method 2 timing (fixed 2026-11-10).**
- If M2 has not reached the minimum forward trade count by the 01-15 close, it
  is not decided in January. Its forward test continues through Q4 earnings
  season, to the close of **Fri 2027-03-12** (date confirmed by you), and it
  is decided that evening.
- **The count is never lowered.** The extended decision uses the same Check 2,
  with the band and the minimum recomputed for the longer window, so the
  minimum can only rise.
- Check 3 is re-read at that date on the then-latest 10 placements.
- M1 is decided on 01-15 regardless. If M1 passes, its funding does not wait
  for M2.
- The B4 feasibility estimate (fill counts only, from the IS-year spans
  2022-11-23 to 2023-01-13 and 2023-11-23 to 2024-01-12; no R, no OOS) says
  before go-live whether the extension is likely, and how many paper
  placements to expect by 01-15.

**Check 3:** the last 10 placements whose first legible capture arrived by the
decision close are all first-try passes (section 5). Fewer than 10 placements
counts as a fail.

**The January report also reminds you to:**
- **switch the live account from margin to cash before funding it.** It reports
  as a MARGIN account today, where a mis-built short-sale exit opens a short
  instead of being rejected;
- settle the funded-account procedure: per-order approval or a standing
  approval of the system, and the sizing basis.

---------------------------------------------------------------------------

## 7. Tests and regressions

- **Unit tests:**
  - every M1/M2 qualify/reject path;
  - every fill branch: opening fill; intraday trigger; triggered-unfilled with
    no fill and cancel; fill at C on a trade-through, both target-credit
    variants; entry-day stop; gap-through; gap past the target; both levels
    touched; the trade-through boundaries (high = P, low = C); time exit with
    the OCO first on session 41; replacement; invalidation; breadth cancel;
    missing-bar gap; split rescale during an open trade;
  - cost arithmetic and the 3.5 anchors;
  - the cent-rounding direction;
  - the calendar and the completed-session guard.
- **Contracts** (section 2): parity, window invariance, known-answer fills, no
  order placement, OOS seal.
- **Existing regressions** stay green. Every code commit's diff waits for your
  word.

---------------------------------------------------------------------------

## 8. Build sequence

Every code milestone is shown as a diff before commit.

- **B0 (now).** Spec v3, the Phase 2 block in trading-rules.md and the token
  monitor change, as one diff for your commit word.
- **B1. Data-contract checks (read-only; started 2026-11-10).** Done:
  - paperMoney is not visible to the API (section 5);
  - daily history is deep enough: 1,471 AAPL bars from 2021-01-04, and a 1990
    window also returns;
  - timestamps: only New York-date conversion is correct (section 2);
  - splits: price and volume are both back-adjusted (3.1);
  - delisted names are missing (3.1);
  - `assetSubType` is useful but incomplete (3.1);
  - quotes: `regularMarketLastPrice` is the 16:00 close and `closePrice` is the
    previous close. `lastEarningsDate` exists and is kept only as an audit
    field;
  - EDGAR: the filing index carries item codes and SIC codes. Acceptance times
    in the JSON matched the filing headers on four Apple earnings 8-Ks; the
    headers stay the source.

  Still open in B1:
  - **bar finality** (section 4): samples tonight and tomorrow morning;
  - whether a bar's timestamp or values are rewritten overnight;
  - your golden paperMoney probe (section 5).
- **B1b.** `fills.py` and its unit tests (diff first), then the known-answer
  calibration on the 14 real stop-outs, which sets g.
- **B2. Freeze:** spec + params (with g and the bar-finality cutoff) + code
  hash, committed before any IS number exists.
- **B3. Pulls:** the directory, security types, bars from 2021-01-04, the
  yfinance split table, EDGAR 8-K Item 2.02 headers and SIC codes. About 4-5
  hours of machine time, most of it the paced EDGAR header pull.
- **B4.** universe / events / signals, the sector map and its validation, tests
  and contracts, and the feasibility estimate (section 6).
- **B5.** The nightly goes live (target the week of Nov 23): forward logging and
  default-config paper tickets.
- **B6a.** IS run and pick commit (early December). I ask then whether paper
  tickets switch to the picks (approved in principle, D9).
- **B6b.** Sealed OOS after the 2026-12-30 close, and the Part 1 report.
- **B7.** Decision report 2027-01-15, and M2's on 2027-03-12 if it was extended.

---------------------------------------------------------------------------

## 9. Approved decisions (2026-11-10)

| | Decision | As approved |
|---|---|---|
| D1 | Phase 2 rule block | Yes, with your fix: position cap **17.5% ($262.50)**, so four full positions fit the 70% cap. The 3-share minimum then limits paper to ceiling prices <= $87.50 and risk <= $5.00 a share |
| D2 | Stop rule | S = min(structural stop, T - k x ATR) |
| D3 | Exits | 3R static target; time exit at the session-41 open; no trailing; M1 keeps rr >= 3 on its structural stop |
| D4 | M1 mechanics | Touch rule; trigger 1 cent over the signal-day high; ceiling +0.25 ATR; 3-session window |
| D5 | M2 earnings dates | SEC 8-K Item 2.02 with filing-header times; price/volume fallback for foreign issuers. The contact you supplied lives in `.env` only and is never committed |
| D6 | Universe and splits | Security types plus directory rules; MLPs, royalty trusts and SPACs excluded; split table via yfinance; survivorship flagged |
| D7 | Fills and costs | The model in 3.4; g calibrated on the 14 real stop-outs before the freeze |
| D8 | Protocol | Fill-date windows; OOS sealed in code; pick eligibility; sealed OOS after 12-30; bug rules |
| D9 | Paper process | The ledger is the record; 2 slots per method; **SIC codes mapped to the 11 GICS sectors**; paper switches to the IS picks in December (asked again then) |
| D10 | Part 4 | Analog-window band plus the count rule; Check 3 = placement + activation; funding per method; **M2 extends to 2027-03-12 if short of the count, which is never lowered** |
| D11 | Operations | Nightly run plus retries; token fail-closed; live-account alarm; token-monitor warning at 5.0 days (**applied 2026-11-10**) |

**Pass-rule additions:** A1, A2, A3, A4 and A6 approved. A5 approved **as a pass
rule (P5)**: 1,000 random-entry runs, 95% bar, not report-only.

**Also on record:**
- paperMoney stays at $100,000 (its minimum) with Cash margin type. Every paper
  trade is sized and tracked on the $1,500 basis, and 8-check item 1 fails any
  quantity that doesn't match.
- The 7-cent change in the live balance is not traced. If the balance drops
  below $1.01 before January, the transactions are pulled then.
- The January report reminds you to switch the live account from margin to
  cash before funding.
