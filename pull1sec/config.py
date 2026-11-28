"""Runtime configuration, read once from the environment.

Every knob is optional; the defaults are tuned for a single-user machine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_PREFIX = "PULL1SEC_"

#: Browsers yt-dlp can read session cookies from. Used to unlock private,
#: age-gated or login-walled posts (Instagram, some TikTok/Facebook content).
SUPPORTED_COOKIE_BROWSERS: tuple[str, ...] = (
    "chrome",
    "chromium",
    "firefox",
    "edge",
    "brave",
    "opera",
    "vivaldi",
    "safari",
    "whale",
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(f"{ENV_PREFIX}{name}")
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(f"{ENV_PREFIX}{name}")
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(f"{ENV_PREFIX}{name}")
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _default_download_dir() -> Path:
    raw = os.getenv(f"{ENV_PREFIX}DOWNLOAD_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    # Keep downloads in the user's data directory, not next to the source:
    # installed copies live in a read-only-ish cache dir (npm/curl installers).
    base = os.getenv("XDG_DATA_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return (root / "pull1sec" / "downloads").resolve()


def _default_state_dir() -> Path:
    """Credentials live outside the repo, under the XDG state directory."""
    raw = os.getenv(f"{ENV_PREFIX}STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    base = os.getenv("XDG_STATE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    return (root / "pull1sec").resolve()


#: Session lifetimes, in seconds. Persistent logins survive a restart.
SESSION_TTL_PERSISTENT = 30 * 24 * 3600
SESSION_TTL_SHORT = 12 * 3600


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the process configuration."""

    #: Bound to every interface by default: the app is meant to be opened from
    #: another device on the same network. Set PULL1SEC_HOST=127.0.0.1 to keep
    #: it on this machine only.
    host: str = field(default_factory=lambda: os.getenv(f"{ENV_PREFIX}HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8787))
    download_dir: Path = field(default_factory=_default_download_dir)
    state_dir: Path = field(default_factory=_default_state_dir)

    #: How many downloads may run at the same time.
    max_concurrent: int = field(default_factory=lambda: _env_int("MAX_CONCURRENT", 3))
    #: Finished jobs (and their files) are swept after this many seconds.
    job_ttl_seconds: int = field(default_factory=lambda: _env_int("JOB_TTL", 3600))
    #: Hard ceiling for a single download, in megabytes. 0 disables the limit.
    max_filesize_mb: int = field(default_factory=lambda: _env_int("MAX_FILESIZE_MB", 0))

    #: Metadata extraction timeout, seconds.
    probe_timeout: float = field(default_factory=lambda: _env_float("PROBE_TIMEOUT", 60.0))
    #: Abort a download that makes no progress for this many seconds.
    socket_timeout: float = field(default_factory=lambda: _env_float("SOCKET_TIMEOUT", 30.0))

    #: When false, URLs that resolve to a private/loopback address are refused,
    #: which keeps the JSON API from being used as an SSRF proxy.
    allow_private_hosts: bool = field(default_factory=lambda: _env_bool("ALLOW_PRIVATE_HOSTS", False))

    #: Refuse to serve on a network interface when no account exists. Overriding
    #: this exposes the whole API to anyone on the LAN.
    require_auth: bool = field(default_factory=lambda: _env_bool("REQUIRE_AUTH", True))
    #: Remember-me lifetime for a browser login.
    session_ttl_seconds: int = field(
        default_factory=lambda: _env_int("SESSION_TTL", SESSION_TTL_PERSISTENT)
    )

    @property
    def auth_path(self) -> Path:
        return self.state_dir / "auth.json"

    def ensure_dirs(self) -> None:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.state_dir, 0o700)
        except OSError:
            pass


settings = Settings()

