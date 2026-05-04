from __future__ import annotations

import logging
import re

from telegram import InputMediaPhoto, InputMediaVideo, Update
from telegram.ext import ContextTypes

from config import URL_PATTERNS, detect_platform
from extractor import ExtractionResult, VideoDurationExceeded, cleanup, extract_media

logger = logging.getLogger(__name__)

_GENERIC_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
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
    """Remove source URLs from captions that already have a linked header."""
    return _GENERIC_URL_PATTERN.sub("", text).strip()


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= len(_ELLIPSIS):
        return _ELLIPSIS[:limit]
    return text[:limit - len(_ELLIPSIS)] + _ELLIPSIS


def _build_attribution(user_name: str, platform: str, url: str, user_text: str | None, post_caption: str | None) -> str:
    """Build the attribution caption: 'First [Platform] - commentary or post caption'."""
    from html import escape
    name = _first_name(user_name)
    visible_header = f"{name} [{platform}]"
    header = f'{escape(name)} [<a href="{escape(url)}">{escape(platform)}</a>]'

    # User's own text around the link takes priority
    if user_text and user_text.strip():
        body = user_text.strip()
        body_limit = _MAX_CAPTION_CHARS - len(visible_header) - len(_CAPTION_SEPARATOR)
        return f"{header}{_CAPTION_SEPARATOR}{escape(_truncate_text(body, body_limit))}"
    # Fall back to the post's original caption
    cleaned_caption = _strip_embedded_urls(post_caption or "")
    if cleaned_caption:
        body_limit = _MAX_CAPTION_CHARS - len(visible_header) - len(_CAPTION_SEPARATOR)
        return f"{header}{_CAPTION_SEPARATOR}{escape(_truncate_text(cleaned_caption, body_limit))}"
    return header


def _strip_urls(text: str) -> str:
    """Remove matched URLs from the message text to get the user's commentary."""
    return URL_PATTERNS.sub("", text).strip()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle an incoming message — detect links, extract media, repost inline."""
    message = update.effective_message
    if not message or not message.text:
        return

    urls = URL_PATTERNS.findall(message.text)
    if not urls:
        return

    chat_id = message.chat_id
    thread_id = message.message_thread_id  # None unless in a forum topic/thread
    user_name = message.from_user.first_name if message.from_user else "Someone"
    user_text = _strip_urls(message.text)

    # Process each URL
    results: list[tuple[str, ExtractionResult]] = []
    skipped = 0

    for url in urls:
        platform = detect_platform(url)
        try:
            result = extract_media(url, platform)
            if result.items:
                results.append((url, result))
            else:
                logger.warning("No media extracted from %s", url)
        except VideoDurationExceeded as e:
            skipped += 1
            mins = e.duration // 60
            secs = e.duration % 60
            logger.info("Skipped %s — too long (%dm%ds)", url, mins, secs)
            await context.bot.send_message(
                chat_id,
                f"Skipped — that video is {mins}m{secs}s, max is {e.limit // 60}m.",
                message_thread_id=thread_id,
            )
        except Exception:
            logger.exception("Failed to extract media from %s", url)

    if not results:
        if not skipped:
            # Everything genuinely failed — reply with error
            await context.bot.send_message(
                chat_id,
                "Couldn't fetch this one — link might be private or down.",
                message_thread_id=thread_id,
            )
        return

    # Post each extraction result FIRST — only delete the original after we've
    # successfully replaced it, so a failed upload doesn't leave the link gone.
    sent_any = False
    send_failures: list[str] = []

    for url, result in results:
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

            sent_any = True

        except Exception:
            logger.exception("Failed to send media for %s", url)
            send_failures.append(url)
        finally:
            cleanup(result)

    # Only delete the original after at least one successful repost — otherwise
    # the user is left with a deleted link and no replacement.
    if sent_any:
        try:
            await message.delete()
        except Exception:
            logger.warning("Could not delete original message in chat %s", chat_id)

    # If some URLs failed extraction OR upload, note it
    failed_count = (len(urls) - len(results) - skipped) + len(send_failures)
    if failed_count > 0:
        await context.bot.send_message(
            chat_id,
            f"Heads up: {failed_count} link(s) couldn't be fetched — might be private or down.",
            message_thread_id=thread_id,
        )
