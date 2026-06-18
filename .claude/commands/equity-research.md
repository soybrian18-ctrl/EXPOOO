---
description: Loop 3 — run the gated equity-research loop, present a 9-section report + proposed OCO cells, and write the execution handoff for approval. The command never places orders itself.
---

You are running **Loop 3 (Equity Research Loop)**. Follow these steps EXACTLY. The
approval gate at the end is NON-NEGOTIABLE.

1. **Re-read `references/trading-rules.md` in full** and apply it (binding context).

2. **Pre-flight token + live balance.** Run:
   `.venv/bin/python loops/research_inputs.py`
   - If `token_ok` is `false` or the JSON has an `error`: send a desktop notification
     (`osascript -e 'display notification "Equity research aborted: token/API problem" with title "Equity Research"'`),
     tell the chat session to re-run `setup_auth.py`, and **STOP**. Do not proceed.
   - Otherwise capture `net_liq`, `cash`, `deployed_pct`, `headroom_to_70pct`,
     `two_pct_risk_budget`, and the held tickers (`positions[].symbol`).

3. **Run the gating Workflow** `loops/research_workflow.js` with
   `args = { excluded_tickers: [<held tickers> + CXM, MGNI, WWW], net_liq, deployed_pct, headroom_to_70pct, two_pct_budget }`.
   It screens a candidate pool and gates each candidate (stop at the first approved
   or after `MAX_CANDIDATES = 5` evaluated) against: **reward:risk ≥ 3:1 at Target 1
   computed from REAL `loops/technicals.py` levels** (never guessed), **NOT (no moat
   AND declining revenue)**, **no position-sizing conflict**, price $5–50, FCF-positive,
   a catalyst within 60 days, and an allowed sector.

4. **If the workflow returns `approved: null`** → present the "no qualifying candidate"
   summary (every evaluated ticker + the gate each failed), then **STOP**. There is no
   trade to approve, so no approval gate is needed.

5. **If a candidate is approved** → using the workflow's `dossier`, the REAL technicals
   levels (`approved.entry/stop/t1`), and the step-2 live balance, write:
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
