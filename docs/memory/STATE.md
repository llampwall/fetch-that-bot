<!-- DO: Rewrite freely. Keep under 30 lines. Current truth only. -->
<!-- DON'T: Add history, rationale, or speculation. No "we used to..." -->
<!-- ANCHOR: if the only commits since the anchor are `docs(memory):` anchor bumps,
     memory is current — report up-to-date and make NO commit. -->


# State

## Current Objective
Telegram bot + REST API that extracts and delivers media from social URLs (Instagram, X, TikTok, YouTube, Reddit, Threads)

## Active Work
- Log hygiene: yt-dlp output now routed to a logger adapter at debug; the yt-dlp exception is held and reported once at warning only when the gallery-dl fallback also comes back empty (9943c46)
- `fetch-bot` is Running (pythonw + main.py, delayed auto-start); the `fetch` wrapper service was never installed
- strap lifecycle output is `start-fetch-bot.cmd` / `stop-fetch-bot.cmd` / `.strap/nssm-install-fetch-bot.cmd` (all untracked); the installer is self-referential and must not be run
- Untracked/uncommitted: `.gitignore` edit (lookup.json), `test_threads.py`, `AGENTS.md`, `.claude/`, `QLAUDE_SMOKE.md`, `test_out.txt`/`test_err.txt`, `cookies.txt.bak-20260921-160400`

## Blockers
None known

## Next Actions
- [ ] Gitignore `cookies.txt*` — the `cookies.txt.bak-20260921-160400` backup is untracked but NOT ignored and holds live session cookies
- [ ] Fix the `fetch` entry in `P:\software\_strap\registry.json` so lifecycle stops emitting a self-targeting `nssm install fetch-bot` installer; then delete the stale `start.cmd`/`stop.cmd`/`.strap/nssm-install.cmd`
- [ ] Commit the `.gitignore` change plus `test_threads.py` and `AGENTS.md`; gitignore or delete `test_out.txt`/`test_err.txt`
- [ ] Fix the `ytdlp_plugins.extractor` name collision that errors 3 of 19 tests under `unittest discover`
- [ ] Add gallery-dl to requirements.txt and run `playwright install chromium` in .venv (Threads)

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
Last memory update: 2026-09-21
Commits covered through: 9943c4624b99d9fba42e0ee0a7795526a66f780c

<!-- chinvex:last-commit:9943c4624b99d9fba42e0ee0a7795526a66f780c -->
