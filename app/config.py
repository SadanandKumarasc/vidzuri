import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLIP_MODEL = os.environ.get("CLIP_MODEL", "claude-haiku-4-5-20251001")

STORAGE_DIR = Path(os.environ.get("CLIP_STORAGE_DIR", "./data/clips")).resolve()
WORK_DIR = STORAGE_DIR / "_work"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
WORK_DIR.mkdir(parents=True, exist_ok=True)

RETENTION_HOURS = float(os.environ.get("CLIP_RETENTION_HOURS", "48"))

MIN_CLIP_SECONDS = 10
MAX_CLIP_SECONDS = 15
AUTO_MODE_MAX_CLIPS = 4
