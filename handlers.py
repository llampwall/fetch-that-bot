from __future__ import annotations

import logging
import re
from html import escape

from telegram import InputMediaPhoto, InputMediaVideo, Update
from telegram.ext import ContextTypes

from config import URL_PATTERNS, detect_platform
from extractor import ExtractionResult, VideoDurationExceeded, cleanup, extract_media

logger = logging.getLogger(__name__)

_GENERIC_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_URL_TRAILING_PUNCT = ".,;:!?)\"']>"
_LINK_LABEL = "link"
_MAX_CAPTION_CHARS = 225
_ELLIPSIS = "..."
_CAPTION_SEPARATOR = " - "


def _first_name(user_name: str) -> str:
    """Return the first display-name token."""
    name = (user_name or "").strip()
    if not name:
        return "Someone"
    return name.split()[0]


def _strip_embedded_urls(text: str) -> str:
    """Remove source URLs from plain-text fallback messages.

    Used only on the failure path where the original URL is shown on its own
    line — embedded t.co/quote-tweet URLs would just be visual noise there.
    The success-path caption uses `_format_caption_body` instead, which keeps
    URLs as clean linked text.
    """
    return _GENERIC_URL_PATTERN.sub("", text).strip()


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= len(_ELLIPSIS):
        return _ELLIPSIS[:limit]
    return text[:limit - len(_ELLIPSIS)] + _ELLIPSIS


def _format_caption_body(text: str, limit: int) -> str:
    """Build an HTML caption body: escape text, replace each URL with
    `<a href="URL">link</a>`. Truncates by visible character count so the
    rendered message stays under `limit` characters in the chat UI.

    URL anchor tags count as `len(_LINK_LABEL)` visible characters; t.co and
    other embedded URLs in social captions become tidy "link" links instead
    of long bare strings.
    """
    text = (text or "").strip()
    if not text or limit <= 0:
        return ""

    pieces: list[str] = []
    visible = 0
    cursor = 0

    def append_plain(seg: str) -> bool:
        """Escape and append a plain segment. Returns False if the limit was
        hit and the caller should stop emitting further pieces."""
        nonlocal visible
        if not seg:
            return True
        room = limit - visible
        if len(seg) <= room:
            pieces.append(escape(seg))
            visible += len(seg)
            return visible < limit
        keep = max(room - len(_ELLIPSIS), 0)
        pieces.append(escape(seg[:keep]) + _ELLIPSIS[:room])
        visible = limit
        return False

    for m in _GENERIC_URL_PATTERN.finditer(text):
        if m.start() > cursor:
            if not append_plain(text[cursor:m.start()]):
                return "".join(pieces)
        url = m.group(0).rstrip(_URL_TRAILING_PUNCT)
        cursor = m.start() + len(url)
        room = limit - visible
        if room <= 0:
            break
        if len(_LINK_LABEL) > room:
            pieces.append(_ELLIPSIS[:room])
            visible = limit
            return "".join(pieces)
        pieces.append(f'<a href="{escape(url, quote=True)}">{_LINK_LABEL}</a>')
        visible += len(_LINK_LABEL)

    if cursor < len(text) and visible < limit:
        append_plain(text[cursor:])

    return "".join(pieces)


def _build_attribution(user_name: str, platform: str, url: str, user_text: str | None, post_caption: str | None) -> str:
    """Build the attribution caption: 'First [Platform] - commentary or post caption'.

    URLs inside user_text or post_caption are kept as clean `<a>link</a>`
    anchors so captions stay readable instead of being polluted with bare
    t.co URLs from quote-RTs and similar.
    """
    name = _first_name(user_name)
    visible_header = f"{name} [{platform}]"
    header = f'{escape(name)} [<a href="{escape(url, quote=True)}">{escape(platform)}</a>]'
    body_limit = _MAX_CAPTION_CHARS - len(visible_header) - len(_CAPTION_SEPARATOR)

    # User's own text around the link takes priority
    body = _format_caption_body(user_text or "", body_limit)
    if body:
        return f"{header}{_CAPTION_SEPARATOR}{body}"
    # Fall back to the post's original caption
    body = _format_caption_body(post_caption or "", body_limit)
    if body:
        return f"{header}{_CAPTION_SEPARATOR}{body}"
    return header


def _strip_urls(text: str) -> str:
    """Remove matched URLs from the message text to get the user's commentary."""
    return URL_PATTERNS.sub("", text).strip()


def _format_skip_message(prefix: str, url: str, caption: str | None) -> str:
    """Build a `<prefix>: <caption>\\n<url>` message in plain text.

    The URL is plain (not a text_link entity) so it's visible and copyable.
    Bot messages are filtered out at the top of `handle_message`, so a plain
    URL won't re-trigger extraction; `disable_web_page_preview=True` on the
    send call suppresses the unfurl.
    """
    body = (caption or "").strip()
    if body:
        body = _truncate_text(body, 200)
        return f"{prefix}: {body}\n{url}"
    return f"{prefix}\n{url}"


