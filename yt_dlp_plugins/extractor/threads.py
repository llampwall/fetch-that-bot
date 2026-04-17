"""Threads extractor plugin for yt-dlp.

Threads serves different HTML to browsers vs plain HTTP clients. A plain GET
returns an empty SPA shell with no post data. When a real browser loads the page,
the server includes structured post data inside <script type="application/json">
tags — the same Instagram-style format with video_versions / image_versions2.

This extractor uses Playwright to fetch the page as a browser, intercepts the
HTML response, and parses the embedded JSON to extract media URLs. The data
flows back through yt-dlp's normal pipeline (formats, thumbnails, playlists).
"""

import concurrent.futures
import json
import logging
import re

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, int_or_none

logger = logging.getLogger(__name__)


class ThreadsIE(InfoExtractor):
    _VALID_URL = r'https?://(?:www\.)?threads\.(?:net|com)/(?:@)?(?P<uploader>[^/]+)/post/(?P<id>[^/?#&]+)'
    IE_NAME = 'threads'

    def _real_extract(self, url):
        post_id = self._match_id(url)
        uploader_id = self._match_valid_url(url).group('uploader').lstrip('@')

        self.to_screen('Rendering page with Playwright to extract media...')

        post = self._fetch_post_data(url, post_id)
        if not post:
            raise ExtractorError(
                f'Could not extract post data for {post_id}. '
                'The page structure may have changed.',
                expected=True,
            )

        # Metadata
        user = post.get('user') or {}
        uploader_name = user.get('full_name') or user.get('username') or uploader_id
        actual_uploader_id = user.get('username') or uploader_id
        uploader_url = f'https://www.threads.com/@{actual_uploader_id}'

        caption_data = post.get('caption')
        caption = caption_data.get('text') if isinstance(caption_data, dict) else (
            caption_data if isinstance(caption_data, str) else None
        )

        title = f'{uploader_name}: {caption[:80]}...' if caption and len(caption) > 80 else (
            f'{uploader_name}: {caption}' if caption else f'Threads post by {uploader_name}'
        )

        common_info = {
            'uploader': uploader_name,
            'uploader_id': actual_uploader_id,
            'uploader_url': uploader_url,
            'like_count': post.get('like_count'),
            'timestamp': post.get('taken_at'),
        }

        # Carousel (multiple media items)
        carousel = post.get('carousel_media')
        if carousel and isinstance(carousel, list):
            entries = []
            for idx, media in enumerate(carousel):
                entry = self._extract_single_media(media, f'{post_id}_{idx}')
                if entry:
                    entry.update(common_info)
                    entries.append(entry)

            if not entries:
                raise ExtractorError(f'No media found in carousel for {post_id}', expected=True)

            if len(entries) == 1:
                entries[0].update({'title': title, 'description': caption})
                return entries[0]

            return self.playlist_result(entries, post_id, title, caption)

        # Single media post
        entry = self._extract_single_media(post, post_id)
        if not entry:
            raise ExtractorError(f'No media found for {post_id}', expected=True)

        return {
            **common_info,
            **entry,
            'title': title,
            'description': caption,
        }

    def _fetch_post_data(self, url, post_id):
        """Use Playwright to load the page and extract post data from embedded JSON."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ExtractorError(
                'Playwright is required for Threads extraction. '
                'Install with: pip install playwright && playwright install chromium',
                expected=True,
            )

        # Playwright sync API cannot run inside an asyncio event loop (the
        # Telegram bot's handler runs in one).  Run it in a separate thread so
        # it gets its own loop-free context.
        def _run_playwright():
            html_body = {}

            def capture_html(response):
                if response.status == 200 and '/post/' in response.url:
                    ct = response.headers.get('content-type', '')
                    if 'text/html' in ct:
                        try:
                            html_body['html'] = response.text()
                        except Exception:
                            pass

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    ctx = browser.new_context(
                        user_agent=(
                            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                            'AppleWebKit/537.36 (KHTML, like Gecko) '
                            'Chrome/125.0.0.0 Safari/537.36'
                        ),
                        viewport={'width': 1280, 'height': 720},
                        locale='en-US',
                    )
                    page = ctx.new_page()
                    page.on('response', capture_html)
                    page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    page.wait_for_timeout(2000)
                finally:
                    browser.close()

            return html_body.get('html')

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            html = pool.submit(_run_playwright).result(timeout=60)
        if not html:
            return None

        # Parse <script type="application/json"> tags for the one containing post data
        scripts = re.findall(
            r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )

        for script_content in scripts:
            if 'video_versions' not in script_content and 'image_versions2' not in script_content:
                continue
            if post_id not in script_content:
                continue
            try:
                data = json.loads(script_content)
                post = self._find_post(data, post_id)
                if post:
                    return post
            except (json.JSONDecodeError, ValueError):
                continue

        # Fallback: check ALL scripts containing the post_id (some posts may
        # embed media data without explicit video_versions, e.g. image-only)
        for script_content in scripts:
            if post_id not in script_content:
                continue
            try:
                data = json.loads(script_content)
                post = self._find_post(data, post_id)
                if post and (post.get('image_versions2') or post.get('video_versions')):
                    return post
            except (json.JSONDecodeError, ValueError):
                continue

        return None

    def _find_post(self, obj, post_id):
        """Recursively search JSON for a dict with 'code' matching post_id."""
        if isinstance(obj, dict):
            if obj.get('code') == post_id:
                return obj
            for value in obj.values():
                found = self._find_post(value, post_id)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = self._find_post(item, post_id)
                if found:
                    return found
        return None

    def _extract_single_media(self, media, media_id):
        """Extract a single media entry — video or image."""
        # Try video first
        videos = media.get('video_versions')
        if videos and isinstance(videos, list):
            formats = []
            for video in videos:
                url = video.get('url')
                if not url:
                    continue
                formats.append({
                    'format_id': str(video.get('type', '')),
                    'url': url,
                    'width': int_or_none(video.get('width') or media.get('original_width')),
                    'height': int_or_none(video.get('height') or media.get('original_height')),
                })

            if formats:
                thumbnails = []
                candidates = (media.get('image_versions2') or {}).get('candidates') or []
                for thumb in candidates:
                    if thumb.get('url'):
                        thumbnails.append({
                            'url': thumb['url'],
                            'width': int_or_none(thumb.get('width')),
                            'height': int_or_none(thumb.get('height')),
                        })
                return {
                    'id': media_id,
                    'formats': formats,
                    'thumbnails': thumbnails,
                }

        # Fall back to image
        image_versions = media.get('image_versions2')
        if isinstance(image_versions, dict):
            candidates = image_versions.get('candidates')
            if candidates and isinstance(candidates, list):
                best = max(
                    candidates,
                    key=lambda x: (x.get('width') or 0) * (x.get('height') or 0),
                )
                if best.get('url'):
                    return {
                        'id': media_id,
                        'url': best['url'],
                        'ext': 'jpg',
                        'width': int_or_none(best.get('width')),
                        'height': int_or_none(best.get('height')),
                    }

        return None


class ThreadsShortIE(InfoExtractor):
    """Handle threads.net/t/CODE and threads.com/t/CODE short URLs."""
    _VALID_URL = r'https?://(?:www\.)?threads\.(?:net|com)/t/(?P<id>[^/?#&]+)'
    IE_NAME = 'threads:short'

    def _real_extract(self, url):
        post_id = self._match_id(url)
        return self.url_result(
            f'https://www.threads.com/@_/post/{post_id}',
            ThreadsIE, post_id)
