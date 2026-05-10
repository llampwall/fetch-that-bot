<!-- DO: Append new entries to current month. Rewrite Recent rollup. -->
<!-- DON'T: Edit or delete old entries. Don't log trivial changes. -->

# Decisions

## Recent (last 30 days)
- YouTube over-duration videos now silently skipped — no bot output, original message stays untouched
- Fixed URL-dominant captions collapsing to empty strings — linkify embedded URLs as HTML links instead of stripping
- Fixed Telegram TimedOut false-alarm after large video upload — PTB read_timeout bumped to 180s
- Extraction failures now preserve original URL + caption in fallback message (no more silent link drops)
- ffmpeg compression hardened with progressive bitrate/resolution fallback; 720p source cap added to format selector
- Fixed TikTok link deleted on upload timeout — reordered to send-then-delete; bumped httpx timeouts

## 2026-05

### 2026-05-10 — YouTube over-duration videos now silently skipped

- **Why:** Prior behavior deleted the user's message then posted a "video too long" notice — the link was unrecoverable from chat and the bot output was noisy for a routine filter
- **Impact:** `precheck_duration()` added to `extractor.py`; called in `handlers.py` before any side effects; if any YouTube URL in the message exceeds `FETCH_MAX_YT_DURATION`, the handler exits immediately — no message delete, no bot reply; non-YouTube platforms bypass the precheck entirely (no latency cost)
- **Evidence:** 51df5d2803c6cec49388eda5ee719df71ed2644a

### 2026-05-08 — Fixed URL-dominant captions collapsing to empty strings

- **Symptom:** Quote-tweet captions where the body was just a `t.co` URL rendered as a bare "Author [X]" attribution with no body text after URL stripping
- **Root cause:** `_strip_embedded_urls()` removed all URLs from caption text — when a caption's entire body was a URL, stripping left an empty string
- **Fix:** Replace with `_format_caption_body()`: HTML-escape text, convert each embedded URL to `<a href="URL">link</a>`, truncate by visible character count (URLs count as 4 chars); captions sent with `parse_mode=HTML`
- **Prevention:** Do not revert to URL stripping; linkification preserves readability while keeping URLs accessible
- **Evidence:** b11f1ad94f1ae29eb0daba4a4539934d4f1e32bb

### 2026-05-08 — Fixed Telegram TimedOut false-alarm after successful large video upload

- **Symptom:** Bot posted "Couldn't fetch" error even though the video appeared in chat moments later
- **Root cause:** Telegram's server-side processing (probe, transcode for streaming, thumbnail generation) for 30–45MB videos exceeded 60s before emitting the Message response; PTB ApplicationBuilder read_timeout was 60s, causing httpx to raise ReadTimeout even on successful uploads
- **Fix:** Bump PTB ApplicationBuilder read_timeout from 60s to 180s to match the upload write window
- **Prevention:** When modifying upload flow, ensure read_timeout accounts for server-side processing time, not just transfer time
- **Evidence:** 52ebd811b81cfe30ac4634b2ba7abd9c5b35514a

### 2026-05-08 — Preserve link and caption on extraction failures; harden ffmpeg compression

- **Why:** Old "Couldn't fetch" fallback dropped the original URL — links were unrecoverable from chat; "Skipped — Xm Ys" duration-rejection messages dropped both URL and caption context; ffmpeg compression was fragile on high-bitrate sources
- **Impact:** Per-URL fallback messages now include original URL and post caption (or user commentary); ffmpeg compression uses progressive bitrate/resolution fallback; yt-dlp format selector capped at 720p to avoid pulling 1080p60 streams that would need downscaling
- **Evidence:** 5c515e05c7313a2938e18940dd568bfb90ed9ad2

### 2026-05-03 — Fixed TikTok link deleted when upload times out

- **Symptom:** Original TikTok message was deleted before `send_video` completed; httpx 5s write timeout caused the upload to fail, leaving no trace of the link in chat
- **Root cause:** `handle_message` deleted the user's original message before attempting the send; httpx default timeouts (5s write) were too short for large media uploads
- **Fix:** Reorder to send first, delete original only after at least one repost succeeds; failed sends count toward failure notice; bump httpx timeouts (connect=20s, read=60s, write=120s, media=180s); refactor metadata to single `_apply_metadata` extract_info pass; caption trimmed to 225 chars; source URLs stripped from fallback captions
- **Prevention:** Never delete the original before confirming at least one delivery succeeded
- **Evidence:** d3f31851d872b4179536367ef01fc145ecb75d5a

## 2026-04

