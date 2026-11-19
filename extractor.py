from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp

from config import TEMP_DIR, MAX_UPLOAD_BYTES, COOKIES_FILE, MAX_YOUTUBE_DURATION

logger = logging.getLogger(__name__)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class VideoDurationExceeded(Exception):
    """Raised when a video exceeds the configured max duration."""
    def __init__(self, duration: int, limit: int, title: str | None = None):
        self.duration = duration
        self.limit = limit
        self.title = title
        super().__init__(f"Video is {duration}s, limit is {limit}s")


@dataclass
class MediaItem:
    file_path: Path
    media_type: str  # "photo" or "video"
    width: int | None = None
    height: int | None = None
    duration: int | None = None


@dataclass
class ExtractionResult:
    items: list[MediaItem] = field(default_factory=list)
    caption: str | None = None
    platform: str = "Unknown"
    thumbnail: str | None = None
    # True when at least one video was dropped because it stayed over the
    # Telegram size cap even after compression. Lets handlers post an honest
    # "too big" fallback instead of a generic "couldn't fetch".
    oversize: bool = False


def _apply_metadata(result: ExtractionResult, info: dict | None) -> None:
    if not info:
        return

    caption = (
        info.get("description")
        or info.get("title")
        or info.get("fulltitle")
    )
    if caption:
        result.caption = caption
    if info.get("thumbnail"):
        result.thumbnail = info.get("thumbnail")


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".avi"}


