import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator
from starlette.requests import Request

from app import jobs
from app.clipper import cleanup_expired_clips
from app.config import MAX_CLIP_SECONDS, MIN_CLIP_SECONDS, STORAGE_DIR
from app.youtube import InvalidYouTubeURL, extract_video_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clipper")

CLEANUP_INTERVAL_SECONDS = 3600


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()


app = FastAPI(title="Vidzuri", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


class JobRequest(BaseModel):
    url: str
    mode: str  # "manual" | "auto"
    start: str | float | None = None
    duration: float = MAX_CLIP_SECONDS
    vertical: bool = False

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("manual", "auto"):
            raise ValueError("mode must be 'manual' or 'auto'")
        return v


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "min_seconds": MIN_CLIP_SECONDS, "max_seconds": MAX_CLIP_SECONDS},
    )


@app.post("/api/jobs")
async def submit_job(req: JobRequest):
    try:
        extract_video_id(req.url)
    except InvalidYouTubeURL as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.mode == "manual" and req.start in (None, ""):
        raise HTTPException(status_code=400, detail="start time is required in manual mode")

    job_id = jobs.create_job(req.model_dump())
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/clips/{filename}")
async def get_clip(filename: str):
    path = STORAGE_DIR / filename
    if ".." in filename or not path.is_file():
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(path, media_type="video/mp4", filename=filename)


async def _cleanup_loop():
    while True:
        try:
            removed = cleanup_expired_clips()
            if removed:
                logger.info("Cleanup: removed %d expired clip(s)", removed)
        except Exception:
            logger.exception("Cleanup sweep failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
