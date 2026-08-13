<!-- DO: Rewrite freely. Keep under 30 lines. Current truth only. -->
<!-- DON'T: Add history, rationale, or speculation. No "we used to..." -->

# State

## Current Objective
Telegram bot + REST API that extracts and delivers media from social URLs (Instagram, X, TikTok, YouTube, Reddit, Threads)

## Active Work
- No code changes since 4c9de9d; service reliability work (delayed auto-start, 10MB log rotation) is settled
- Untracked in the working tree: `test_threads.py`, `AGENTS.md`, `docs/sys/lookup.json`, `.claude/`, `QLAUDE_SMOKE.md`, `test_out.txt`/`test_err.txt`

## Blockers
None known

## Next Actions
- [ ] Commit `test_threads.py`, `AGENTS.md`, and `docs/sys/lookup.json`; gitignore or delete `test_out.txt`/`test_err.txt`
- [ ] Expand `docs/sys/lookup.json` — CLAUDE.md tells agents to consult it but it indexes only one concept (`extractor`)
- [ ] Re-run `install-service.ps1` as admin if the delayed-start/rotation settings are not yet applied to the live service
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
Last memory update: 2026-08-13
Commits covered through: d875dfc63d0beea1bed0150829fca5b439292caf

<!-- chinvex:last-commit:d875dfc63d0beea1bed0150829fca5b439292caf -->
