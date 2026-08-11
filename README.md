# Vidzuri

Paste a YouTube URL, get back a 10-15 second clip — either at a timestamp you
pick, or auto-picked by Claude from the video's transcript. Optional 9:16
vertical reformat for Shorts/Reels/TikTok.

It never downloads a full source video: yt-dlp fetches only the requested
seconds via range requests, and auto mode reads YouTube's own captions
before falling back to local transcription.

## How it works

1. **Manual mode**: you give a start time + duration (10-15s) → that section
   is downloaded and re-encoded.
2. **Auto mode**: the app pulls the video's captions (or transcribes the
   audio locally with whisper if none exist) → sends the transcript to
   Claude, which picks 1-4 clip-worthy moments → each is downloaded and
   re-encoded.

## Local setup

Requires Python 3.11+ and `ffmpeg` on your PATH.

```bash
python -m venv venv
venv/Scripts/activate   # (Windows) — or `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env    # fill in ANTHROPIC_API_KEY for auto mode
uvicorn app.main:app --reload
```

Open http://localhost:8000.

Manual mode works without any API key. Auto mode needs `ANTHROPIC_API_KEY`
set (get one at https://console.anthropic.com/).

## Run with Docker

```bash
docker build -t shortclip .
docker run -p 8000:8000 --env-file .env -v shortclip-data:/data shortclip
```

## Deploy

Built as a single Dockerized service — deploy to any host that runs
containers with a writable disk and no hard execution-time limit. **Vercel
and Netlify will not work** (no ffmpeg, execution-time caps, no persistent
disk).

**Railway** (recommended):
1. `railway login`, then `railway init` in this folder (or connect the repo
   in the Railway dashboard).
2. Set the `ANTHROPIC_API_KEY` environment variable in the Railway project
   settings.
3. `railway up` (or push to the connected repo). `railway.json` is already
   configured to build from the Dockerfile.
4. Attach a volume mounted at `/data` in the Railway dashboard so clips
   survive restarts (optional — clips are ephemeral and auto-delete after
   `CLIP_RETENTION_HOURS` anyway).

**Render** works the same way: create a new "Web Service" from this repo,
it will detect the Dockerfile, set `ANTHROPIC_API_KEY` in the environment
tab, and add a persistent disk mounted at `/data` if you want.

## Configuration

All via environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | required for auto-highlight mode |
| `CLIP_MODEL` | `claude-haiku-4-5-20251001` | model used to pick highlights |
| `CLIP_STORAGE_DIR` | `./data/clips` | where finished clips are written |
| `CLIP_RETENTION_HOURS` | `48` | clips older than this are swept hourly |
| `PORT` | `8000` | server port |

## Notes

- This tool processes whatever URL you give it — only clip videos you have
  the rights to use or that fall under fair use. It doesn't enforce that;
  that's on you.
- yt-dlp occasionally needs bumping (`pip install -U yt-dlp`) when YouTube
  changes its site internals.
- `faster-whisper` downloads its model weights (~250MB for the "small"
  model) on first use; the first no-captions video will be slower.
