# CLAUDE.md

## Project

fetch - Telegram bot that extracts and sends media from social URLs (Instagram, X, TikTok, YouTube, Reddit)

## Language

Python 3

## Structure

- `main.py` - Entry point; runs bot webhook (port 8443) and REST API (port 8444) in single process
- `config.py` - Env var loading, URL regex patterns, platform detection
- `extractor.py` - yt-dlp + gallery-dl extraction, ffmpeg compression, cleanup
- `handlers.py` - Telegram message handler logic
- `docs/specs/` - Implementation specs
- `docs/memory/` - Project memory files (STATE, CONSTRAINTS, DECISIONS)
- `tmp/` - Temp download directory (gitignored)

## Commands (PowerShell)

```powershell
python main.py          # Start the bot (requires .env)
```

## Service Management

fetch-bot runs as a native Windows service via NSSM — **not PM2**. It is fully decoupled from AllMind's PM2 lifecycle.

```powershell
nssm status fetch-bot    # Check if running
nssm restart fetch-bot   # Restart the service
nssm stop fetch-bot      # Stop
nssm start fetch-bot     # Start
Get-Service fetch-bot    # Standard Windows service query
```

- Auto-starts on boot, auto-restarts on crash (5s delay)
- Logs: `P:\software\fetch\logs\out.log` and `error.log`
- Install script: `install-service.ps1` (run as admin to recreate)
- **Do NOT add fetch-bot back to PM2** — that coupling caused repeated outages

## Architecture

- **Webhook server**: `python-telegram-bot[webhooks]` runs tornado on port 8443
- **REST API**: tornado server on port 8444 (`FETCH_API_PORT`); `GET /extract?url=...`; `/files/` static serving; both run in same process from `main.py`
- **Extractor**: yt-dlp primary; gallery-dl fallback for image-only posts
- **Compression**: ffmpeg re-encodes videos over 50MB, targeting 45MB
- **Config**: All secrets via `.env` — never hardcoded

## Memory System

Chinvex repos use structured memory files in `docs/memory/`:

- **STATE.md**: Current objective, active work, blockers, next actions
- **CONSTRAINTS.md**: Infrastructure facts, rules, hazards (merge-only)
- **DECISIONS.md**: Append-only decision log with dated entries

**SessionStart Integration**: When you open a chinvex-managed repo, a hook runs `chinvex brief --context <name>` to load project context.

**If memory files are uninitialized** (empty or bootstrap templates), the brief will show "ACTION REQUIRED" instructing you to run `/update-memory`.

**The /update-memory skill** analyzes git history and populates memory files with:
- Current state from recent commits
- Constraints learned from bugs/infrastructure
- Decisions with evidence (commit hashes)

## Rules

- `.env` and `cookies.txt` are gitignored — never commit credentials
- Webhook mode only — do not switch to polling
- Do not re-enable `writethumbnail` (creates duplicate files)
- Ask before adding dependencies
- When opening a repo, check if brief shows "ACTION REQUIRED" - if so, offer to run `/update-memory`


Before searching for files with Glob/Grep, check docs/sys/lookup.json — a concept-to-files index. If your search term matches a key, you already know which files to read.
