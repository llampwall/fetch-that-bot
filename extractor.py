from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp

from config import TEMP_DIR, MAX_UPLOAD_BYTES, COOKIES_FILE

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


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


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".avi"}


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


def _prepare_video(path: Path) -> tuple[Path, dict | None]:
    """Ensure a video is iOS-compatible and under Telegram's size limit.

    Re-encodes to H.264/AAC/yuv420p with square pixels if the codec is wrong,
    the pixel format is wrong, or the file is too large. Returns the final path
    and its probe info.
    """
    info = _probe_video(path)
    if info is None:
        return path, None

    size = path.stat().st_size
    needs_reencode = _needs_reencode(info)
    needs_compress = size > MAX_UPLOAD_BYTES

    if not needs_reencode and not needs_compress:
        return path, info

    out = path.with_name(path.stem + "_enc.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(path),
        "-c:v", "libx264", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
    ]
    if needs_compress:
        # Size-targeted: scale to 720p max and target 45MB for headroom
        target_bytes = 45 * 1024 * 1024
        duration = info.get("duration") or 60
        target_bitrate = int((target_bytes * 8) / duration)
        cmd += [
            "-b:v", str(target_bitrate),
            "-maxrate", str(target_bitrate),
            "-bufsize", str(target_bitrate // 2),
            "-vf", "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease,setsar=1",
        ]
    else:
        # Quality-targeted: original resolution, CRF 23
        cmd += ["-crf", "23", "-vf", "setsar=1"]
    cmd.append(str(out))

    subprocess.run(cmd, capture_output=True, timeout=600, creationflags=_NO_WINDOW)

    if out.exists() and out.stat().st_size > 0:
        new_info = _probe_video(out) or info
        if not needs_compress or out.stat().st_size < MAX_UPLOAD_BYTES:
            return out, new_info
        # Re-encode didn't get us under the limit — still return it, caller decides
        return out, new_info

    return path, info


def _collect_files(download_dir: str) -> list[Path]:
    """Collect all media files from a download directory."""
    files = []
    for f in sorted(Path(download_dir).iterdir()):
        if _is_image(f) or _is_video(f):
            files.append(f)
    return files


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

    # gallery-dl may still create subdirs — collect from all of them
    files = _collect_files(download_dir)
    for sub in Path(download_dir).iterdir():
        if sub.is_dir():
            files.extend(_collect_files(str(sub)))
    return files


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
        # Prefer H.264 (avc1) explicitly — iOS Telegram can't decode AV1 or VP9
        "format": (
            "bv*[vcodec^=avc1]+ba[acodec^=mp4a]"
            "/bv*[vcodec^=avc1]+ba"
            "/b[vcodec^=avc1]"
            "/b[ext=mp4]"
            "/b"
        ),
        # Move moov atom to front of file so Telegram can stream inline
        "postprocessor_args": {"ffmpeg": ["-movflags", "+faststart"]},
        # Don't download overly massive files — we'll compress if needed
        "max_filesize": MAX_UPLOAD_BYTES * 3,
    }

    # Use cookies if available (needed for Instagram stories, private content)
    if os.path.isfile(COOKIES_FILE):
        ydl_opts["cookiefile"] = COOKIES_FILE

    result = ExtractionResult(platform=platform)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if info is None:
            return result

        # Extract caption and thumbnail from metadata
        result.caption = (
            info.get("description")
            or info.get("title")
            or info.get("fulltitle")
        )
        result.thumbnail = info.get("thumbnail")
        # Keep post captions short — just enough context, not the whole essay
        if result.caption and len(result.caption) > 200:
            result.caption = result.caption[:200] + "..."

        # Collect downloaded files
        files = _collect_files(download_dir)

        if not files:
            # Sometimes yt-dlp puts files in a subdirectory
            for sub in Path(download_dir).iterdir():
                if sub.is_dir():
                    files.extend(_collect_files(str(sub)))

        for f in files[:10]:  # Telegram album max is 10
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

    except Exception:
        # yt-dlp failed — will try gallery-dl fallback below
        import logging as _log
        _log.getLogger(__name__).exception("yt-dlp extraction failed for %s", url)

    # Fallback to gallery-dl if yt-dlp got nothing (e.g. image-only tweets)
    if not result.items:
        try:
            fallback_files = _gallery_dl_fallback(url, download_dir)
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
