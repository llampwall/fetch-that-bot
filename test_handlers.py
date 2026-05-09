import unittest
import re

from handlers import _build_attribution


def visible_text(html: str) -> str:
    """Strip HTML tags so we can measure rendered length the way Telegram does."""
    return re.sub(r"<[^>]+>", "", html)


class AttributionCaptionTests(unittest.TestCase):
    def test_keeps_post_caption_and_linkifies_embedded_url(self):
        url = "https://x.com/indian_bronson/status/2049999139665264887"
        post_caption = (
            "“The original Xbox dashboard has been fully reverse-engineered "
            "and reconstructed to run on PC.”\n\n"
            "I thought, no way. But, way:\n\n"
            "https://t.co/bVC3e6dzrU"
        )

        caption = _build_attribution(
            "Jordan Hewitt",
            "X",
            url,
            "",
            post_caption,
        )

        self.assertEqual(
            caption,
            f'Jordan [<a href="{url}">X</a>] - '
            "“The original Xbox dashboard has been fully reverse-engineered "
            "and reconstructed to run on PC.”\n\n"
            "I thought, no way. But, way:\n\n"
            '<a href="https://t.co/bVC3e6dzrU">link</a>',
        )

    def test_user_text_still_overrides_source_caption(self):
        caption = _build_attribution(
            "Alex",
            "TikTok",
            "https://www.tiktok.com/@example/video/123",
            "look at this",
            "original caption",
        )

        self.assertEqual(
            caption,
            'Alex [<a href="https://www.tiktok.com/@example/video/123">TikTok</a>] - look at this',
        )

    def test_visible_caption_is_capped_at_225_characters(self):
        caption = _build_attribution(
            "Jordan Hewitt",
            "X",
            "https://x.com/example/status/123",
            "",
            "a" * 300,
        )

        rendered = visible_text(caption)
        self.assertEqual(len(rendered), 225)
        self.assertTrue(rendered.endswith("..."))

    # --- regression gauntlet — cases that have actually broken in chat ---

    def test_url_only_caption_does_not_collapse_to_bare_header(self):
        """An X post whose description is just a t.co link must not produce
        a bare 'Archibald [X]' caption."""
        url = "https://x.com/somebody/status/999"
        caption = _build_attribution(
            "Archibald",
            "X",
            url,
            "",
            "https://t.co/abc123",
        )

        self.assertEqual(
            caption,
            f'Archibald [<a href="{url}">X</a>] - <a href="https://t.co/abc123">link</a>',
        )

    def test_caption_with_url_in_the_middle(self):
        url = "https://x.com/foo/status/1"
        caption = _build_attribution(
            "Sam",
            "X",
            url,
            "",
            "before https://t.co/abc after",
        )

        self.assertEqual(
            caption,
            f'Sam [<a href="{url}">X</a>] - before <a href="https://t.co/abc">link</a> after',
        )

    def test_multiple_embedded_urls_each_become_link(self):
        url = "https://x.com/foo/status/1"
        caption = _build_attribution(
            "Sam",
            "X",
            url,
            "",
            "see https://t.co/aaa and https://t.co/bbb",
        )

        self.assertEqual(
            caption,
            f'Sam [<a href="{url}">X</a>] - see <a href="https://t.co/aaa">link</a> '
            'and <a href="https://t.co/bbb">link</a>',
        )

    def test_trailing_punctuation_not_swallowed_into_url(self):
        url = "https://x.com/foo/status/1"
        caption = _build_attribution(
            "Sam",
            "X",
            url,
            "",
            "look here: https://t.co/abc, and reply",
        )

        self.assertEqual(
            caption,
            f'Sam [<a href="{url}">X</a>] - look here: <a href="https://t.co/abc">link</a>, and reply',
        )

    def test_html_special_chars_in_caption_are_escaped(self):
        url = "https://x.com/foo/status/1"
        caption = _build_attribution(
            "Sam",
            "X",
            url,
            "",
            "rage & <fury> at https://t.co/x",
        )

        self.assertEqual(
            caption,
            f'Sam [<a href="{url}">X</a>] - rage &amp; &lt;fury&gt; at <a href="https://t.co/x">link</a>',
        )

    def test_quotes_in_url_are_escaped_in_href(self):
        # Defensive — yt-dlp shouldn't hand us URLs with quotes, but if it
        # does we must not break out of the href attribute.
        weird = 'https://example.com/"onclick=alert(1)'
        caption = _build_attribution("Sam", "X", weird, "", "")
        # No raw unescaped quote should appear inside the href value
        self.assertNotIn('"onclick', caption.replace("&quot;", ""))
        self.assertIn("&quot;onclick", caption)

    def test_empty_user_text_falls_through_to_post_caption(self):
        url = "https://x.com/foo/status/1"
        caption = _build_attribution(
            "Sam",
            "X",
            url,
            "   ",
            "the actual caption",
        )

        self.assertEqual(
            caption,
            f'Sam [<a href="{url}">X</a>] - the actual caption',
        )

    def test_no_caption_no_user_text_yields_bare_header(self):
        url = "https://x.com/foo/status/1"
        caption = _build_attribution("Sam", "X", url, "", "")
        self.assertEqual(caption, f'Sam [<a href="{url}">X</a>]')

    def test_first_name_only_used_in_attribution(self):
        url = "https://x.com/foo/status/1"
        caption = _build_attribution("Jordan Hewitt", "X", url, "hi", "")
        self.assertTrue(caption.startswith("Jordan ["))
        self.assertNotIn("Hewitt", caption)

    def test_unknown_first_name_falls_back_to_someone(self):
        url = "https://x.com/foo/status/1"
        caption = _build_attribution("", "X", url, "hi", "")
        self.assertTrue(caption.startswith("Someone ["))

    def test_caption_truncation_preserves_visible_limit_with_links(self):
        """Truncation budget counts a URL as len('link') visible characters."""
        url = "https://x.com/foo/status/1"
        body = ("word " * 60) + "https://t.co/x " + ("tail " * 60)
        caption = _build_attribution("Sam", "X", url, "", body)
        rendered = visible_text(caption)
        self.assertLessEqual(len(rendered), 225)


if __name__ == "__main__":
    unittest.main()
