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


# ------------------------------------------------------------------- network


#: Prefixes of interfaces that never accept a phone on the wifi.
VIRTUAL_INTERFACE_PREFIXES = (
    "docker",
    "br-",
    "veth",
    "virbr",
    "vmnet",
    "vboxnet",
    "tun",
    "tap",
    "wg",
    "zt",
    "tailscale",
    "podman",
    "cni",
    "dummy",
)


def _primary_address() -> str | None:
    """The address of the interface carrying the default route, if any."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
        return address if not address.startswith("127.") else None
    except OSError:
        return None
    finally:
        probe.close()


def _addresses_from_ip_command() -> list[str]:
    """Ask iproute2, which also tells us the interface name."""
    import shutil
    import subprocess

    if not shutil.which("ip"):
        return []

    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    addresses: list[str] = []
    for line in result.stdout.splitlines():
        # e.g. "3: wlan0    inet 192.168.1.26/24 brd ... scope global wlan0"
        fields = line.split()
        if len(fields) < 4 or fields[2] != "inet":
            continue
        name = fields[1]
        if any(name.startswith(prefix) for prefix in VIRTUAL_INTERFACE_PREFIXES):
            continue
        address = fields[3].split("/")[0]
        if address and not address.startswith("127."):
            addresses.append(address)
    return addresses


def local_ipv4_addresses() -> list[str]:
    """Non-loopback IPv4 addresses, most likely one first.

    The interface carrying the default route comes first: that is the address a
    phone on the same wifi should be given. Bridges for containers and virtual
    machines are skipped unless iproute2 is unavailable.
    """
    primary = _primary_address()

    found = _addresses_from_ip_command()
    if not found:
        try:
            found = [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
        except OSError:
            found = []
        found = [address for address in found if not address.startswith("127.")]

    unique = {address for address in found if not address.startswith("127.")}
    ordered = ([primary] if primary else []) + sorted(unique - {primary})
    return ordered


def is_loopback_host(host: str) -> bool:
    """True when ``host`` keeps the server on this machine only."""
    return host in {"127.0.0.1", "localhost", "::1"}


def server_urls(host: str, port: int) -> dict[str, list[str]]:
    """The addresses this server answers on, split into local and LAN."""
    local = [f"http://127.0.0.1:{port}"]
    lan: list[str] = []
    if not is_loopback_host(host):
        addresses = [host] if host not in {"0.0.0.0", "::"} else local_ipv4_addresses()
        lan = [f"http://{address}:{port}" for address in addresses]
    return {"local": local, "lan": lan}


def describe_user_agent(user_agent: str | None) -> str:
    """Short, human label for a session list, e.g. ``Chrome · Android``."""
    if not user_agent:
        return "unknown"

    browsers = (
        ("Edg/", "Edge"),
        ("OPR/", "Opera"),
        ("Firefox/", "Firefox"),
        ("Chrome/", "Chrome"),
        ("Safari/", "Safari"),
        ("curl/", "curl"),
        ("python-requests", "requests"),
    )
    systems = (
        ("Android", "Android"),
        ("iPhone", "iPhone"),
        ("iPad", "iPad"),
        ("Windows", "Windows"),
        ("Macintosh", "macOS"),
        ("Linux", "Linux"),
    )

    browser = next((label for token, label in browsers if token in user_agent), None)
    if browser is None:
        lowered = user_agent.lower()
        for token, label in browsers:
            if token.lower() in lowered:
                browser = label
                break

    system = next((label for token, label in systems if token in user_agent), None)

    if browser and system:
        return f"{browser} · {system}"
    return browser or "other"

