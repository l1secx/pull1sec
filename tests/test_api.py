"""HTTP-level tests. Network extraction is stubbed so the suite is hermetic."""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import pull1sec.main as main
from pull1sec.jobs import JobManager, JobStatus

STATIC_DIR = Path(main.__file__).parent / "static"

SAMPLE_MEDIA: dict[str, Any] = {
    "url": "https://www.youtube.com/watch?v=abcdefghijk",
    "title": "A test clip",
    "uploader": "Test Channel",
    "uploader_url": None,
    "platform": "YouTube",
    "extractor": "YoutubeIE",
    "duration": 212.0,
    "thumbnail": "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
    "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk",
    "is_live": False,
    "view_count": 1234,
    "upload_date": "20250101",
    "description": None,
    "qualities": [
        {"height": 1080, "label": "1080p · Full HD", "fps": 30, "filesize": 10_000_000},
        {"height": 720, "label": "720p · HD", "fps": 30, "filesize": 5_000_000},
    ],
    "has_video": True,
    "has_audio": True,
    "audio_formats": ["mp3", "m4a"],
}


def fake_runner(job) -> None:
    out_dir = job_dir() / job.id
    out_dir.mkdir(parents=True, exist_ok=True)
    job.update(force=True, status=JobStatus.downloading, title="A test clip", platform="YouTube")
    job.update(percent=50.0, downloaded_bytes=5, total_bytes=10, speed=2048.0, eta=1)
    target = out_dir / "clip.mp4"
    target.write_bytes(b"fake-video-bytes")
    job.update(
        force=True,
        file_path=target,
        filename="clip.mp4",
        filesize=target.stat().st_size,
        mimetype="video/mp4",
    )
    job.finish(JobStatus.completed)


def job_dir() -> Path:
    return main.settings.download_dir


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    settings = dataclasses.replace(main.settings, download_dir=tmp_path, allow_private_hosts=True)
    settings.ensure_dirs()
    monkeypatch.setattr(main, "settings", settings)

    manager = JobManager(download_dir=tmp_path, max_concurrent=2, job_ttl_seconds=600)
    manager.set_runner(fake_runner)
    monkeypatch.setattr(main, "manager", manager)

    with TestClient(main.app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_meta_lists_cookie_browsers(client: TestClient) -> None:
    body = client.get("/api/meta").json()
    assert "chrome" in body["cookie_browsers"]
    assert body["name"] == "Pull1sec"


def test_index_page_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Pull1sec" in response.text


def test_probe_returns_media(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_probe(url: str, *, settings, cookies_from_browser=None):
        captured["url"] = url
        captured["cookies"] = cookies_from_browser
        return dict(SAMPLE_MEDIA)

    monkeypatch.setattr(main, "probe", fake_probe)

    response = client.post("/api/probe", json={"url": "youtube.com/watch?v=abcdefghijk"})
    assert response.status_code == 200
    body = response.json()
    assert body["media"]["platform"] == "YouTube"
    assert body["media"]["qualities"][0]["height"] == 1080
    assert captured["url"] == "https://youtube.com/watch?v=abcdefghijk"


def test_probe_rejects_unusable_url(client: TestClient) -> None:
    response = client.post("/api/probe", json={"url": "not a url"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_url"


def test_probe_surfaces_site_errors(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from pull1sec.errors import AuthenticationRequiredError

    def failing_probe(url: str, *, settings, cookies_from_browser=None):
        raise AuthenticationRequiredError("Login required.", code="authentication_required")

    monkeypatch.setattr(main, "probe", failing_probe)
    response = client.post("/api/probe", json={"url": "https://www.instagram.com/p/abc/"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "authentication_required"


def test_download_then_serve_file_then_delete(client: TestClient) -> None:
    response = client.post(
        "/api/download",
        json={"url": "https://www.youtube.com/watch?v=abcdefghijk", "mode": "video", "height": 720},
    )
    assert response.status_code == 200
    job_id = response.json()["job"]["id"]

    deadline = time.time() + 10
    job: dict[str, Any] = {}
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "canceled"}:
            break
        time.sleep(0.05)

    assert job["status"] == "completed", job
    assert job["filename"] == "clip.mp4"

    download = client.get(f"/api/jobs/{job_id}/file")
    assert download.status_code == 200
    assert download.content == b"fake-video-bytes"
    assert "clip.mp4" in download.headers["content-disposition"]

    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_events_stream_reaches_terminal_state(client: TestClient) -> None:
    job_id = client.post(
        "/api/download",
        json={"url": "https://www.youtube.com/watch?v=abcdefghijk", "mode": "audio"},
    ).json()["job"]["id"]

    seen: list[str] = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        event = None
        for line in stream.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event:
                seen.append(event)

    # A late subscriber still receives the terminal state immediately.
    assert seen and seen[-1] == "completed"


def test_file_is_conflict_until_ready(client: TestClient) -> None:
    job = main.manager.create(url="https://example.com/v", mode="video")
    response = client.get(f"/api/jobs/{job.id}/file")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_ready"


def test_cancel_marks_job_canceled(client: TestClient) -> None:
    job = main.manager.create(url="https://example.com/v", mode="video")
    response = client.post(f"/api/jobs/{job.id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "canceled"


def test_unknown_job_returns_404(client: TestClient) -> None:
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_thumbnail_rejects_non_https(client: TestClient) -> None:
    response = client.get("/api/thumbnail", params={"url": "http://example.com/a.png"})
    assert response.status_code == 422


# ---------------------------------------------------------------- front end


def test_static_assets_are_served(client: TestClient) -> None:
    css = client.get("/styles.css")
    js = client.get("/app.js")
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]


def test_every_element_id_used_by_the_script_exists_in_the_markup() -> None:
    """Guards the class of bug where JS references an id the HTML never defines."""
    import re

    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'getElementById\("([^"]+)"\)', js))
    assert ids, "app.js should look up element ids"
    missing = sorted(node_id for node_id in ids if f'id="{node_id}"' not in html)
    assert not missing, f"ids referenced by app.js but missing from index.html: {missing}"


def test_css_forces_hidden_elements_to_stay_hidden() -> None:
    """Components set their own display, so [hidden] needs !important."""
    import re

    css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"\[hidden\]\s*\{[^}]*display:\s*none\s*!important", css)