def _is_audio(path: Path) -> bool:
    return path.suffix.lower() in {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav"}


def _probe_video(path: Path) -> dict | None:
    """Run ffprobe on a video file and return codec/dimensions/duration info."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, check=True, timeout=30,
            creationflags=_NO_WINDOW,
        )
        data = json.loads(result.stdout)
        video_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            None,
        )
        if not video_stream:
            return None
        return {
            "vcodec": video_stream.get("codec_name"),
            "width": int(video_stream.get("width") or 0),
            "height": int(video_stream.get("height") or 0),
            "pix_fmt": video_stream.get("pix_fmt"),
            "sar": video_stream.get("sample_aspect_ratio"),
            "duration": float(data.get("format", {}).get("duration") or 0),
        }
    except Exception:
        return None


def _needs_reencode(info: dict) -> bool:
    """Check whether a video needs re-encoding for iOS Telegram compatibility."""
    # iOS Telegram reliably handles H.264 only — AV1, VP9, HEVC all fail
    if info.get("vcodec") not in ("h264",):
        return True
    # iOS expects 4:2:0 chroma subsampling
    if info.get("pix_fmt") not in ("yuv420p", "yuvj420p"):
        return True
    # Non-square pixel aspect ratio causes "squished" appearance on iOS
    sar = info.get("sar") or "1:1"
    if sar not in ("1:1", "0:1"):
        return True
    return False


_AUDIO_BITRATE_KBPS = 128
_COMPRESS_HEADROOM_BYTES = 3 * 1024 * 1024  # leave ~3MB under the cap for mux overhead


def _compress_cmd(src: Path, dst: Path, info: dict, target_bytes: int, max_dim: int) -> tuple[list[str], int, float]:
    """Build an ffmpeg command targeting `target_bytes` total output.

    Returns (command, video_bitrate_bps, duration_seconds) for logging.
    """
    duration = max(float(info.get("duration") or 600), 1.0)
    audio_bytes = int(_AUDIO_BITRATE_KBPS * 1000 / 8 * duration)
    video_budget = max(target_bytes - audio_bytes - _COMPRESS_HEADROOM_BYTES, 256 * 1024)
    video_bitrate = int(video_budget * 8 / duration)
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", f"{_AUDIO_BITRATE_KBPS}k",
        "-movflags", "+faststart",
        "-b:v", str(video_bitrate),
        "-maxrate", str(video_bitrate),
        # bufsize=bitrate gives ffmpeg a tight rate-control window; doubling
        # bufsize loosens the cap and is a common cause of overshoot. Keep it
        # equal to bitrate for predictable output size.
        "-bufsize", str(max(video_bitrate, 1)),
        "-vf",
        f"scale='min({max_dim},iw)':'min({max_dim},ih)':force_original_aspect_ratio=decrease,setsar=1",
        # Hard size cap: ffmpeg stops writing once the file hits this size.
        # Output will be truncated if hit, but at least the file is sendable.
        "-fs", str(MAX_UPLOAD_BYTES - _COMPRESS_HEADROOM_BYTES),
        str(dst),
    ]
    return cmd, video_bitrate, duration


def _prepare_video(path: Path) -> tuple[Path, dict | None]:
    """Ensure a video is iOS-compatible and under Telegram's size limit.

    Re-encodes to H.264/AAC/yuv420p with square pixels if the codec is wrong,
    the pixel format is wrong, or the file is too large. If a single compression
    pass overshoots the size cap, retries with a lower bitrate / smaller frame.
    Returns the final path and its probe info; the caller is responsible for
    checking the final size against `MAX_UPLOAD_BYTES`.
    """
    import logging as _log
    log = _log.getLogger(__name__)

    info = _probe_video(path)
    if info is None:
        return path, None

    size = path.stat().st_size
    needs_reencode = _needs_reencode(info)
    needs_compress = size > MAX_UPLOAD_BYTES

    if not needs_reencode and not needs_compress:
        return path, info

    out = path.with_name(path.stem + "_enc.mp4")

    # HEVC sources reliably balloon under CRF 23 H.264 at the same resolution
    # (2-3x growth is typical), so the CRF pass is wasted work that gets
    # discarded by the overshoot check below. Skip straight to the size-
    # targeted ladder for HEVC.
    skip_crf = info.get("vcodec") in ("hevc", "h265")

    if not needs_compress and not skip_crf:
        # Quality-targeted: original resolution, CRF 23.
        cmd = [
            "ffmpeg", "-y", "-i", str(path),
            "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", f"{_AUDIO_BITRATE_KBPS}k",
            "-movflags", "+faststart",
            "-crf", "23", "-vf", "setsar=1",
            str(out),
        ]
        subprocess.run(cmd, capture_output=True, timeout=600, creationflags=_NO_WINDOW)
        if out.exists() and out.stat().st_size > 0:
            # A small source can balloon under CRF 23 (HEVC TikToks are the
            # canonical case — 18 MB in, 60 MB out at 1080p). If the quality
            # pass overshoots the cap, fall through to the size-targeted
            # ladder instead of trusting the bloated output.
            if out.stat().st_size <= MAX_UPLOAD_BYTES:
                return out, _probe_video(out) or info
            log.info(
                "CRF re-encode overshot (%d MB > cap), falling through to size-targeted passes",
                out.stat().st_size // (1024 * 1024),
            )
            info = _probe_video(out) or info
        else:
            return path, info

    # Size-targeted with progressive fallback. Each pass picks a tighter
    # byte budget and a smaller frame in case the previous overshot.
    passes = [
        (35 * 1024 * 1024, 1280),
        (25 * 1024 * 1024, 960),
        (15 * 1024 * 1024, 720),
    ]
    log.info(
        "Compressing %s: %d MB, duration=%.1fs, codec=%s",
        path.name, size // (1024 * 1024),
        float(info.get("duration") or 0), info.get("vcodec"),
    )
    for target_bytes, max_dim in passes:
        cmd, vbr, dur = _compress_cmd(path, out, info, target_bytes, max_dim)
        proc = subprocess.run(
            cmd, capture_output=True, timeout=600, creationflags=_NO_WINDOW,
        )
        produced = out.stat().st_size if out.exists() else 0
        log.info(
            "Pass target=%d MB max_dim=%d vbr=%d kbps dur=%.1fs -> %d MB (rc=%d)",
            target_bytes // (1024 * 1024), max_dim,
            vbr // 1000, dur, produced // (1024 * 1024), proc.returncode,
        )
        if proc.returncode != 0:
            stderr_tail = (proc.stderr or b"").decode("utf-8", "replace")[-500:]
            log.warning("ffmpeg pass failed (rc=%d): %s", proc.returncode, stderr_tail)
            continue
        if produced > 0 and produced < MAX_UPLOAD_BYTES:
            return out, _probe_video(out) or info
        # else: fall through and try a tighter pass

    # All passes failed to fit — return whatever we have; caller will reject.
    if out.exists() and out.stat().st_size > 0:
        return out, _probe_video(out) or info
    return path, info


def _collect_files(download_dir: str, include_audio: bool = False) -> list[Path]:
    """Collect all media files from a download directory."""
    files = []
    for f in sorted(Path(download_dir).iterdir()):
        if _is_image(f) or _is_video(f) or (include_audio and _is_audio(f)):
            files.append(f)
    return files


def _probe_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, check=True, timeout=30,
            creationflags=_NO_WINDOW,
        )
        return float(json.loads(result.stdout).get("format", {}).get("duration") or 0)
    except Exception:
        return 0.0


_SLIDE_MIN_SECONDS = 2.0
_SLIDE_DEFAULT_SECONDS = 3.0
_SLIDESHOW_MAX_DIM = (1080, 1920)


def _build_slideshow(images: list[Path], audio: Path, out: Path) -> Path | None:
    """Render image slides over their soundtrack as one H.264/AAC video.

    TikTok photo posts are a set of images played over a music track. yt-dlp
    rejects them and gallery-dl hands back the images plus the track as an mp3;
    sent as a photo album the post arrives silent. The slides split the track's
    length evenly (at least `_SLIDE_MIN_SECONDS` each) on a canvas sized to the
    largest slide, and the track plays once from the start.

    Slides in one post differ in size (one 11-slide post ran 964 to 1250 px
    tall), which breaks ffmpeg's concat demuxer, so each slide is its own
    looped input, normalized to the canvas before the concat filter joins them.
    """
    audio_seconds = _probe_duration(audio)
    if audio_seconds > 0:
        per_slide = max(audio_seconds / len(images), _SLIDE_MIN_SECONDS)
    else:
        per_slide = _SLIDE_DEFAULT_SECONDS

    dims = [_probe_video(img) or {} for img in images]
    w = max((d.get("width") or 0) for d in dims) or 1080
    h = max((d.get("height") or 0) for d in dims) or 1920
    scale = min(_SLIDESHOW_MAX_DIM[0] / w, _SLIDESHOW_MAX_DIM[1] / h, 1.0)
    w, h = int(w * scale) // 2 * 2, int(h * scale) // 2 * 2

    cmd = ["ffmpeg", "-y"]
    for img in images:
        cmd += ["-loop", "1", "-framerate", "25", "-t", f"{per_slide:.3f}", "-i", str(img)]
    cmd += ["-i", str(audio)]
    chains = [
        f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[s{i}]"
        for i in range(len(images))
    ]
    joined = "".join(f"[s{i}]" for i in range(len(images)))
    chains.append(f"{joined}concat=n={len(images)}:v=1:a=0[v]")
    cmd += [
        "-filter_complex", ";".join(chains),
        "-map", "[v]", "-map", f"{len(images)}:a",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "23",
        "-c:a", "aac", "-b:a", f"{_AUDIO_BITRATE_KBPS}k",
        "-movflags", "+faststart",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=600, creationflags=_NO_WINDOW)
    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        stderr_tail = (proc.stderr or b"").decode("utf-8", "replace")[-500:]
        logger.warning("Slideshow render failed (rc=%d): %s", proc.returncode, stderr_tail)
        return None
    return out


def _gallery_dl_fallback(url: str, download_dir: str) -> list[Path]:
    """Fallback to gallery-dl for image extraction (handles image-only tweets, etc.)."""
    cmd = [
        str(Path(__file__).parent / ".venv" / "Scripts" / "gallery-dl.exe"),
        "--dest", download_dir,
        "--option", "extractor.directory=[]",
        "--option", "extractor.filename={num:>03}_{id}.{extension}",
        url,
    ]
    if os.path.isfile(COOKIES_FILE):
        cmd.extend(["--cookies", COOKIES_FILE])

    subprocess.run(cmd, capture_output=True, timeout=60, creationflags=_NO_WINDOW)

    # gallery-dl may still create subdirs — collect from all of them. Audio is
    # kept so a photo post's soundtrack can be laid under its slides.
    files = _collect_files(download_dir, include_audio=True)
    for sub in Path(download_dir).iterdir():
        if sub.is_dir():
            files.extend(_collect_files(str(sub), include_audio=True))
    return files


def precheck_duration(url: str, platform: str) -> int | None:
    """Return the duration (seconds) if the video exceeds the configured cap,
    or None if it's under the cap, unknown, or not a duration-capped platform.

    Currently only YouTube has a duration cap. Uses a metadata-only yt-dlp
    call (no download) so the caller can decide whether to touch the original
    message before paying for the full extract.
    """
    if platform != "YouTube" or MAX_YOUTUBE_DURATION <= 0:
        return None
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    if os.path.isfile(COOKIES_FILE):
        ydl_opts["cookiefile"] = COOKIES_FILE
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    duration = info.get("duration") if info else None
    if duration and duration > MAX_YOUTUBE_DURATION:
        return int(duration)
    return None


class _YtdlpLog:
    """Route yt-dlp's own output into our logger instead of stderr.

    `quiet` silences progress but not errors, so an image-only post still wrote
    an ERROR line to error.log even though the gallery-dl fallback then served
    it. These are reported by the caller only when the fallback also comes back
    empty, so they arrive here as debug.
    """

    def debug(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    info = debug

    def warning(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)


def extract_media(url: str, platform: str) -> ExtractionResult:
    """Download media from a URL using yt-dlp and return extracted items."""
    os.makedirs(TEMP_DIR, exist_ok=True)
    download_dir = tempfile.mkdtemp(dir=TEMP_DIR)

    ydl_opts = {
        "outtmpl": os.path.join(download_dir, "%(autonumber)03d_%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        # Prefer mp4 container for video
        "merge_output_format": "mp4",
        # Prefer H.264 (avc1) explicitly — iOS Telegram can't decode AV1 or VP9.
        # Cap height at 720p so we don't pull a 1080p60 source we'd just have to
        # downscale anyway (TikTok in particular ships ~150MB 1080p60 streams).
        "format": (
            "bv*[vcodec^=avc1][height<=720]+ba[acodec^=mp4a]"
            "/bv*[vcodec^=avc1][height<=720]+ba"
            "/bv*[vcodec^=avc1]+ba[acodec^=mp4a]"
            "/bv*[vcodec^=avc1]+ba"
            "/b[vcodec^=avc1][height<=720]"
            "/b[vcodec^=avc1]"
            "/b[ext=mp4]"
            "/b"
        ),
        # Move moov atom to front of file so Telegram can stream inline
        "postprocessor_args": {"ffmpeg": ["-movflags", "+faststart"]},
        # Don't download overly massive files — we'll compress if needed
        "max_filesize": MAX_UPLOAD_BYTES * 3,
        "logger": _YtdlpLog(),
    }

    # Use cookies if available (needed for Instagram stories, private content)
    if os.path.isfile(COOKIES_FILE):
        ydl_opts["cookiefile"] = COOKIES_FILE

    result = ExtractionResult(platform=platform)
    metadata = None
    ytdlp_error: Exception | None = None

    try:
        with yt_dlp.YoutubeDL({**ydl_opts, "quiet": True}) as ydl:
            metadata = ydl.extract_info(url, download=False)
        _apply_metadata(result, metadata)
    except Exception:
        pass

    # Pre-download duration check for YouTube
    if platform == "YouTube" and MAX_YOUTUBE_DURATION > 0:
        try:
            if metadata is None:
                with yt_dlp.YoutubeDL({**ydl_opts, "quiet": True}) as ydl:
                    metadata = ydl.extract_info(url, download=False)
                _apply_metadata(result, metadata)
            if metadata and metadata.get("duration") and metadata["duration"] > MAX_YOUTUBE_DURATION:
                shutil.rmtree(download_dir, ignore_errors=True)
                raise VideoDurationExceeded(
                    int(metadata["duration"]),
                    MAX_YOUTUBE_DURATION,
                    title=metadata.get("title") or metadata.get("fulltitle"),
                )
        except VideoDurationExceeded:
            raise
        except Exception:
            pass  # If metadata fetch fails, proceed with normal download

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if info is None:
            return result

        _apply_metadata(result, info)

        # Collect downloaded files
        files = _collect_files(download_dir)

        if not files:
            # Sometimes yt-dlp puts files in a subdirectory
            for sub in Path(download_dir).iterdir():
                if sub.is_dir():
                    files.extend(_collect_files(str(sub)))

        import logging as _log
        log = _log.getLogger(__name__)
        ytdlp_produced_files = bool(files)
        for f in files[:10]:  # Telegram album max is 10
            if _is_video(f):
                f, vinfo = _prepare_video(f)
                if f.exists() and f.stat().st_size > MAX_UPLOAD_BYTES:
                    log.warning(
                        "Skipping %s — still %d MB after compression (cap %d MB)",
                        f.name, f.stat().st_size // (1024 * 1024),
                        MAX_UPLOAD_BYTES // (1024 * 1024),
                    )
                    result.oversize = True
                    continue
                result.items.append(MediaItem(
                    file_path=f,
                    media_type="video",
                    width=vinfo.get("width") if vinfo else None,
                    height=vinfo.get("height") if vinfo else None,
                    duration=int(vinfo.get("duration") or 0) if vinfo else None,
                ))
            elif _is_image(f):
                result.items.append(MediaItem(file_path=f, media_type="photo"))
        # If yt-dlp produced files but every one was too big to send, don't
        # waste time re-downloading the same thing via gallery-dl.
        if ytdlp_produced_files and not result.items:
            return result

    except Exception as e:
        # An image-only post ALWAYS fails here — yt-dlp has no image path for one — and the
        # gallery-dl fallback below is what serves it. Logging a traceback at this point
        # recorded the design as a failure on every image the bot handled. The error is held
        # instead and reported only if the fallback ALSO comes back empty, which is the case
        # that is actually a failure.
        ytdlp_error = e
        logger.debug("yt-dlp got nothing for %s (%s) — trying gallery-dl", url, e)

    # Fallback to gallery-dl if yt-dlp got nothing (e.g. image-only tweets)
    if not result.items:
        try:
            fallback_files = _gallery_dl_fallback(url, download_dir)
            images = [f for f in fallback_files if _is_image(f)]
            audio = [f for f in fallback_files if _is_audio(f)]
            slideshow = None
            if images and audio and not any(_is_video(f) for f in fallback_files):
                slideshow = _build_slideshow(
                    images, audio[0], Path(download_dir) / "slideshow.mp4",
                )
            if slideshow is not None:
                # Every slide is in the video, so it goes out alone rather
                # than beside a silent album of the same images.
                fallback_files = [slideshow]
            for f in fallback_files[:10]:
                if _is_video(f):
                    f, vinfo = _prepare_video(f)
                    result.items.append(MediaItem(
                        file_path=f,
                        media_type="video",
                        width=vinfo.get("width") if vinfo else None,
                        height=vinfo.get("height") if vinfo else None,
                        duration=int(vinfo.get("duration") or 0) if vinfo else None,
                    ))
                elif _is_image(f):
                    result.items.append(MediaItem(file_path=f, media_type="photo"))
        except Exception as e:
            shutil.rmtree(download_dir, ignore_errors=True)
            raise RuntimeError(f"Extraction failed for {url}: {e}") from e

    # Both paths came back empty. THIS is the failure, and it is the one place the
    # held yt-dlp error is worth reading, so it goes out with its cause attached
    # rather than as a bare "no media" the caller cannot act on.
    if not result.items and ytdlp_error is not None:
        logger.warning("No media from either extractor for %s — yt-dlp said: %s", url, ytdlp_error)

    return result


def cleanup(result: ExtractionResult) -> None:
    """Remove temp files after they've been sent."""
    dirs_to_remove = set()
    for item in result.items:
        dirs_to_remove.add(item.file_path.parent)
        if item.file_path.exists():
            item.file_path.unlink(missing_ok=True)
    for d in dirs_to_remove:
        shutil.rmtree(d, ignore_errors=True)
