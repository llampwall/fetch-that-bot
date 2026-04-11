"""Fetch — Telegram bot + REST API for social media extraction.

Bot: monitors group chats for social links, extracts media, reposts inline.
API: GET /extract?url=... for the Interlink web client.
"""

import asyncio
import logging
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tornado.ioloop
import tornado.web
from telegram.ext import Application, MessageHandler, filters

from config import (
    API_PORT, BOT_TOKEN, TEMP_DIR, URL_PATTERNS,
    WEBHOOK_PATH, WEBHOOK_PORT, WEBHOOK_URL, detect_platform,
)
from extractor import extract_media
from handlers import handle_message

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("fetch")

executor = ThreadPoolExecutor(max_workers=4)

# Track temp dirs for cleanup (path -> creation timestamp)
_temp_dirs: dict[str, float] = {}
CLEANUP_AGE_SECS = 300  # 5 minutes


# --- REST API handlers (for Interlink web client) ---

class CORSMixin:
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")

    def options(self):
        self.set_status(204)
        self.finish()


class ExtractHandler(CORSMixin, tornado.web.RequestHandler):
    async def get(self):
        url = self.get_argument("url", None)
        if not url:
            self.set_status(400)
            self.write({"success": False, "error": "Missing 'url' parameter"})
            return

        if not URL_PATTERNS.search(url):
            self.set_status(400)
            self.write({"success": False, "error": "URL not from a supported platform"})
            return

        platform = detect_platform(url)
        logger.info("API: Extracting %s from %s", platform, url)

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(executor, extract_media, url, platform)
        except Exception as e:
            logger.exception("API: Extraction failed for %s", url)
            self.set_status(500)
            self.write({"success": False, "error": str(e)})
            return

        if not result.items:
            self.set_status(404)
            self.write({"success": False, "error": "No media found"})
            return

        items = []
        for item in result.items:
            rel_path = item.file_path.relative_to(Path(TEMP_DIR))
            file_url = f"/files/{rel_path.as_posix()}"
            entry = {"type": item.media_type, "url": file_url}
            if item.width:
                entry["width"] = item.width
            if item.height:
                entry["height"] = item.height
            if item.duration:
                entry["duration"] = item.duration
            items.append(entry)
            _temp_dirs[str(item.file_path.parent)] = time.time()

        self.write({
            "success": True,
            "platform": result.platform,
            "caption": result.caption,
            "thumbnail": result.thumbnail,
            "items": items,
        })


class FileHandler(CORSMixin, tornado.web.StaticFileHandler):
    def set_default_headers(self):
        super().set_default_headers()
        self.set_header("Access-Control-Allow-Origin", "*")


def cleanup_old_files():
    now = time.time()
    to_remove = [d for d, ts in _temp_dirs.items() if now - ts > CLEANUP_AGE_SECS]
    for d in to_remove:
        shutil.rmtree(d, ignore_errors=True)
        del _temp_dirs[d]
    if to_remove:
        logger.info("Cleaned up %d old temp dir(s)", len(to_remove))


# --- Main ---

def main() -> None:
    if not BOT_TOKEN:
        logger.error("FETCH_BOT_TOKEN not set.")
        sys.exit(1)
    if not WEBHOOK_URL:
        logger.error("FETCH_WEBHOOK_URL not set.")
        sys.exit(1)

    os.makedirs(TEMP_DIR, exist_ok=True)

    # Start the REST API server (non-blocking — registers with tornado IOLoop)
    api_app = tornado.web.Application([
        (r"/extract", ExtractHandler),
        (r"/files/(.*)", FileHandler, {"path": TEMP_DIR}),
    ])
    api_app.listen(API_PORT, address="0.0.0.0")
    logger.info("API listening on port %d", API_PORT)

    # Schedule temp file cleanup every 60 seconds
    tornado.ioloop.PeriodicCallback(cleanup_old_files, 60_000).start()

    # Start the Telegram bot webhook (blocking — starts the tornado IOLoop)
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot webhook: %s (port %d)", WEBHOOK_URL, WEBHOOK_PORT)
    app.run_webhook(
        listen="0.0.0.0",
        port=WEBHOOK_PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL,
    )


if __name__ == "__main__":
    main()
