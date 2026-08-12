---
description: Loop 3 — run the gated equity-research loop, present a 9-section report + proposed OCO cells, and write the execution handoff for approval. The command never places orders itself.
---

You are running **Loop 3 (Equity Research Loop)**. Follow these steps EXACTLY. The
approval gate at the end is NON-NEGOTIABLE.

1. **Re-read `references/trading-rules.md` in full** and apply it (binding context).

2. **Pre-flight + live balance (Alpaca — the EXECUTION account).** Run:
   `.venv/bin/python loops/alpaca_account.py`
   - If the JSON has an `error`: send a desktop notification
     (`osascript -e 'display notification "Equity research aborted: Alpaca connectivity problem" with title "Equity Research"'`)
     and **STOP**. Do not proceed.
   - Otherwise capture `equity`, `cash`, `deployed_pct`, `position_count`, and `held_symbols`.
     **Sizing and the rule gates are computed against THIS Alpaca paper balance** (where the
     order executes), not the Schwab monitor. Derive `two_pct_budget = 0.02*equity` and
     `headroom_to_70pct = 0.70*equity − deployed_value`.
   - (Entry/stop/target *price levels* in the gating step still come from Schwab read-only
     data via `loops/technicals.py` — same market, Schwab is data-only.)

3. **Run the gating Workflow** `loops/research_workflow.js` with
   `args = { excluded_tickers: [<held tickers> + prior exits/rejects], net_liq, deployed_pct, headroom_to_70pct, two_pct_budget, held_sectors: {<ticker>: "<GICS sector>", ...} }`.
   `held_sectors` maps every CURRENT holding to its GICS sector (from the position
   records/memory) — the workflow fails fast without it, and enforces the C1 cap
   deterministically: a would-be 3rd position in a sector fails regardless of R:R;
   a 2nd-in-sector passes with a soft flag that MUST appear in the report. Name any
   sector-blocked candidate in the rejects table (user-confirmed D1).
   Pipeline (2026-07-23): screen a pool → **one deterministic `loops/technicals.py`
   prefilter pass over the whole pool** (falling-knife, aged-support anchor,
   **R:R ≥ 3:1 at Target 1 from REAL levels**, ≥300k avg volume, price $5–50, and the
   full deterministic sizing check) → web-gate the technical survivors only (FCF+,
   dated catalyst ≤60 days, allowed sector, and the numeric declining-revenue/moat
   rule) → stop at the first full pass or `MAX_CANDIDATES = 5` survivors gated.
   **P2 breakout mode is RETIRED (2026-08-12)** — full-population replay showed no
   edge (20% hit rate ≈ breakeven; motivating escapes were gaps, not breakouts).
   No shadow logging exists. `loops/breakout_replay.py` is retained as the harness
   for evaluating any future entry-pattern idea; a gap-continuation redesign is
   PARKED until the October 29 review — do not spec or build it before then.

4. **If the workflow returns `approved: null`** → present the "no qualifying candidate"
   summary (every evaluated ticker + the gate each failed), then **STOP**. There is no
   trade to approve, so no approval gate is needed.

5. **If a candidate is approved** → using the workflow's `dossier`, the REAL technicals
   levels (`approved.entry/stop/t1`), and the step-2 live balance, write —
   including in section 6 the C3 insider-BUYING line (buys/buyers/$ total, trailing
   90d, with the data note) alongside any selling observations, and the C1 sector
   soft flag prominently if the candidate is a 2nd-in-sector:
   - the **full 9-section equity report** in the exact `trading-rules.md` format, and
   - the **proposed OCO order cells**: `BUY <N>` → `OCO { SELL LIMIT <T1>, SELL STOP <stop> }`,
     GTC, "1st Triggers OCO", with the shares/capital/cash/R:R table, sized against the
     live balance with the 2% rule.

6. **Write the execution handoff** (this is what `loops/order_executor.py` consumes when you
   type `approved`). **Before** the approval line, write `logs/pending_order.json` from the
   approved order — the REAL numbers from the report, `env:"paper"`, a current `computed_at`,
   and a short `report_fingerprint`. Write it deterministically:
   ```bash
   .venv/bin/python - <<'PY'
   import json, hashlib, datetime as dt, pathlib
   o = {"ticker": "<TICKER>", "shares": <N>, "entry_limit": <ENTRY>,
        "stop": <STOP>, "target_t1": <T1>, "env": "paper",
        "computed_at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
   o["report_fingerprint"] = hashlib.sha256(
       f"{o['ticker']}|{o['shares']}|{o['entry_limit']}|{o['stop']}|{o['target_t1']}|{o['computed_at']}".encode()
   ).hexdigest()[:12]
   pathlib.Path("logs").mkdir(exist_ok=True)
   pathlib.Path("logs/pending_order.json").write_text(json.dumps(o, indent=2))
   print("handoff written:", o["report_fingerprint"])
   PY
   ```
   Substitute `<TICKER>/<N>/<ENTRY>/<STOP>/<T1>` with the approved candidate's values. The
   executor enforces a 15-minute freshness TTL on `computed_at`, so write this at report time.

7. **Send a desktop notification:**
   `osascript -e 'display notification "Equity research report ready for review" with title "Equity Research"'`

8. **Then output this line VERBATIM as the FINAL action and STOP. Output nothing after it:**

```
AWAITING APPROVAL — show this report to the chat session before entering any order in thinkorswim.
```

## Full flow
`/equity-research` **generates the report and writes the handoff** (`logs/pending_order.json`)
→ **you type `approved`** → `loops/order_executor.py` **validates the rules against the live
Alpaca paper balance and places the paper bracket** (BUY + 1st-Triggers-OCO, GTC).
`ALPACA_ENV=paper` is hard-enforced; the Schwab integration stays strictly read-only.

## HARD RULES (never violate)
- **This command never places orders.** It only writes the handoff and presents the report.
  Order placement happens ONLY in `loops/order_executor.py`, against the **Alpaca PAPER**
  account, and ONLY after you explicitly type `approved`. Schwab stays strictly read-only.
- **NEVER assume approval.** Stop at the AWAITING APPROVAL line (step 8); do NOT invoke the
  executor yourself — it runs only when the user types `approved`.
- The reward:risk gate MUST use real levels from `loops/technicals.py` (live data), never
  LLM-guessed numbers (H4, non-negotiable).
- Honors the saved `equity-report-approval-gate` memory.
