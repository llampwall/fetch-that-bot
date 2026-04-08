from __future__ import annotations

import logging

from telegram import InputMediaPhoto, InputMediaVideo, Update
from telegram.ext import ContextTypes

from config import URL_PATTERNS, detect_platform
from extractor import ExtractionResult, cleanup, extract_media

logger = logging.getLogger(__name__)


def _build_attribution(user_name: str, platform: str, user_text: str | None, post_caption: str | None) -> str:
    """Build the attribution caption: 'Name (via Platform): commentary or post caption'."""
    header = f"{user_name} (via {platform})"

    # User's own text around the link takes priority
    if user_text and user_text.strip():
        return f"{header}: {user_text.strip()}"
    # Fall back to the post's original caption
    if post_caption and post_caption.strip():
        return f"{header}: {post_caption.strip()}"
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
    user_name = message.from_user.first_name if message.from_user else "Someone"
    user_text = _strip_urls(message.text)

    # Process each URL
    results: list[tuple[str, ExtractionResult]] = []
    all_succeeded = True

    for url in urls:
        platform = detect_platform(url)
        try:
            result = extract_media(url, platform)
            if result.items:
                results.append((url, result))
            else:
                all_succeeded = False
                logger.warning("No media extracted from %s", url)
        except Exception:
            all_succeeded = False
            logger.exception("Failed to extract media from %s", url)

    if not results:
        # Everything failed — reply with error, don't delete original
        await message.reply_text("Couldn't fetch this one — link might be private or down.")
        return

    # Delete original message (only if we have at least one success)
    try:
        await message.delete()
    except Exception:
        # Bot might not have admin rights — continue anyway
        logger.warning("Could not delete original message in chat %s", chat_id)

    # Post each extraction result
    for url, result in results:
        platform = result.platform
        caption = _build_attribution(user_name, platform, user_text, result.caption)
        # Telegram caption limit is 1024 chars
        if len(caption) > 1024:
            caption = caption[:1021] + "..."

        try:
            if len(result.items) == 1:
                item = result.items[0]
                with open(item.file_path, "rb") as f:
                    if item.media_type == "video":
                        await context.bot.send_video(chat_id, video=f, caption=caption)
                    else:
                        await context.bot.send_photo(chat_id, photo=f, caption=caption)

            elif len(result.items) > 1:
                # Send as album — caption goes on the first item only
                media_group = []
                file_handles = []
                for i, item in enumerate(result.items):
                    fh = open(item.file_path, "rb")
                    file_handles.append(fh)
                    item_caption = caption if i == 0 else None
                    if item.media_type == "video":
                        media_group.append(InputMediaVideo(media=fh, caption=item_caption))
                    else:
                        media_group.append(InputMediaPhoto(media=fh, caption=item_caption))

                await context.bot.send_media_group(chat_id, media=media_group)

                for fh in file_handles:
                    fh.close()

        except Exception:
            logger.exception("Failed to send media for %s", url)
        finally:
            cleanup(result)

    # If some URLs failed, note it
    if not all_succeeded:
        failed_count = len(urls) - len(results)
        await context.bot.send_message(
            chat_id,
            f"Heads up: {failed_count} link(s) couldn't be fetched — might be private or down.",
        )