async def _post_failure(context, chat_id, thread_id, user_name, url, user_text, post_caption):
    """Post a 'couldn't fetch' fallback that preserves the user's link + context.

    Caption priority: user's own commentary first, otherwise the post's caption
    if extraction got far enough to retrieve it.
    """
    name = _first_name(user_name)
    platform = detect_platform(url)
    caption = (user_text or "").strip() or _strip_embedded_urls(post_caption or "")
    prefix = f"Couldn't fetch — {name} [{platform}]"
    text = _format_skip_message(prefix, url, caption)
    try:
        await context.bot.send_message(
            chat_id,
            text,
            disable_web_page_preview=True,
            message_thread_id=thread_id,
        )
    except Exception:
        logger.exception("Failed to post failure fallback for %s", url)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle an incoming message — detect links, extract media, repost inline."""
    message = update.effective_message
    if not message or not message.text:
        return

    # Defensive: never react to bot messages (including our own fallbacks).
    if message.from_user and message.from_user.is_bot:
        return

    urls = URL_PATTERNS.findall(message.text)
    if not urls:
        return

    chat_id = message.chat_id
    thread_id = message.message_thread_id  # None unless in a forum topic/thread
    user_name = message.from_user.first_name if message.from_user else "Someone"
    user_text = _strip_urls(message.text)

    # Delete the original immediately so the chat doesn't sit with a stale link
    # while we extract/compress/upload. Failures get re-posted as a "couldn't
    # fetch" fallback that preserves the link + commentary.
    try:
        await message.delete()
    except Exception:
        logger.warning("Could not delete original message in chat %s", chat_id)

    # Process each URL — extract, then send. Failures (any reason) fall through
    # to a per-URL fallback message at the end. Each failed entry carries the
    # post caption (when extraction got far enough to retrieve one) so the
    # fallback message can include it.
    extractions: list[tuple[str, ExtractionResult]] = []
    failed_urls: list[tuple[str, str | None]] = []

    for url in urls:
        platform = detect_platform(url)
        try:
            result = extract_media(url, platform)
            if result.items:
                extractions.append((url, result))
            else:
                logger.warning("No media extracted from %s", url)
                failed_urls.append((url, result.caption))
        except VideoDurationExceeded as e:
            mins = e.duration // 60
            secs = e.duration % 60
            logger.info("Skipped %s — too long (%dm%ds)", url, mins, secs)
            name = _first_name(user_name)
            prefix = f"{name} [too long, {mins}m{secs:02d}s]"
            caption = (user_text or "").strip() or (e.title or "")
            text = _format_skip_message(prefix, url, caption)
            try:
                await context.bot.send_message(
                    chat_id,
                    text,
                    disable_web_page_preview=True,
                    message_thread_id=thread_id,
                )
            except Exception:
                logger.exception("Failed to post too-long fallback for %s", url)
        except Exception:
            logger.exception("Failed to extract media from %s", url)
            failed_urls.append((url, None))

    # Send each successful extraction
    for url, result in extractions:
        platform = result.platform
        caption = _build_attribution(user_name, platform, url, user_text, result.caption)
        # Telegram caption limit is 1024 chars
        if len(caption) > 1024:
            caption = caption[:1021] + "..."

        try:
            if len(result.items) == 1:
                item = result.items[0]
                with open(item.file_path, "rb") as f:
                    if item.media_type == "video":
                        await context.bot.send_video(
                            chat_id,
                            video=f,
                            caption=caption,
                            parse_mode="HTML",
                            supports_streaming=True,
                            width=item.width,
                            height=item.height,
                            duration=item.duration,
                            message_thread_id=thread_id,
                        )
                    else:
                        await context.bot.send_photo(
                            chat_id, photo=f, caption=caption,
                            parse_mode="HTML",
                            message_thread_id=thread_id,
                        )

            elif len(result.items) > 1:
                # Send as album — caption goes on the first item only
                media_group = []
                file_handles = []
                for i, item in enumerate(result.items):
                    fh = open(item.file_path, "rb")
                    file_handles.append(fh)
                    item_caption = caption if i == 0 else None
                    item_parse_mode = "HTML" if i == 0 else None
                    if item.media_type == "video":
                        media_group.append(InputMediaVideo(
                            media=fh,
                            caption=item_caption,
                            parse_mode=item_parse_mode,
                            supports_streaming=True,
                            width=item.width,
                            height=item.height,
                            duration=item.duration,
                        ))
                    else:
                        media_group.append(InputMediaPhoto(
                            media=fh, caption=item_caption,
                            parse_mode=item_parse_mode,
                        ))

                await context.bot.send_media_group(
                    chat_id, media=media_group,
                    message_thread_id=thread_id,
                )

                for fh in file_handles:
                    fh.close()

        except Exception:
            logger.exception("Failed to send media for %s", url)
            failed_urls.append((url, result.caption))
        finally:
            cleanup(result)

    # Per-URL fallback for anything we couldn't deliver — preserves the link
    # and the user's commentary so the message isn't a black hole.
    for url, post_caption in failed_urls:
        await _post_failure(context, chat_id, thread_id, user_name, url, user_text, post_caption)
