"""In-memory job registry with thread-safe progress fan-out.

Downloads run in worker threads (yt-dlp is synchronous); events are pushed back
onto the event loop so SSE subscribers can stream them without a broker.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Callable

PROGRESS_THROTTLE_SECONDS = 0.25
PROGRESS_THROTTLE_PERCENT = 0.5


class JobStatus(str, Enum):
    queued = "queued"
    downloading = "downloading"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL


TERMINAL = {JobStatus.completed, JobStatus.failed, JobStatus.canceled}
TERMINAL_VALUES = {status.value for status in TERMINAL}


@dataclass
class Job:
    """One download request and everything we know about its lifecycle."""

    id: str
    url: str
    mode: str
    status: JobStatus = JobStatus.queued

    # Media metadata (filled in by the downloader once yt-dlp reports it).
    title: str | None = None
    uploader: str | None = None
    platform: str | None = None
    thumbnail: str | None = None
    duration: float | None = None

    # Progress
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None
    message: str | None = None

    # Result
    file_path: Path | None = None
    filename: str | None = None
    filesize: int | None = None
    mimetype: str | None = None
    error: str | None = None
    error_code: str | None = None

    # Bookkeeping
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    #: Per-job download options handed to the runner (mode, height, codec…).
    options: dict[str, Any] = field(default_factory=dict)

    #: Set from the API thread; the yt-dlp progress hook polls it.
    cancel_requested: bool = False

    _subscribers: set["asyncio.Queue[dict[str, Any]]"] = field(default_factory=set, repr=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, repr=False)
    _last_publish: float = field(default=0.0, repr=False)
    _last_percent: float = field(default=-1.0, repr=False)

    # ------------------------------------------------------------------ views

    def snapshot(self) -> dict[str, Any]:
        """Plain dict matching ``models.JobView``."""
        return {
            "id": self.id,
            "url": self.url,
            "mode": self.mode,
            "status": self.status.value,
            "title": self.title,
            "uploader": self.uploader,
            "platform": self.platform,
            "thumbnail": self.thumbnail,
            "duration": self.duration,
            "percent": round(self.percent, 2),
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "speed": self.speed,
            "eta": self.eta,
            "filename": self.filename,
            "filesize": self.filesize,
            "mimetype": self.mimetype,
            "message": self.message,
            "error": self.error,
            "error_code": self.error_code,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "download_url": f"/api/jobs/{self.id}/file" if self.file_path else None,
        }

    # ------------------------------------------------------------- lifecycle

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def update(self, *, publish: bool = True, force: bool = False, **changes: Any) -> None:
        """Apply ``changes`` and (maybe) notify subscribers."""
        status_changed = changes.get("status") is not None and changes["status"] is not self.status
        message_changed = "message" in changes and changes["message"] != self.message
        for key, value in changes.items():
            setattr(self, key, value)
        self.updated_at = time.time()

        if not publish:
            return
        if not force and not status_changed and not message_changed and not self._should_publish_progress():
            return
        self._publish({"type": "job", "job": self.snapshot()})

    def _should_publish_progress(self) -> bool:
        now = time.time()
        percent = self.percent
        if now - self._last_publish >= PROGRESS_THROTTLE_SECONDS:
            self._last_publish = now
            self._last_percent = percent
            return True
        if abs(percent - self._last_percent) >= PROGRESS_THROTTLE_PERCENT:
            self._last_publish = now
            self._last_percent = percent
            return True
        return False

    def finish(
        self,
        status: JobStatus,
        *,
        error: str | None = None,
        error_code: str | None = None,
    ) -> None:
        if self.status.is_terminal:
            # Already settled; a late hook must not publish a second outcome.
            return
        changes: dict[str, Any] = {"status": status}
        if error is not None:
            changes["error"] = error
        if error_code is not None:
            changes["error_code"] = error_code
        if status is JobStatus.completed:
            changes["percent"] = 100.0
            changes["eta"] = 0
            changes["speed"] = None
        self.finished_at = time.time()
        self.update(force=True, **changes)
        self._publish({"type": status.value, "job": self.snapshot()})

    # ------------------------------------------------------------ pub/sub

    def _publish(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._fanout, event)
        except RuntimeError:
            # Loop shut down between the check and the call.
            pass

    def _fanout(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A slow client must not stall the download; it will be caught
                # up by the next snapshot / heartbeat.
                continue

    def subscribe(self) -> "asyncio.Queue[dict[str, Any]]":
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[dict[str, Any]]") -> None:
        self._subscribers.discard(queue)

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        """Yield job snapshots until the job reaches a terminal state.

        The loop stops as soon as a delivered snapshot is terminal, so the
        final state can never be missed between two queued events.
        """
        queue = self.subscribe()
        try:
            first = self.snapshot()
            yield {
                "type": first["status"] if self.status.is_terminal else "job",
                "job": first,
            }
            if self.status.is_terminal:
                return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    snapshot = self.snapshot()
                    if self.status.is_terminal:
                        yield {"type": snapshot["status"], "job": snapshot}
                        return
                    yield {"type": "heartbeat", "job": snapshot}
                    continue

                job_payload = event.get("job") or {}
                status = job_payload.get("status")
                if status in TERMINAL_VALUES:
                    # Guarantee a terminal-named event before closing.
                    if event.get("type") != status:
                        yield {"type": status, "job": job_payload}
                    else:
                        yield event
                    return
                yield event
        finally:
            self.unsubscribe(queue)


class JobManager:
    """Creates jobs, caps concurrency, and sweeps expired files."""

    def __init__(
        self,
        *,
        download_dir: Path,
        max_concurrent: int = 3,
        job_ttl_seconds: int = 3600,
    ) -> None:
        self.download_dir = download_dir
        self.max_concurrent = max(1, max_concurrent)
        self.job_ttl_seconds = max(60, job_ttl_seconds)
        self._jobs: dict[str, Job] = {}
        self._semaphore: asyncio.Semaphore | None = None
        self._runner: Callable[[Job], None] | None = None

    # ------------------------------------------------------------------ setup

    def set_runner(self, runner: Callable[[Job], None]) -> None:
        """Register the synchronous function that performs a job's download."""
        self._runner = runner

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._semaphore

    # ------------------------------------------------------------------- crud

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def create(
        self,
        *,
        url: str,
        mode: str,
        title: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:16],
            url=url,
            mode=mode,
            title=title,
            options=dict(options or {}),
        )
        self._jobs[job.id] = job
        return job

    def start(self, job: Job) -> None:
        """Schedule ``job`` to run, honouring the concurrency limit."""
        if self._runner is None:
            raise RuntimeError("JobManager.set_runner() was never called")
        job.bind_loop(asyncio.get_running_loop())
        asyncio.create_task(self._run(job))

    async def _run(self, job: Job) -> None:
        assert self._runner is not None
        if job.cancel_requested:
            job.finish(JobStatus.canceled)
            return
        async with self._get_semaphore():
            if job.cancel_requested:
                job.finish(JobStatus.canceled)
                return
            try:
                await asyncio.to_thread(self._runner, job)
            except Exception as exc:  # noqa: BLE001 - last-resort guard
                if not job.status.is_terminal:
                    job.finish(JobStatus.failed, error=str(exc), error_code="internal_error")

    def cancel(self, job: Job) -> bool:
        if job.status.is_terminal:
            return False
        job.cancel_requested = True
        if job.status is JobStatus.queued:
            # Nothing has started yet, so settle it right away.
            job.finish(JobStatus.canceled)
        else:
            job.update(force=True, message="canceling")
        return True

    def discard(self, job_id: str, *, remove_files: bool = True) -> bool:
        job = self._jobs.pop(job_id, None)
        if job is None:
            return False
        job.cancel_requested = True
        if remove_files:
            _remove_tree(job_dir_for(self.download_dir, job_id))
        return True

    # ---------------------------------------------------------------- upkeep

    def sweep(self) -> int:
        """Delete finished jobs and files older than the TTL. Returns count."""
        now = time.time()
        removed = 0
        for job_id, job in list(self._jobs.items()):
            reference = job.finished_at or job.created_at
            if job.status.is_terminal and now - reference > self.job_ttl_seconds:
                self.discard(job_id)
                removed += 1
        # Orphaned directories from a previous process.
        if self.download_dir.exists():
            for child in self.download_dir.iterdir():
                if not child.is_dir() or child.name in self._jobs:
                    continue
                try:
                    if now - child.stat().st_mtime > self.job_ttl_seconds:
                        _remove_tree(child)
                        removed += 1
                except OSError:
                    continue
        return removed


def job_dir_for(download_dir: Path, job_id: str) -> Path:
    return download_dir / job_id


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    for item in sorted(path.rglob("*"), reverse=True):
        try:
            item.unlink() if item.is_file() else item.rmdir()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        pass
