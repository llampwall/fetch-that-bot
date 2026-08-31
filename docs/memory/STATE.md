<!-- DO: Rewrite freely. Keep under 30 lines. Current truth only. -->
<!-- DON'T: Add history, rationale, or speculation. No "we used to..." -->
<!-- ANCHOR: if the only commits since the anchor are `docs(memory):` anchor bumps,
     memory is current — report up-to-date and make NO commit. -->


# State

## Current Objective
Telegram bot + REST API that extracts and delivers media from social URLs (Instagram, X, TikTok, YouTube, Reddit, Threads)

## Active Work
- No app code changes since 4c9de9d; only memory/lifecycle commits since
- `fetch-bot` is SERVICE_RUNNING (pythonw + main.py, delayed auto-start); the old `fetch` wrapper service was never installed
- strap regenerated lifecycle as `start-fetch-bot.cmd` / `stop-fetch-bot.cmd` / `.strap/nssm-install-fetch-bot.cmd` (untracked); the installer is self-referential and must not be run
- Untracked: `test_threads.py`, `AGENTS.md`, `docs/sys/`, `.claude/`, `QLAUDE_SMOKE.md`, `test_out.txt`/`test_err.txt`

## Blockers
None known

## Next Actions
- [ ] Fix the `fetch` entry in `P:\software\_strap\registry.json` so lifecycle stops emitting a self-targeting `nssm install fetch-bot` installer; then delete the stale `start.cmd`/`stop.cmd`/`.strap/nssm-install.cmd`
- [ ] Commit `test_threads.py`, `AGENTS.md`, and `docs/sys/lookup.json`; gitignore or delete `test_out.txt`/`test_err.txt`
- [ ] Expand `docs/sys/lookup.json` — it indexes only `extractor` and `install`
- [ ] Run `playwright install chromium` in .venv to enable Threads extraction
- [ ] Add gallery-dl to requirements.txt (currently only installed in .venv)

## Quick Reference
- Run: `python main.py` (requires `.env` with `FETCH_BOT_TOKEN` and `FETCH_WEBHOOK_URL`)
- Service: `nssm status fetch-bot` / `nssm restart fetch-bot` (Windows NSSM service; install via `install-service.ps1` as admin)
- Bot webhook: port 8443 | REST API: port 8444 (`GET /extract?url=...`)
- Test: `python -m pytest test_handlers.py test_extractor.py`
- Entry point: `main.py` (bot + API in single process)

## Out of Scope (for now)
- Polling mode (webhook-only design)
- Separate api.py process (merged into main.py as of 2026-04-11)

---
Last memory update: 2026-08-30
Commits covered through: ccc2ffebb38eb06c05d0976490da73af78b421c8

<!-- chinvex:last-commit:ccc2ffebb38eb06c05d0976490da73af78b421c8 -->
