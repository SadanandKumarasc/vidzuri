"""ffmpeg wrappers: reformat a downloaded section into the final clip, and
sweep old clips out of storage.
"""

import logging
import subprocess
import time
import uuid
from pathlib import Path

from app.config import RETENTION_HOURS, STORAGE_DIR

logger = logging.getLogger("clipper")

VERTICAL_FILTER = (
    "scale=1080:1920:force_original_aspect_ratio=increase,"
    "crop=1080:1920,setsar=1,format=yuv420p"
)

MIN_SOURCE_DURATION = 1.0  # seconds -- below this, the download is treated as corrupt


def _validate_source(src: Path) -> None:
    """Catch a truncated/corrupt download early with a clear error, instead
    of letting ffmpeg fail deep into an encode with an opaque log dump.

    Duration alone isn't enough -- a truncated download can still carry
    correct-looking container/duration metadata while the actual video
    payload is empty. Confirm the video stream actually has packets too.
    """
    duration_result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
        capture_output=True,
        text=True,
    )
    duration = None
    if duration_result.returncode == 0:
        try:
            duration = float(duration_result.stdout.strip())
        except ValueError:
            duration = None

    packets_result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
            "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(src),
        ],
        capture_output=True,
        text=True,
    )
    packet_count = None
    if packets_result.returncode == 0:
        try:
            packet_count = int(packets_result.stdout.strip())
        except ValueError:
            packet_count = None

    if duration is None or duration < MIN_SOURCE_DURATION or not packet_count:
        logger.error(
            "Source validation failed for %s: duration=%s, video_packets=%s, dur_stderr=%s, pkt_stderr=%s",
            src, duration, packet_count, duration_result.stderr[-500:], packets_result.stderr[-500:],
        )
        raise RuntimeError(
            "The video download came back incomplete (this happens occasionally with YouTube). Please try again."
        )


def finalize_clip(src: Path, job_id: str, index: int, vertical: bool) -> Path:
    """Re-encode the downloaded section into the final delivered clip
    (optionally reformatted to 9:16), and write it into storage.
    """
    _validate_source(src)

    out_path = STORAGE_DIR / f"{job_id}-{index}-{uuid.uuid4().hex[:6]}.mp4"

    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if vertical:
        cmd += ["-vf", VERTICAL_FILTER]
    cmd += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg failed for job %s (src=%s): %s", job_id, src, result.stderr)
        raise RuntimeError("Rendering this clip failed. Please try again -- if it keeps happening, try a different timestamp.")

    return out_path


def cleanup_expired_clips() -> int:
    """Delete clips older than RETENTION_HOURS. Returns count removed."""
    cutoff = time.time() - RETENTION_HOURS * 3600
    removed = 0
    for f in STORAGE_DIR.glob("*.mp4"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed
