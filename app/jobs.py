"""In-memory job store + background orchestration for both clip modes."""

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from app import clipper, highlights, transcribe, youtube
from app.config import MAX_CLIP_SECONDS, MIN_CLIP_SECONDS, WORK_DIR

logger = logging.getLogger("jobs")

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, dict] = {}

# Each retry re-downloads from scratch with a different strategy (see
# _download_and_render): range-limited vs. full download, proxied vs.
# direct. Different videos have needed different combinations to get a
# clean, decodable download, so all four get a shot before giving up.
MAX_CLIP_ATTEMPTS = 4


def create_job(payload: dict) -> str:
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "message": "Queued",
        "error": None,
        "clips": [],
        "created_at": time.time(),
    }
    _executor.submit(_run_job, job_id, payload)
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    return _jobs.get(job_id)


def _set(job_id: str, **kwargs):
    _jobs[job_id].update(kwargs)


def _run_job(job_id: str, payload: dict) -> None:
    job_work_dir = WORK_DIR / job_id
    try:
        url = payload["url"]
        vertical = bool(payload.get("vertical", False))

        _set(job_id, status="processing", message="Fetching video info")
        info = youtube.get_video_info(url)
        duration = info["duration"] or 0

        if payload["mode"] == "manual":
            windows = _manual_window(payload, info, duration)
        else:
            windows = _auto_windows(job_id, url, duration, job_work_dir)

        clips = []
        for i, w in enumerate(windows, start=1):
            out_path = _download_and_render(job_id, url, w, i, len(windows), vertical, job_work_dir)
            clips.append(
                {
                    "title": w.get("title", info["title"]),
                    "reason": w.get("reason", ""),
                    "start": w["start"],
                    "end": w["end"],
                    "filename": out_path.name,
                }
            )

        _set(job_id, status="done", message="Done", clips=clips)
    except Exception as exc:  # noqa: BLE001 -- surfaced to the UI, not swallowed
        _set(job_id, status="error", message=str(exc), error=str(exc))
    finally:
        _cleanup_dir(job_work_dir)


def _download_and_render(
    job_id: str, url: str, w: dict, i: int, total: int, vertical: bool, job_work_dir: Path
) -> Path:
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_CLIP_ATTEMPTS + 1):
        suffix = f" (retry {attempt - 1}/{MAX_CLIP_ATTEMPTS - 1})" if attempt > 1 else ""
        # Attempts 1-2: yt-dlp's byte-range section download, which is fast
        # (fetches only the needed window) but has been traced as the
        # actual source of an undecodable-track failure for certain videos
        # -- confirmed by it persisting identically with and without a
        # proxy. force_keyframes_at_cuts gives a frame-exact cut via a local
        # re-encode; attempt 2 drops it in case that step is implicated too.
        # Attempts 3-4: sidestep range-downloading entirely -- fetch the
        # whole video and trim locally in finalize_clip. That's a bigger
        # transfer than a 15s range fetch: the proxy tunnel has timed out on
        # it (502) for some videos, while going direct has hit YouTube's
        # bot-check wall for others (cookies alone don't always clear it on
        # a datacenter IP) -- so attempt 3 tries proxied, attempt 4 direct.
        use_ranges = attempt <= 2
        force_keyframes = attempt == 1
        use_proxy = attempt != MAX_CLIP_ATTEMPTS
        try:
            _set(job_id, message=f"Downloading clip {i}/{total}{suffix}")
            src = youtube.download_section(
                url,
                w["start"],
                w["end"],
                job_work_dir,
                force_keyframes=force_keyframes,
                use_ranges=use_ranges,
                use_proxy=use_proxy,
            )
            _set(job_id, message=f"Rendering clip {i}/{total}{suffix}")
            trim = None if use_ranges else (w["start"], w["end"] - w["start"])
            return clipper.finalize_clip(src, job_id, i, vertical, trim=trim)
        except Exception as exc:  # noqa: BLE001 -- any download/render failure is retryable
            last_exc = exc
            logger.warning("Clip %s/%s attempt %s/%s failed: %s", i, total, attempt, MAX_CLIP_ATTEMPTS, exc)
    raise RuntimeError(
        "Couldn't generate this clip after a few tries. Please try again -- if it keeps happening, try a different timestamp."
    ) from last_exc


def _manual_window(payload: dict, info: dict, duration: float) -> list[dict]:
    start = youtube.parse_timestamp(payload["start"])
    length = float(payload.get("duration", MAX_CLIP_SECONDS))
    length = max(MIN_CLIP_SECONDS, min(MAX_CLIP_SECONDS, length))
    end = start + length
    if duration:
        if start >= duration:
            raise ValueError("Start time is past the end of the video")
        end = min(end, duration)
    return [{"start": start, "end": end, "title": info["title"]}]


def _auto_windows(job_id: str, url: str, duration: float, job_work_dir: Path) -> list[dict]:
    _set(job_id, message="Fetching captions")
    transcript = youtube.get_captions(url)

    if not transcript:
        _set(job_id, message="No captions available, transcribing audio (this can take a minute)")
        audio_path = youtube.download_audio(url, job_work_dir)
        transcript = transcribe.transcribe_audio(audio_path)
        audio_path.unlink(missing_ok=True)

    if not transcript:
        raise RuntimeError("Could not obtain a transcript for this video")

    _set(job_id, message="Picking highlight moments")
    return highlights.pick_highlights(transcript, duration)


def _cleanup_dir(d: Path) -> None:
    if not d.exists():
        return
    for f in d.glob("*"):
        f.unlink(missing_ok=True)
    d.rmdir()
