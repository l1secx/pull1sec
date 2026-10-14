"""yt-dlp integration: metadata probing and file download with progress."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, DownloadCancelled, ExtractorError, UnsupportedError

from .config import Settings
from .errors import (
    AuthenticationRequiredError,
    Pull1secError,
    MediaUnavailableError,
    UnsupportedSiteError,
)
from .jobs import Job, JobStatus, job_dir_for
from .utils import platform_label

log = logging.getLogger("pull1sec.downloader")

AUDIO_CODECS: tuple[str, ...] = ("mp3", "m4a", "wav", "opus", "flac")
MIN_QUALITY_HEIGHT = 144
MAX_QUALITIES = 12


# --------------------------------------------------------------------- helpers


class _CaptureLogger:
    """Swallows yt-dlp's console chatter and keeps the last few messages."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def debug(self, message: str) -> None:  # noqa: D102 - yt-dlp protocol
        pass

    def info(self, message: str) -> None:  # noqa: D102
        pass

    def warning(self, message: str) -> None:  # noqa: D102
        self.warnings.append(str(message))
        del self.warnings[:-10]

    def error(self, message: str) -> None:  # noqa: D102
        self.errors.append(str(message))
        del self.errors[:-10]


def _base_opts(settings: Settings, logger: _CaptureLogger) -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": settings.socket_timeout,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
        "logger": logger,
        "ignoreerrors": False,
        "no_color": True,
    }


def _cookies_opts(cookies_from_browser: str | None) -> dict[str, Any]:
    # yt-dlp expects a tuple: (browser, profile, keyring, container)
    if cookies_from_browser:
        return {"cookiesfrombrowser": (cookies_from_browser, None, None, None)}
    return {}


def classify_error(message: str) -> tuple[str, str]:
    """Map a raw yt-dlp message onto ``(error_code, friendly_message)``."""
    text = (message or "").strip()
    lowered = text.lower()

    if any(
        token in lowered
        for token in (
            "sign in to confirm",
            "login required",
            "you need to log in",
            "log in to",
            "logged-in",
            "logged in",
            "requires login",
            "use --cookies",
            "cookies-from-browser",
            "private video",
            "members-only",
            "this video is private",
            "requested content is not available",
            "confirm you're not a bot",
        )
    ):
        return (
            "authentication_required",
            "This post needs a signed-in session. Retry with “Use browser cookies” set to the browser you are logged in with.",
        )
    if "impersonation" in lowered:
        return (
            "impersonation_unavailable",
            "This site needs a browser-like TLS fingerprint. Reinstall with the curl-cffi extra, or retry with browser cookies.",
        )
    if "cookies database" in lowered or ("could not find" in lowered and "cookies" in lowered):
        return (
            "cookies_unavailable",
            "Could not read cookies from that browser. Pick a browser you are signed in with, or leave it off.",
        )
    if "unsupported url" in lowered or "no video formats found" in lowered:
        return ("unsupported_site", "This link is not supported. Try the direct post or video URL.")
    if any(
        token in lowered
        for token in (
            "video unavailable",
            "this video is not available",
            "has been removed",
            "no longer available",
            "not available in your country",
            "geo restricted",
            "content is not available",
        )
    ):
        return ("media_unavailable", "The media is unavailable or has been removed.")
    if any(token in lowered for token in ("timed out", "timeout", "temporary failure", "connection")):
        return ("network_error", "The site did not respond in time. Check your connection and retry.")
    if "http error 404" in lowered:
        return ("not_found", "That page does not exist any more.")
    if "http error 403" in lowered:
        return ("forbidden", "The site refused the request. Retry with browser cookies.")
    if "ffmpeg" in lowered and "not found" in lowered:
        return ("ffmpeg_missing", "ffmpeg is required to merge or convert this file but was not found.")
    if "disk" in lowered and "space" in lowered:
        return ("disk_full", "Not enough disk space to finish the download.")

    friendly = text.splitlines()[0].strip() if text else "The download failed."
    friendly = friendly.removeprefix("ERROR:").strip()
    return ("download_failed", friendly[:400] or "The download failed.")


def _select_error_message(exc: BaseException, logger: _CaptureLogger) -> str:
    for candidate in (str(exc), *_reversed(logger.errors), *_reversed(logger.warnings)):
        if candidate and candidate.strip():
            return candidate
    return "The download failed."


def _reversed(items: list[str]) -> list[str]:
    return list(reversed(items))


# ----------------------------------------------------------------------- probe


def _detect_streams(formats: list[dict[str, Any]]) -> tuple[bool, bool]:
    """Return ``(has_video, has_audio)`` from a yt-dlp format list.

    When an extractor reports no codec information at all we assume a normal
    audio+video file rather than mislabelling it as audio-only.
    """
    video_codecs = [fmt.get("vcodec") for fmt in formats]
    audio_codecs = [fmt.get("acodec") for fmt in formats]
    has_video = any(codec not in (None, "none") for codec in video_codecs) or not any(video_codecs)
    has_audio = any(codec not in (None, "none") for codec in audio_codecs) or not any(audio_codecs)
    return has_video, has_audio


