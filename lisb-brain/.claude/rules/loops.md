# Loop Rules

## Loop Guardrails
Every loop must have:
- A clear stopping condition
- A maximum iteration limit
- A spending cap stored in .env
- A log file recording every execution and API calls made

## Active Loops
- Daily outreach briefing at 8 AM. Runs outreach_briefing.py. Zero API cost. Stops if tracker is missing.
- Caption validation. Runs caption_scorer.py after generation. Rewrites on failure. Maximum 3 attempts.
- Algorithm score gate. Runs algorithm_score.py after render. Rebuilds if below threshold. Only outputs on pass.
- Lead sourcer replenishment. Runs Sunday night. If Stage 1 count drops below 30, runs lead sourcer for two niches.
- Reel generation loop. Runs reel_loop.py. Maximum 3 attempts. Logs every attempt to reel_loop_log.csv.
- Weekly content calendar loop. Runs content_calendar.py. Generates one reel per posting day. Skips MANUAL_REVIEW entries and continues.

## Loop Boundary
No loop ever sends an Instagram action. Loops prepare, score, validate, and organize. The human sends.
