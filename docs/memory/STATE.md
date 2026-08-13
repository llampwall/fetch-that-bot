<!-- DO: Rewrite freely. Keep under 30 lines. Current truth only. -->
<!-- DON'T: Add history, rationale, or speculation. No "we used to..." -->

# State

## Current Objective
Telegram bot + REST API that extracts and delivers media from social URLs (Instagram, X, TikTok, YouTube, Reddit, Threads)

## Active Work
- Service reliability settled: fetch-bot now uses delayed auto-start and 10MB log rotation
- test_threads.py exists but is not yet committed

## Blockers
None known

## Next Actions
- [ ] Re-run `install-service.ps1` as admin if the delayed-start/rotation settings are not yet applied to the live service
- [ ] Commit test_threads.py
- [ ] Run `playwright install chromium` in .venv to enable Threads extraction
- [ ] Add gallery-dl to requirements.txt (currently only installed in .venv)

## Quick Reference
- Run: `python main.py` (requires `.env` with `FETCH_BOT_TOKEN` and `FETCH_WEBHOOK_URL`)
- Service: `nssm status fetch-bot` / `nssm restart fetch-bot` (Windows NSSM service)
- Bot webhook: port 8443 | REST API: port 8444 (`GET /extract?url=...`)
- Test: `python -m pytest test_handlers.py test_extractor.py`
- Entry point: `main.py` (bot + API in single process)

## Out of Scope (for now)
- Polling mode (webhook-only design)
- Separate api.py process (merged into main.py as of 2026-04-11)

---
Last memory update: 2026-08-12
Commits covered through: 4c9de9d69cfd888106bac390a71d6b1a5b50b7fa

<!-- chinvex:last-commit:4c9de9d69cfd888106bac390a71d6b1a5b50b7fa -->
