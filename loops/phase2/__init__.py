"""Phase 2: backtest, nightly forward test and paper verification.

Authority: specs/phase2_spec.md (approved 2026-11-10). Everything that decides a
signal, an order, a fill or an exit lives here as a pure function, called by
both the backtester and the nightly job. Nothing in this package can place an
order. ("phase2", not "p2": P2 is the retired breakout mode in technicals.py.)
"""