### 2026-04-08 — Initial Fetch bot: Instagram/X/TikTok media extraction

- **Why:** Need a Telegram bot that can extract and relay social media content inline
- **Impact:** Core bot created with webhook mode, yt-dlp extraction, temp file management, ffmpeg compression
- **Evidence:** 6952ab5e9542c799081182b3443aa69086f96aaa

### 2026-04-08 — Add YouTube/Reddit support, gallery-dl fallback, streaming fixes, cookie auth

- **Why:** Expand platform coverage; fix inline video streaming; support private/stories content
- **Impact:** YouTube + Reddit URL patterns added; gallery-dl fallback for image-only posts; `+faststart` for inline playback; cookie file support; caption truncated to 200 chars; `writethumbnail` removed
- **Evidence:** b5896f102873dbd79fa4d7d4181c4dc7b4e6f17d

### 2026-04-10 — Add REST extraction API, iOS video normalization, and thumbnail support

- **Why:** Web client fork needs headless extraction without the Telegram bot; iOS Telegram plays video incorrectly with AV1/VP9 or non-square pixel formats
- **Impact:** `api.py` created with `GET /extract?url=...` endpoint and `/files/` static serving; 5-min temp file auto-cleanup; H.264/AAC/yuv420p normalization added; explicit width/height/duration passed to `send_video`; thumbnail URL returned in API response for platforms where Telegram preview crawler is blocked (e.g. Instagram)
- **Evidence:** 03d4ee6528bec8a49525b957d3280a012e7ccb86

### 2026-04-11 — Merge REST API into main process

- **Why:** Separate `api.py` process caused orphaned process accumulation (PM2 kept spawning duplicate fetch-api entries); single-process model is simpler and eliminates the risk
- **Impact:** `api.py` deleted; REST API handlers moved into `main.py`; API tornado server starts non-blocking before the bot webhook IOLoop; bot on port 8443, API on port 8444 (`FETCH_API_PORT`); single `python main.py` starts everything
- **Evidence:** 82d82a49a6671db46a848b187e863979bd945b93

### 2026-04-17 — Add Threads support via Playwright-based yt-dlp plugin

- **Why:** Threads (Meta) serves an empty SPA shell to plain HTTP clients — no OG tags, no embedded media data — so yt-dlp's normal extraction returns nothing
- **Impact:** `yt_dlp_plugins/extractor/threads.py` created; uses Playwright headless Chromium to render page and parse `<script type="application/json">` tags containing Instagram-style post data (video_versions/image_versions2); supports single videos, images, and carousels (as playlists); `ThreadPoolExecutor` wrapper avoids asyncio conflicts with the bot's event loop; `ecosystem.config.cjs` added for PM2 managed deployment; `message_thread_id` passed through all send calls for forum topic support; `_NO_WINDOW` flag added to subprocess calls on Windows
- **Evidence:** 75f23536a8da46e198c42b7a4e0fb776ceb1d08b

### 2026-04-22 — Switch to NSSM Windows service for production deployment

- **Why:** PM2 coupling to AllMind's lifecycle caused repeated outages; a native Windows service is fully decoupled and auto-starts on boot independently
- **Impact:** fetch-bot now managed via `nssm status/restart/stop/start fetch-bot`; `install-service.ps1` added for recreation; PM2 config (`ecosystem.config.cjs`) is superseded; do not re-add to PM2
- **Evidence:** 54f60d8c4de73f04fd0252cccf1e95ace45bd078

### 2026-04-22 — Add YouTube video duration cap (skip videos > 5 min)

- **Why:** Long YouTube videos caused slow downloads and large files that hit Telegram's 50MB limit; better to reject early than fail mid-download
- **Impact:** Pre-download metadata check via `yt-dlp extract_info(download=False)` rejects videos exceeding `FETCH_MAX_YT_DURATION` (default 300s); configurable via env var; attribution captions reworked to use HTML links with `parse_mode`
- **Evidence:** 3bd7688f08b989fdceea6c2363f8604d567d3fe8

### 2026-04-22 — Fixed duplicate error message when YouTube video skipped for duration

- **Symptom:** After skipping a long YouTube video, the bot sent both a "video too long" skip message AND a generic "Couldn't fetch" error
- **Root cause:** Skipped URLs left the results list empty, which triggered the generic failure handler
- **Fix:** Track skips separately in `handlers.py` so the generic error only fires for genuine extraction failures (not skips)
- **Prevention:** Any new skip/filter logic must update the skip counter, not just leave results empty
- **Evidence:** e0ee392b330ef51f2f1fbfb7a786f1594cb16884
