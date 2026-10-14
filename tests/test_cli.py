"""The command line surface: user management, sessions, serve guardrails.

Every CLI invocation opens the credential file itself, so the tests re-read it
rather than holding one object across calls.
"""

from __future__ import annotations

import dataclasses
import sys
import types
from pathlib import Path

import pytest

from pull1sec import cli
from pull1sec.auth import AuthStore
from pull1sec.config import settings as real_settings

PASSWORD = "supersecret1"
NEW_PASSWORD = "brandnewpass9"


@pytest.fixture()
def auth_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    settings = dataclasses.replace(real_settings, state_dir=state_dir)
    monkeypatch.setattr(cli, "settings", settings)
    import pull1sec.tui as tui

    monkeypatch.setattr(tui, "settings", settings)
    return settings.auth_path


def store(path: Path) -> AuthStore:
    """Read the credential file the way a fresh process would."""
    return AuthStore(path)


def run(*argv: str) -> int:
    return cli.main(list(argv))


def fake_stdin(text: str):
    """A stdin that is not a TTY and yields one line."""
    return type("S", (), {"readline": lambda self: text + "\n", "isatty": lambda self: False})()


# ------------------------------------------------------------------ account


def test_user_set_creates_an_account(auth_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", fake_stdin(PASSWORD))
    assert run("user", "set", "--username", "kerem", "--password-stdin") == 0

    saved = store(auth_path)
    assert saved.configured is True
    assert saved.username == "kerem"
    assert saved.verify_password("kerem", PASSWORD) is True

    out = capsys.readouterr().out
    assert "güncellendi" in out
    assert PASSWORD not in out  # never echoed back


def test_user_set_rejects_a_short_password(auth_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", fake_stdin("abc"))
    assert run("user", "set", "--username", "kerem", "--password-stdin") == 1
    assert store(auth_path).configured is False
    assert "en az 8 karakter" in capsys.readouterr().err


def test_user_set_rejects_the_username_as_password(auth_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", fake_stdin("kerem"))
    assert run("user", "set", "--username", "kerem", "--password-stdin") == 1
    assert store(auth_path).configured is False


def test_user_set_requires_force_when_an_account_exists(
    auth_path: Path, monkeypatch, capsys
) -> None:
    store(auth_path).set_credentials("kerem", PASSWORD)
    monkeypatch.setattr(sys, "stdin", fake_stdin(NEW_PASSWORD))

    # No TTY here, so the current password cannot be asked for.
    assert run("user", "set", "--password-stdin") == 1
    assert store(auth_path).verify_password("kerem", PASSWORD) is True
    assert "--force" in capsys.readouterr().err

    assert run("user", "set", "--password-stdin", "--force") == 0
    updated = store(auth_path)
    assert updated.verify_password("kerem", NEW_PASSWORD) is True
    assert updated.verify_password("kerem", PASSWORD) is False


def test_changing_the_password_revokes_sessions(auth_path: Path, monkeypatch, capsys) -> None:
    store(auth_path).set_credentials("kerem", PASSWORD)
    store(auth_path).create_session(ttl_seconds=3600, address="192.168.1.5")

    monkeypatch.setattr(sys, "stdin", fake_stdin(NEW_PASSWORD))
    assert run("user", "set", "--password-stdin", "--force") == 0
    assert store(auth_path).list_sessions() == []
    assert "hepsi kapatıldı" in capsys.readouterr().out


def test_keep_sessions_flag(auth_path: Path, monkeypatch) -> None:
    store(auth_path).set_credentials("kerem", PASSWORD)
    store(auth_path).create_session(ttl_seconds=3600, address="192.168.1.5")

    monkeypatch.setattr(sys, "stdin", fake_stdin(NEW_PASSWORD))
    assert run("user", "set", "--password-stdin", "--force", "--keep-sessions") == 0
    assert len(store(auth_path).list_sessions()) == 1


def test_user_show_reports_metadata_without_secrets(auth_path: Path, capsys) -> None:
    store(auth_path).set_credentials("kerem", PASSWORD)
    assert run("user", "show") == 0
    out = capsys.readouterr().out
    assert "kerem" in out
    assert "pbkdf2-sha256" in out
    assert "210000" in out
    assert "0o600" in out
    assert PASSWORD not in out


def test_user_show_when_unconfigured(auth_path: Path, capsys) -> None:
    assert run("user", "show") == 0
    assert "tanımlı değil" in capsys.readouterr().out


def test_user_remove(auth_path: Path, capsys) -> None:
    store(auth_path).set_credentials("kerem", PASSWORD)
    assert run("user", "remove", "--yes") == 0
    assert store(auth_path).configured is False
    assert "silindi" in capsys.readouterr().out


def test_user_remove_without_yes_on_a_pipe(auth_path: Path, capsys) -> None:
    store(auth_path).set_credentials("kerem", PASSWORD)
    assert run("user", "remove") == 1
    assert store(auth_path).configured is True


# ----------------------------------------------------------------- sessions


def test_sessions_list_and_revoke(auth_path: Path, capsys) -> None:
    saved = store(auth_path)
    saved.set_credentials("kerem", PASSWORD)
    saved.create_session(
        ttl_seconds=3600, user_agent="Mozilla/5.0 (Linux) Firefox/121", address="192.168.1.7"
    )
    saved.create_session(
        ttl_seconds=3600, user_agent="Mozilla/5.0 (iPhone) Safari/604", address="192.168.1.8"
    )

    assert run("sessions", "list") == 0
    out = capsys.readouterr().out
    assert "Firefox · Linux" in out
    assert "Safari · iPhone" in out
    assert "192.168.1.7" in out

    assert run("sessions", "revoke-all") == 0
    assert store(auth_path).list_sessions() == []


def test_sessions_list_when_empty(auth_path: Path, capsys) -> None:
    store(auth_path).set_credentials("kerem", PASSWORD)
    assert run("sessions", "list") == 0
    assert "Açık oturum yok" in capsys.readouterr().out


# --------------------------------------------------------------------- misc


def test_url_command(auth_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "settings", dataclasses.replace(cli.settings, host="127.0.0.1", port=1234))
    assert run("url") == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:1234" in out
    assert "(kapalı)" in out


def test_version_command(capsys) -> None:
    assert run("version") == 0
    assert "Pull1sec" in capsys.readouterr().out


def test_serve_refuses_without_an_account_on_a_network_bind(
    auth_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli, "settings", dataclasses.replace(cli.settings, host="0.0.0.0"))

    started: list[bool] = []
    fake = types.ModuleType("uvicorn")
    fake.run = lambda *a, **k: started.append(True)
    monkeypatch.setitem(sys.modules, "uvicorn", fake)

    assert run("serve") == 1
    assert started == []
    assert "pull1sec user set" in capsys.readouterr().out


def test_serve_starts_when_an_account_exists(auth_path: Path, monkeypatch) -> None:
    store(auth_path).set_credentials("kerem", PASSWORD)
    monkeypatch.setattr(cli, "settings", dataclasses.replace(cli.settings, host="0.0.0.0"))

    called: dict[str, object] = {}
    fake = types.ModuleType("uvicorn")
    fake.run = lambda app, **kwargs: called.update(app=app, **kwargs)
    monkeypatch.setitem(sys.modules, "uvicorn", fake)

    assert run("serve") == 0
    assert called["app"] == "pull1sec.main:app"
    assert called["host"] == "0.0.0.0"


def test_bare_invocation_means_serve(monkeypatch) -> None:
    seen: list[str] = []

    def fake_serve(args):
        seen.append("serve")
        return 0

    monkeypatch.setattr(cli, "cmd_serve", fake_serve)
    assert cli.main([]) == 0
    assert seen == ["serve"]


def test_tui_without_a_terminal(auth_path: Path, capsys) -> None:
    assert run("tui") == 2
    assert "uçbirim" in capsys.readouterr().err


def test_corrupt_state_file_is_a_clean_error(tmp_path: Path, monkeypatch, capsys) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "auth.json").write_text("{ broken", encoding="utf-8")
    monkeypatch.setattr(cli, "settings", dataclasses.replace(real_settings, state_dir=state_dir))

    assert run("user", "show") == 1
    assert "okunamadı" in capsys.readouterr().err
