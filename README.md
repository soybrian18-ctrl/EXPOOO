# Schwab Individual Trader — Account Monitor

A small, terminal-first monitor for a **Charles Schwab Individual Trader API**
account, built entirely on [`schwab-py`](https://github.com/alexgolec/schwab-py)
by Alex Golec. Every Schwab request goes through `schwab-py` — there are **no
raw HTTP calls** anywhere in this project. All output is rendered with
[`rich`](https://github.com/Textualize/rich).

## What it does

| Script | Purpose |
| --- | --- |
| `setup_auth.py` | One-time, step-by-step OAuth 2.0 browser login. Writes the token file. |
| `portfolio.py` | Net liquidating value, every open position with P/L, deployed capital, cash & buying power, and all working orders (with a bright red flag on any `DAY`-TIF order). |
| `stop_check.py` | Cross-checks open positions against working stop orders; flags any stop within 5% of the mark or with `DAY` (not `GTC`) time-in-force; prints an all-clear when nothing trips. |

Each script is independently runnable from the terminal.

## Requirements

- Python 3.9+
- A Schwab developer app with the **Trader API – Individual** product enabled
  (https://developer.schwab.com)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 1. Configure your Schwab app

In the Schwab developer portal, create/confirm an app and note its **App Key**
and **App Secret**. Set the app's **Callback URL** to exactly:

```
https://127.0.0.1
```

The callback must match byte-for-byte (scheme, host, no trailing slash here)
everywhere it appears.

## 2. Credentials (`.env`)

Credentials live only in a local, git-ignored `.env` file (loaded with
`python-dotenv`). Copy the template and fill it in — or let `setup_auth.py`
prompt you and write it for you:

```bash
cp .env.example .env
```

```ini
SCHWAB_API_KEY=your_app_key
SCHWAB_APP_SECRET=your_app_secret
SCHWAB_CALLBACK_URL=https://127.0.0.1
SCHWAB_TOKEN_PATH=./schwab_token.json
# optional, default 0 — which linked account to report on
SCHWAB_ACCOUNT_INDEX=0
```

`.env` and the token file are git-ignored from the first commit. Nothing is ever
hardcoded.

## 3. First-time authentication

```bash
python setup_auth.py
```

Schwab requires a **manual browser redirect** on the first login. The script
uses `schwab-py`'s `client_from_manual_flow` and walks you through it:

1. It prints an authorization link.
2. Open it, log in to Schwab, and approve access.
3. Schwab redirects you to `https://127.0.0.1/?code=...`. Your browser will
   likely show "site can't be reached" — that's expected; nothing is listening
   on the loopback address.
4. Copy the **full** URL from the address bar and paste it back when prompted.

On success the token is written to `SCHWAB_TOKEN_PATH`, its permissions are set
to `600`, and the script verifies it by listing your (masked) linked accounts.

## 4. Daily use

```bash
python portfolio.py     # full account snapshot
python stop_check.py    # protective-stop health check
```

`stop_check.py` exits `0` when all clear and `3` when one or more flags trip,
so it slots cleanly into cron/alerting.

## How token refresh works

- **Access token** — lives ~30 minutes. `schwab-py`'s session refreshes it
  automatically and rewrites the token file; the reporting scripts never block
  on a browser.
- **Refresh token** — lives ~7 days. When it lapses, the next call fails with a
  clear "re-run `setup_auth.py`" message (HTTP 401 or a refresh error). Just run
  `setup_auth.py` again.

## Security model

- Credentials only in `.env` (git-ignored); the token file is git-ignored and
  `chmod 600`.
- Schwab requires the **hashed** account number on every request. `schwab-py`
  resolves it via `get_account_numbers`; this project never bypasses that and
  never prints the raw number or full hash (account numbers are masked to the
  last four digits).
- `schwab-py` automatically redacts secrets from its own logs.

## Notes & limitations

- The Schwab order endpoint only returns orders entered within the last ~60
  days (`ORDER_LOOKBACK_DAYS` in `config.py`). A GTC stop placed earlier than
  that window will not be returned.
- "Deployed capital" is gross position market value (`Σ |marketValue|`).
- Marks come from the broker-supplied `marketValue` in the account snapshot, so
  position and stop views stay consistent without extra quote calls.

## Project layout

```
config.py        settings, schwab-py client, account hashing, HTTP unwrap
analysis.py      pure logic: P/L, deployment, order flattening, stop proximity
render.py        rich console, formatters, the DAY-TIF flag, CLI error handler
setup_auth.py    guided first-time OAuth flow
portfolio.py     account snapshot report
stop_check.py    stop-loss health check
tests/           unit tests for analysis.py (no network/credentials needed)
```

## Testing

```bash
python -m unittest discover -s tests -v
```

The tests cover the financial math (longs, shorts, zero-cost edge cases),
balance parsing (margin vs cash), OCO/bracket order flattening, stop proximity,
and the flag/all-clear logic — all on representative Schwab payloads, with no
network or credentials required.
