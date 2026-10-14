"""Job lifecycle, throttling and cleanup."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from pull1sec.jobs import Job, JobManager, JobStatus, job_dir_for


def make_job(**kwargs) -> Job:
    return Job(id="job1", url="https://example.com/v", mode="video", **kwargs)


def test_snapshot_has_every_api_field() -> None:
    from pull1sec.models import JobView

    job = make_job()
    view = JobView(**job.snapshot())
    assert view.status == "queued"
    assert view.download_url is None


def test_progress_updates_are_throttled() -> None:
    job = make_job()
    assert job._should_publish_progress() is True  # first call always publishes
    # Same percentage, well within the throttle window: suppressed.
    assert job._should_publish_progress() is False
    # A big jump forces a publish even inside the window.
    job.percent = 55.0
    assert job._should_publish_progress() is True


def test_throttle_window_expires() -> None:
    job = make_job()
    job._should_publish_progress()
    job._last_publish = time.time() - 1.0
    job.percent = 0.1
    assert job._should_publish_progress() is True


def test_finish_is_idempotent() -> None:
    job = make_job()
    job.finish(JobStatus.completed)
    finished_at = job.finished_at
    job.finish(JobStatus.failed, error="late failure")
    assert job.status is JobStatus.completed
    assert job.error is None
    assert job.finished_at == finished_at


def test_completed_job_reports_full_progress() -> None:
    job = make_job()
    job.finish(JobStatus.completed)
    assert job.percent == 100.0
    assert job.eta == 0


def test_cancel_settles_a_queued_job_immediately() -> None:
    manager = JobManager(download_dir=Path("/tmp"), max_concurrent=1)
    job = manager.create(url="https://example.com/v", mode="video")
    assert manager.cancel(job) is True
    assert job.status is JobStatus.canceled
    assert job.cancel_requested is True
    # Cancelling twice is a no-op.
    assert manager.cancel(job) is False


def test_cancel_flags_a_running_job() -> None:
    manager = JobManager(download_dir=Path("/tmp"), max_concurrent=1)
    job = manager.create(url="https://example.com/v", mode="video")
    job.update(force=True, status=JobStatus.downloading)
    manager.cancel(job)
    assert job.status is JobStatus.downloading
    assert job.cancel_requested is True
    assert job.message == "canceling"


def test_runner_marks_queued_canceled_job_without_downloading(tmp_path: Path) -> None:
    manager = JobManager(download_dir=tmp_path, max_concurrent=1)
    calls: list[str] = []

    def runner(job: Job) -> None:
        calls.append(job.id)

    manager.set_runner(runner)

    async def scenario() -> None:
        job = manager.create(url="https://example.com/v", mode="video")
        manager.start(job)
        manager.cancel(job)
        await asyncio.sleep(0.1)
        assert job.status is JobStatus.canceled

    asyncio.run(scenario())
    assert calls == []


def test_runner_records_failures(tmp_path: Path) -> None:
    manager = JobManager(download_dir=tmp_path, max_concurrent=1)

    def runner(job: Job) -> None:
        raise RuntimeError("boom")

    manager.set_runner(runner)

    async def scenario() -> None:
        job = manager.create(url="https://example.com/v", mode="video")
        manager.start(job)
        for _ in range(40):
            await asyncio.sleep(0.05)
            if job.status.is_terminal:
                break
        assert job.status is JobStatus.failed
        assert "boom" in (job.error or "")

    asyncio.run(scenario())


def test_sweep_deletes_old_jobs_and_files(tmp_path: Path) -> None:
    manager = JobManager(download_dir=tmp_path, max_concurrent=1, job_ttl_seconds=60)
    job = manager.create(url="https://example.com/v", mode="video")
    job.finish(JobStatus.completed)

    directory = job_dir_for(tmp_path, job.id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "clip.mp4").write_bytes(b"x")

    # Fresh job: nothing to do yet.
    assert manager.sweep() == 0

    job.finished_at = time.time() - 120
    assert manager.sweep() == 1
    assert manager.get(job.id) is None
    assert not directory.exists()


def test_manager_lists_newest_first(tmp_path: Path) -> None:
    manager = JobManager(download_dir=tmp_path, max_concurrent=2)
    first = manager.create(url="https://example.com/1", mode="video")
    first.created_at = time.time() - 10
    second = manager.create(url="https://example.com/2", mode="video")
    assert [job.id for job in manager.all()] == [second.id, first.id]


@pytest.mark.parametrize("mode", ["video", "audio"])
def test_create_passes_options_through(tmp_path: Path, mode: str) -> None:
    manager = JobManager(download_dir=tmp_path, max_concurrent=1)
    job = manager.create(url="https://example.com/v", mode=mode, options={"height": 720, "mode": mode})
    assert job.options["height"] == 720
    assert job.mode == mode
