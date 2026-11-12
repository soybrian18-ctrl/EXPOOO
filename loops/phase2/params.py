"""Phase 2 parameters -- every number in specs/phase2_spec.md, in one place.

STATUS: NOT FROZEN. One value is still unset and blocks the freeze (spec 3.7
step 1, build step B2):
  * ``bar_final_cutoff_et`` -- the earliest time the nightly may expect final
    bars (spec 4). B1 found that a bar is final when it is stamped midnight
    America/Chicago; the time of day that stamp appears is still being sampled.
The stop-exit cost was ruled on 2026-11-11 (spec 3.4): every stop exit pays 4
half-spreads, the smallest whole number that keeps the model from being more
optimistic than any of the experiment's 14 real stop-outs. It replaces the
open-fill slippage g.
After the freeze, any edit here is a non-bug change under spec 3.7 step 7.

Section references are to specs/phase2_spec.md. The NYSE calendar (holidays and
13:00 closes) joins this file when the bars are pulled (B3), validated against
SPY's own bar dates; spec 3.7 step 1 allows that re-freeze before the first IS
number.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Params:
    # --- 3.1 universe -------------------------------------------------------
    price_min: float = 5.0                 # as-traded close, lower bound
    price_max: float = 100.0               # as-traded close, upper bound
    adv_min_shares: int = 500_000          # as-traded average volume floor
    adv_window: int = 30                   # sessions ending t-1
    min_history_sessions: int = 60
    bars_present_min: int = 58             # bars present in the prior ...
    bars_present_window: int = 60          # ... 60 sessions
    bars_start: str = "2021-01-04"         # bars pulled from here for warm-up; signals start at is_start

    # --- 3.2 signals --------------------------------------------------------
    levels_window: int = 120               # trailing bars passed to compute_levels
    trigger_offset: float = 0.01           # T = high(t) + 0.01
    ceiling_atr: float = 0.25              # C = T + 0.25 ATR
    stop_buffer_atr: float = 0.2           # S0 = structure - 0.2 ATR (both methods)
    touch_atr: float = 0.25                # M1: low(t) <= anchor + 0.25 ATR
    m1_min_rr: float = 3.0                 # M1: rr to the 40-session high, structural stop
    m1_window: int = 3                     # M1 entry window, sessions t+1..t+3
    m2_window: int = 5                     # M2 entry window, sessions t+1..t+5
    m2_gap_pct: float = 0.03               # gap >= max(3% of prior close, ...
    m2_gap_atr: float = 1.0                # ... 1.0 x ATR at t-1)
    m2_volume_mult: float = 3.0            # volume(t) >= 3.0 x 30-session average ending t-1
    m2_close_range_min: float = 0.5        # "held": close(t) at or above the midpoint of day t's range
    m2_spy_gap_max: float = 0.01           # fallback mode: SPY gap < +1.0%
    m2_cadence_sessions: int = 40          # fallback mode: no detected event in prior 40 sessions
    edgar_window_start_et: str = "16:00"   # acceptance after 16:00 ET on the prior session ...
    edgar_window_end_et: str = "16:00"     # ... and no later than 16:00 ET on t

    # --- 3.3 breadth --------------------------------------------------------
    breadth_sma: int = 50                  # closes t-49..t
    breadth_min: float = 0.50              # entries blocked below 50%

    # --- 3.4 brackets and exits --------------------------------------------
    stop_k: tuple = (1.0, 1.5, 2.0)        # S = min(S0, T - k x ATR)
    default_k: float = 1.5                 # paper default
    default_breadth_on: bool = True        # paper default
    target_r: float = 3.0                  # P = T + 3 x (T - S)
    time_exit_session: int = 41            # still open after session 40 -> sold at the open of session 41
    trade_through: float = 0.01            # resting limits need a 1-cent trade-through

    # --- 3.4 costs ----------------------------------------------------------
    # (minimum average dollar volume, half-spread in bps); first match wins
    cost_tiers: tuple = ((100e6, 5.0), (25e6, 10.0), (5e6, 20.0), (0.0, 40.0))
    cost_dollar_volume_window: int = 30    # sessions ending t-1, fixed at the signal
    min_half_spread: float = 0.005         # half a cent per leg
    open_fill_cost_mult: float = 2.0       # opening fills (gap-up entries, time exits) pay 2h
    stop_exit_cost_mult: float = 4.0       # every stop exit, intraday or gap-through, pays 4h (ruling 2026-11-11)

    # --- 3.4 sensitivity rows ---------------------------------------------
    # Report-only, with one exception: rule A6 judges Check 1 on the costs x 2 row
    # if measured spreads run more than 50% over the model.
    cost_mult: float = 1.0                 # 1.0 for every judged number; the sensitivity row uses ...
    cost_sensitivity_mult: float = 2.0     # ... "costs x 2": every cost doubles, stop exits included (ruling 2026-11-11)
    crash_bar_bound: bool = False          # stop sessions with open > S and low < S - 1 ATR fill at the low
    crash_bar_atr: float = 1.0

    # --- 4 paper sizing -----------------------------------------------------
    basis: float = 1500.0
    risk_pct: float = 0.01                 # $15
    position_cap_pct: float = 0.175        # $262.50 (four full positions fit the 70% cap)
    deployment_cap_pct: float = 0.70       # $1,050
    open_risk_cap_pct: float = 0.04        # $60
    max_positions: int = 4
    max_per_method: int = 2
    max_per_sector: int = 2
    min_shares: int = 3

    # --- 3.7 / 3.8 protocol and pass rules ---------------------------------
    is_start: str = "2022-01-03"           # IS = fills dated is_start..is_end
    is_end: str = "2024-12-31"
    oos_start: str = "2025-01-02"          # OOS = fills dated oos_start..oos_end
    oos_end: str = "2026-10-30"
    oos_seal_close: str = "2026-12-30"     # sealed OOS runs once, after this close
    p1_min_trades: int = 300
    p2_min_avg_r: float = 0.20
    pick_min_is_fills: int = 187           # 300 x 753/1,212, rounded up
    pick_tie_r: float = 0.005              # |difference| below this is a tie ...
    pick_tie_breadth_on_first: bool = True # ... which goes to breadth on, then ...
    pick_tie_k_order: tuple = (1.5, 1.0, 2.0)   # ... to k in this order
    p4_remove_trades: int = 3
    p4_remove_months: int = 3              # A1: binding form
    p5_runs: int = 1000                    # random-entry runs
    p5_beat_pct: float = 95.0              # pick must beat at least 95% of them
    p5_redraws: int = 20
    a2_min_oos_trades: int = 100
    a3_exclude_start: str = "2026-04-24"   # M1 only: slice its rules were shaped on
    a3_exclude_end: str = "2026-09-22"
    a6_spread_excess: float = 0.50         # measured median half-spread > model by 50% ...
    a6_min_obs: int = 30                   # ... on at least 30 observations
    random_seed: int = 20261110            # base seed: every seeded procedure (P5 runs, tie orders, bootstrap) derives its stream from it

    # --- 3.8 / 3.9 report-only rows ----------------------------------------
    bootstrap_level_pct: float = 90.0      # bootstrap interval ...
    bootstrap_block_months: int = 3        # ... on 3-month blocks
    survivorship_stress_r: float = -1.0    # stress row: each missing delisted trade at -1R
    sim_tie_orders: int = 200              # portfolio simulation: random same-day tie orders

    # --- 6 decision ---------------------------------------------------------
    decision_date: str = "2027-01-15"
    m2_extension_date: str = "2027-03-12"  # if M2 is short of the minimum count on 01-15
    band_lo_pct: float = 5.0
    band_hi_pct: float = 95.0
    min_forward_trades_floor: int = 10     # minimum = max(10, 5th percentile of window counts)
    check3_placements: int = 10
    go_live_target: str = "2026-11-23"     # forward logging target; L is frozen at the actual go-live
    # B4 feasibility estimate: fill counts only, on these IS-year spans
    feasibility_spans: tuple = (("2022-11-23", "2023-01-13"), ("2023-11-23", "2024-01-12"))

    # --- 4 nightly ----------------------------------------------------------
    nightly_run_et: str = "17:30"          # PROVISIONAL (spec 4) until the bar-finality decision
    nightly_retry_et: tuple = ("19:30", "21:00", "06:30")
    bar_final_cutoff_et: Optional[str] = None        # UNSET until the bar-finality samples are in
    completeness_min: float = 0.99         # SPY and >= 99% of the prior session's eligible names
    token_min_hours: float = 3.0
    request_limit_per_min: int = 100
    refresh_overlap_sessions: int = 15     # bars are re-pulled with this overlap (basis-change detection)
    missing_bar_cusip_sessions: int = 2    # a tracked symbol with no bar this long gets a CUSIP lookup
    sector_map_min_agreement: float = 0.90 # SIC -> GICS map validation target
    ticket_deadline_et: str = "09:25"      # CANCEL / TIME-EXIT / REPLACE instructions are due before this
    live_balance_baseline: float = 1.01    # 2026-11-10; a drop below it triggers a transaction pull


PARAMS = Params()


def params_hash(params: Params = PARAMS) -> str:
    """SHA-256 of the canonical parameter set; printed in every report and log line."""
    blob = json.dumps(dataclasses.asdict(params), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def unset(params: Params = PARAMS) -> list[str]:
    """Names of values that still block the freeze."""
    return [f.name for f in dataclasses.fields(params) if getattr(params, f.name) is None]