def _quality_label(height: int) -> str:
    aliases = {4320: "8K", 2160: "4K", 1440: "2K", 1080: "Full HD", 720: "HD", 480: "SD"}
    alias = aliases.get(height)
    return f"{height}p · {alias}" if alias else f"{height}p"


def _collect_qualities(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Collapse yt-dlp's format list into one entry per usable height."""
    by_height: dict[int, dict[str, Any]] = {}
    for fmt in info.get("formats") or []:
        if fmt.get("vcodec") in (None, "none"):
            continue
        height = fmt.get("height")
        if not height or height < MIN_QUALITY_HEIGHT:
            continue
        filesize = fmt.get("filesize") or fmt.get("filesize_approx")
        current = by_height.get(height)
        if current is None:
            by_height[height] = {"height": height, "fps": fmt.get("fps"), "filesize": filesize}
        else:
            if filesize and (not current["filesize"] or filesize > current["filesize"]):
                current["filesize"] = filesize
            if (fmt.get("fps") or 0) > (current.get("fps") or 0):
                current["fps"] = fmt.get("fps")

    ordered = sorted(by_height.values(), key=lambda item: item["height"], reverse=True)
    for item in ordered:
        item["label"] = _quality_label(item["height"])
        if item.get("fps"):
            item["label"] = f"{item['label']} · {round(item['fps'])}fps"
    return ordered[:MAX_QUALITIES]


def probe(
    url: str,
    *,
    settings: Settings,
    cookies_from_browser: str | None = None,
) -> dict[str, Any]:
    """Fetch metadata for ``url`` without downloading anything."""
    logger = _CaptureLogger()
    opts = _base_opts(settings, logger)
    opts.update(_cookies_opts(cookies_from_browser))
    opts.update({"skip_download": True, "extract_flat": False})

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except UnsupportedError as exc:
        raise UnsupportedSiteError(_select_error_message(exc, logger)) from exc
    except ExtractorError as exc:
        raise _to_pull1sec_error(_select_error_message(exc, logger)) from exc
    except DownloadError as exc:
        raise _to_pull1sec_error(_select_error_message(exc, logger)) from exc
    except Exception as exc:  # noqa: BLE001
        raise _to_pull1sec_error(str(exc)) from exc

    if not info:
        raise MediaUnavailableError("No media found at that link.")

    # A playlist URL with noplaylist still yields one entry; unwrap it.
    if info.get("_type") == "playlist":
        entries = [entry for entry in (info.get("entries") or []) if entry]
        if not entries:
            raise MediaUnavailableError("No media found at that link.")
        info = entries[0]

    formats = info.get("formats") or []
    has_video, has_audio = _detect_streams(formats)

    description = info.get("description")
    if isinstance(description, str) and len(description) > 480:
        description = description[:480].rstrip() + "…"

    return {
        "url": url,
        "title": info.get("title") or "Untitled",
        "uploader": info.get("uploader") or info.get("channel") or info.get("uploader_id"),
        "uploader_url": info.get("uploader_url") or info.get("channel_url"),
        "platform": platform_label(info.get("extractor_key"), info.get("extractor")),
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail") or _last_thumbnail(info),
        "webpage_url": info.get("webpage_url") or url,
        "is_live": bool(info.get("is_live")),
        "view_count": info.get("view_count"),
        "upload_date": info.get("upload_date"),
        "description": description,
        "qualities": _collect_qualities(info) if has_video else [],
        "has_video": has_video,
        "has_audio": has_audio,
        "audio_formats": list(AUDIO_CODECS[:4]),
    }


def _last_thumbnail(info: dict[str, Any]) -> str | None:
    thumbnails = info.get("thumbnails") or []
    for thumb in reversed(thumbnails):
        if thumb.get("url"):
            return thumb["url"]
    return None


def _to_pull1sec_error(message: str) -> Pull1secError:
    code, friendly = classify_error(message)
    if code == "authentication_required":
        return AuthenticationRequiredError(friendly, code=code)
    if code == "unsupported_site":
        return UnsupportedSiteError(friendly, code=code)
    return MediaUnavailableError(friendly, code=code)


# -------------------------------------------------------------------- download


def build_format_selector(mode: str, height: int | None) -> str:
    """yt-dlp format string for the requested mode."""
    if mode == "audio":
        return "bestaudio/best"
    if height:
        return f"bv*[height<={height}]+ba/b[height<={height}]/bv*+ba/b"
    return "bv*+ba/b"


def run_download(job: Job, *, settings: Settings) -> None:
    """Blocking download used as a ``JobManager`` runner (runs in a thread)."""
    options = job.options or {}
    mode = options.get("mode", "video")
    height = options.get("height")
    audio_format = options.get("audio_format", "mp3")
    cookies_from_browser = options.get("cookies_from_browser")

    out_dir = job_dir_for(settings.download_dir, job.id)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger = _CaptureLogger()
    ydl_opts = _base_opts(settings, logger)
    ydl_opts.update(_cookies_opts(cookies_from_browser))
    ydl_opts.update(
        {
            "outtmpl": {"default": "%(title).150B [%(id)s].%(ext)s"},
            "paths": {"home": str(out_dir), "temp": str(out_dir)},
            "format": build_format_selector(mode, height),
            "overwrites": True,
            "progress_hooks": [_make_progress_hook(job)],
            "postprocessor_hooks": [_make_postprocessor_hook(job)],
        }
    )

    if mode == "audio":
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": "192" if audio_format == "mp3" else "0",
            },
            {"key": "FFmpegMetadata", "add_metadata": True},
        ]
        ydl_opts["keepvideo"] = False
    else:
        ydl_opts["merge_output_format"] = "mp4"
        ydl_opts["postprocessors"] = [{"key": "FFmpegMetadata", "add_metadata": True}]

    if settings.max_filesize_mb > 0:
        ydl_opts["max_filesize"] = settings.max_filesize_mb * 1024 * 1024

    job.update(force=True, status=JobStatus.downloading, message=None)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(job.url, download=True)
    except DownloadCancelled:
        job.finish(JobStatus.canceled, error=None)
        return
    except (UnsupportedError, ExtractorError, DownloadError) as exc:
        message = _select_error_message(exc, logger)
        code, friendly = classify_error(message)
        job.finish(JobStatus.failed, error=friendly, error_code=code)
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("unexpected download failure for job %s", job.id)
        job.finish(JobStatus.failed, error=f"Unexpected error: {exc}", error_code="internal_error")
        return

    if job.cancel_requested:
        job.finish(JobStatus.canceled)
        return

    if info and info.get("_type") == "playlist":
        entries = [entry for entry in (info.get("entries") or []) if entry]
        info = entries[0] if entries else info

    file_path = _resolve_output_path(info, out_dir)
    if file_path is None:
        job.finish(
            JobStatus.failed,
            error="The download finished but no file was produced.",
            error_code="no_output",
        )
        return

    filesize = file_path.stat().st_size
    mimetype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    job.update(
        force=True,
        file_path=file_path,
        filename=file_path.name,
        filesize=filesize,
        mimetype=mimetype,
        downloaded_bytes=filesize,
        total_bytes=filesize,
    )
    job.finish(JobStatus.completed)


