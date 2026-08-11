"""ffmpeg wrappers: reformat a downloaded section into the final clip, and
sweep old clips out of storage.
"""

import subprocess
import time
import uuid
from pathlib import Path

from app.config import RETENTION_HOURS, STORAGE_DIR

VERTICAL_FILTER = (
    "scale=1080:1920:force_original_aspect_ratio=increase,"
    "crop=1080:1920,setsar=1,format=yuv420p"
)


def finalize_clip(src: Path, job_id: str, index: int, vertical: bool) -> Path:
    """Re-encode the downloaded section into the final delivered clip
    (optionally reformatted to 9:16), and write it into storage.
    """
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
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-2000:]}")

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
