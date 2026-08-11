"""yt-dlp wrappers: video info, captions, and range-limited downloads.

Deliberately never downloads a full video. Section downloads use yt-dlp's
download_ranges + force_keyframes_at_cuts so only the requested window is
fetched and the cut lands on an exact timestamp (re-encoded via ffmpeg
internally by yt-dlp, not just a keyframe-snapped copy).
"""

import re
import uuid
from pathlib import Path
from typing import Optional

import webvtt
import yt_dlp
from yt_dlp.utils import download_range_func

from app.config import WORK_DIR

YOUTUBE_URL_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})"
)


class InvalidYouTubeURL(ValueError):
    pass


def extract_video_id(url: str) -> str:
    match = YOUTUBE_URL_RE.search(url)
    if not match:
        raise InvalidYouTubeURL(f"Not a recognizable YouTube URL: {url}")
    return match.group(1)


def get_video_info(url: str) -> dict:
    """Metadata only -- no download."""
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "id": info["id"],
        "title": info.get("title", "Untitled"),
        "duration": info.get("duration") or 0,
        "thumbnail": info.get("thumbnail"),
    }


def get_captions(url: str) -> Optional[list[dict]]:
    """Return [{start, end, text}] in seconds, preferring human captions over
    auto-generated ones. Returns None if no English captions are available.
    """
    job_dir = WORK_DIR / f"captions-{uuid.uuid4().hex[:8]}"
    job_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(job_dir / "%(id)s")

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-orig"],
        "subtitlesformat": "vtt",
        "outtmpl": outtmpl,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        vtt_files = sorted(job_dir.glob("*.vtt"))
        if not vtt_files:
            return None

        segments = []
        for caption in webvtt.read(str(vtt_files[0])):
            segments.append(
                {
                    "start": _timestamp_to_seconds(caption.start),
                    "end": _timestamp_to_seconds(caption.end),
                    "text": caption.text.replace("\n", " ").strip(),
                }
            )
        return segments or None
    except Exception:
        return None
    finally:
        for f in job_dir.glob("*"):
            f.unlink(missing_ok=True)
        job_dir.rmdir()


def _timestamp_to_seconds(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_timestamp(value: str | float) -> float:
    """Accept plain seconds ("95", 95.0) or "mm:ss" / "hh:mm:ss" strings."""
    if isinstance(value, (int, float)):
        return float(value)
    value = value.strip()
    if ":" not in value:
        return float(value)
    parts = [float(p) for p in value.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def download_section(url: str, start: float, end: float, out_dir: Path) -> Path:
    """Download only [start, end] seconds of the video, re-encoded on the cut
    boundaries. Returns the path to the downloaded file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"src-{uuid.uuid4().hex[:8]}"
    outtmpl = str(out_dir / f"{stem}.%(ext)s")

    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/best",
        "download_ranges": download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    matches = list(out_dir.glob(f"{stem}.*"))
    if not matches:
        raise RuntimeError("yt-dlp did not produce an output file for the requested section")
    return matches[0]


def download_audio(url: str, out_dir: Path) -> Path:
    """Audio-only download, used as the whisper-transcription fallback when a
    video has no captions. Still avoids fetching the video stream.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"audio-{uuid.uuid4().hex[:8]}"
    outtmpl = str(out_dir / f"{stem}.%(ext)s")

    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "ba/b",
        "outtmpl": outtmpl,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    matches = list(out_dir.glob(f"{stem}.*"))
    if not matches:
        raise RuntimeError("yt-dlp did not produce an audio file")
    return matches[0]
