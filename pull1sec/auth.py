"""Authentication for Pull1sec.

One local account, no registration. The password is never stored and never
sent over the wire:

* **At rest** the on-disk verifier is ``PBKDF2-SHA256(password, salt)`` — a
  one-way, salted derivation. Losing the file does not reveal the password.
* **On the wire** the client proves knowledge of the password with a
  challenge/response: it derives the verifier locally, mixes it with a
  single-use server nonce, and sends only that proof. A passive listener on
  plain HTTP therefore learns nothing reusable, and the stored verifier is
  never accepted as a bearer credential (the nonce is mixed in each time).

This matters because the app is served over plain HTTP on a LAN.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALGORITHM = "pbkdf2-sha256"
ITERATIONS = 210_000
DERIVED_KEY_BYTES = 32
SALT_BYTES = 16

NONCE_TTL_SECONDS = 120
SESSION_COOKIE = "pull1sec_session"

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
MAX_USERNAME_LENGTH = 64

LOCKOUT_THRESHOLD = 5
LOCKOUT_BASE_SECONDS = 30
LOCKOUT_MAX_SECONDS = 900

STATE_VERSION = 1


class AuthError(Exception):
    """Anything the auth layer refuses to do."""


class AuthNotConfigured(AuthError):
    """No account exists yet; the credential must be created from the CLI/TUI."""


class AuthStorageError(AuthError):
    """The credential file is missing or unreadable/corrupt."""


class PasswordPolicyError(AuthError):
    """The supplied password does not meet the minimum policy."""


# --------------------------------------------------------------------- hashing


def derive_verifier(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    """One-way derivation of the password. This is what we store."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=DERIVED_KEY_BYTES,
    )


