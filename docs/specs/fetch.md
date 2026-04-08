# Fetch

**Version:** v0.1.0
**Spec Type:** feature
**Language/Runtime:** Python 3.12+
**Created:** 2026-04-08

## Problem

When friends share Instagram, X, or TikTok links in Telegram, everyone has to leave the chat and open a browser to see the content. The links are opaque in chat history — you can't tell which link was which without clicking through again.

## Solution

A Telegram bot (Fetch) that sits in the group chat, detects social media links, extracts the actual media, deletes the original message, and reposts the content inline with attribution — so the chat reads like a media feed, not a link dump.

## Technical Approach

- **Bot framework:** `python-telegram-bot` v21+ (async, webhook mode)
- **Media extraction:** `yt-dlp` imported as Python library (installed at `P:\software\yt-dlp\`)
- **Webhook delivery:** via existing cloudflared tunnel
- **URL detection:** regex matching for `instagram.com`, `x.com`, `twitter.com`, `tiktok.com` domain patterns
- **Temp storage:** extracted media written to a temp dir, cleaned up after each successful post
- **Large video handling:** `ffmpeg` re-encode via yt-dlp postprocessors if file exceeds 50MB

### File Structure

```
P:\software\fetch\
├── main.py           # Entry point — webhook setup, bot startup
├── handlers.py       # Message handler — link detection, orchestration
├── extractor.py      # yt-dlp wrapper — download media, get metadata
├── config.py         # Bot token, webhook URL, temp dir, platform patterns
├── requirements.txt  # python-telegram-bot, yt-dlp
```

## Wiring Map

```json
{
  "existing_seams": [],
  "new_modules": [
    {
      "file": "main.py",
      "exports": ["main"],
      "imports": ["python-telegram-bot", "./config", "./handlers"]
    },
    {
      "file": "handlers.py",
      "exports": ["handle_message"],
      "imports": ["python-telegram-bot", "./extractor", "./config"]
    },
    {
      "file": "extractor.py",
      "exports": ["extract_media"],
      "imports": ["yt_dlp", "pathlib", "tempfile"]
    },
    {
      "file": "config.py",
      "exports": ["BOT_TOKEN", "WEBHOOK_URL", "TEMP_DIR", "URL_PATTERNS"],
      "imports": ["os"]
    }
  ],
  "public_interfaces": [
    {
      "type": "route",
      "path": "/webhook/fetch",
      "method": "POST",
      "description": "Telegram webhook endpoint — receives message updates from Telegram API"
    }
  ]
}
```

## Interaction Flows

Flow: Link shared — happy path
1. User sends message containing an Instagram/TikTok/X link → bot detects URL pattern
2. Bot calls yt-dlp to extract media + metadata (thumbnail, caption, source platform)
3. Bot deletes the original message
4. Bot posts media (photo or video) as a new message with caption: "Caroline (via Instagram): [original caption if any]"
5. If post is a carousel → bot sends as a Telegram media group (album), attribution on first item

Flow: Link shared — extraction fails
1. User sends a link → bot detects URL → yt-dlp fails (private account, deleted post, rate limit)
2. Bot does NOT delete the original message (preserve the link since we can't replace it)
3. Bot replies to the original message: "Could not fetch this one — link might be private or down"

Flow: Link shared — video too large
1. User sends a link → yt-dlp extracts a video > 50MB
2. Bot compresses/re-encodes to fit Telegram's limit, OR falls back to sending a thumbnail + caption if compression isn't feasible
3. Original message deleted, media posted with attribution as normal

Flow: Message with link + extra text
1. User sends "lmao look at this [link]" → bot detects link within message
2. Bot extracts media, deletes original
3. Bot posts media with attribution: "Caroline (via TikTok): lmao look at this" — preserving the user's commentary as the caption

Flow: Multiple links in one message
1. User sends a message with 2+ links → bot processes each link separately
2. Original message deleted → bot posts one media message per link, each with attribution

## Acceptance Criteria

- [ ] Bot receives a Telegram message containing an Instagram/X/TikTok link and responds with the extracted media inline
- [ ] Original message is deleted and replaced with media + attribution in format `"Name (via Platform): caption"`
- [ ] Carousel posts are sent as Telegram media groups (albums)
- [ ] If extraction fails, original message is preserved and bot replies with an error notice
- [ ] Videos over 50MB are re-encoded to fit Telegram's upload limit
- [ ] User commentary surrounding the link is preserved in the attribution caption
- [ ] Multiple links in one message are each posted as separate media messages
- [ ] Webhook receives updates with < 1s latency via cloudflared tunnel

## Constraints

- Telegram bot API file upload limit: 50MB (2GB for premium users)
- Telegram media groups: max 10 items per album
- Bot must have admin rights in the group chat to delete other users' messages
- Instagram may require session cookies for private or age-gated content
- yt-dlp installed at `P:\software\yt-dlp\`
- Bot runs on Windows 11 (Jordan's PC)

## Out of Scope (v1)

- YouTube, Reddit, or other platforms (easy to add later since yt-dlp supports them)
- Inline mode / DM support — group chats only for now
- Web dashboard or admin UI
- Message queue or retry logic
- Database / persistence of any kind
- Multi-group support (works technically, but not designing around it)

## Notes

- If delete-and-repost feels too aggressive in practice, fallback to reply-with-media (keep original message) is a config toggle away
- Instagram is the flakiest platform for extraction — may need cookie auth eventually
- YouTube is an easy future win since yt-dlp was literally built for it
