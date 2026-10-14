"""HTTP-level tests. Network extraction is stubbed so the suite is hermetic."""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import pull1sec.main as main
from pull1sec.auth import AuthStore, derive_proof, derive_verifier
from pull1sec.jobs import JobManager, JobStatus

STATIC_DIR = Path(main.__file__).parent / "static"

USERNAME = "kerem"
PASSWORD = "supersecret1"

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
def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire the app to throwaway storage and a stubbed download runner."""
    settings = dataclasses.replace(main.settings, download_dir=tmp_path, allow_private_hosts=True)
    settings.ensure_dirs()
    monkeypatch.setattr(main, "settings", settings)

    manager = JobManager(download_dir=tmp_path, max_concurrent=2, job_ttl_seconds=600)
    manager.set_runner(fake_runner)
    monkeypatch.setattr(main, "manager", manager)

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials(USERNAME, PASSWORD)
    monkeypatch.setattr(main, "auth", store)


@pytest.fixture()
def anon_client(_app: None) -> TestClient:
    """Not signed in."""
    with TestClient(main.app) as test_client:
        yield test_client


def sign_in(client: TestClient, *, password: str = PASSWORD, remember: bool = True):
    """Run the real challenge/response handshake, exactly like the browser."""
    challenge = client.post("/api/auth/challenge", json={"username": USERNAME}).json()
    verifier = derive_verifier(password, bytes.fromhex(challenge["salt"]), challenge["iterations"])
    proof = derive_proof(verifier, bytes.fromhex(challenge["nonce"]), challenge["iterations"])
    return client.post(
        "/api/auth/login",
        json={
            "username": USERNAME,
            "nonce": challenge["nonce"],
            "proof": proof.hex(),
            "remember": remember,
        },
    )


@pytest.fixture()
def client(anon_client: TestClient) -> TestClient:
    """Signed in, the way the front end would be."""
    assert sign_in(anon_client).status_code == 200
    return anon_client


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


def test_every_translation_key_used_by_the_markup_exists_in_both_languages() -> None:
    """A key present in only one dictionary silently leaks the source language."""
    import re

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    keys = set(re.findall(r'data-i18n(?:-aria)?="([^"]+)"', html))
    assert keys, "index.html should use data-i18n attributes"
    missing = sorted(key for key in keys if js.count(f'"{key}":') < 2)
    assert not missing, f"missing from one of the dictionaries: {missing}"


def test_css_forces_hidden_elements_to_stay_hidden() -> None:
    """Components set their own display, so [hidden] needs !important."""
    import re

    css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"\[hidden\]\s*\{[^}]*display:\s*none\s*!important", css)


# --------------------------------------------------------------------- auth


def test_health_is_public(anon_client: TestClient) -> None:
    response = anon_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["auth_configured"] is True


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/meta"),
        ("GET", "/api/jobs"),
        ("GET", "/api/jobs/abc"),
        ("GET", "/api/jobs/abc/events"),
        ("GET", "/api/jobs/abc/file"),
        ("POST", "/api/probe"),
        ("POST", "/api/download"),
        ("POST", "/api/jobs/abc/cancel"),
        ("DELETE", "/api/jobs/abc"),
        ("GET", "/api/thumbnail"),
    ],
)
def test_protected_endpoints_require_a_session(
    anon_client: TestClient, method: str, path: str
) -> None:
    response = anon_client.request(method, path)
    assert response.status_code == 401, f"{method} {path} was reachable without a session"
    assert response.json()["error"]["code"] == "unauthorized"


def test_me_reports_the_signed_out_state(anon_client: TestClient) -> None:
    body = anon_client.get("/api/auth/me").json()
    assert body["authenticated"] is False
    assert body["configured"] is True
    # Nothing about the account leaks before signing in.
    assert body["username"] is None
    assert body["sessions"] == []


def test_challenge_hides_every_secret(anon_client: TestClient) -> None:
    body = anon_client.post("/api/auth/challenge", json={"username": USERNAME}).json()
    assert body["algorithm"] == "pbkdf2-sha256"
    assert body["iterations"] > 100_000
    assert "username" not in body
    raw = json.dumps(body)
    assert PASSWORD not in raw
    assert main.auth._data["verifier"] not in raw


def test_login_flow_and_session_cookie(anon_client: TestClient) -> None:
    response = sign_in(anon_client)
    assert response.status_code == 200
    assert response.json()["username"] == USERNAME

    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.replace("samesite", "SameSite")
    assert "Secure" not in cookie  # plain HTTP on a LAN, documented trade-off
    assert "Max-Age=" in cookie

    me = anon_client.get("/api/auth/me").json()
    assert me["authenticated"] is True
    assert me["username"] == USERNAME
    assert len(me["sessions"]) == 1
    assert me["sessions"][0]["current"] is True
    assert anon_client.get("/api/meta").status_code == 200


def test_login_with_the_wrong_password_fails(anon_client: TestClient) -> None:
    response = sign_in(anon_client, password="not-the-password")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "bad_credentials"
    assert anon_client.get("/api/meta").status_code == 401


def test_login_never_sends_the_password(anon_client: TestClient, monkeypatch) -> None:
    """What reaches the server is a proof, never the password."""
    seen: dict[str, str] = {}
    original = main.auth.verify_proof

    def spy(username: str, nonce: str, proof: str) -> bool:
        seen.update(username=username, nonce=nonce, proof=proof)
        return original(username, nonce, proof)

    monkeypatch.setattr(main.auth, "verify_proof", spy)
    assert sign_in(anon_client).status_code == 200

    assert seen["username"] == USERNAME
    assert PASSWORD not in seen["proof"]
    assert len(seen["proof"]) == 64  # 32 bytes, hex encoded
    assert seen["nonce"] != seen["proof"]


def test_a_nonce_cannot_be_replayed(anon_client: TestClient) -> None:
    challenge = anon_client.post("/api/auth/challenge", json={"username": USERNAME}).json()
    verifier = derive_verifier(PASSWORD, bytes.fromhex(challenge["salt"]), challenge["iterations"])
    proof = derive_proof(verifier, bytes.fromhex(challenge["nonce"]), challenge["iterations"]).hex()
    body = {"username": USERNAME, "nonce": challenge["nonce"], "proof": proof, "remember": True}

    assert anon_client.post("/api/auth/login", json=body).status_code == 200
    replayed = anon_client.post("/api/auth/login", json=body)
    assert replayed.status_code == 401
    assert replayed.json()["error"]["code"] == "bad_credentials"


def test_repeated_failures_are_locked_out(anon_client: TestClient) -> None:
    for _ in range(4):
        assert sign_in(anon_client, password="wrong-password").status_code == 401

    # The fifth failure trips the lock.
    assert sign_in(anon_client, password="wrong-password").status_code == 429

    # From here even the challenge is refused, so no proof can be built.
    blocked = anon_client.post("/api/auth/challenge", json={"username": USERNAME})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "too_many_attempts"

    login = anon_client.post(
        "/api/auth/login",
        json={"username": USERNAME, "nonce": "aa" * 24, "proof": "bb" * 32},
    )
    assert login.status_code == 429
    assert anon_client.get("/api/meta").status_code == 401


def test_logout_clears_the_session(client: TestClient) -> None:
    assert client.get("/api/meta").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/meta").status_code == 401


def test_logout_all_closes_every_device(client: TestClient) -> None:
    sign_in(client)  # a second "device"
    me = client.get("/api/auth/me").json()
    assert len(me["sessions"]) >= 2

    response = client.post("/api/auth/logout-all")
    assert response.status_code == 200
    assert response.json()["revoked"] >= 2
    assert client.get("/api/meta").status_code == 401


def test_cross_origin_writes_are_refused(client: TestClient) -> None:
    response = client.post(
        "/api/download",
        json={"url": "https://www.youtube.com/watch?v=abcdefghijk"},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 401

    same_origin = client.post(
        "/api/download",
        json={"url": "https://www.youtube.com/watch?v=abcdefghijk"},
        headers={"Origin": "http://testserver"},
    )
    assert same_origin.status_code == 200


def test_login_without_an_account_reports_setup_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = AuthStore(tmp_path / "empty.json")
    monkeypatch.setattr(main, "auth", empty)
    with TestClient(main.app) as test_client:
        me = test_client.get("/api/auth/me").json()
        assert me == {"authenticated": False, "configured": False, "username": None,
                      "expires_at": None, "registered_at": None, "sessions": []}
        response = test_client.post("/api/auth/challenge", json={})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "auth_not_configured"


def test_static_login_assets_are_public(anon_client: TestClient) -> None:
    assert anon_client.get("/auth.js").status_code == 200
    page = anon_client.get("/")
    assert "login-form" in page.text
    assert "/auth.js" in page.text
