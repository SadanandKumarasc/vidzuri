"""Local whisper transcription -- fallback for videos with no YouTube captions."""

from pathlib import Path

from faster_whisper import WhisperModel

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        # "small" balances accuracy and speed/memory on a modest CPU host.
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    return _model


def transcribe_audio(audio_path: Path) -> list[dict]:
    """Return [{start, end, text}] in seconds."""
    model = _get_model()
    segments, _info = model.transcribe(str(audio_path), vad_filter=True)
    return [
        {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
        for seg in segments
    ]