def _resolve_output_path(info: dict[str, Any] | None, out_dir: Path) -> Path | None:
    """Find the real file yt-dlp produced (post-merge, post-conversion)."""
    if info:
        requested = info.get("requested_downloads") or []
        for entry in requested:
            for key in ("filepath", "_filename"):
                candidate = entry.get(key)
                if candidate:
                    path = Path(candidate)
                    if path.exists() and path.is_file():
                        return path
        for key in ("filepath", "_filename"):
            candidate = info.get(key)
            if candidate:
                path = Path(candidate)
                if path.exists() and path.is_file():
                    return path

    # Fallback: the most recent non-partial file in the job directory.
    files = [
        path
        for path in out_dir.rglob("*")
        if path.is_file() and not path.name.endswith((".part", ".ytdl", ".temp"))
    ]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


# ---------------------------------------------------------------------- hooks


def _make_progress_hook(job: Job):
    state = {"announced": False, "last_title": None}

    def hook(payload: dict[str, Any]) -> None:
        if job.cancel_requested:
            raise DownloadCancelled("Canceled by user")

        status = payload.get("status")
        info_dict = payload.get("info_dict") or {}

        if not state["announced"] and info_dict.get("title"):
            state["announced"] = True
            state["last_title"] = info_dict.get("title")
            job.update(
                publish=True,
                title=info_dict.get("title"),
                uploader=info_dict.get("uploader") or info_dict.get("channel"),
                platform=platform_label(info_dict.get("extractor_key"), info_dict.get("extractor")),
                duration=info_dict.get("duration"),
                thumbnail=info_dict.get("thumbnail") or _last_thumbnail(info_dict),
            )

        if status == "downloading":
            total = payload.get("total_bytes") or payload.get("total_bytes_estimate")
            downloaded = payload.get("downloaded_bytes") or 0
            percent = (downloaded / total * 100.0) if total else job.percent
            job.update(
                status=JobStatus.downloading,
                downloaded_bytes=int(downloaded),
                total_bytes=int(total) if total else None,
                speed=payload.get("speed"),
                eta=payload.get("eta"),
                percent=min(percent, 99.9),
                message=None,
            )
        elif status == "finished":
            job.update(
                status=JobStatus.processing,
                percent=100.0,
                speed=None,
                eta=0,
                message="processing",
            )

    return hook


def _make_postprocessor_hook(job: Job):
    def hook(payload: dict[str, Any]) -> None:
        if job.cancel_requested:
            raise DownloadCancelled("Canceled by user")
        if payload.get("status") == "started":
            name = payload.get("postprocessor") or ""
            if "ExtractAudio" in name:
                job.update(message="converting_audio")
            elif "Merger" in name:
                job.update(message="merging")
            else:
                job.update(message="postprocessing")
        elif payload.get("status") == "finished":
            job.update(message=None)

    return hook


__all__ = [
    "AUDIO_CODECS",
    "build_format_selector",
    "classify_error",
    "probe",
    "run_download",
]
