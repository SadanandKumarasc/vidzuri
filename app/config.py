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

# Optional: route yt-dlp traffic through a proxy (e.g. a residential proxy
# provider) to work around YouTube's bot-check on datacenter host IPs.
# Format: http://user:pass@host:port -- leave unset to make direct requests.
YTDLP_PROXY = os.environ.get("YTDLP_PROXY", "")

# Optional: authenticate yt-dlp as a logged-in YouTube session. A trusted
# session is far less likely to get served throttled/degraded video streams
# than an anonymous proxy request. Paste the full contents of a Netscape-
# format cookies.txt file (exported from a browser logged into YouTube) --
# it's written to disk once at startup and passed to yt-dlp as a cookiefile.
YTDLP_COOKIES_CONTENT = os.environ.get("YTDLP_COOKIES_CONTENT", "")
YTDLP_COOKIES_FILE = ""
if YTDLP_COOKIES_CONTENT:
    _cookies_path = STORAGE_DIR / "cookies.txt"
    _cookies_path.write_text(YTDLP_COOKIES_CONTENT, encoding="utf-8")
    YTDLP_COOKIES_FILE = str(_cookies_path)

# Optional: URL of a running bgutil-ytdlp-pot-provider HTTP server (see
# https://github.com/Brainicism/bgutil-ytdlp-pot-provider). Generates the
# PO (Proof-of-Origin) tokens YouTube now requires to trust a request as a
# real browser -- without one, YouTube either blocks non-browser clients
# outright or silently serves them degraded/corrupted video data, which is
# the failure this was added to fix. Leave unset to skip PO tokens.
YTDLP_POT_PROVIDER_URL = os.environ.get("YTDLP_POT_PROVIDER_URL", "")

MIN_CLIP_SECONDS = 10
MAX_CLIP_SECONDS = 15
AUTO_MODE_MAX_CLIPS = 4
