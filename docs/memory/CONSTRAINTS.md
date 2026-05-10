<!-- DO: Add bullets. Edit existing bullets in place with (updated YYYY-MM-DD). -->
<!-- DON'T: Delete bullets. Don't write prose. Don't duplicate — search first. -->

# Constraints

## Infrastructure
- Telegram bot file upload limit: 50MB max
- Webhook port: default 8443 (configurable via `FETCH_WEBHOOK_PORT`)
- Temp files stored in `./tmp/` (auto-created on startup)
- gallery-dl executable path hardcoded: `.venv/Scripts/gallery-dl.exe`
- Telegram album max: 10 media items per message
- REST API serves extracted files via `/files/` static endpoint
- REST API port: 8444 (configurable via `FETCH_API_PORT` env var)
- Bot and REST API run in the same process from `main.py` — `api.py` no longer exists (merged 2026-04-11)
- Temp files auto-deleted after 5 minutes (REST API cleanup timer)
- Custom yt-dlp extractors live in `yt_dlp_plugins/extractor/` — yt-dlp discovers them automatically
- Threads extractor uses Playwright (headless Chromium) — requires separate `playwright install chromium`
- fetch-bot runs as a Windows NSSM service (not PM2) — auto-starts on boot, auto-restarts on crash (5s delay) (updated 2026-04-22)
- NSSM logs: `P:\software\fetch\logs\out.log` and `error.log`; install script: `install-service.ps1` (run as admin)
- YouTube video duration cap: default 300s (5 min), configurable via `FETCH_MAX_YT_DURATION` env var (updated 2026-04-22)

## Rules
- `.env` and `cookies.txt` are gitignored — never commit credentials
- Webhook mode only (not polling) — architecture uses `run_webhook()`
- Video compression target: 45MB (headroom under 50MB Telegram limit)
- Caption truncated to 225 visible chars — embedded URLs rendered as `<a href="URL">link</a>` (HTML mode); URLs count as 4 chars in truncation budget (updated 2026-05-08)
- Caption body built by `_format_caption_body()` in `handlers.py` — HTML-escapes text, linkifies embedded URLs; do not revert to stripping (URL-only captions become empty strings)
- Do not re-enable `writethumbnail` — it creates duplicate files alongside videos
- iOS normalization required: encode to H.264/AAC/yuv420p with square pixels — fixes audio-only and squished aspect ratio on iOS Telegram
- yt-dlp format selector prefers H.264 (avc1) to avoid AV1/VP9 codec issues (updated 2026-04-10)
- Pass explicit width/height/duration to Telegram `send_video` calls
- Threads extractor wraps Playwright in `ThreadPoolExecutor` — required to avoid asyncio event loop conflicts with the bot's async runtime
- Windows subprocess calls use `_NO_WINDOW` (`CREATE_NO_WINDOW`) flag — prevents console windows from popping up on Windows
- Pass `message_thread_id` through all Telegram send calls — required for forum topic (supergroup thread) support
- YouTube videos over `FETCH_MAX_YT_DURATION` seconds (default 300) are silently skipped via `precheck_duration()` in `extractor.py` — no bot output, original message left untouched; metadata-only yt-dlp call (download=False) so no download occurs (updated 2026-05-10)
- Do NOT add fetch-bot back to PM2 — NSSM decoupling was deliberate (PM2 coupling caused repeated outages)
- Delete original user message only after at least one repost succeeds — prevents link disappearing on upload timeout
- On extraction failure, duration-rejection, or upload error: send a per-URL fallback that preserves original URL and post caption — never drop the link silently (updated 2026-05-08)
- ffmpeg compression uses progressive bitrate/resolution fallback; yt-dlp format selector caps source at 720p to avoid pulling 1080p60 streams that would need downscaling (updated 2026-05-08)
- httpx Application timeouts: connect=20s, read=60s, write=120s; media uploads use 180s write timeout
- Telegram PTB ApplicationBuilder read_timeout: 180s — matches upload window to absorb server-side processing lag (transcoding, thumbnail gen) for 30–45MB videos (updated 2026-05-08)

## Key Facts
- Bot token env var: `FETCH_BOT_TOKEN`
- Webhook URL env var: `FETCH_WEBHOOK_URL` (e.g. `https://yourtunnel.com/webhook/fetch`)
- Webhook path: `/webhook/fetch` (hardcoded in `config.py`)
- Cookies file: `./cookies.txt` (needed for Instagram stories/private content)
- Supported platforms: Instagram, X/Twitter, TikTok, YouTube (watch + shorts), Reddit (posts + v.redd.it + i.redd.it), Threads (threads.net + threads.com) (updated 2026-04-17)
- YouTube duration cap env var: `FETCH_MAX_YT_DURATION` (default 300 seconds)
- REST API endpoint: `GET /extract?url=<url>` — returns media info + thumbnail URL; no bot required
- Thumbnail URL returned in API response for platforms where Telegram preview crawler is blocked (e.g. Instagram)

## Hazards
- gallery-dl is NOT in requirements.txt — must be installed separately into `.venv`
- `ffprobe` and `ffmpeg` must be on PATH for video compression to work
- yt-dlp format selector uses a flexible fallback chain — Reddit DASH streams require this
- `writethumbnail` was removed intentionally; re-enabling it causes duplicate files
- Playwright/Chromium is NOT in requirements.txt — run `playwright install chromium` separately or Threads extraction will fail silently
- Threads extractor depends on page structure (`<script type="application/json">` tags) — if Meta changes the SPA format, extraction will break

## Superseded
- (Superseded 2026-04-22) PM2 config: `ecosystem.config.cjs` — replaced by NSSM Windows service; PM2 coupling caused outages
