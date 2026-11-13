# Phase 2 spec: backtest, nightly forward test, paper verification, January decision

Status: **APPROVED 2026-11-10 (v3)**, with your changes: a 17.5% position cap,
GICS sectors, the random-entry test as a pass rule, and the fixed Method 2
extension. Section 9 records the approvals. Committed 2026-11-10 (0183433).
The B1b commit adds the B1 and B1b results (section 8) and your 2026-11-11
rulings (3.4, 3.5, 3.7, section 9). The seal-hardening commit (030af69,
2026-11-12, committed with your word) changes no spec text.

This version also records your 2026-11-11 instructions on the nightly timing
and the drill (D11, D12), and your 2026-11-12 rulings: sealed bars as
look-back for indicators (3.7, D8), the Mac precondition (section 4,
step 3), and your rulings on commit B. Your words (2026-11-12): "Rulings on
commit B: yes on items 1 to 8 as recommended. DRILL-2026-11-12-01 counts both
ways. Off-machine alert: not now. Put it on the January go/no-go list." So
everything commit B proposed is ruled 2026-11-12 and written as rules where
it appears:
- section 2: commit B's module rows and the `bars.py` retry of truncated
  responses;
- 3.1 and D6: the universe rules for B3/B4: BDCs are in, known by their SEC
  814- file number; MLPs are excluded by the approved K-1 criterion, not by
  name; SPACs are also identified by SIC code 6770;
- 3.4: T rounded up to the cent, which amends 3.2 (twice), P5, D4 and the
  entry-order line of trading-rules.md;
- section 4: the night job and the watchdog (steps 1 and 2), the ticket
  states, the freeze with the night schedule, the sampler, its schedule and
  installing its launchd job (step 4), the flip report and what it decides,
  LATE nights out of the pooled numbers, the 1-minute bars kept, how go-live
  is recorded, and the ticket's sizing-line format;
- section 5: the drill's construction rules and end lines, placed or not
  placed, how later drills count, a drill's exclusion from the paper book and
  the forward log, the provisional reading of items 3 and 7, items 5 and 8,
  the after-fill re-read, the interim scoring of DRILL-2026-11-12-01, the
  activation-check wording, simulator artifacts and the two records.
  DRILL-2026-11-12-01 counts both ways in Check 3 (section 6);
- the off-machine alert is not built now and is on the January report's list
  (section 6).
Two more rulings of yours, 2026-11-12: the flip report's acceptance bar
(section 4, step 4, "What it decides") and a standing rule on statistics
(3.7). Nothing in this spec awaits your ruling. Still to come, as scheduled:
the flip report itself and your acceptance of it (section 4, step 4), the
golden probe (section 5), the December question on paper picks (D9) and the
January decision (section 6). Besides factual records, two edits of approved
text are not rulings: 3.7 step 2's description of the seal is brought up to
date with commit A (030af69) and commit B (no rule changes), and section 9's
heading now names the rulings its rows carry.

On 2026-11-12 you also said: "Drill: not placed. Issue a fresh ticket from
tonight's close." So DRILL-2026-11-11-01 is void and does not count, and
DRILL-2026-11-12-01 replaces it (section 5, D12).

3.7 also discloses a second statistic aggregated over sealed sessions, found
after your ruling: the first count behind the 3.4 T-rounding rule (then a
proposal; ruled 2026-11-12). It is replaced by the same count over the eight
post-seal sessions and is not repeated.

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
| `bars.py` | Schwab daily candles. Explicit America/New_York date conversion, never machine-local time and never Central. B1 found two kinds of daily candle: a **final** bar is stamped midnight America/Chicago (06:00 UTC in winter, 05:00 UTC in summer; checked across both 2026 clock changes and on 2024 bars), and the **provisional** bar for the current session is stamped midnight America/New_York. Only New York time dates both correctly, so bars are keyed by that date, not by the raw timestamp. Overnight both candles for one date can come back in the same response: the final one is kept, and a date with only a provisional candle is not final (section 4). endDate=now and needExtendedHoursData=false on every call (the flag changed nothing in the B1 sample). A completed-session guard (section 4). An evening mode reads the provisional candle with the quote's official close, marked PROVISIONAL (section 4) *(ruled 2026-11-12, with the section 4 schedule)*. A response that carries no prior history is TRUNCATED and retried, never read as a missing bar (B1: 19 such responses in 42 seconds on 2026-11-12) *(ruled 2026-11-12)*. Throttled to <=100 requests/minute under one shared lock (the app has about 120/min across all jobs) |
| `universe.py` | symbol list plus security type, point-in-time eligibility, split factors for as-traded tests |
| `events.py` | M2 earnings events (EDGAR header acceptance times, or the price/volume fallback) |
| `signals.py` | M1/M2 tests and breadth; brackets through `orders.py`. Calls `technicals.compute_levels` **unchanged** |
| `orders.py` | pure order levels T, C, S, P, the $1,500-basis share count N, and the ticket lines; `signals.py` and the ticket writer call it |
| `fills.py` | the order state machine and pessimistic fill model (3.4). Used by the backtest, the forward tracker and the portfolio simulations |
| `known_answer.py` | the experiment's 14 real stop-outs: the only orders the seal exemption lets through (3.7) |
| `sample_bars.py` | the flip-measurement sampler (I/O): the symbol directory (two public Nasdaq Trader files, fetched by the package itself over HTTPS) and, through a read-only wrapper built by `loops/phase2_sample.py`, the runner outside the package, quotes and daily and 1-minute bars (section 4, step 4) |
| `compare_bars.py` | the flip measurement (read-only; it writes a report, never a ticket or an order). Its signal level is an interim second implementation of eligibility, breadth, M1 and M2, behind its own look-back guard, until the B4 replay through `signals.py` |
| `backtest.py` / `nightly.py` / `paper.py` | runners and the paper ledger |

*The `orders.py`, `sample_bars.py` and `compare_bars.py` rows, and "brackets
through `orders.py`", come with commit B (2026-11-12), ruled yes on
2026-11-12. In them, T's rounding is the 3.4 rule and the sampler's schedule
is the section 4 schedule, both ruled 2026-11-12. The sampler's own constants
(its pull times and 06:30 full pull, the 10-minute lead, the 7-pass cap, the
10-session look-back, the stand-in calendar, the Method 2-like strata) live in
`sample_bars.py`, not `params.py`: they enter no backtest number, belong to the
section 4 schedule and are frozen with the code hash.*

Contracts, each enforced by a test:
- **Parity:** `nightly.py --as-of DATE` on stored bars reproduces the
  backtest's signals, orders and order states for DATE exactly, all 12
  variants. Dates are drawn from the IS and from post-go-live sessions only (OOS seal, 3.7; the approved limit, kept although your 2026-11-12 ruling would also allow sessions after 2026-10-30). Parity is a property of the run of record, the overnight
  recheck on final bars (section 4); the evening scan's provisional outputs
  are compared with the run of record, not with the backtest. *(Ruled
  2026-11-12, with the section 4 schedule.)*
- **Window invariance:** `compute_levels` on the full history equals
  `compute_levels` on the trailing 120 bars, which both paths pass.
- **One cutoff evaluation:** the forward window and every analog band window
  evaluate trades open at their cutoff through the same `fills` function.
- **Known-answer fills:** run at B1, before the freeze (3.4). The model must
  never be more optimistic than Schwab's real fills on the experiment's 14
  stop-outs. (Met by the 4-half-spread stop exit, 3.4.)
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
  K-1 tax forms) and SPAC shares ("Acquisition Corp"). **Your ruling of
  2026-11-12, for B4:** an MLP is excluded by that approved K-1 criterion, not
  by its name, so PAGP and HESM, which issue 1099s, are in; SPACs are also
  identified by SIC code 6770.
- Every excluded symbol is logged with its reason.
- **BDCs (your ruling of 2026-11-12, for B3/B4):** business development
  companies (BDCs) are in the universe. A BDC is known by its SEC file number
  (814-), checked at B3/B4, not by its name.
