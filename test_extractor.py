import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import extractor


class FakeYoutubeDL:
    calls = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=True):
        self.calls.append(download)
        if download is False:
            return {
                "description": "source caption https://t.co/example",
                "thumbnail": "https://example.test/thumb.jpg",
            }
        raise RuntimeError("download failed")


class ExtractMediaTests(unittest.TestCase):
    def setUp(self):
        FakeYoutubeDL.calls = []

    def test_keeps_metadata_caption_when_download_uses_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            download_dir = Path(temp_dir) / "download"

            def fallback(url, fallback_dir):
                Path(fallback_dir).mkdir(parents=True, exist_ok=True)
                file_path = Path(fallback_dir) / "001_photo.jpg"
                file_path.write_bytes(b"fake image")
                return [file_path]

            with (
                patch("extractor.tempfile.mkdtemp", return_value=str(download_dir)),
                patch("extractor.yt_dlp.YoutubeDL", FakeYoutubeDL),
                patch("extractor._gallery_dl_fallback", fallback),
                patch("logging.Logger.exception"),
            ):
                result = extractor.extract_media(
                    "https://x.com/example/status/123",
                    "X",
                )

            self.assertEqual(result.caption, "source caption https://t.co/example")
            self.assertEqual(result.thumbnail, "https://example.test/thumb.jpg")
            self.assertEqual(len(result.items), 1)
            self.assertEqual(result.items[0].media_type, "photo")
            self.assertIn(False, FakeYoutubeDL.calls)

            extractor.cleanup(result)

    def test_metadata_caption_is_not_truncated_before_formatting(self):
        result = extractor.ExtractionResult(platform="X")
        caption = "a" * 300

        extractor._apply_metadata(result, {"description": caption})

        self.assertEqual(result.caption, caption)

    def test_oversize_default_is_false(self):
        result = extractor.ExtractionResult(platform="TikTok")
        self.assertFalse(result.oversize)


class PrepareVideoTests(unittest.TestCase):
    """The 'small HEVC source ballooned under CRF 23' regression — TikTok ships
    18 MB HEVC clips that our codec-fix pass re-encodes to ~60 MB at 1080p. The
    CRF path must fall through to the size-targeted ladder if its output
    overshoots `MAX_UPLOAD_BYTES`, not return the bloated file.
    """

    def test_crf_overshoot_falls_through_to_size_targeted_passes(self):
        src = Path("/tmp/fake_source.mp4")
        produced_out = src.with_name(src.stem + "_enc.mp4")

        probe_info = {
            "vcodec": "hevc",  # triggers needs_reencode
            "width": 1080, "height": 1920,
            "pix_fmt": "yuv420p", "sar": "1:1",
            "duration": 240.0,
        }

        # 18 MB source (under cap → needs_reencode only, not needs_compress)
        src_stat = type("S", (), {"st_size": 18 * 1024 * 1024})()
        # First CRF pass overshoots at 60 MB; ladder passes land at 30 MB.
        crf_stat = type("S", (), {"st_size": 60 * 1024 * 1024})()
        ladder_stat = type("S", (), {"st_size": 30 * 1024 * 1024})()
        stat_calls = []

        def fake_stat(self):
            stat_calls.append(str(self))
            if str(self) == str(src):
                return src_stat
            # First time we look at the encoded output it's the CRF result;
            # after the size-targeted pass runs it's the smaller ladder result.
            return crf_stat if stat_calls.count(str(produced_out)) <= 2 else ladder_stat

        ran_commands = []

        def fake_run(cmd, *args, **kwargs):
            ran_commands.append(cmd)
            return type("P", (), {"returncode": 0, "stderr": b""})()

        with (
            patch.object(extractor.Path, "stat", fake_stat),
            patch.object(extractor.Path, "exists", lambda self: True),
            patch("extractor._probe_video", return_value=probe_info),
            patch("extractor.subprocess.run", fake_run),
        ):
            out, info = extractor._prepare_video(src)

        self.assertEqual(out, produced_out)
        # At least two ffmpeg invocations: the CRF pass plus one ladder pass.
        self.assertGreaterEqual(len(ran_commands), 2)
        # The ladder pass uses -b:v (size-targeted), the CRF pass uses -crf.
        self.assertTrue(any("-b:v" in cmd for cmd in ran_commands[1:]))


if __name__ == "__main__":
    unittest.main()
