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
- fetch-bot runs as a Windows NSSM service (not PM2) — delayed auto-start on boot (~2 min), auto-restarts on crash (5s delay) (updated 2026-08-12)
- NSSM logs: `P:\software\fetch\logs\out.log` and `error.log`; rotated at 10MB via `AppRotateFiles`/`AppRotateOnline`/`AppRotateBytes`; install script: `install-service.ps1` (run as admin) (updated 2026-08-12)
- YouTube video duration cap: default 300s (5 min), configurable via `FETCH_MAX_YT_DURATION` env var (updated 2026-04-22)
- strap lifecycle artifacts at repo root: `start.cmd`, `stop.cmd`, `.strap/nssm-install.cmd` — generated from the `fetch` entry in `P:\software\_strap\registry.json`; regenerate with `strap lifecycle fetch`, never hand-edit (added 2026-08-29)
- strap's wrapper service was named `fetch` and only ran `nssm start fetch-bot`; the real service is still `fetch-bot` from `install-service.ps1` (updated 2026-08-30 — strap now emits `-fetch-bot`-suffixed artifacts that target the `fetch-bot` name directly)
- Current strap output is `start-fetch-bot.cmd`, `stop-fetch-bot.cmd`, `.strap/nssm-install-fetch-bot.cmd` (untracked); the tracked `start.cmd`/`stop.cmd`/`.strap/nssm-install.cmd` are the older `fetch`-wrapper generation and are now stale (added 2026-08-30)
- Real `fetch-bot` service config: Application `P:\software\fetch\.venv\Scripts\pythonw.exe`, AppParameters `P:\software\fetch\main.py`, Start `SERVICE_DELAYED_AUTO_START` (added 2026-08-30)

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
- TikTok photo posts (`/photo/`) are unsupported by yt-dlp; gallery-dl returns the slides plus the soundtrack mp3, and `_build_slideshow()` renders them into one H.264/AAC video — never send them as a photo album (it arrives silent). Slides in one post differ in size, so each slide is its own looped ffmpeg input; the concat demuxer truncates the video track (added 2026-11-18)
- TikTok formats report `vcodec=h264`, not `avc1`; the format selector matches both via `_H264` (`[vcodec~='^(avc1|h264)']`). TikTok's H.264 stream carries HE-AACv2 audio, so `_prepare_video` copies the video and re-encodes only the audio to AAC-LC (updated 2026-11-18)
- TikTok blocks yt-dlp unless it impersonates a browser: `curl_cffi` (`yt-dlp[curl-cffi]`) is required. Without it every TikTok fails yt-dlp and falls back to gallery-dl's 1080p HEVC stream (files named `000_*`; yt-dlp's are `001_*`) (added 2026-11-18)
- fetch-bot service must use `SERVICE_DELAYED_AUTO_START` — plain `SERVICE_AUTO_START` races the P: volume at boot and NSSM dies with "The system cannot open the file" (Event 7024) (updated 2026-08-12)
- Delete original user message only after at least one repost succeeds — prevents link disappearing on upload timeout
- On extraction failure, duration-rejection, or upload error: send a per-URL fallback that preserves original URL and post caption — never drop the link silently (updated 2026-05-08)
- ffmpeg compression uses progressive bitrate/resolution fallback; yt-dlp format selector caps source at 720p to avoid pulling 1080p60 streams that would need downscaling (updated 2026-05-08)
- HEVC (h265) sources skip the CRF re-encode pass — CRF 23 H.264 at same resolution balloons 2-3x; go straight to size-targeted ladder (35→25→15 MB, 1280→960→720) (updated 2026-05-16)
- CRF pass for non-HEVC sources checks output size after encode; if over cap, falls through to size-targeted ladder rather than silently dropping (updated 2026-05-16)
- Failure tags in bot message headers: `<XL>` = too big to upload; `<X>` = couldn't fetch; URL + caption preserved on next line; `ExtractionResult.oversize` flag routes between them; `VideoDurationExceeded` backstop uses `<XL>` (updated 2026-05-16)
- yt-dlp is configured with a `logger` adapter (`_YtdlpLog` in `extractor.py`) that downgrades its warning/error output to debug — `quiet` alone silences progress but not errors. Do not remove it or revert to bare stderr (added 2026-09-21)
- An image-only post ALWAYS fails yt-dlp (no image path); gallery-dl is what serves it. Hold the yt-dlp exception and report it once at warning (with `exc_info`/cause) only when the gallery-dl fallback also returns no items — never `log.exception` at the yt-dlp catch site (added 2026-09-21)
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
- Service binary and working dir live on the P: volume — any Windows service pointed there must not start early in boot (added 2026-08-12)
- The `fetch` wrapper service is not installed (`nssm status fetch` → "service does not exist"); `start.cmd`/`stop.cmd` fail until `.strap\nssm-install.cmd` is run as admin (added 2026-08-29)
- `.strap/nssm-install.cmd` sets `Start SERVICE_AUTO_START` on the `fetch` wrapper — do not point that wrapper at a P:-resident binary; it only calls `nssm start fetch-bot`, and `fetch-bot` itself must stay `SERVICE_DELAYED_AUTO_START` (added 2026-08-29)
- DO NOT run `.strap\nssm-install-fetch-bot.cmd` — it would `nssm install fetch-bot` pointing at `cmd /c nssm start fetch-bot` (self-referential) and set `SERVICE_AUTO_START`, clobbering the real python service and violating the delayed-start rule. Regenerating strap lifecycle for `fetch` produced a self-targeting installer because the registry service name equals the real service name (added 2026-08-30)
- `.gitignore` lists `cookies.txt` literally, not `cookies.txt*` — timestamped backups such as `cookies.txt.bak-20260921-160400` are NOT ignored and will be picked up by `git add -A`. Never `git add -A` in this repo until the pattern is widened (added 2026-09-21)
- `unittest discover` errors 3 of 19 tests on a pre-existing `ytdlp_plugins.extractor` package-name collision — that is the known baseline, not a regression (added 2026-09-21)
- Threads extractor depends on page structure (`<script type="application/json">` tags) — if Meta changes the SPA format, extraction will break

## Superseded
- (Superseded 2026-04-22) PM2 config: `ecosystem.config.cjs` — replaced by NSSM Windows service; PM2 coupling caused outages
