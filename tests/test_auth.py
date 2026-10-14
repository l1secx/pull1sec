"""Credential storage, the challenge/response handshake and session handling."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from pull1sec.auth import (
    ALGORITHM,
    DERIVED_KEY_BYTES,
    ITERATIONS,
    AuthNotConfigured,
    AuthStorageError,
    AuthStore,
    PasswordPolicyError,
    derive_proof,
    derive_verifier,
    validate_password,
    validate_username,
)
from pull1sec.utils import describe_user_agent, is_loopback_host, server_urls

PASSWORD = "supersecret1"
USER = "kerem"


@pytest.fixture()
def store(tmp_path: Path) -> AuthStore:
    return AuthStore(tmp_path / "auth.json")


@pytest.fixture()
def configured(store: AuthStore) -> AuthStore:
    store.set_credentials(USER, PASSWORD)
    return store


# ------------------------------------------------------------------- hashing


def test_derivation_is_deterministic() -> None:
    salt = b"0123456789abcdef"
    assert derive_verifier(PASSWORD, salt) == derive_verifier(PASSWORD, salt)
    assert len(derive_verifier(PASSWORD, salt)) == DERIVED_KEY_BYTES


def test_different_salts_give_different_verifiers() -> None:
    assert derive_verifier(PASSWORD, b"a" * 16) != derive_verifier(PASSWORD, b"b" * 16)


def test_proof_is_not_the_stored_verifier() -> None:
    """A proof captured off the wire must not work as a credential."""
    salt = b"0123456789abcdef"
    verifier = derive_verifier(PASSWORD, salt)
    proof = derive_proof(verifier, b"nonce-value", ITERATIONS)
    assert proof != verifier


def test_proof_changes_with_the_nonce() -> None:
    verifier = derive_verifier(PASSWORD, b"0123456789abcdef")
    assert derive_proof(verifier, b"nonce-one", 1000) != derive_proof(verifier, b"nonce-two", 1000)


def test_password_policy() -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password("")
    with pytest.raises(PasswordPolicyError):
        validate_password("short")
    with pytest.raises(PasswordPolicyError):
        validate_password(USER, username=USER)
    with pytest.raises(PasswordPolicyError):
        validate_password("x" * 500)
    validate_password("longenough1")


def test_username_policy() -> None:
    assert validate_username("  kerem  ") == "kerem"
    for bad in ("", "   ", "with space", "x" * 100):
        with pytest.raises(Exception):
            validate_username(bad)


# ------------------------------------------------------------------ storage


def test_unconfigured_store_reports_itself(store: AuthStore) -> None:
    assert store.configured is False
    assert store.username is None
    assert store.metadata()["configured"] is False
    assert store.resolve_session("anything") is None
    with pytest.raises(AuthNotConfigured):
        store.create_challenge()


def test_credentials_round_trip(store: AuthStore) -> None:
    store.set_credentials(USER, PASSWORD)
    assert store.configured is True
    assert store.username == USER
    assert store.verify_password(USER, PASSWORD) is True
    assert store.verify_password(USER, "wrong-password") is False
    assert store.verify_password("someone-else", PASSWORD) is False


def test_password_is_not_written_to_disk(configured: AuthStore) -> None:
    raw = configured.path.read_text(encoding="utf-8")
    assert PASSWORD not in raw
    payload = json.loads(raw)
    assert payload["algorithm"] == ALGORITHM
    assert payload["iterations"] == ITERATIONS
    assert "verifier" in payload and "salt" in payload
    # The verifier is not a hash of the password we can reverse, and it is not
    # the password itself.
    assert payload["verifier"] != PASSWORD


def test_state_file_is_private(configured: AuthStore) -> None:
    assert (configured.path.stat().st_mode & 0o777) == 0o600
    assert (configured.path.parent.stat().st_mode & 0o777) == 0o700


def test_corrupt_state_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(AuthStorageError):
        AuthStore(path)


def test_clear_removes_everything(configured: AuthStore) -> None:
    configured.clear()
    assert configured.configured is False
    assert not configured.path.exists()


# --------------------------------------------------------------- handshake


def test_challenge_reveals_no_secret(configured: AuthStore) -> None:
    challenge = configured.create_challenge()
    assert challenge["algorithm"] == ALGORITHM
    assert challenge["iterations"] == ITERATIONS
    assert len(challenge["nonce"]) >= 32
    raw = json.dumps(challenge)
    assert PASSWORD not in raw
    assert configured._data["verifier"] not in raw
    assert "username" not in challenge


def test_valid_proof_is_accepted(configured: AuthStore) -> None:
    challenge = configured.create_challenge()
    verifier = derive_verifier(PASSWORD, bytes.fromhex(challenge["salt"]), challenge["iterations"])
    proof = derive_proof(verifier, bytes.fromhex(challenge["nonce"]), challenge["iterations"])
    assert configured.verify_proof(USER, challenge["nonce"], proof.hex()) is True


def test_proof_is_single_use(configured: AuthStore) -> None:
    challenge = configured.create_challenge()
    verifier = derive_verifier(PASSWORD, bytes.fromhex(challenge["salt"]), challenge["iterations"])
    proof = derive_proof(verifier, bytes.fromhex(challenge["nonce"]), challenge["iterations"]).hex()
    assert configured.verify_proof(USER, challenge["nonce"], proof) is True
    # Replaying the very same proof must fail: the nonce was consumed.
    assert configured.verify_proof(USER, challenge["nonce"], proof) is False


def test_stored_verifier_is_rejected_as_a_proof(configured: AuthStore) -> None:
    """Pass-the-hash: the on-disk secret must not authenticate on its own."""
    challenge = configured.create_challenge()
    verifier = configured._data["verifier"]
    assert configured.verify_proof(USER, challenge["nonce"], verifier) is False


def test_wrong_proof_and_unknown_nonce_are_rejected(configured: AuthStore) -> None:
    challenge = configured.create_challenge()
    assert configured.verify_proof(USER, challenge["nonce"], "ab" * 32) is False
    assert configured.verify_proof(USER, "never-issued", "ab" * 32) is False
    assert configured.verify_proof(USER, challenge["nonce"], "not-hex") is False
    assert configured.verify_proof("someone-else", challenge["nonce"], "ab" * 32) is False


def test_expired_nonce_is_rejected(configured: AuthStore) -> None:
    challenge = configured.create_challenge()
    configured._pending_nonces[challenge["nonce"]] = time.time() - 1
    verifier = derive_verifier(PASSWORD, bytes.fromhex(challenge["salt"]), challenge["iterations"])
    proof = derive_proof(verifier, bytes.fromhex(challenge["nonce"]), challenge["iterations"]).hex()
    assert configured.verify_proof(USER, challenge["nonce"], proof) is False


# ---------------------------------------------------------------- sessions


def test_session_lifecycle(configured: AuthStore) -> None:
    token, session = configured.create_session(ttl_seconds=3600, user_agent="Firefox/1", address="192.168.1.9")
    assert configured.resolve_session(token).id == session.id
    assert configured.revoke_session(token) is True
    assert configured.resolve_session(token) is None
    assert configured.revoke_session(token) is False


def test_session_token_is_not_stored_in_clear(configured: AuthStore) -> None:
    token, _ = configured.create_session(ttl_seconds=3600)
    raw = configured.path.read_text(encoding="utf-8")
    assert token not in raw
    assert configured.resolve_session(token) is not None


def test_expired_session_does_not_resolve(configured: AuthStore) -> None:
    token, session = configured.create_session(ttl_seconds=3600)
    for raw in configured._sessions():
        if raw["id"] == session.id:
            raw["expires_at"] = time.time() - 1
    assert configured.resolve_session(token) is None


def test_revoke_all_closes_everything(configured: AuthStore) -> None:
    first, _ = configured.create_session(ttl_seconds=3600, address="10.0.0.1")
    second, _ = configured.create_session(ttl_seconds=3600, address="10.0.0.2")
    assert len(configured.list_sessions()) == 2
    assert configured.revoke_all() == 2
    assert configured.resolve_session(first) is None
    assert configured.resolve_session(second) is None
    assert configured.list_sessions() == []


def test_changing_the_password_revokes_sessions(configured: AuthStore) -> None:
    token, _ = configured.create_session(ttl_seconds=3600)
    configured.set_credentials(USER, "another-secret1")
    assert configured.resolve_session(token) is None
    assert configured.verify_password(USER, "another-secret1") is True
    assert configured.verify_password(USER, PASSWORD) is False


def test_keep_sessions_flag_is_honoured(configured: AuthStore) -> None:
    token, _ = configured.create_session(ttl_seconds=3600)
    configured.set_credentials(USER, "another-secret1", keep_sessions=True)
    assert configured.resolve_session(token) is not None


def test_renaming_the_user_revokes_sessions(configured: AuthStore) -> None:
    token, _ = configured.create_session(ttl_seconds=3600)
    configured.set_credentials("someone", "another-secret1", keep_sessions=True)
    assert configured.resolve_session(token) is None
    assert configured.username == "someone"


def test_session_list_is_capped(configured: AuthStore) -> None:
    for index in range(60):
        configured.create_session(ttl_seconds=3600, address=f"10.0.0.{index}")
    assert len(configured.list_sessions()) <= 50


# --------------------------------------------------------------- throttling


def test_failures_lead_to_a_lockout(store: AuthStore) -> None:
    assert store.lockout_remaining("1.2.3.4") == 0.0
    for _ in range(4):
        assert store.note_failure("1.2.3.4") == 0.0
    assert store.note_failure("1.2.3.4") > 0
    assert store.lockout_remaining("1.2.3.4") > 0
    store.note_success("1.2.3.4")
    assert store.lockout_remaining("1.2.3.4") == 0.0


def test_lockout_grows_but_is_capped(store: AuthStore) -> None:
    for _ in range(6):
        store.note_failure("5.6.7.8")
    first = store.note_failure("5.6.7.8")
    for _ in range(20):
        last = store.note_failure("5.6.7.8")
    assert last >= first
    assert last <= 900


# --------------------------------------------------------- cross-language


def test_browser_crypto_matches_python() -> None:
    """The JS fallback must derive exactly what hashlib derives."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    salt = bytes.fromhex("9f2b3c4d5e6f708192a3b4c5d6e7f809")
    nonce = "5f3d2c1b0a99887766554433221100ffaabbccddeeff0011"
    iterations = 1000
    verifier = derive_verifier("supersecret1", salt, iterations)
    proof = derive_proof(verifier, bytes.fromhex(nonce), iterations)

    script = f"""
    const lib = require({str(Path("pull1sec/static/auth.js").resolve())!r});
    const enc = new TextEncoder();
    const verifier = lib._pbkdf2(enc.encode("supersecret1"), lib.fromHex("9f2b3c4d5e6f708192a3b4c5d6e7f809"), {iterations});
    const proof = lib._pbkdf2(verifier, lib.fromHex("{nonce}"), {iterations});
    console.log(lib.toHex(verifier));
    console.log(lib.toHex(proof));
    """
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=120, check=True
    )
    js_verifier, js_proof = result.stdout.strip().splitlines()

    assert js_verifier == verifier.hex()
    assert js_proof == proof.hex()


# ------------------------------------------------------------------ helpers


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        ("Mozilla/5.0 (Linux; Android 13) Chrome/120", "Chrome · Android"),
        ("Mozilla/5.0 (iPhone) Version/16 Safari/604", "Safari · iPhone"),
        ("Mozilla/5.0 (X11; Linux x86_64) Firefox/121", "Firefox · Linux"),
        (None, "unknown"),
        ("curl/8.4.0", "curl"),
        ("Mozilla/5.0 (Windows NT 10) Edg/120", "Edge · Windows"),
    ],
)
def test_describe_user_agent(agent: str | None, expected: str) -> None:
    assert describe_user_agent(agent) == expected


def test_server_urls() -> None:
    assert server_urls("127.0.0.1", 8787)["lan"] == []
    assert server_urls("0.0.0.0", 8787)["local"] == ["http://127.0.0.1:8787"]
    assert is_loopback_host("localhost") is True
    assert is_loopback_host("0.0.0.0") is False
