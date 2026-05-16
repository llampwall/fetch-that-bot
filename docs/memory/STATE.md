<!-- DO: Rewrite freely. Keep under 30 lines. Current truth only. -->
<!-- DON'T: Add history, rationale, or speculation. No "we used to..." -->

# State

## Current Objective
Telegram bot + REST API that extracts and delivers media from social URLs (Instagram, X, TikTok, YouTube, Reddit, Threads)

## Active Work
- test_extractor.py and test_threads.py exist but are not yet committed (test_handlers.py committed 2026-05-08)

## Blockers
None known

## Next Actions
- [ ] Commit remaining test files (test_extractor.py, test_threads.py)
- [ ] Run `playwright install chromium` in .venv to enable Threads extraction
- [ ] Add gallery-dl to requirements.txt (currently only installed in .venv)

## Quick Reference
- Run: `python main.py` (requires `.env` with `FETCH_BOT_TOKEN` and `FETCH_WEBHOOK_URL`)
- Service: `nssm status fetch-bot` / `nssm restart fetch-bot` (Windows NSSM service)
- Bot webhook: port 8443 | REST API: port 8444 (`GET /extract?url=...`)
- Test: `python -m pytest test_handlers.py` (test_extractor.py, test_threads.py not yet committed)
- Entry point: `main.py` (bot + API in single process)

## Out of Scope (for now)
- Polling mode (webhook-only design)
- Separate api.py process (merged into main.py as of 2026-04-11)

---
Last memory update: 2026-05-10
Commits covered through: 496152c9e752d756fd483b5d82ccc6c1d605e68a

<!-- chinvex:last-commit:496152c9e752d756fd483b5d82ccc6c1d605e68a -->
