"""Unit tests for URL handling, formatting and error classification."""

from __future__ import annotations

import pytest

from pull1sec.downloader import build_format_selector, classify_error, _detect_streams
from pull1sec.utils import (
    InvalidURLError,
    guard_url,
    human_bytes,
    human_duration,
    normalize_url,
    platform_label,
    sanitize_filename,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://youtu.be/abc", "https://youtu.be/abc"),
        ("youtube.com/watch?v=abc", "https://youtube.com/watch?v=abc"),
        ("www.tiktok.com/@user/video/1", "https://www.tiktok.com/@user/video/1"),
        ("  https://x.com/u/status/1  ", "https://x.com/u/status/1"),
        ('"https://vimeo.com/1"', "https://vimeo.com/1"),
        ("https://youtu.be/abc#t=30", "https://youtu.be/abc"),
    ],
)
def test_normalize_url_accepts_and_cleans(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not a url", "ftp://example.com/x", "javascript:alert(1)", "https://"],
)
def test_normalize_url_rejects(raw: str) -> None:
    with pytest.raises(InvalidURLError):
        normalize_url(raw)


def test_guard_url_blocks_private_hosts_when_disabled() -> None:
    with pytest.raises(InvalidURLError):
        guard_url("http://127.0.0.1:8000/secret", allow_private_hosts=False)
    with pytest.raises(InvalidURLError):
        guard_url("http://10.0.0.5/video", allow_private_hosts=False)


def test_guard_url_allows_private_hosts_when_enabled() -> None:
    assert guard_url("http://127.0.0.1/x", allow_private_hosts=True) == "http://127.0.0.1/x"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Cool Video: Part 2?", "Cool Video Part 2"),
        ("../../etc/passwd", "etc passwd"),
        ("   spaced   out   ", "spaced out"),
        ("", "video"),
        ("CON", "CON"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_truncates_long_names() -> None:
    result = sanitize_filename("a" * 500 + ".mp4")
    assert len(result) <= 180
    assert result.endswith(".mp4")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0 B"), (512, "512 B"), (2048, "2.0 KB"), (5 * 1024 * 1024, "5.0 MB")],
)
def test_human_bytes(value: int, expected: str) -> None:
    assert human_bytes(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, ""), (0, ""), (59, "0:59"), (61, "1:01"), (3661, "1:01:01")],
)
def test_human_duration(value: float | None, expected: str) -> None:
    assert human_duration(value) == expected


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("YoutubeIE", "YouTube"),
        ("TikTokIE", "TikTok"),
        ("InstagramIE", "Instagram"),
        ("TwitterIE", "X"),
        ("", "Web"),
        (None, "Web"),
        ("FooIE", "Foo"),
    ],
)
def test_platform_label(key: str | None, expected: str) -> None:
    assert platform_label(key, None) == expected


@pytest.mark.parametrize(
    ("mode", "height", "needle"),
    [
        ("video", None, "bv*+ba/b"),
        ("video", 1080, "height<=1080"),
        ("audio", 720, "bestaudio"),
    ],
)
def test_build_format_selector(mode: str, height: int | None, needle: str) -> None:
    assert needle in build_format_selector(mode, height)


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("ERROR: Sign in to confirm you're not a bot", "authentication_required"),
        ("[vimeo] 1: The web client only works when logged-in. Use --cookies", "authentication_required"),
        ("Unsupported URL: https://example.com", "unsupported_site"),
        ("ERROR: Video unavailable", "media_unavailable"),
        ("Connection timed out", "network_error"),
        ("HTTP Error 403: Forbidden", "forbidden"),
        ("ffmpeg not found", "ffmpeg_missing"),
        (
            'could not find chrome cookies database in "/home/u/.config/google-chrome"',
            "cookies_unavailable",
        ),
        ("The extractor is attempting impersonation, but is not installed", "impersonation_unavailable"),
        ("something else entirely", "download_failed"),
    ],
)
def test_classify_error(message: str, code: str) -> None:
    assert classify_error(message)[0] == code


@pytest.mark.parametrize(
    ("formats", "expected"),
    [
        # A plain direct file: yt-dlp reports no codec info at all.
        ([{"vcodec": None, "acodec": None, "height": None}], (True, True)),
        ([], (True, True)),
        # DASH: separate video-only and audio-only streams.
        (
            [
                {"vcodec": "avc1", "acodec": "none", "height": 1080},
                {"vcodec": "none", "acodec": "mp4a", "height": None},
            ],
            (True, True),
        ),
        # Audio-only source.
        ([{"vcodec": "none", "acodec": "mp4a"}], (False, True)),
        # Video-only source (no audio track at all).
        ([{"vcodec": "vp9", "acodec": "none", "height": 720}], (True, False)),
    ],
)
def test_detect_streams(formats: list, expected: tuple[bool, bool]) -> None:
    assert _detect_streams(formats) == expected