- *The stand-in universe* (section 4, step 4) keeps its own name rules until
  B4. It keeps BDCs listed under Nasdaq's "Closed End Fund" label (ARCC and
  others) and NYSE-listed BDCs, which pass as ordinary common stock (MAIN,
  OBDC, FSK and others). Its fund rule excludes BDCs whose names say "Fund":
  BXSL, FSSL, MSDL and MSIF (the first three are BDCs by general knowledge,
  not yet checked against their SEC filings), and its exclusion records say
  so. Its MLP and SPAC rules are name rules too.

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
- **Schwab does not rebase bars for ordinary dividends, but it does for special
  distributions** (B1b, checked against this project's own end-of-day logs).
  Seven names that went ex-dividend after being held (AEO, F, RF, ASO, CCL,
  VTRS, WWW) match the logged closes to the cent. FRO's bars before its
  2026-09-18 distribution sit exactly $1.60 below the logged closes on all
  eight sessions: a constant dollar shift, not a ratio.
  - A dollar shift keeps every price difference, so ATR, risk and R are
    unaffected. Percentage rules (the 3% gap, costs in bps) and the $5-100
    band are off by the size of the shift for those names (stated).
  - Any real fill replayed on today's bars must first be moved onto the bar
    basis (the known-answer test does this for FRO).
  - An open forward trade is moved the same way: `fills.shift` moves every
    level and the entry price by the dollar amount and leaves ATR, risk and
    the costs already paid alone. Splits use `fills.rescale`.
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
- Both methods enter on a **buy stop 1 cent above the signal day's high,
  rounded up to the cent** (3.4, your ruling of 2026-11-12). The
  methods differ only in what qualifies the signal day, and exits are identical
  (3.4).
- ATR = ATR14 exactly as `compute_levels` computes it, at the signal close.

**M1: pullback to an aged shelf (current technical rules + a touch rule)**

`L = compute_levels(bars[t-119..t], last = T)`, with T = high(t) + $0.01
(T rounded up to the cent, ruled 2026-11-12 in 3.4).
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
- trigger **T** = high(t) + 0.01, rounded up to the cent (your ruling of
  2026-11-12), the high read at the millionth (the resolution fills.py
  compares at). About a quarter of Schwab's daily highs carry sub-cent digits
  (3,648 of 15,395 final candles, 23.7%, over the eight sessions
  11-02..11-11); rounding a buy stop up keeps it at least a cent above the
  high, at that resolution. The ruling amends T wherever this spec says one
  cent above the high: 3.2 (twice), P5 and D4, and the entry-order line of
  trading-rules.md.
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
2. open >= P + 0.01: target at P (no gap bonus);
3. low <= S: stopped at S;
4. high >= P + 0.01: target at P.

Resting limits need a 1-cent trade-through, at the open as well as intraday;
stops and triggers fire on a touch. (Your ruling, 2026-11-11: an open exactly
at P is not a fill at P. The bar can still trade through P later, under
rule 4.)

**Time exit.** The fill session is session 0. Full sessions start the next
session, and half days count. A trade still open after session 40 is sold at
the open of session 41, with the OCO rules applied first, so the 3R cap is
exact. (A session-41 open at P, or less than a cent above it, is not a gap
past the target, so it is sold at that open. Net of its 2h it is below P.)

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

- **Opening fills pay 2h:** gap-up entries and time exits, because spreads are
  widest at the open.
- **Every stop exit pays 4h,** intraday or gap-through (your ruling,
  2026-11-11). This replaces the open-fill slippage g x ATR of the approved
  draft, which could not reach an intraday stop (section 8, B1b).
  - **Why 4:** it is the smallest whole number of half-spreads that keeps the
    model from being more optimistic than any of the experiment's 14 real
    stop-outs (the known-answer contract, section 2). 3 misses CXM by one
    cent. 4 ties CXM exactly: stop $5.00, h = 1 cent, real fill $4.96.
  - **Why half-spreads and not a flat cent value** (your reasoning): the 14
    stop-outs ran $5 to $47 and the universe runs to $100. A flat value
    overcharges cheap names and undercharges pricier ones; half-spreads scale
    with price and liquidity. P5's random entries pay the same cost, so only
    the +0.20R floor feels the difference. (My note: P4's zero floors, and
    A3/A4's subsets of the +0.20R floor, move with it too.)
  - Exits are classified as gap or intraday from the bars, not from report
    labels; ASO's "gap open" actually filled at 10:05.
  - There is no separate slippage term, so "at the open" holds literally for
    opening entries, gap-through stops and time exits.
- **Limit-price fills** (C, P) pay h, and so does an intraday trigger entry.
  Charging a limit fill at all is deliberately conservative.
- Commissions are $0; SEC/TAF fees are ignored (about $0.01 per trade in the
  ledger).

**Sensitivity rows (report-only):**
- costs x 2: every cost doubles, the 4h of stop exits included (your ruling,
  2026-11-11);
- a crash-bar bound: on stop sessions with open > S and low < S - 1 ATR, fill
  at the low, which bounds intraday halts and limit-down pauses.

### 3.5 R and wins

R = (net exit - net entry) / (T - S), where net entry = raw fill + cost and net
exit = raw fill - cost. A fill above T or a gap through S shows up as a loss
worse than -1R. Win = R > 0; loss = R <= 0.

Unit-test anchor, a $20 stock in the $5-25M tier (h = 20 bps):
- T 20.00, S 19.00, intraday trigger (h = 0.04), intraday stop (4h = 0.152):
  R = (19.00 - 0.152 - 20.04) / 1.00 = **-1.192**;
- the same trade with a gap-through open at 18.80 (4h = 0.1504):
  R = (18.80 - 0.1504 - 20.04) / 1.00 = **-1.3904**.

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
   Those bars may be read as look-back to compute indicators for any session
   after 2026-10-30 (your ruling of 2026-11-12, below). The forward tracker
   starts empty at go-live.
   - **Look-back ruling (yours, 2026-11-12):** "Reading sealed bars as
     look-back to compute indicators for a session after October 30 is
     allowed. That covers ATR, shelves, dollar volume, and breadth for the
     drill, the nightly scan, and the flip comparison. Statistics aggregated
     over sealed sessions stay off-limits, except the 14 real fill records.
     The drill's 250-session fill-rate figure crossed that line. Keep it
     disclosed and don't repeat it. It touched no Method 1 or 2 signal, fill,
     or R, so the out-of-sample test stands. Signal-level flip comparisons
     can resume." The approved sentence it replaces read: "Those bars may be
     read only as look-back for post-go-live sessions."
   - **Disclosure, kept as you ruled.** The 2026-11-11 drill ticket's
     fill-frequency line ("194 of the last 250 sessions") counted
     next-session entries for a near-market BAC order on 250 sessions, 242
     of them inside the sealed window: a statistic aggregated over sealed
     sessions. The count ran `technicals.compute_levels` (which also computes
     Method 1 setup fields) on its signal days and used only ATR14; no
     Method 1 or Method 2 signal, fill or R was evaluated. It is not
     repeated: no later ticket or report carries a statistic aggregated over
     sealed sessions (the 14 real fill records excepted). The same ticket's
     ATR14 (1.2133: 14 true ranges from 10-23 to 11-11, reading 7 sealed
     bars, 10-22..10-30), which set T, C, S, P and N, its name ranking by
     30-session average dollar volume (09-30..11-10: 23 sealed sessions), and
     the night-1 flip comparison's threshold tests for 2026-11-11 (the
     50-session average of closes 09-02..11-11, 42 sealed; ATR14 at t-1, 14
     true ranges 10-22..11-10 reading 8 sealed bars, 10-21..10-30; the
     30-session average volume, 09-30..11-10, 23 sealed) read sealed bars as
     look-back for a session after 10-30, which the ruling allows. The 8-check
     record carries the disclosure in rows seq 3, 8, 10 and 11. One more
     statistic crossed the same line, found after your ruling: the 3.4
     T-rounding proposal (ruled 2026-11-12) first gave its sub-cent share as 24.1% (41,033 of
     170,569 final candles in night 1's sample), which counted highs back to
     about 2026-07, mostly sealed sessions. It is a count of price precision
     only (no signal, fill or R), but it is a statistic aggregated over sealed
     sessions, so it is replaced by the same count over the eight post-seal
     sessions (23.7%) and is not repeated.
   - **Standing rule on statistics (yours, 2026-11-12):** "New standing rule:
     before you compute any statistic, state its session range. If it uses
     2025-01-02 to 2026-10-30 for anything beyond look-back, stop and ask me
     first." So every statistic (in a report, a ticket, a message or a check)
     has its session range stated before it is computed, and one that would
     use the sealed sessions for anything beyond look-back is not computed
     until you have been asked and have answered.
   - In `fills.py` the seal is the default of `step`, `run` and the two
     marking functions: a session in that window raises an error unless the
     caller names an unseal. The window is also fixed in the code, so a params
     set carrying another window cannot open it. The unseals are private
     objects compared by identity, so no string, typed or computed or read
     from a file or the environment, can stand in for one. There are two
     names. A contract test pins every place a scanned repo file writes
     either name, file by file, and fails a lookup of the fills module by a
     computed name in the plain forms (`getattr`, `vars`, `__dict__`); it
     cannot see code outside the repo, or every dynamic route inside it, so
     for `UNSEALED_BY_PICK` the backtest runner's check of the committed pick
     is the real guard. *(This description of the seal is brought up to date
     2026-11-12 with commit A (030af69) and commit B; no rule changes.)* The
     two names:
     - `UNSEALED_BY_PICK`, passed only by the backtest runner after it has
       verified the committed pick;
     - `KNOWN_ANSWER_REPLAY`, the one exemption. The known-answer contract
       (section 2) replays the experiment's own 14 real stop-outs. Those are
       April-September 2026 sessions, and the contract has to run before the
       freeze. **Scope (your ruling, 2026-11-11): the 14 real fill records and
       the bars those trades need,** entry day through exit day, 62 bars in
       all. The records are listed in `known_answer.py`, and a test compares
       that list with the stored fills. The exemption covers exact replays
       only: the record's ticker, trigger = ceiling = the real entry, the real
       stop, a far target (3 x the entry) so the replay can end only at the
       real stop, and a one-session window on the real entry day. Any other
       order or session inside the window is refused under it.
     - Other reads of sealed-window bars before the pick, none of which
       evaluates a signal, a fill or an R: each record's ATR and cost tier
       were computed once from the sessions before its entry day; the data
       checks in 3.1 and section 8 compare sealed-window closes with this
       project's end-of-day logs; and the September gate-regression harness
       replays its own 2026 decision dates.
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
  - **Same order construction:** trigger 1 cent above that ticker's high(t),
    rounded up to the cent (3.4, ruled 2026-11-12);
    ceiling +0.25 ATR; a stop the same number of ATRs below the trigger as the
    real trade's; a 3R target; the same entry window, breadth gate, exits and
    costs. A random order has no shelf or gap low, so it is canceled only by
    window expiry, a triggered-unfilled session, or breadth.
  - **Same trade count:** a draw that doesn't fill is redrawn, up to 20 times,
    so each run has as many filled trades as the pick.
  - **The bar:** 1,000 runs, seeded from the fixed base seed 20261110 (params).
    P5 passes if the pick's average R is above
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

**Schedule.** Your instruction (2026-11-11): "I place orders in the evening,
so design for that. Run the scan on provisional bars in the evening, recheck
against the final bars overnight, and alert me before the open if any ticket
changed or disappeared. Before relying on it, measure how often provisional
bars flip a signal across the nights you sample. Also alert me if a nightly
run misses its window."

*How it is carried out (steps 1 and 2, and the flip report in step 4) was
ruled 2026-11-12 ("yes on items 1 to 8 as recommended"); you accepted step
3's Mac precondition on 2026-11-12. It replaces the approved schedule: a
weekday run at 17:30 ET with retry slots at 19:30, 21:00 and 06:30, whose
17:30, 19:30 and 21:00 times were provisional until the bar-finality
measurement. The forward log comes from the overnight recheck on final bars.
The flip report (step 4) goes to you before go-live (target Mon 11-23), and
your acceptance bar judges M1 and M2 separately. If you accept it, you place
the evening tickets of each method that meets the bar from go-live, with the
overnight recheck and the pre-open alert as the safety net. A method with any
flip, and every method until you accept the report, gets its tickets from the
overnight recheck alone, placed before the open (by 09:25).*

1. **One night job per session** (a launchd agent, idempotent per session).
   It is started and kept awake the way the sampler is (step 4): weekdays at
   17:20 ET and at login, with an idle-sleep assertion from 17:20 until the
   night's last recheck retry at 07:30. As in the sampler, it builds a client
   for each run, so a re-authentication is never reverted, and a job still
   running when the next session's job is due carries on into that session.
   - **a. Evening scan, 17:30 ET** (retries at 18:15 and 19:00 inside the
     job), on provisional bars:
     - the day's bar is the provisional candle with one substitution: its
       close is the quote's regular-session last price, the official close;
       its open, high, low and volume stay provisional;
     - completeness gate: SPY and at least 99% of the prior session's eligible
       names; truncated responses are retried;
     - it writes PROVISIONAL tickets. For a method that has evening tickets
       (you accepted the flip report and the method met your bar, step 4), it
       notifies you, so you can place them that evening; for a method on
       recheck tickets it writes them without sending them, so the recheck
       can compare them. It never writes the forward log.
   - **b.** The job then waits for the recheck, watching the wall clock (a
     long sleep does not count down while the Mac sleeps).
   - **c. Overnight recheck, the run of record, from 01:00 ET**, retried every
     30 minutes until 07:30:
     - it needs final candles for SPY, for every name with an evening ticket,
       a pending order or an open paper order, and for at least 99% of the
       other names; a truncated response is retried, never read as a missing
       bar;
     - it recomputes the session from scratch on final bars (signals, order
       states, tickets) and writes the forward log;
     - it compares each evening instruction with its own, by ticker (entry
       tickets, CANCEL, REPLACE and TIME-EXIT lines alike):
       - **confirmed:** the same instruction, T, C, S, P and N;
       - **changed:** any of those differ. Instruction: cancel the whole group,
         confirm it is gone, place the replacement;
       - **disappeared:** no instruction on final bars for a name whose final
         bar exists. For an entry ticket the instruction is: cancel the whole
         group. For an evening CANCEL or REPLACE you may already have carried
         out, the morning message prints instead what the run of record
         expects: re-place the group it keeps, at its levels, or log a
         "provisional-bar flip" deviation (ruled 2026-11-12);
       - **unconfirmed:** the name's final bar is still missing at the last
         retry. Never reported as disappeared. The default (ruled
         2026-11-12): leave the order as placed and act only on a later
         CHANGED or DISAPPEARED;
       - **appeared:** an instruction that exists only on final bars. An entry
         ticket is printed as a LATE TICKET you may place before the open, and
         leaving it is not a deviation. A CANCEL, REPLACE or TIME-EXIT line is
         due before 09:25 ET like any other, and missing it is a process
         deviation (section 5). *(Ruled 2026-11-12. B5 tests each class with
         each kind of instruction.)*
   - **d. Morning message, sent when the recheck finishes and by 08:30 ET:**
     "recheck: all N confirmed", or, with an alarm sound, "RECHECK: k changed,
     m disappeared, u unconfirmed, l late. Act before 09:25 ET", with the steps
     in the ticket file. The alarm sounds no earlier than 07:00 ET (ruled
     2026-11-12). For a method on recheck tickets (step 4), the message also
     carries the recheck's tickets, to place before 09:25. It states when the
     recheck finished and any time the Mac slept. Silence never means all
     clear: the watchdog covers a missing message.
   - **e. A recheck that finishes after 09:25** *(ruled 2026-11-12)*: you act on its
     alert as soon as you see it. A changed or disappeared entry group that
     has not filled is canceled, and a changed group's replacement is placed
     only while its entry window is open (an entry placed after 09:30 is
     logged as a process deviation). A group that has filled keeps its
     bracket and is logged as the deviation "provisional-bar flip" in the
     8-check record; its ledger row stays and is left out of the
     simulator-vs-paperMoney fill difference. A CANCEL, REPLACE or TIME-EXIT
     line that appeared, and an evening CANCEL or REPLACE already carried out
     that changed or disappeared, are handled as in rule c; a fill or exit
     that came before you could act is logged as a "provisional-bar flip",
     not as a missed cancel.
   - **f. An INCOMPLETE or failed recheck** *(ruled 2026-11-12)* keeps retrying hourly through the
     day until the session's final bars are complete. The next evening scan
     first completes any missing run of record, in session order, before it
     issues tickets.
   - The live-account alarm runs in both parts. The token check is one rule
     for every run ("Each run", step 1).
2. **Watchdog** (a separate launchd agent, run at 19:30 and 08:00 ET, at
   login, and every `params.watchdog_every_min` minutes, 60): it reads the
   night job's status file against the NYSE calendar and alerts once per
   missed window: at 19:30 ET, "the evening scan missed its window: no
   tickets for <date>"; at 08:00 ET, "the recheck missed its window: last
   night's tickets are UNCONFIRMED". It watches the night job of step 1
   only; a night the sampler misses is flagged by the sampler's next pass
   (MISSED-NIGHT, step 4). A Mac that is off at 17:20 runs neither agent
   until it is started. A login then starts both, as it starts the sampler
   (step 4). The watchdog reports any window already missed. A recheck
   missed while the Mac was off is completed late, at the latest by the next
   evening scan (rule f), and rule e applies to any ticket already placed.
3. **What the Mac has to do** *(accepted by you, 2026-11-12: "I'll keep it
   plugged in with the lid open on ticket nights.")*:
   - caffeinate (an idle-sleep assertion) stops idle sleep only while the Mac
     is fully awake. It does not stop lid-close, Apple-menu or low-battery
     sleep, has no effect in the brief maintenance wakes, and never wakes the
     Mac. Measured 2026-11-10/11: 93 maintenance wakes while the Mac slept
     (median 46 seconds; 17 lasted from 81 seconds to 68 minutes), and the
     08:30 token monitor started at 08:42 inside a 401-second one.
   - So on ticket nights the Mac stays on AC power with the lid open; once you
     have woken it in the evening, the night job keeps it from idle sleep until
     morning. A weekday wake schedule (`pmset`, a system setting you would run)
     is an optional backup.
   - The sampled nights before go-live need the same (a request, not a rule):
     with the lid closed, a night loses its overnight pulls, including the
     00:30 and 01:00 pulls that test the 01:00 recheck start. The Mac also has
     to run on New York time: the launch is at 17:20 local time.
   - Alerts are macOS notifications on this Mac only. An off-machine alert is
     not built. Your ruling of 2026-11-12: "Off-machine alert: not now. Put it
     on the January go/no-go list." (section 6).
4. **Flip measurement, before the evening tickets are relied on** (your
   instruction):
   - **Night 1 (2026-11-11), bar level, 1,926 names** (evening sample 17:55 ET;
     final pulls 22:00, 01:30 and 06:30; `compare_bars.py --all --bars-only`,
     run while night 1 was the only night). Night 1 was taken by the earlier
     sampler: it has no SPY and no 1-minute bars.
     - highs, lows and the official close identical on every name, and the
       whole-cent trigger T (from the high alone) moved on none;
     - the open differed on 11 names (0.57%; 4 up, 7 down; median 0.33% of
       price, at most 2.65%). The provisional open equals the quote's open on
       all 1,926; whether it is the first trade or another print is not yet
       verified (night 1 has no 1-minute bars to check it against). The
       Method 2 gap test reads the open, so it is the test most exposed. In
       the quote-field Method 2-like stratum (31 names; defined below) no open
       differed;
     - the candle's own close differed on 4 names, which is why the scan uses
       the quote's official close (0 differed);
     - volume differed on 98.9% (median +0.02%, from -1.8% to +16.7%);
     - between the 17:55 evening pull and the 22:00 pull, the provisional
       open, high, low and close were identical on all 1,926 names. Volume rose
       on 749 of them (it never fell; median +0.07% among those, at most
       +7.4%). From 22:00 to 01:30 the provisional candle did not change at
       all. So on night 1, retries at 18:15 and 19:00 would have seen the same
       prices as the 17:55 sample. Volume only rose during the evening on
       night 1, so between the 17:30 sample and its retries Method 2's volume
       test could only move from fail to pass; against the final bar it can
       move either way (the final volume was lower on PBF and XRAY);
     - finality: at 22:00 no name was final; at 01:30, 99.0% (the other 19
       responses were truncated: one candle, no history, at 01:49:51-01:50:33;
       at 06:30 all 19 were final with full history); at 06:30, 100%. The final
       bars at 06:30 were identical to those at 01:30 on all 1,907 names final
       in both. Three names returned no history in any pull and are not
       compared.
     - The first count, 1,897 names, used only the 22:00 and 01:30 pulls
       (taken at 04:05, before the 06:30 pull began): it left out the 19
       truncated names and 10 names with fewer than 50 prior sessions. That
       night's threshold tests (none flipped) read sealed bars as look-back;
       see 3.7.
   - **Night 2 (session 2026-11-12)** is being taken by the earlier sampler
     too, started by hand in a session: old universe rules, no SPY, no
     1-minute bars, and three candles kept per evening row (90 per final
     row). Its universe-wide pulls are queued at 17:40 (the evening) and at
     00:30, 01:00, 04:30 and 06:30; the 04:30 and 06:30 pulls run only if the
     17:40 run ends without an error. A second script samples 12 names at
     17:40, at 20:30 and every 15 minutes from 23:30 to 04:30.
   - **Nights from 11-13:** you ruled yes on commit B and on installing the
     sampler's launchd job on 2026-11-12. Its launchd template,
     `deploy/launchd/com.stockmonitor.phase2barsample.night.plist`, is
     installed by your steps: replace `{{PROJECT_ROOT}}` with the project
     path, copy the file to `~/Library/LaunchAgents`, then run `launchctl
     load` on it. Until it is loaded, each night is sampled only by the
     earlier sampler started by hand in a session, at night-2 quality, or not
     at all. As of the afternoon of 11-12, nothing is started for 11-13.
   - **The sampler** (`loops/phase2/sample_bars.py`, run through
     `loops/phase2_sample.py`), as built in commit B; its schedule was ruled
     2026-11-12 with it. Each night it stores the evening quotes and
     provisional candles for a stand-in of the 3.1 universe plus SPY, the
     final candles overnight, and regular-session 1-minute bars for SPY, every
     name whose final open differs from its evening open, and every Method
     2-like name on quote fields. How it runs:
     - one launchd label runs its night mode on weekdays at 17:20 ET. Its
       template sets RunAtLoad, so once the template is loaded, a login also
       starts it. A process makes one pass per session it samples;
     - it holds an idle-sleep assertion from 17:20, ten minutes before the
       evening sample, until the night's last pull, so a daytime start does not
       keep the Mac awake. The assertion does not stop lid-close sleep, so
       sampled nights need the Mac on AC power with the lid open (step 3);
     - the evening sample runs at 17:30 ET, with retries at 18:15 and 19:00 if
       it FAILED or was INCOMPLETE. An evening is complete with SPY and at
       least 99% of the candidates (`params.completeness_min`); an incomplete
       one may be re-run for its missing names. An evening sample started
       after 19:30 (`params.watchdog_evening_et`) is LATE and stays out of the
       pooled numbers. An evening still INCOMPLETE whose retries were lost to
       sleep is notified once ("INCOMPLETE, and its retries were not made");
     - overnight pulls run at 00:30, 01:00, 01:30, 04:30, 06:30 and 07:30.
       Each takes only the names without a final bar yet, except the 06:30
       pull, which re-pulls every name so a final bar can be compared with a
       later one;
     - the token is checked before every pull (at least 3 hours left,
       `params.token_min_hours`). Once per pass, after the evening sample, the
       sampler warns you if the token will not still have those 3 hours left
       at the night's last pull;
     - a client is built for every pull, never one per night, so a
       re-authentication between pulls is picked up and never reverted. Do not
       re-authenticate while a pull runs (a pull takes about 20 minutes);
     - each pass first records MISSED-NIGHT, with one notification, for any of
       the last 10 sessions since the sampler's first night that has no usable
       evening sample;
     - it makes one catch-up final pull for each recent session whose evening
       sample has no completed final pull. A night whose INCOMPLETE pulls all
       started before its last pull time counts as not completed (a night cut
       short by a power loss, a crash or a token failure). A start before 17:20 makes these pulls while it waits for the evening; a start at or after 17:20 (the 17:20 launch itself, a later start or a roll-over) samples the evening first and makes them after it;
     - a pass whose session already has an evening sample and a final pull, DONE or INCOMPLETE, made at or after its last pull time does nothing. So after a complete
       night, a start on a weekend or a holiday, the 17:20 launch on a weekday
       holiday included, pulls nothing and holds no assertion;
     - if the process is still running at the next session's 17:20 (a Mac
       asleep through the night), it rolls over: it carries on into that
       session instead of losing it. If the Mac wakes on the next session's day after its 17:20, the pass stops its remaining overnight pulls (a wake two or more sessions later still makes them first); the next pass
       samples the new evening first, then catches up the earlier night. A
       process that has made 7 passes exits, with a notification naming the
       session it will not sample;
     - a Mac that is off at 17:20 samples that night on time only if it is
       started by 19:30: the login then starts the sampler's job, which
       samples the evening before any catch-up pull. Started after 19:30, its
       evening is LATE. If the Mac stays off, nothing is sampled and the next
       pass flags the missed night;
     - its calendar is a stand-in that ends 2027-03-31; a run keyed past it
       fails with a notification.
   - **The flip report and what it decides (ruled 2026-11-12).**
     - **Nights:** every night sampled through Fri 2026-11-20, up to eight
       nights, the 11-20 monthly expiration included. The report goes to you
       before go-live (target Mon 11-23).
     - **Contents, instead of a count of nights:** per-field difference rates
       per name-night; the open's difference in ATRs; each signal's margin to
       each threshold; exact binomial bounds on every flip count ("0 of 10 M2
       signals, 95% upper bound 26%"); and two Method 2-like strata. The bars
       stratum is |gap| >= 2% of the prior close and volume >= 2 x ADV30, on
       final bars; about 200 name-nights of it are wanted. The quote-field
       stratum is |open / prior close - 1| >= 2% and volume >= 2 x the 10-day
       average (`sample_bars.M2_LIKE_GAP`, `M2_LIKE_VOLUME`).
     - **Signal level (your 3.7 ruling of 2026-11-12):** the ATR, margin,
       signal-flip and bars-stratum parts read sealed-window bars as
       look-back for nights after 10-30, which the ruling allows, so every
       sampled night, nights 1 and 2 included, is compared at the signal
       level as well as field by field. The report carries no statistic
       aggregated over sealed sessions.
     - **What it decides.** Your acceptance bar, in your words (2026-11-12):
       "Flip report acceptance bar, fixed now before the report lands: a
       method gets evening tickets only if it had zero flips on every sampled
       night, in either direction (a ticket changed, disappeared, or appeared
       only on final bars). Judge M1 and M2 separately. Any flip keeps that
       method on recheck tickets." So M1 and M2 are judged separately:
       - a method with zero flips on every sampled night, in either
         direction, meets the bar. If you accept the report, you place that
         method's evening tickets from go-live, with the overnight recheck and
         the pre-open alert as the safety net;
       - a method with any flip (a ticket that changed, disappeared, or
         appeared only on final bars, on any sampled night) stays on recheck
         tickets, as does every method until you accept the report: its
         tickets come from the overnight recheck alone and are placed before
         the open (by 09:25). The evening scan still runs and writes its
         tickets without sending them, so the recheck can compare them;
       - your answers of 2026-11-12, in your words: "Keep all three k. The
         December pick can land on any of them, so the evidence has to cover
         every variant paper might trade. Count flips with the breadth filter
         on and off the same way, if you don't already." / "Yes. One flip
         after acceptance moves that method back to recheck tickets until the
         January review." / "Skip it like a missed night. The bar then needs
         at least 6 compared nights through 11-20. Fewer than 6 means not
         met." (The last answers which nights count: a night with a folder
         but no usable evening sample is skipped like a missed night.)
       - `compare_bars.py` prints, per method, "acceptance bar (ruled
         2026-11-12): met / not met" over every sampled night, LATE nights
         included; a MISSED-NIGHT or a night with no usable evening sample is
         skipped. A flip is a ticket, at any of the three k, with the breadth
         filter on or off, that changed, disappeared or appeared. A night
         without the ticket comparison cannot show zero flips and leaves the
         bar not met, and so do fewer than 6 compared nights through 11-20.
       - After acceptance, one flip on any later night moves that method back
         to recheck tickets until the January review; the nightly job (B5) checks this every night.
     - **Also ruled 2026-11-12:** LATE nights stay out of the pooled numbers
       (`--include-late` adds them only on request); the 1-minute bars are
       kept; go-live is recorded as a reviewed edit of
       `compare_bars.GO_LIVE_ACTUAL`, never a command-line flag.
     - **Later special sessions** (the 11-27 half day, the 12-18 quarterly
       expiration, the 12-24 half day) are added to the report as they come,
       and any flip on one is sent to you at once.
     - **The replay:** once `signals.py` exists (B4), every stored night is
       replayed through it both ways, with the same bounds per method (its
       look-back is allowed by the 3.7 ruling).

- **Completed-session guard:** the run of record processes only sessions whose
  bar is final; later candles are dropped. The evening scan uses the
  provisional bar as described above and is marked as such. *(The evening
  scan on provisional bars is your instruction; "the run of record" was
  ruled 2026-11-12, with the section 4 schedule. The approved guard
  applied to every run.)*
  - **B1 result** (samples on 2026-11-10 at 16:58, 17:35, 18:35 and 20:20 ET
    and on 2026-11-11 at 01:10 ET; AAPL, NVDA, F, AMC, PBT, SPY):
    - Through 20:20 ET the session's candle was still provisional. It was
      stamped midnight New York. Its close was not the official close on 2 of
      the 6 names (AAPL 348.562 against 348.51; NVDA 168.795633 against
      168.89), and its volume kept growing with after-hours trading.
    - By 01:10 ET a second candle for the same date was present, stamped
      midnight Chicago like every older bar. Its close equals the official
      close (the quote's regular-session last price) on all six names. Its
      volume is the final figure, 0.02% to 1.5% above the 17:35 figure. Open,
      high and low were identical in both candles.
    - The provisional candle was still listed beside the final one at 01:10,
      so the last candle in a response is not always the final one.
  - **So a bar is final when it is stamped midnight America/Chicago.** The
    guard tests the stamp, not the clock. A date whose only candle is stamped
    midnight New York is not final; where both exist, the final one is used.
    With that test the close needs no cross-check against the quote.
  - **Measured 2026-11-11/12:** at 22:00-22:20 ET every sampled candle for
    the session was still provisional. The tracked names' final candles
    appeared between 23:45 and 00:05 ET, and at 01:30-01:50 every complete
    response of the 1,926 names was final. *Ruled 2026-11-12, with the
    section 4 schedule: the recheck therefore starts at 01:00 ET with
    retries.* From night 2 on, the 00:30 and 01:00 pulls (step 4) show on
    every sampled night whether every name is final by the 01:00 pull.
- **Completeness gate:** SPY and at least 99% of the prior session's eligible
  names must have a bar for today. Otherwise the run is INCOMPLETE: notify,
  retry, and never log "no session" on a calendar session.

**Each run** (the evening scan and the recheck alike, except where a step says
otherwise; *the two runs and the steps marked "the recheck only" were ruled
2026-11-12, with the section 4 schedule*):
1. **Token check:** fail closed unless the token outlives max(now +
   `params.token_min_hours`, the last recheck retry of its night at
   `params.recheck_last_et`). At 17:30 that is about 14 hours. *(Ruled
   2026-11-12, with the section 4 schedule. The approved rule, at least 3
   hours of life left, stays as the floor. The sampler's own check is in
   step 4 of the schedule.)* Every notification states the token's expiry and
   escalates to "re-auth tonight" when needed.
2. **Refresh bars** from each symbol's last cached date, with a 15-session
   overlap.
   - **Basis-change detection:** across the overlap, a uniform ratio other than
     1 means a split, and a uniform dollar difference means a special
     distribution (B1b: FRO, $1.60). The full history is re-pulled, the levels and share counts
     of open forward and paper trades are rescaled, CORP-ACTION is logged, and
     a cancel-and-replace ticket is printed. (A split rescales levels and
     share counts by the ratio. A special distribution moves the levels by the
     dollar amount and leaves share counts alone.)
   - A tracked symbol with no bar for 2 sessions gets a CUSIP lookup. A rename
     continues under the new symbol; otherwise the trade is closed at its last
     print, labeled DELISTED, and kept in the statistics.
   - The directory files are archived nightly (the forward universe is truly
     point-in-time).
   - *Ruled 2026-11-12, with the section 4 schedule:* the forward-trade
     actions in this step (rescaling open forward and paper trades,
     CORP-ACTION, the DELISTED close and the 2-session missing-bar count)
     belong to the recheck only. The evening scan detects a basis change,
     warns, and prints any cancel-and-replace ticket as PROVISIONAL.
3. **Pull the session's 8-K Item 2.02 filings** with header acceptance times
   (EDGAR, approved D5).
4. **Signals for all 12 variants,** with breadth-blocked and unsizable signals
   logged too.
5. **Forward tracker** (the recheck only: the run of record; *ruled
   2026-11-12, with the section 4 schedule*): advance every forward trade with
   `fills.py`.
   - Idempotent, keyed by session: each run rebuilds every tracked order from
     its signal day on the stored bars. `fills.py` consumes a session once and
     refuses a replay, so a bar that arrives late, or a corrected breadth
     figure, is applied by the next rebuild and is never silently ignored. The
     tracker therefore always equals what the backtest computes from the same
     bars.
   - Report-only: a 1-minute-bar audit of each fill and exit session.
   - Report-only: regular-hours bid/ask snapshots for signaled, pending and
     open names, to check the spread model. These need the Mac awake during
     market hours.
6. **Paper book update and tickets** (below). The evening scan writes
   PROVISIONAL tickets; the recheck rebuilds them on final bars and compares
   (schedule, step 1c). Paper slots are allocated by the run whose tickets you
   place. *(Ruled 2026-11-12, with the section 4 schedule.)*
7. **Self-parity** (the recheck only; *ruled 2026-11-12, with the section 4
   schedule*): re-derive the night's outputs from the decision snapshot with
   `--as-of` and diff them against what the run produced. Any difference sends
   an alert.
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
         1st trgs OCO:  SELL -N SYM LMT <P> GTC  /  SELL -N SYM STP <S> GTC  (trigger: STD)

  (The sell stop's STD was ruled 2026-11-12: section 5, item 5.) It shows the
  sizing math, in the format of `orders.sizing_lines` (ruled 2026-11-12),
  deployment and cash after, positions after, and any 2nd-in-sector flag.
- **CANCEL, TIME-EXIT and REPLACE instructions** carry a hard deadline
  ("before 09:25 ET Fri 12-04") and the exact sequence: cancel the whole group,
  confirm it is gone, then act. Never edit an order in place.
- **Live-account alarm:** in both runs (*ruled 2026-11-12, with the section
  4 schedule; approved: every night*), read-only, the live account must have no
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
- a nightly SHA-256 manifest of signals, trades, the paper ledger and the
  8-check record (`placements.jsonl`) is kept outside `logs/` and backed up,
  and committed at milestones (diff first). *(The 8-check record as its own
  file was ruled 2026-11-12, section 5, "Two records".)*

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

**Drill placements (your instructions, 2026-11-11 and 2026-11-12; the
construction rules below were ruled 2026-11-12).** Your words: "I want to
rehearse the order mechanics in paperMoney while the scan gets built.
Generate one drill ticket tonight from today's close: a liquid name, a buy
stop-limit entry near the market so it likely fills tomorrow, and a
1st-triggers-OCO bracket with a sell limit target and a sell stop, all GTC,
sized on the $1,500 basis. I'll place it tonight and send a screenshot, then
another after it fills. Run the 8-check on both, including that the bracket
goes live correctly after the fill. Count it in the 8-check record and keep
it out of the paper P&L ledger." Your words on 2026-11-12: "Drill: not
placed. Issue a fresh ticket from tonight's close." So DRILL-2026-11-11-01
was never sent: it is void (8-check record row seq 9) and does not count.
DRILL-2026-11-12-01, issued from the 2026-11-12 close, replaces it under the
same instruction. Neither is a scan signal, and neither claims an edge.
DRILL-2026-11-12-01 is your explicit exception to "entries come only from the
Phase 2 nightly scan", as DRILL-2026-11-11-01 was.
- **How a drill is built (ruled 2026-11-12):** its entry sits near the market
  so that it fills soon, and above the after-hours ask, since thinkorswim
  warns on a buy stop at or below the market: trigger T = max(max(close,
  after-hours last) + max(0.10 x ATR, $0.05), after-hours ask + $0.01),
  rounded up to the cent, from a quote whose time and bid/ask are printed on
  the ticket. The rest is as before: C, S and P follow 3.4 (the 0.25-ATR
  ceiling, a 1.5-ATR stop with no structural stop, a 3R target), and N the
  $1,500 sizing. The name is chosen by a printed rule, never by a view. The
  ticket carries no fill-rate figure: under your 3.7 ruling, no ticket
  carries a statistic aggregated over sealed sessions. This rule replaces the
  earlier proposal, trigger = max(close, after-hours last, after-hours ask) +
  max(0.10 x ATR, $0.05). (DRILL-2026-11-11-01's trigger left out the ask, so
  its T, 50.85, was at times below the after-hours ask, which ranged from
  50.74 to 50.90.)
- **DRILL-2026-11-12-01 counts toward Check 3** (your instruction: "Count it
  in the 8-check record"); DRILL-2026-11-11-01 does not. Counted this way, a
  first-try pass fills one of the ten placements Check 3 needs, and a fail
  fails Check 3 until ten later placements exist. Your ruling of 2026-11-12:
  "DRILL-2026-11-12-01 counts both ways." A drill after DRILL-2026-11-12-01
  counts only if you say so when you ask for it (ruled 2026-11-12).
- **DRILL-2026-11-12-01 is kept out of the paper P&L ledger** (your
  instruction) and is in the 8-check record like any other placement.
  Ruled 2026-11-12: it is also kept out of the paper book (it takes no
  slot, risk or deployment) and out of the forward log.
- *Ruled 2026-11-12:* a drill ticket states its own end: a CANCEL after the
  last session of its entry window (three sessions, from the NYSE calendar); a
  CANCEL that evening if it opens above C and has not filled by the close; a
  close-out by a stated date if the position is still open, so the account is
  flat before the nightly goes live. For DRILL-2026-11-12-01 the entry window
  is the three sessions Fri 11-13, Mon 11-16 and Tue 11-17: a CANCEL if it has
  not filled by the close of Tue 2026-11-17; a CANCEL that evening if it opens
  above C on one of them and has not filled by the close; and a close-out at
  the close of Fri 2026-11-20 if the position is still open. Until the nightly
  goes live (B5), nothing sends these lines automatically: I post them in a
  conversation with you on the dates printed on the ticket, and on a day with
  no conversation, you follow the end lines on the ticket yourself. After B5
  the nightly job sends them.
- *Ruled 2026-11-12:* items 3 and 7 on a drill are read against this
  section's wording and marked provisional until the golden probe exists. A
  provisional item scores as read. If the golden probe later shows the reading
  was wrong, the placement is re-scored with a correction row and you are
  told.

**Placed or not placed** *(ruled 2026-11-12)*: nothing is placed, and
nothing is scored, only if thinkorswim never accepts the order: the ticket is
never sent, an error comes before any order ID exists, or you stop at the
confirmation dialog. The unsent ticket gets a void row, and a new ticket gets
its own id, from the date it is issued. Once any leg has an order ID, it is a
placement and is scored, a leg shown REJECTED included (items 4 and 7).
DRILL-2026-11-11-01 was never sent (your word, 2026-11-12), so it has a void
row (seq 9) and is not scored; DRILL-2026-11-12-01 replaces it.

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
5. Target LMT at P and stop STP at S, exactly, the stop's trigger STD.
   *(STD on the stop ruled 2026-11-12: the model stops out on low <= S, so
   the exit stop needs the same trigger as the entry. The exit line in
   section 4 and in `orders.ticket_lines` is
   `SELL -N SYM STP <S> GTC  (trigger: STD)`.)*
6. All three legs GTC.
7. Status: parent WORKING or QUEUED, both children WAIT TRG (API:
   AWAITING_PARENT_ORDER, correct only while the BUY parent is unfilled), and
   no leg REJECTED.
8. No working orders beyond the expected set: the orders of every placement
   whose 8-check record is still open, scan and drill alike, as listed on the
   ticket. *(Ruled 2026-11-12: the approved "the ledger's expected set" left
   out drills, which have no ledger row.)*

**Activation check** (after the entry fills; this is the original 8-check):
- the position quantity is N, the $1,500-basis count;
- the fill is <= C;
- both exits are WORKING and linked as an OCO, at the exact levels, -N, GTC,
  and both SELL TO CLOSE (the 9/17 AR error went live with a SELL SHORT stop)
  *(the SELL TO CLOSE clause ruled 2026-11-12)*;
- no live entry; no working orders or positions outside the expected set
  *(ruled 2026-11-12; the approved wording was "no strays")*.

On the drill's after-fill screenshot (your instruction, which now applies to
DRILL-2026-11-12-01: "Run the 8-check on both, including that the bracket goes
live correctly after the fill") all eight items are read again, item 7 in its
FILLED wording, together with the activation check. Ruled 2026-11-12: the
same re-read for every placement. After the fill, items 2 and 3 read the BUY
parent in Filled Orders (BUY +N, stop T, limit C, filled at or below C) and
the two exits linked as an OCO. A failed re-read fails the first-try pass,
like a failed activation check.

**Interim scoring (ruled 2026-11-12):** DRILL-2026-11-12-01 is scored under
its ticket's own wording, as the 8-check record set out for
DRILL-2026-11-11-01 (rows seq 4 and 7), so item 8 reads the drill's own group
as the expected set. On its after-fill screenshot, items 2 and 3 are read
from Filled Orders, where the ticket asks for the BUY's stop and limit as
well as its fill price and time, and from the two linked exits. A re-read
result outside the activation check is recorded and reported to you; under
the re-read ruled above, a failed re-read fails the first-try pass.

Ruled 2026-11-12: a simulator artifact (a fill the moment the order is
sent, a fill above C, a fill outside 09:30-16:00) is logged as an incident for
your judgment, like a partial fill, not as a construction error.

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

**Two records** *(ruled 2026-11-12; your instruction kept the drill in the
8-check record and out of the paper P&L ledger, which the spec had as one
file)*:
- **The 8-check record** (`logs/phase2/placements.jsonl`, append-only: a row is
  never edited, and a correction is a new row naming the one it corrects).
  Every placement has one, scan, replacement, late and drill tickets alike.
  The event types are issue, addendum, capture, score, instruction, incident,
  deviation, note, rule, expected_set, void and disposition: an issue row
  first, then the others as they happen. A "rule" row quotes one of your
  rulings; a proposal of mine goes in a "note" row (row seq 5 is a "rule"
  row that records a proposal, as row seq 7 says). Every row carries a
  sequence number, the event type, the placement id and its time. Rows 1 and
  2 of DRILL-2026-11-11-01 predate sequence numbers and are seq 1 and 2 (row
  3 says so); row 1, the issue row, has no event field and gives its time as
  "issued". Check 3, the activation results and the process-deviation tally
  are computed from this file only.
- **The paper ledger** (`logs/phase2/paper_ledger.jsonl`, the paper P&L): one
  row per scan placement, keyed by its placement id: method, ticker, N,
  T/C/S/P, sector, paperMoney fills, exit type, R, and the
  simulator-vs-paperMoney fill difference. The paper book, paper R and the P&L
  side of the Friday reconciliation read this file only. A drill has no row;
  the reconciliation matches drill orders and fills to their 8-check record.

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
counts as a fail. DRILL-2026-11-12-01 counts here: it replaces
DRILL-2026-11-11-01, which was never sent and does not count, under the same
instruction (yours, 2026-11-11 and 2026-11-12). It counts both ways (your
ruling of 2026-11-12: "DRILL-2026-11-12-01 counts both ways."): a first-try
pass fills one of the ten placements Check 3 needs, and a fail fails Check 3
until ten later placements exist (section 5). Later drills count only as
section 5 says.

**The January report also reminds you to:**
- **switch the live account from margin to cash before funding it.** It reports
  as a MARGIN account today, where a mis-built short-sale exit opens a short
  instead of being rejected;
- settle the funded-account procedure: per-order approval or a standing
  approval of the system, and the sizing basis;
- decide whether an off-machine alert is needed (your 2026-11-12 'not now').

---------------------------------------------------------------------------

## 7. Tests and regressions

- **Unit tests:**
  - every M1/M2 qualify/reject path;
  - every fill branch: opening fill; intraday trigger; triggered-unfilled with
    no fill and cancel; fill at C on a trade-through, both target-credit
    variants; entry-day stop; gap-through; gap past the target; both levels
    touched; the trade-through boundaries (high = P, low = C, open = P and
    open = P + 0.01); time exit with
    the OCO first on session 41; replacement; invalidation; breadth cancel;
    missing-bar gap; split rescale during an open trade; special-distribution
    shift; the seal and the exact scope of its one exemption;
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

- **B0 (done, commit 0183433).** Spec v3, the Phase 2 block in
  trading-rules.md and the token monitor change.
- **B1. Data-contract checks (read-only; started 2026-11-10).** Done:
  - paperMoney is not visible to the API (section 5);
  - daily history is deep enough: 1,471 AAPL bars from 2021-01-04, and a 1990
    window also returns;
  - timestamps: only New York-date conversion is correct (section 2);
  - splits: price and volume are both back-adjusted (3.1);
  - delisted names are missing (3.1);
  - `assetSubType` is useful but incomplete (3.1);
  - quotes: `regularMarketLastPrice` is the 16:00 close and `closePrice` is the
    previous close, less any dividend going ex that day (F on 2026-11-10: 12.37
    against a 12.52 bar close, its $0.15 dividend), so it is not used as a
    price check. `lastEarningsDate` exists and is kept only as an audit field;
  - EDGAR: the filing index carries item codes and SIC codes. Acceptance times
    in the JSON matched the filing headers on four Apple earnings 8-Ks; the
    headers stay the source.

  - final bars carry the official close: this project's 4:15 pm end-of-day
    marks match today's bar closes to the cent on 12 of 13 names held (FRO is
    the special-distribution case in 3.1).

  - bar finality: a final bar is stamped midnight America/Chicago and carries
    the official close and the final volume. Overnight a second, provisional
    candle for the same date (stamped midnight New York, with an unofficial
    close) can sit beside it (section 4).

  - when the final bar appears: for the six tracked names, between 23:45 and
    00:05 ET; by 01:50 every complete response of the 1,926 names was final
    (2026-11-11/12, section 4). Some responses come back truncated (one
    candle, no history); the commit B sampler and the `bars.py` retry
    (ruled 2026-11-12) retry them.

  Still open in B1:
  - more nights of finality and flip sampling (section 4);
  - your golden paperMoney probe (section 5).
- **B1b.** `fills.py` and its unit tests (diff first), then the known-answer
  calibration on the 14 real stop-outs.
  - **Result (2026-11-10):** all 14 exits replay on the right day, 12 intraday
    and 2 gap-throughs (AR, RRC), classified from the bars.
  - Under the approved draft's g x ATR rule: with g = 0 the model is optimistic
    on RRC by 2.4 cents; g = 0.05 fixes it.
  - **No value of g fixes CXM:** an intraday stop at $5.00 that really filled at
    $4.96, 3 cents below the model's S - h. Open-fill slippage can't reach an
    intraday fill, so the approved calibration can't satisfy the known-answer
    contract. **Ruled 2026-11-11: every stop exit pays 4 half-spreads (3.4),
    and g is gone.** With it the model is below the real fill on 13 of the 14
    and ties CXM.
  - **Review (2026-11-10 and 11-11).** Four independent reviewers (entry
    rules, holding rules, costs and params, mutation testing) checked
    `fills.py` against this spec.
    - **The code matched the spec.** No fill, exit, price, cost or R differed
      from the text. Their spec-derived oracles agreed with the code as it
      stood before your 11-11 rulings on 5.9 million cases with no mismatch,
      and 43 hand traces passed.
    - **The tests were too weak.** 163 of the reviewers' roughly 540
      deliberately broken copies of the code passed the first suite, because
      every test order had ATR = T - S = $1.00 and cent-grid prices.
    - **Changes made from the review:**
      - tests: 87 -> 206, on two fixtures (the second has ATR 0.40, T - S 0.60
        and a 5 bps tier) and with sub-cent prices;
      - the OOS seal in `fills.py`, with the known-answer exemption (3.7);
      - sessions are consumed once, in order, and the tracker rebuilds from
        the signal day (section 4);
      - prices compared in millionths of a dollar (B1 saw six-decimal bars);
      - `fills.shift` for special distributions (3.1);
      - no silent defaults or inputs: breadth and params must be passed, and a
        bad tier, a non-finite number, a stale order or a close that an open
        trade can't have is an error;
      - the crash-bar row follows the text literally (open > S);
      - 13 spec numbers that had no field in `params.py` now have one, and a
        test compares every field with this spec.
    - **After those changes, before your rulings:** 889 broken copies were
      run against the tests of the time: the 508 of the reviewers' that still
      applied, 59 rewritten by hand for the lines that changed, and 322
      generated mechanically. 867 were caught; the 22 that passed were each
      checked.
    - **Side finding:** the September gate-regression harness had gone red on
      one hard row (FRO 2026-07-29) for the same reason as the known-answer
      fixture: it replayed a recorded price of 38.60 on bars Schwab has since
      rebased by $1.60. With the price moved onto the bar basis the row
      replays as recorded (stop 0.909 x ATR) and the harness is 16/16 again.
  - **Your rulings (2026-11-11), applied in 3.4, 3.5 and 3.7:**
    1. stop exits: 4 half-spreads on every stop exit, not a flat cent value;
    2. the seal exemption: yes, scoped to the 14 real fill records and the
       bars those trades need;
    3. an open exactly at P: the trade-through at P + 0.01 is required;
    4. the "costs x 2" row doubles slippage as well as spreads. With ruling 1
       the stop-exit charge is itself in half-spreads, so the row doubles
       every cost.
    After these, the Phase 2 tests pass, the known-answer contract among them.
    A second independent review then checked the rulings as applied
    (2026-11-11). Five of its six agents reported and found no blocker:
    spec consistency, test quality, a new spec-text cost oracle (no mismatch
    on 500,000 scenarios and 2.8 million boundary bars), a boundary grid and
    a mutation run. The gaps they found were in the tests (rule 2 at exactly
    P + 0.01, costs x 2 on limit fills, the seal on a trade already open, the
    exemption's exact scope) and are closed: 240 Phase 2 tests. The sixth
    agent, an attack on the seal exemption, was stopped unfinished when the
    usage limit was reached; the exemption check was tightened from the other
    agents' findings.
  - **Seal hardening (030af69, committed 2026-11-12 with your word).** A
    later attack on the seal found that a string, a look-alike object or a
    moved or inverted params window could get past it. The commit makes the
    seals private identity objects and fixes the spec's window in `fills.py`;
    its contract test pins every place a scanned repo file writes an unseal
    name and fails a lookup of the fills module by a computed name in the
    plain forms. Commit B widens that scan to notebooks, makefiles and larger
    files (3.7). 276 tests.
- **B2. Freeze:** spec + params (with the night schedule) + code hash,
  committed before any IS number exists. The night schedule's times are
  operational and enter no backtest number. *(The night schedule, and the
  freeze including it, were ruled 2026-11-12, with the section 4 schedule; the
  approved text froze the bar-finality cutoff here. `params.PENDING_RULING` is
  now empty, so no field awaits a ruling. T's rounding (3.4) and the universe
  rules (3.1), which are not params fields and change backtest numbers, were
  ruled 2026-11-12 too.)*
- **B3. Pulls:** the directory, security types, bars from 2021-01-04, the
  yfinance split table, EDGAR 8-K Item 2.02 headers and SIC codes. About 4-5
  hours of machine time, most of it the paced EDGAR header pull.
- **B4.** universe / events / signals, the sector map and its validation, tests
  and contracts, and the feasibility estimate (section 6). The universe
  carries your 2026-11-12 rulings (3.1): BDCs in, known by their SEC 814-
  file number; MLPs out by the K-1 criterion, not by name; SPACs also by SIC
  6770. *Ruled 2026-11-12:* then the flip replay: every stored night through `signals.py`
  both ways (section 4, step 4; its look-back reads sealed bars, which the
  3.7 ruling allows).
- **B5.** The nightly goes live (target the week of Nov 23): forward logging and
  default-config paper tickets. *Ruled 2026-11-12, with the section 4
  schedule:* the forward log comes from the overnight recheck. If you accept
  the flip report before go-live, the evening tickets start at go-live for
  each method that meets your acceptance bar; every other method, and every
  method until you accept the report, gets recheck tickets placed before the
  open (section 4, step 4). Go-live is recorded as a reviewed edit of
  `compare_bars.GO_LIVE_ACTUAL`.
  From acceptance on, it re-checks each method every night, and one flip
  moves that method back to recheck tickets until the January review
  (ruled 2026-11-12).
- **B6a.** IS run and pick commit (early December). I ask then whether paper
  tickets switch to the picks (approved in principle, D9).
- **B6b.** Sealed OOS after the 2026-12-30 close, and the Part 1 report.
- **B7.** Decision report 2027-01-15, and M2's on 2027-03-12 if it was extended.

---------------------------------------------------------------------------

## 9. Decisions (approved 2026-11-10, ruled 2026-11-11 and 2026-11-12)

| | Decision | As approved |
|---|---|---|
| D1 | Phase 2 rule block | Yes, with your fix: position cap **17.5% ($262.50)**, so four full positions fit the 70% cap. The 3-share minimum then limits paper to ceiling prices <= $87.50 and risk <= $5.00 a share |
| D2 | Stop rule | S = min(structural stop, T - k x ATR) |
| D3 | Exits | 3R static target; time exit at the session-41 open; no trailing; M1 keeps rr >= 3 on its structural stop |
| D4 | M1 mechanics | Touch rule; trigger 1 cent over the signal-day high, rounded up to the cent (**ruled 2026-11-12**, 3.4); ceiling +0.25 ATR; 3-session window |
| D5 | M2 earnings dates | SEC 8-K Item 2.02 with filing-header times; price/volume fallback for foreign issuers. The contact you supplied lives in `.env` only and is never committed |
| D6 | Universe and splits | Security types plus directory rules; MLPs, royalty trusts and SPACs excluded; split table via yfinance; survivorship flagged. **Ruled 2026-11-12, for B3/B4 (3.1):** BDCs are in, known by their SEC 814- file number, not by name; MLPs are excluded by the approved K-1 criterion, not by name (so PAGP and HESM, 1099 issuers, are in); SPACs are also identified by SIC 6770. The stand-in sampler keeps its name rules |
| D7 | Fills and costs | The model in 3.4, calibrated on the 14 real stop-outs before the freeze. **Ruled 2026-11-11: every stop exit pays 4 half-spreads; no separate slippage; a gap past the target needs P + 0.01; the costs x 2 row doubles every cost** |
| D8 | Protocol | Fill-date windows; OOS sealed in code; pick eligibility; sealed OOS after 12-30; bug rules. **Ruled 2026-11-11: one seal exemption, for exact replays of the 14 known-answer records and the bars they need. Ruled 2026-11-12: sealed bars may be read as look-back to compute indicators (ATR, shelves, dollar volume, breadth) for any session after 2026-10-30; statistics aggregated over sealed sessions stay off-limits, except the 14 real fill records; the drill's fill-rate figure stays disclosed and is not repeated** |
| D9 | Paper process | The ledger is the record, split into two records, the 8-check record and the paper ledger (**ruled 2026-11-12**, section 5); 2 slots per method; **SIC codes mapped to the 11 GICS sectors**; paper switches to the IS picks in December (asked again then) |
| D10 | Part 4 | Analog-window band plus the count rule; Check 3 = placement + activation; funding per method; **M2 extends to 2027-03-12 if short of the count, which is never lowered** |
| D11 | Operations | Nightly run plus retries; token fail-closed; live-account alarm; token-monitor warning at 5.0 days (**applied 2026-11-10**). **Instructed by you, 2026-11-11:** an evening scan on provisional bars; an overnight recheck on final bars; an alert before the open if any ticket changed or disappeared; an alert if a nightly run misses its window; measure how often provisional bars flip a signal before relying on the evening scan. **Accepted by you, 2026-11-12:** the Mac precondition (section 4, step 3): "I'll keep it plugged in with the lid open on ticket nights." **Ruled 2026-11-12** ("yes on items 1 to 8 as recommended"): the night job and the watchdog (section 4, steps 1 and 2: the two runs with the recheck as the run of record, the ticket states with the CANCEL / REPLACE splits, the UNCONFIRMED default, rules e and f, the morning message with an alarm no earlier than 07:00, the token horizon), the `bars.py` truncated retry, the freeze including the night schedule, the sampler and installing its launchd job, and the flip report with what accepting it decides. **Your acceptance bar, 2026-11-12:** "a method gets evening tickets only if it had zero flips on every sampled night, in either direction (a ticket changed, disappeared, or appeared only on final bars). Judge M1 and M2 separately. Any flip keeps that method on recheck tickets." **Off-machine alert, 2026-11-12:** "not now", on the January list (section 6) |
| D12 | Drill | **Instructed by you, 2026-11-11:** one drill ticket from that day's close, to rehearse the order mechanics in paperMoney: a liquid name, a buy stop-limit entry near the market, a 1st-triggers-OCO bracket with a sell limit target and a sell stop, all GTC, sized on the $1,500 basis; the 8-check on both screenshots, including that the bracket goes live correctly after the fill; counted in the 8-check record and kept out of the paper P&L ledger. **Instructed by you, 2026-11-12:** "Drill: not placed. Issue a fresh ticket from tonight's close." DRILL-2026-11-11-01 was never sent and is void (8-check record row seq 9); DRILL-2026-11-12-01, from the 2026-11-12 close, replaces it under the same instruction. **Ruled 2026-11-12** ("yes on items 1 to 8 as recommended"): the drill rules (the construction T = max(max(close, AH last) + max(0.10 ATR, $0.05), AH ask + $0.01) rounded up; end lines; out of the paper book and the forward log; later drills count only if you say so when asking; items 3 and 7 provisional until the golden probe; numbering; interim scoring) and the 8-check changes (item 5's STD on the sell stop, item 8's expected set, the after-fill re-read for every placement, the activation additions, placed or not placed, simulator artifacts as incidents, two records). "DRILL-2026-11-12-01 counts both ways" in Check 3 |

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
