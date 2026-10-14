"""Request/response schemas for the JSON API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .config import SUPPORTED_COOKIE_BROWSERS

DownloadMode = Literal["video", "audio"]
AudioFormat = Literal["mp3", "m4a", "wav", "opus"]
CookieBrowser = Literal[
    "chrome", "chromium", "firefox", "edge", "brave", "opera", "vivaldi", "safari", "whale"
]


class ProbeRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    cookies_from_browser: CookieBrowser | None = None

    @field_validator("url")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a URL.")
        return value


class DownloadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    mode: DownloadMode = "video"
    #: Preferred maximum height for video, e.g. 1080. ``None`` means "best".
    height: int | None = Field(default=None, ge=144, le=4320)
    audio_format: AudioFormat = "mp3"
    cookies_from_browser: CookieBrowser | None = None

    @field_validator("url")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a URL.")
        return value


class MediaQuality(BaseModel):
    height: int
    label: str
    fps: float | None = None
    filesize: int | None = None


class MediaInfo(BaseModel):
    url: str
    title: str
    uploader: str | None = None
    uploader_url: str | None = None
    platform: str
    extractor: str | None = None
    duration: float | None = None
    thumbnail: str | None = None
    webpage_url: str | None = None
    is_live: bool = False
    view_count: int | None = None
    upload_date: str | None = None
    description: str | None = None
    qualities: list[MediaQuality] = Field(default_factory=list)
    has_video: bool = True
    has_audio: bool = True
    audio_formats: list[str] = Field(default_factory=lambda: ["mp3", "m4a"])


class ProbeResponse(BaseModel):
    ok: bool = True
    media: MediaInfo


class JobView(BaseModel):
    id: str
    url: str
    mode: DownloadMode
    status: str
    title: str | None = None
    uploader: str | None = None
    platform: str | None = None
    thumbnail: str | None = None
    duration: float | None = None
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None
    filename: str | None = None
    filesize: int | None = None
    mimetype: str | None = None
    message: str | None = None
    error: str | None = None
    error_code: str | None = None
    created_at: float
    updated_at: float
    finished_at: float | None = None
    download_url: str | None = None


class DownloadResponse(BaseModel):
    ok: bool = True
    job: JobView


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    ok: bool = False
    error: ErrorBody


class MetaResponse(BaseModel):
    name: str
    version: str
    max_concurrent: int
    job_ttl_seconds: int
    max_filesize_mb: int
    cookie_browsers: list[str]
    audio_formats: list[str]


__all__ = [
    "AudioFormat",
    "CookieBrowser",
    "DownloadMode",
    "DownloadRequest",
    "DownloadResponse",
    "ErrorBody",
    "ErrorResponse",
    "JobView",
    "MediaInfo",
    "MediaQuality",
    "MetaResponse",
    "ProbeRequest",
    "ProbeResponse",
    "SUPPORTED_COOKIE_BROWSERS",
]
