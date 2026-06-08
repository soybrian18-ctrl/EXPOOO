# CLAUDE.md

Project: a Charles Schwab Individual Trader API account monitor built on
`schwab-py`. Key scripts: `portfolio.py` (equity report), `stop_check.py`
(stop-loss check), `setup_auth.py` (OAuth setup). Shared code lives in
`config.py`, `analysis.py`, and `render.py`; tests in `tests/`.

## Trading rules are binding context

`references/trading-rules.md` holds the rules for the trading experiment. They
are authoritative.

**Before producing an equity/portfolio report — including running or
interpreting `portfolio.py`, or analyzing account holdings — OR sizing a
position, you MUST first read `references/trading-rules.md` and apply it.**

- Re-read the file each time so you always use the latest version of the rules.
- If the rules conflict with a default behavior or with a request, surface the
  conflict explicitly and follow the rules unless the user overrides them.
- If the file is missing or still a placeholder, say so rather than guessing.
