"""Ask Claude to pick the best short-clip-worthy moments from a transcript."""

import anthropic

from app.config import ANTHROPIC_API_KEY, AUTO_MODE_MAX_CLIPS, CLIP_MODEL, MAX_CLIP_SECONDS, MIN_CLIP_SECONDS

_PICK_HIGHLIGHTS_TOOL = {
    "name": "pick_highlights",
    "description": "Return the chosen highlight windows for short-clip creation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "highlights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "number", "description": "Start time in seconds"},
                        "end": {"type": "number", "description": "End time in seconds"},
                        "title": {"type": "string", "description": "Short punchy hook/title for the clip, <= 60 chars"},
                        "reason": {"type": "string", "description": "One sentence on why this moment is clip-worthy"},
                    },
                    "required": ["start", "end", "title", "reason"],
                },
            }
        },
        "required": ["highlights"],
    },
}


class NoAPIKeyError(RuntimeError):
    pass


def pick_highlights(transcript: list[dict], video_duration: float) -> list[dict]:
    if not ANTHROPIC_API_KEY:
        raise NoAPIKeyError("ANTHROPIC_API_KEY is not configured")

    transcript_text = "\n".join(
        f"[{seg['start']:.1f}-{seg['end']:.1f}] {seg['text']}" for seg in transcript
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=CLIP_MODEL,
        max_tokens=2000,
        tools=[_PICK_HIGHLIGHTS_TOOL],
        tool_choice={"type": "tool", "name": "pick_highlights"},
        messages=[
            {
                "role": "user",
                "content": (
                    "You're picking the best moments from a video transcript to turn into "
                    "short vertical clips (like YouTube Shorts / TikTok / Reels).\n\n"
                    f"The video is {video_duration:.0f} seconds long. Pick between 1 and "
                    f"{AUTO_MODE_MAX_CLIPS} non-overlapping moments that would work as standalone "
                    f"clips: a hook, a punchline, a surprising claim, a complete thought. "
                    f"Each clip's (end - start) MUST be between {MIN_CLIP_SECONDS} and "
                    f"{MAX_CLIP_SECONDS} seconds, and start/end must fall within the transcript's "
                    "time range. Prefer fewer, stronger clips over padding out the count.\n\n"
                    f"Transcript (format is [start-end] text):\n{transcript_text}"
                ),
            }
        ],
    )

    for block in message.content:
        if block.type == "tool_use" and block.name == "pick_highlights":
            highlights = block.input.get("highlights", [])
            return _validate(highlights, video_duration)

    raise RuntimeError("Claude did not return a pick_highlights tool call")


def _validate(highlights: list[dict], video_duration: float) -> list[dict]:
    valid = []
    for h in highlights:
        start, end = float(h["start"]), float(h["end"])
        duration = end - start
        if start < 0 or end > video_duration or start >= end:
            continue
        if duration < MIN_CLIP_SECONDS - 1 or duration > MAX_CLIP_SECONDS + 1:
            continue
        valid.append({"start": start, "end": end, "title": h["title"], "reason": h.get("reason", "")})
    if not valid:
        raise RuntimeError("Claude's highlight picks failed validation (bad timestamps/durations)")
    return valid[:AUTO_MODE_MAX_CLIPS]
