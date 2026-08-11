"""yt-dlp wrappers: video info, captions, and range-limited downloads.

Deliberately never downloads a full video. Section downloads use yt-dlp's
download_ranges + force_keyframes_at_cuts so only the requested window is
fetched and the cut lands on an exact timestamp (re-encoded via ffmpeg
internally by yt-dlp, not just a keyframe-snapped copy).
"""

import logging
import re
import uuid
from pathlib import Path
from typing import Callable, Optional

import webvtt
import yt_dlp
from yt_dlp.utils import download_range_func

from app.config import WORK_DIR, YTDLP_COOKIES_FILE, YTDLP_PROXY

logger = logging.getLogger("youtube")


def _proxy_opts() -> dict:
    """Merge into any yt-dlp opts dict. Empty when YTDLP_PROXY is unset, so
    requests go out directly with no behavior change.
    """
    return {"proxy": YTDLP_PROXY} if YTDLP_PROXY else {}


def _cookie_opts() -> dict:
    """Merge into any yt-dlp opts dict. A trusted, logged-in session is much
    less likely to get served a throttled/degraded stream than an anonymous
    proxy request. Empty when YTDLP_COOKIES_FILE is unset.
    """
    return {"cookiefile": YTDLP_COOKIES_FILE} if YTDLP_COOKIES_FILE else {}

YOUTUBE_URL_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})"
)

# Cloud-host IPs occasionally hit YouTube's "Sign in to confirm you're not a
# bot" wall -- and it's intermittent per-request, not just per-video. Each
# player client hits a different backend endpoint with different bot-check
# enforcement, so cycling through a few on that specific error is the
# standard mitigation (short of using login cookies or a residential proxy).
_CLIENT_FALLBACKS = [
    ["android", "web"],
    ["ios", "web"],
    ["tv_embedded", "web"],
]

_BOT_CHECK_MARKERS = ("sign in to confirm", "not a bot")


class InvalidYouTubeURL(ValueError):
    pass


def extract_video_id(url: str) -> str:
    match = YOUTUBE_URL_RE.search(url)
    if not match:
        raise InvalidYouTubeURL(f"Not a recognizable YouTube URL: {url}")
    return match.group(1)


def _is_bot_check_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _BOT_CHECK_MARKERS)


def _run_with_client_fallback(attempt: Callable[[dict], object]) -> object:
    """Call attempt(extractor_args) across a few player-client combos,
    retrying only on YouTube's bot-check wall.
    """
    last_exc: Optional[Exception] = None
    for clients in _CLIENT_FALLBACKS:
        try:
            return attempt({"youtube": {"player_client": clients}})
        except yt_dlp.utils.DownloadError as e:
            last_exc = e
            if not _is_bot_check_error(e):
                raise
            logger.warning("yt-dlp bot-check hit with player_client=%s, trying next client", clients)
    raise RuntimeError(
        "YouTube is temporarily blocking this server's requests for this video. Please try again in a few minutes."
    ) from last_exc


def get_video_info(url: str) -> dict:
    """Metadata only -- no download."""

    def _attempt(extractor_args: dict) -> dict:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extractor_args": extractor_args,
            **_proxy_opts(),
            **_cookie_opts(),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    info = _run_with_client_fallback(_attempt)
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

    def _attempt(extractor_args: dict) -> None:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en", "en-US", "en-orig"],
            "subtitlesformat": "vtt",
            "outtmpl": outtmpl,
            "extractor_args": extractor_args,
            **_proxy_opts(),
            **_cookie_opts(),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    try:
        _run_with_client_fallback(_attempt)

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


def download_section(url: str, start: float, end: float, out_dir: Path, force_keyframes: bool = True) -> Path:
    """Download only [start, end] seconds of the video, re-encoded on the cut
    boundaries. Returns the path to the downloaded file.

    force_keyframes_at_cuts makes yt-dlp re-encode the downloaded fragment
    locally to land the cut on an exact timestamp. That local re-encode has
    been observed to occasionally produce an undecodable video track when
    the source download came in over a proxy -- ffprobe still reports valid
    duration/packet-count metadata, but ffmpeg later decodes zero frames.
    Callers that hit this can retry with force_keyframes=False, which skips
    that internal re-encode (a plain stream copy of the keyframe-bound
    range) at the cost of the clip possibly starting a couple seconds early.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"src-{uuid.uuid4().hex[:8]}"
    outtmpl = str(out_dir / f"{stem}.%(ext)s")

    def _attempt(extractor_args: dict) -> None:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/best",
            "download_ranges": download_range_func(None, [(start, end)]),
            "force_keyframes_at_cuts": force_keyframes,
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "extractor_args": extractor_args,
            **_proxy_opts(),
            **_cookie_opts(),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    _run_with_client_fallback(_attempt)

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

    def _attempt(extractor_args: dict) -> None:
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
            "extractor_args": extractor_args,
            **_proxy_opts(),
            **_cookie_opts(),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    _run_with_client_fallback(_attempt)

    matches = list(out_dir.glob(f"{stem}.*"))
    if not matches:
        raise RuntimeError("yt-dlp did not produce an audio file")
    return matches[0]
