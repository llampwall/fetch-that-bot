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
