"""REST API for media extraction. Called by the forked Telegram web client."""

import asyncio
import json
import logging
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tornado.ioloop
import tornado.web

from config import API_PORT, TEMP_DIR, URL_PATTERNS, detect_platform
from extractor import extract_media

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("fetch-api")

executor = ThreadPoolExecutor(max_workers=4)

# Track temp dirs for cleanup (path -> creation timestamp)
_temp_dirs: dict[str, float] = {}
CLEANUP_AGE_SECS = 300  # 5 minutes


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
        logger.info("Extracting %s from %s", platform, url)

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(executor, extract_media, url, platform)
        except Exception as e:
            logger.exception("Extraction failed for %s", url)
            self.set_status(500)
            self.write({"success": False, "error": str(e)})
            return

        if not result.items:
            self.set_status(404)
            self.write({"success": False, "error": "No media found"})
            return

        # Build response with file URLs
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

            # Track the temp dir for cleanup
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
    """Periodically remove temp dirs older than CLEANUP_AGE_SECS."""
    now = time.time()
    to_remove = [d for d, ts in _temp_dirs.items() if now - ts > CLEANUP_AGE_SECS]
    for d in to_remove:
        shutil.rmtree(d, ignore_errors=True)
        del _temp_dirs[d]
    if to_remove:
        logger.info("Cleaned up %d old temp dir(s)", len(to_remove))


def main():
    os.makedirs(TEMP_DIR, exist_ok=True)

    app = tornado.web.Application([
        (r"/extract", ExtractHandler),
        (r"/files/(.*)", FileHandler, {"path": TEMP_DIR}),
    ])
    app.listen(API_PORT)
    logger.info("Fetch API listening on port %d", API_PORT)

    # Schedule cleanup every 60 seconds
    cleanup_callback = tornado.ioloop.PeriodicCallback(cleanup_old_files, 60_000)
    cleanup_callback.start()

    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