def derive_proof(verifier: bytes, nonce: bytes, iterations: int = ITERATIONS) -> bytes:
    """Mix the verifier with a single-use nonce to produce the wire proof."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        verifier,
        nonce,
        iterations,
        dklen=DERIVED_KEY_BYTES,
    )


def validate_password(password: str, *, username: str | None = None) -> None:
    """Raise :class:`PasswordPolicyError` when the password is unusable."""
    if not isinstance(password, str) or not password:
        raise PasswordPolicyError("Şifre boş olamaz.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Şifre en az {MIN_PASSWORD_LENGTH} karakter olmalı."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError("Şifre çok uzun.")
    if username and password.lower() == username.lower():
        raise PasswordPolicyError("Şifre kullanıcı adıyla aynı olamaz.")


def validate_username(username: str) -> str:
    cleaned = (username or "").strip()
    if not cleaned:
        raise AuthError("Kullanıcı adı boş olamaz.")
    if len(cleaned) > MAX_USERNAME_LENGTH:
        raise AuthError(f"Kullanıcı adı en fazla {MAX_USERNAME_LENGTH} karakter olabilir.")
    if any(character.isspace() for character in cleaned):
        raise AuthError("Kullanıcı adı boşluk içeremez.")
    return cleaned


# ---------------------------------------------------------------------- models


@dataclass
class Session:
    """A logged-in browser. Only a hash of the cookie token is persisted."""

    id: str
    token_hash: str
    created_at: float
    expires_at: float
    last_seen_at: float
    user_agent: str | None = None
    address: str | None = None

    @property
    def expired(self) -> bool:
        return self.expires_at <= time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "token_hash": self.token_hash,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_seen_at": self.last_seen_at,
            "user_agent": self.user_agent,
            "address": self.address,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Session":
        return cls(
            id=raw["id"],
            token_hash=raw["token_hash"],
            created_at=float(raw["created_at"]),
            expires_at=float(raw["expires_at"]),
            last_seen_at=float(raw.get("last_seen_at") or raw["created_at"]),
            user_agent=raw.get("user_agent"),
            address=raw.get("address"),
        )


@dataclass
class _Throttle:
    failures: int = 0
    locked_until: float = 0.0
    last_failure: float = 0.0


# ----------------------------------------------------------------------- store


class AuthStore:
    """Credential + session storage backed by a single JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._pending_nonces: dict[str, float] = {}
        self._throttle: dict[str, _Throttle] = {}
        self._data: dict[str, Any] = self._read()

    # ------------------------------------------------------------ persistence

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthStorageError(
                f"{self.path} okunamadı: {exc}. "
                "Dosyayı kenara alıp `pull1sec user set` komutunu tekrar çalıştır."
            ) from exc
        if not isinstance(raw, dict):
            raise AuthStorageError(f"{self.path} bozuk görünüyor.")
        return raw

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        payload = json.dumps(self._data, indent=2, sort_keys=True)
        temp = self.path.with_name(f".{self.path.name}.tmp")
        temp.write_text(payload, encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, self.path)

    # -------------------------------------------------------------- credential

    @property
    def configured(self) -> bool:
        return bool(self._data.get("verifier") and self._data.get("salt"))

    @property
    def username(self) -> str | None:
        return self._data.get("username") or None

    def metadata(self) -> dict[str, Any]:
        """Everything except the secret parts."""
        if not self.configured:
            return {"configured": False, "path": str(self.path)}
        return {
            "configured": True,
            "path": str(self.path),
            "username": self._data.get("username"),
            "algorithm": self._data.get("algorithm", ALGORITHM),
            "iterations": self._data.get("iterations", ITERATIONS),
            "created_at": self._data.get("created_at"),
            "updated_at": self._data.get("updated_at"),
            "sessions": len(self._data.get("sessions") or []),
        }

    def set_credentials(
        self,
        username: str,
        password: str,
        *,
        keep_sessions: bool = False,
    ) -> None:
        """Create or replace the account. Revokes sessions unless asked not to."""
        username = validate_username(username)
        validate_password(password, username=username)

        salt = secrets.token_bytes(SALT_BYTES)
        verifier = derive_verifier(password, salt)
        now = time.time()
        changed_user = self._data.get("username") != username

        with self._lock:
            # Changing the password or the user invalidates every existing login.
            keep = keep_sessions and not changed_user
            sessions = list(self._data.get("sessions") or []) if keep else []
            self._data = {
                "version": STATE_VERSION,
                "username": username,
                "algorithm": ALGORITHM,
                "iterations": ITERATIONS,
                "salt": salt.hex(),
                "verifier": verifier.hex(),
                "created_at": self._data.get("created_at") or now,
                "updated_at": now,
                "sessions": sessions,
            }
            self._pending_nonces.clear()
            self._write()

    def password_salt(self) -> tuple[bytes, int]:
        if not self.configured:
            raise AuthNotConfigured("No account is configured yet.")
        return bytes.fromhex(self._data["salt"]), int(self._data.get("iterations") or ITERATIONS)

    def verify_password(self, username: str, password: str) -> bool:
        """Direct check, used by the CLI and the TUI (no nonce involved)."""
        if not self.configured:
            return False
        salt, iterations = self.password_salt()
        expected = bytes.fromhex(self._data["verifier"])
        candidate = derive_verifier(password, salt, iterations)
        user_ok = hmac.compare_digest(
            (self.username or "").encode(), (username or "").encode()
        )
        return user_ok and hmac.compare_digest(expected, candidate)

    def clear(self) -> None:
        with self._lock:
            self._data = {}
            self._pending_nonces.clear()
            if self.path.exists():
                self.path.unlink()

    # ----------------------------------------------------------------- nonces

    def create_challenge(self) -> dict[str, Any]:
        """Hand the client what it needs to build a proof."""
        if not self.configured:
            raise AuthNotConfigured("No account is configured yet.")
        salt, iterations = self.password_salt()
        nonce = secrets.token_hex(24)
        with self._lock:
            self._prune_nonces()
            self._pending_nonces[nonce] = time.time() + NONCE_TTL_SECONDS
        return {
            "nonce": nonce,
            "salt": salt.hex(),
            "iterations": iterations,
            "algorithm": ALGORITHM,
        }

    def _prune_nonces(self) -> None:
        now = time.time()
        for nonce, expiry in list(self._pending_nonces.items()):
            if expiry <= now:
                del self._pending_nonces[nonce]

    def verify_proof(self, username: str, nonce: str, proof: str) -> bool:
        """Validate a challenge response. The nonce is consumed either way."""
        if not self.configured:
            return False
        with self._lock:
            self._prune_nonces()
            known = self._pending_nonces.pop(nonce or "", None)
        if known is None:
            return False

        try:
            proof_bytes = bytes.fromhex(proof or "")
            # The browser decodes the nonce the same way; see auth.js.
            nonce_bytes = bytes.fromhex(nonce or "")
        except ValueError:
            return False
        if len(proof_bytes) != DERIVED_KEY_BYTES:
            return False

        iterations = int(self._data.get("iterations") or ITERATIONS)
        verifier = bytes.fromhex(self._data["verifier"])
        expected = derive_proof(verifier, nonce_bytes, iterations)

        user_ok = hmac.compare_digest(
            (self.username or "").encode(), (username or "").encode()
        )
        return user_ok and hmac.compare_digest(expected, proof_bytes)

    # --------------------------------------------------------------- sessions

    def _sessions(self) -> list[dict[str, Any]]:
        sessions = self._data.get("sessions")
        if not isinstance(sessions, list):
            sessions = []
            self._data["sessions"] = sessions
        return sessions

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def create_session(
        self,
        *,
        ttl_seconds: int,
        user_agent: str | None = None,
        address: str | None = None,
    ) -> tuple[str, Session]:
        if not self.configured:
            raise AuthNotConfigured("No account is configured yet.")
        token = secrets.token_urlsafe(32)
        now = time.time()
        session = Session(
            id=secrets.token_hex(6),
            token_hash=self._hash_token(token),
            created_at=now,
            expires_at=now + max(60, ttl_seconds),
            last_seen_at=now,
            user_agent=(user_agent or "")[:200] or None,
            address=address,
        )
        with self._lock:
            self.prune_sessions()
            sessions = self._sessions()
            # Keep the list bounded; the oldest entries go first.
            if len(sessions) >= 50:
                sessions.sort(key=lambda item: item.get("last_seen_at") or 0, reverse=True)
                del sessions[20:]
            sessions.append(session.to_dict())
            self._write()
        return token, session

    def resolve_session(self, token: str | None) -> Session | None:
        if not token or not self.configured:
            return None
        digest = self._hash_token(token)
        with self._lock:
            for raw in self._sessions():
                if hmac.compare_digest(raw.get("token_hash", ""), digest):
                    session = Session.from_dict(raw)
                    if session.expired:
                        return None
                    return session
        return None

    def touch_session(self, session: Session) -> None:
        """Record activity without rewriting the file on every request."""
        session.last_seen_at = time.time()
        if int(session.last_seen_at) % 30 != 0:
            return
        with self._lock:
            for raw in self._sessions():
                if raw.get("id") == session.id:
                    raw["last_seen_at"] = session.last_seen_at
                    self._write()
                    return

    def revoke_session(self, token: str) -> bool:
        digest = self._hash_token(token)
        with self._lock:
            sessions = self._sessions()
            for index, raw in enumerate(sessions):
                if hmac.compare_digest(raw.get("token_hash", ""), digest):
                    del sessions[index]
                    self._write()
                    return True
        return False

    def revoke_all(self) -> int:
        with self._lock:
            count = len(self._sessions())
            self._data["sessions"] = []
            if self.configured:
                self._write()
        return count

    def list_sessions(self) -> list[Session]:
        with self._lock:
            self.prune_sessions()
            sessions = [Session.from_dict(raw) for raw in self._sessions()]
        return sorted(sessions, key=lambda item: item.last_seen_at, reverse=True)

    def prune_sessions(self) -> int:
        with self._lock:
            sessions = self._sessions()
            alive = [raw for raw in sessions if float(raw.get("expires_at") or 0) > time.time()]
            removed = len(sessions) - len(alive)
            if removed:
                self._data["sessions"] = alive
                self._write()
            return removed

    # -------------------------------------------------------------- throttling

    def lockout_remaining(self, key: str) -> float:
        state = self._throttle.get(key)
        if state is None:
            return 0.0
        return max(0.0, state.locked_until - time.time())

    def note_failure(self, key: str) -> float:
        """Record a failed attempt and return the lockout, if any, in seconds."""
        state = self._throttle.setdefault(key, _Throttle())
        state.failures += 1
        state.last_failure = time.time()
        if state.failures >= LOCKOUT_THRESHOLD:
            over = state.failures - LOCKOUT_THRESHOLD
            delay = min(LOCKOUT_MAX_SECONDS, LOCKOUT_BASE_SECONDS * (2**over))
            state.locked_until = time.time() + delay
            return float(delay)
        return 0.0

    def note_success(self, key: str) -> None:
        self._throttle.pop(key, None)
