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

    def test_photo_post_with_soundtrack_is_sent_as_one_video(self):
        # TikTok photo posts: yt-dlp fails, gallery-dl returns slides + mp3.
        # Sent as an album they arrive silent; they must go out as one video.
        with tempfile.TemporaryDirectory() as temp_dir:
            download_dir = Path(temp_dir) / "download"

            def fallback(url, fallback_dir):
                Path(fallback_dir).mkdir(parents=True, exist_ok=True)
                files = [Path(fallback_dir) / n for n in ("000_a.mp3", "001_a.jpg", "002_a.jpg")]
                for f in files:
                    f.write_bytes(b"x")
                return files

            built = {}

            def fake_build(images, audio, out):
                built["images"], built["audio"] = images, audio
                out.write_bytes(b"video")
                return out

            with (
                patch("extractor.tempfile.mkdtemp", return_value=str(download_dir)),
                patch("extractor.yt_dlp.YoutubeDL", FakeYoutubeDL),
                patch("extractor._gallery_dl_fallback", fallback),
                patch("extractor._build_slideshow", fake_build),
                patch("extractor._prepare_video", lambda p: (p, {"width": 750, "height": 1250, "duration": 59})),
            ):
                result = extractor.extract_media("https://www.tiktok.com/@a/photo/1", "TikTok")

            self.assertEqual([p.name for p in built["images"]], ["001_a.jpg", "002_a.jpg"])
            self.assertEqual(built["audio"].name, "000_a.mp3")
            self.assertEqual(len(result.items), 1)
            self.assertEqual(result.items[0].media_type, "video")
            self.assertEqual(result.items[0].file_path.name, "slideshow.mp4")
            extractor.cleanup(result)

    def test_photo_post_falls_back_to_album_when_render_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            download_dir = Path(temp_dir) / "download"

            def fallback(url, fallback_dir):
                Path(fallback_dir).mkdir(parents=True, exist_ok=True)
                files = [Path(fallback_dir) / n for n in ("000_a.mp3", "001_a.jpg", "002_a.jpg")]
                for f in files:
                    f.write_bytes(b"x")
                return files

            with (
                patch("extractor.tempfile.mkdtemp", return_value=str(download_dir)),
                patch("extractor.yt_dlp.YoutubeDL", FakeYoutubeDL),
                patch("extractor._gallery_dl_fallback", fallback),
                patch("extractor._build_slideshow", lambda *a: None),
            ):
                result = extractor.extract_media("https://www.tiktok.com/@a/photo/1", "TikTok")

            self.assertEqual([i.media_type for i in result.items], ["photo", "photo"])
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
    """Compression-path regressions — see `_prepare_video`.

    HEVC sources skip the CRF pass entirely (they reliably balloon 2-3x under
    CRF 23 H.264 at the same resolution, so the pass would just be discarded
    by the overshoot check). Other non-H.264 codecs still get the CRF pass
    with a fall-through to the size-targeted ladder on overshoot.
    """

    def _run(self, src, probe_info, stat_for_out):
        produced_out = src.with_name(src.stem + "_enc.mp4")
        src_stat = type("S", (), {"st_size": 18 * 1024 * 1024})()
        stat_calls = []

        def fake_stat(self):
            stat_calls.append(str(self))
            if str(self) == str(src):
                return src_stat
            return stat_for_out(stat_calls.count(str(produced_out)))

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
        return out, ran_commands, produced_out

    def test_hevc_source_skips_crf_and_goes_straight_to_ladder(self):
        src = Path("/tmp/hevc_source.mp4")
        probe_info = {
            "vcodec": "hevc",
            "width": 1080, "height": 1920,
            "pix_fmt": "yuv420p", "sar": "1:1",
            "duration": 240.0,
        }
        ladder_stat = type("S", (), {"st_size": 30 * 1024 * 1024})()
        out, ran, produced_out = self._run(src, probe_info, lambda n: ladder_stat)

        self.assertEqual(out, produced_out)
        # Every ffmpeg invocation should be a size-targeted ladder pass; no CRF.
        self.assertTrue(ran)
        self.assertFalse(any("-crf" in cmd for cmd in ran))
        self.assertTrue(all("-b:v" in cmd for cmd in ran))

    def test_h264_with_he_aac_copies_video_and_reencodes_audio_only(self):
        # TikTok's native stream: H.264 video is fine, HE-AACv2 audio is not.
        src = Path("/tmp/tiktok_h264.mp4")
        probe_info = {
            "vcodec": "h264", "acodec": "aac", "aprofile": "HE-AACv2",
            "width": 720, "height": 1280,
            "pix_fmt": "yuv420p", "sar": "1:1",
            "duration": 74.0,
        }
        small = type("S", (), {"st_size": 13 * 1024 * 1024})()
        out, ran, produced_out = self._run(src, probe_info, lambda n: small)

        self.assertEqual(out, produced_out)
        self.assertEqual(len(ran), 1)
        cmd = ran[0]
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "copy")
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "aac")

    def test_needs_audio_fix(self):
        self.assertFalse(extractor._needs_audio_fix({"acodec": "aac", "aprofile": "LC"}))
        self.assertFalse(extractor._needs_audio_fix({"acodec": None}))
        self.assertTrue(extractor._needs_audio_fix({"acodec": "aac", "aprofile": "HE-AACv2"}))
        self.assertTrue(extractor._needs_audio_fix({"acodec": "opus", "aprofile": None}))

    def test_non_hevc_crf_overshoot_falls_through_to_ladder(self):
        src = Path("/tmp/vp9_source.mp4")
        probe_info = {
            "vcodec": "vp9",  # triggers needs_reencode but not skip_crf
            "width": 1080, "height": 1920,
            "pix_fmt": "yuv420p", "sar": "1:1",
            "duration": 240.0,
        }
        crf_stat = type("S", (), {"st_size": 60 * 1024 * 1024})()
        ladder_stat = type("S", (), {"st_size": 30 * 1024 * 1024})()
        produced_out = src.with_name(src.stem + "_enc.mp4")
        out, ran, _ = self._run(
            src,
            probe_info,
            lambda n: crf_stat if n <= 2 else ladder_stat,
        )

        self.assertEqual(out, produced_out)
        # CRF pass plus at least one ladder pass.
        self.assertGreaterEqual(len(ran), 2)
        self.assertTrue(any("-crf" in cmd for cmd in ran))
        self.assertTrue(any("-b:v" in cmd for cmd in ran[1:]))


if __name__ == "__main__":
    unittest.main()
