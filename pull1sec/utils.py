"""Small, dependency-free helpers shared across the backend."""

from __future__ import annotations

import ipaddress
import re
import socket
import unicodedata
from urllib.parse import urlsplit, urlunsplit

# Matches things like "www.tiktok.com/..." or "youtu.be/xyz" typed without a scheme.
_SCHEMELESS = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}(?::\d+)?(?:/.*)?$", re.IGNORECASE)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)

# Characters that are illegal in a filename on at least one major OS.
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


class InvalidURLError(ValueError):
    """Raised when a URL cannot be safely used."""


def normalize_url(raw: str) -> str:
    """Return a canonical http(s) URL or raise :class:`InvalidURLError`.

    Accepts a URL that is missing its scheme (``youtube.com/watch?v=...``) and
    upgrades a bare domain to ``https``.
    """
    if not isinstance(raw, str):
        raise InvalidURLError("URL must be a string.")

    candidate = raw.strip()
    if not candidate:
        raise InvalidURLError("Enter a URL.")

    # Strip wrapping quotes/angle brackets people paste in by accident.
    candidate = candidate.strip("\"'<>").strip()

    if not _SCHEME_RE.match(candidate):
        if not _SCHEMELESS.match(candidate):
            raise InvalidURLError("That does not look like a web address.")
        candidate = f"https://{candidate.lstrip('/')}"

    parts = urlsplit(candidate)
    if parts.scheme.lower() not in {"http", "https"}:
        raise InvalidURLError("Only http and https links are supported.")
    if not parts.hostname:
        raise InvalidURLError("That link has no host.")

    # Rebuild without fragments; they never change what the server returns.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def is_public_host(hostname: str) -> bool:
    """True when every address ``hostname`` resolves to is publicly routable."""
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        # Unresolvable now; let yt-dlp produce the real error later.
        return True

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def guard_url(raw: str, *, allow_private_hosts: bool = False) -> str:
    """Normalize ``raw`` and reject links that point inside the local network."""
    url = normalize_url(raw)
    if not allow_private_hosts:
        hostname = urlsplit(url).hostname or ""
        if not is_public_host(hostname):
            raise InvalidURLError("That host is on a private network and is not allowed.")
    return url


def sanitize_filename(name: str, *, fallback: str = "video", max_length: int = 180) -> str:
    """Turn arbitrary text into something safe to put in a ``Content-Disposition``."""
    name = unicodedata.normalize("NFC", name or "")
    name = _UNSAFE_FILENAME.sub(" ", name)
    name = _WHITESPACE.sub(" ", name).strip(" .")
    if not name:
        name = fallback
    if len(name) > max_length:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 5:
            keep = max_length - len(ext) - 1
            name = f"{stem[:keep]}.{ext}"
        else:
            name = name[:max_length]
    return name


def human_bytes(size: float | None) -> str:
    """Compact byte size, e.g. ``248.3 MB``."""
    if not size or size <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    value = float(size)
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:.1f} {units[index]}"


def human_duration(seconds: float | None) -> str:
    """``1:02:03`` / ``4:07`` / empty for unknown durations."""
    if not seconds or seconds < 0:
        return ""
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def platform_label(extractor_key: str | None, extractor: str | None) -> str:
    """Best-effort human name for the site a link belongs to."""
    source = extractor_key or extractor or ""
    source = source.replace("IE", "").strip()
    mapping = {
        "youtube": "YouTube",
        "youtubetab": "YouTube",
        "tiktok": "TikTok",
        "instagram": "Instagram",
        "twitter": "X",
        "facebook": "Facebook",
        "reddit": "Reddit",
        "vimeo": "Vimeo",
        "dailymotion": "Dailymotion",
        "twitch": "Twitch",
        "bilibili": "Bilibili",
        "pinterest": "Pinterest",
        "linkedin": "LinkedIn",
        "snapchat": "Snapchat",
        "threads": "Threads",
        "tumblr": "Tumblr",
        "soundcloud": "SoundCloud",
        "odnoklassniki": "Odnoklassniki",
        "rutube": "RuTube",
        "vk": "VK",
        "weibo": "Weibo",
        "douyin": "Douyin",
        "kick": "Kick",
        "rumble": "Rumble",
        "bitchute": "BitChute",
        "imgur": "Imgur",
        "streamable": "Streamable",
    }
    lowered = source.lower()
    for key, label in mapping.items():
        if lowered.startswith(key):
            return label
    if not source:
        return "Web"
    # "SomeSiteIE" -> "Somesite"
    return source[:1].upper() + source[1:]
