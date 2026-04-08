from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp

from config import TEMP_DIR, MAX_UPLOAD_BYTES, COOKIES_FILE


@dataclass
class MediaItem:
    file_path: Path
    media_type: str  # "photo" or "video"


@dataclass
class ExtractionResult:
    items: list[MediaItem] = field(default_factory=list)
    caption: str | None = None
    platform: str = "Unknown"


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".avi"}


def _compress_video(path: Path) -> Path:
    """Re-encode a video with ffmpeg to fit under Telegram's 50MB limit."""
    out = path.with_name(path.stem + "_compressed.mp4")
    # Target ~45MB to leave headroom
    target_bytes = 45 * 1024 * 1024
    # Get duration via ffprobe
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    duration = float(probe.stdout.strip() or "60")
    target_bitrate = int((target_bytes * 8) / duration)

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path),
         "-b:v", str(target_bitrate), "-maxrate", str(target_bitrate),
         "-bufsize", str(target_bitrate // 2),
         "-vf", "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease",
         "-c:a", "aac", "-b:a", "128k",
         str(out)],
        capture_output=True,
    )
    if out.exists() and out.stat().st_size < MAX_UPLOAD_BYTES:
        return out
    # Compression wasn't enough — caller should handle fallback
    if out.exists():
        out.unlink()
    return path


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

    subprocess.run(cmd, capture_output=True, timeout=60)

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
        # Prefer mp4 for video
        "merge_output_format": "mp4",
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
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

        # Extract caption from metadata
        result.caption = (
            info.get("description")
            or info.get("title")
            or info.get("fulltitle")
        )
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
                # Check size and compress if needed
                if f.stat().st_size > MAX_UPLOAD_BYTES:
                    f = _compress_video(f)
                result.items.append(MediaItem(file_path=f, media_type="video"))
            elif _is_image(f):
                result.items.append(MediaItem(file_path=f, media_type="photo"))

    except Exception:
        # yt-dlp failed — will try gallery-dl fallback below
        pass

    # Fallback to gallery-dl if yt-dlp got nothing (e.g. image-only tweets)
    if not result.items:
        try:
            fallback_files = _gallery_dl_fallback(url, download_dir)
            for f in fallback_files[:10]:
                if _is_video(f):
                    if f.stat().st_size > MAX_UPLOAD_BYTES:
                        f = _compress_video(f)
                    result.items.append(MediaItem(file_path=f, media_type="video"))
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
        # Also remove compressed variants
        compressed = item.file_path.with_name(item.file_path.stem + "_compressed.mp4")
        if compressed.exists():
            compressed.unlink(missing_ok=True)
    for d in dirs_to_remove:
        shutil.rmtree(d, ignore_errors=True)
