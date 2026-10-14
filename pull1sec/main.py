"""HTTP layer: JSON API plus the single-page front end."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import SUPPORTED_COOKIE_BROWSERS, settings
from .downloader import AUDIO_CODECS, probe, run_download
from .errors import (
    Pull1secError,
    JobNotFoundError,
    JobNotReadyError,
    MediaUnavailableError,
    TooManyJobsError,
)
from .jobs import JobManager, JobStatus
from .models import (
    DownloadRequest,
    DownloadResponse,
    ErrorResponse,
    JobView,
    MediaInfo,
    MetaResponse,
    ProbeRequest,
    ProbeResponse,
)
from .utils import InvalidURLError, guard_url, sanitize_filename

log = logging.getLogger("pull1sec")

STATIC_DIR = Path(__file__).parent / "static"
THUMBNAIL_TIMEOUT = 12.0
THUMBNAIL_MAX_BYTES = 8 * 1024 * 1024
MAX_ACTIVE_JOBS = 60


def _yt_dlp_version() -> str:
    try:
        from yt_dlp.version import __version__ as yt_dlp_version

        return yt_dlp_version
    except Exception:  # noqa: BLE001
        return "unknown"

manager = JobManager(
    download_dir=settings.download_dir,
    max_concurrent=settings.max_concurrent,
    job_ttl_seconds=settings.job_ttl_seconds,
)
manager.set_runner(lambda job: run_download(job, settings=settings))


async def _sweeper() -> None:
    interval = min(300, max(60, settings.job_ttl_seconds // 4))
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(manager.sweep)
        except Exception:  # noqa: BLE001
            log.exception("background sweep failed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.ensure_dirs()
    task = asyncio.create_task(_sweeper())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Pull1sec",
    version=__version__,
    description="Paste a social media URL, get the video.",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

api = APIRouter(prefix="/api")


# ------------------------------------------------------------------- errors


@app.exception_handler(Pull1secError)
async def _pull1sec_error_handler(_: Request, exc: Pull1secError) -> JSONResponse:
    body = ErrorResponse(error={"code": exc.code, "message": exc.message})  # type: ignore[arg-type]
    return JSONResponse(status_code=exc.status_code, content=body.model_dump())


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    message = "That request was not valid."
    for error in exc.errors():
        if error.get("type") == "string_too_short" or "url" in (error.get("loc") or ()):
            message = "Enter a URL."
            break
    body = ErrorResponse(error={"code": "invalid_request", "message": message})  # type: ignore[arg-type]
    return JSONResponse(status_code=422, content=body.model_dump())


# --------------------------------------------------------------------- meta


@api.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "version": __version__,
        "yt_dlp": _yt_dlp_version(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
    }


@api.get("/meta", response_model=MetaResponse)
async def meta() -> MetaResponse:
    return MetaResponse(
        name="Pull1sec",
        version=__version__,
        max_concurrent=settings.max_concurrent,
        job_ttl_seconds=settings.job_ttl_seconds,
        max_filesize_mb=settings.max_filesize_mb,
        cookie_browsers=list(SUPPORTED_COOKIE_BROWSERS),
        audio_formats=list(AUDIO_CODECS[:4]),
    )


# --------------------------------------------------------------------- probe


@api.post("/probe", response_model=ProbeResponse)
async def probe_endpoint(payload: ProbeRequest) -> ProbeResponse:
    try:
        url = guard_url(payload.url, allow_private_hosts=settings.allow_private_hosts)
    except InvalidURLError as exc:
        raise MediaUnavailableError(str(exc), code="invalid_url") from exc

    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(
                probe,
                url,
                settings=settings,
                cookies_from_browser=payload.cookies_from_browser,
            ),
            timeout=settings.probe_timeout + 15,
        )
    except asyncio.TimeoutError as exc:
        raise MediaUnavailableError(
            "The site took too long to respond. Try again.",
            code="timeout",
        ) from exc

    return ProbeResponse(media=MediaInfo(**info))


# ------------------------------------------------------------------ download


@api.post("/download", response_model=DownloadResponse)
async def download_endpoint(payload: DownloadRequest) -> DownloadResponse:
    try:
        url = guard_url(payload.url, allow_private_hosts=settings.allow_private_hosts)
    except InvalidURLError as exc:
        raise MediaUnavailableError(str(exc), code="invalid_url") from exc

    active = sum(1 for job in manager.all() if not job.status.is_terminal)
    if active >= MAX_ACTIVE_JOBS:
        raise TooManyJobsError("Too many downloads in progress. Wait for one to finish.")

    job = manager.create(
        url=url,
        mode=payload.mode,
        options={
            "mode": payload.mode,
            "height": payload.height,
            "audio_format": payload.audio_format,
            "cookies_from_browser": payload.cookies_from_browser,
        },
    )
    manager.start(job)
    return DownloadResponse(job=JobView(**job.snapshot()))


@api.get("/jobs", response_model=list[JobView])
async def list_jobs(limit: int = Query(default=25, ge=1, le=100)) -> list[JobView]:
    jobs = manager.all()[:limit]
    return [JobView(**job.snapshot()) for job in jobs]


@api.get("/jobs/{job_id}", response_model=JobView)
async def get_job(job_id: str) -> JobView:
    job = manager.get(job_id)
    if job is None:
        raise JobNotFoundError("That download no longer exists.")
    return JobView(**job.snapshot())


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@api.get("/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    job = manager.get(job_id)
    if job is None:
        raise JobNotFoundError("That download no longer exists.")

    async def stream() -> AsyncIterator[str]:
        try:
            async for event in job.stream():
                if event.get("type") == "heartbeat":
                    yield ": ping\n\n"
                    continue
                yield _sse(event.get("type", "job"), event.get("job", {}))
        except asyncio.CancelledError:
            raise

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@api.post("/jobs/{job_id}/cancel", response_model=JobView)
async def cancel_job(job_id: str) -> JobView:
    job = manager.get(job_id)
    if job is None:
        raise JobNotFoundError("That download no longer exists.")
    manager.cancel(job)
    return JobView(**job.snapshot())


@api.delete("/jobs/{job_id}")
async def delete_job(job_id: str) -> dict[str, bool]:
    if not manager.discard(job_id):
        raise JobNotFoundError("That download no longer exists.")
    return {"ok": True}


@api.get("/jobs/{job_id}/file")
async def job_file(job_id: str) -> FileResponse:
    job = manager.get(job_id)
    if job is None:
        raise JobNotFoundError("That download no longer exists.")
    if job.status is not JobStatus.completed or job.file_path is None:
        raise JobNotReadyError("This download is not ready yet.")
    if not job.file_path.exists():
        raise JobNotReadyError("The file has expired and was cleaned up.")

    filename = sanitize_filename(job.filename or f"pull1sec-{job.id}")
    return FileResponse(
        path=job.file_path,
        media_type=job.mimetype or "application/octet-stream",
        filename=filename,
    )


# --------------------------------------------------------------- thumbnails


@api.get("/thumbnail")
async def thumbnail(url: str = Query(min_length=8, max_length=2048)) -> Response:
    """Small proxy so CDN thumbnails that require a referer still render."""
    try:
        target = guard_url(url, allow_private_hosts=settings.allow_private_hosts)
    except InvalidURLError as exc:
        raise MediaUnavailableError(str(exc), code="invalid_url") from exc

    if urlsplit(target).scheme != "https":
        raise MediaUnavailableError("Only https thumbnails can be proxied.", code="invalid_url")

    def fetch() -> tuple[bytes, str]:
        import urllib.request

        request = urllib.request.Request(
            target,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Pull1sec/1.0)",
                "Accept": "image/*,*/*;q=0.8",
                "Referer": f"{urlsplit(target).scheme}://{urlsplit(target).netloc}/",
            },
        )
        with urllib.request.urlopen(request, timeout=THUMBNAIL_TIMEOUT) as response:  # noqa: S310
            content_type = response.headers.get_content_type()
            data = response.read(THUMBNAIL_MAX_BYTES + 1)
        return data, content_type

    try:
        data, content_type = await asyncio.to_thread(fetch)
    except Exception as exc:  # noqa: BLE001
        raise MediaUnavailableError("That thumbnail could not be loaded.", code="thumbnail_failed") from exc

    if not content_type.startswith("image/") or len(data) > THUMBNAIL_MAX_BYTES:
        raise MediaUnavailableError("That thumbnail could not be loaded.", code="thumbnail_failed")

    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


app.include_router(api)

# The SPA is mounted last so it never shadows /api routes.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
