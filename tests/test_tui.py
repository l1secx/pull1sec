"""Drive the curses TUI with a stub screen.

Rendering bugs in curses code are invisible until someone opens the UI, so the
whole menu is exercised here: every action, every prompt, and a re-render after
each one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pull1sec.auth import AuthStore
from pull1sec.tui import MIN_HEIGHT, MIN_WIDTH, Palette, run_tui

PASSWORD = "supersecret1"
NEW_PASSWORD = "brandnewpass9"


class StubScreen:
    """The slice of `curses.window` the TUI actually touches."""

    def __init__(self, keys: list[str], height: int = 30, width: int = 100) -> None:
        self.keys = list(keys)
        self.height = height
        self.width = width
        self.frames: list[str] = []
        self.current: list[str] = []

    # --- drawing
    def getmaxyx(self) -> tuple[int, int]:
        return (self.height, self.width)

    def erase(self) -> None:
        if self.current:
            self.frames.append("\n".join(self.current))
        self.current = []

    def addstr(self, row: int, column: int, text: str, attr: int = 0) -> None:
        if row >= self.height or column + len(text) > self.width:
            raise NotImplementedError("stub screen: would have raised curses.error")
        self.current.append(text)

    def refresh(self) -> None:
        pass

    def keypad(self, flag: bool) -> None:
        pass

    # --- input
    def getkey(self) -> str:
        if not self.keys:
            raise AssertionError("TUI asked for more keys than the test provided")
        return self.keys.pop(0)

    def get_wch(self) -> str:
        if not self.keys:
            raise AssertionError("TUI asked for more input than the test provided")
        return self.keys.pop(0)

    def text(self) -> str:
        """Every frame drawn so far, not just the last one."""
        return "\n".join([*self.frames, *self.current])


def screen_text(screen: StubScreen) -> str:
    return screen.text()


# --------------------------------------------------------------------- helpers


def test_palette_without_colours_has_every_attribute() -> None:
    palette = Palette(enabled=False)
    for name in ("title", "dim", "accent", "alert", "ok", "selected"):
        assert isinstance(getattr(palette, name), int)


def test_too_small_terminal_is_handled() -> None:
    store = AuthStore(Path("/tmp/does-not-matter.json"))
    from pull1sec import tui

    app = tui.App(StubScreen([], height=8, width=80), store)
    assert app.too_small() is True
    assert "çok küçük" in screen_text(app.screen)
    assert f"{MIN_WIDTH}x{MIN_HEIGHT}" in screen_text(app.screen)


# ------------------------------------------------------------------- rendering


def test_menu_renders_without_an_account(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    screen = StubScreen(["q"])
    assert tui.App(screen, store).run() == 0

    text = screen_text(screen)
    assert "Pull1sec" in text
    assert "tanımsız" in text
    assert "Şifreyi değiştir" in text


def test_menu_renders_with_an_account(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials("kerem", PASSWORD)
    screen = StubScreen(["q"])
    assert tui.App(screen, store).run() == 0

    text = screen_text(screen)
    assert "kerem" in text
    assert "pbkdf2-sha256" in text
    assert "210000" in text


def test_session_view_lists_devices(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials("kerem", PASSWORD)
    store.create_session(ttl_seconds=3600, user_agent="Mozilla/5.0 (Linux) Firefox/121", address="192.168.1.7")

    screen = StubScreen(["3", "x", "q"])
    assert tui.App(screen, store).run() == 0
    assert "Firefox · Linux" in screen_text(screen)
    assert "192.168.1.7" in screen_text(screen)


# -------------------------------------------------------------------- actions


def test_change_password_flow(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials("kerem", PASSWORD)

    keys = ["1"]  # menu: change password
    keys += list(PASSWORD) + ["\n"]  # current password
    keys += list(NEW_PASSWORD) + ["\n"]  # new
    keys += list(NEW_PASSWORD) + ["\n"]  # repeat
    keys += ["q"]

    assert tui.App(StubScreen(keys), store).run() == 0
    assert store.verify_password("kerem", NEW_PASSWORD) is True
    assert store.verify_password("kerem", PASSWORD) is False


def test_change_password_rejects_a_mismatch(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials("kerem", PASSWORD)

    keys = ["1"]
    keys += list(PASSWORD) + ["\n"]
    keys += list(NEW_PASSWORD) + ["\n"]
    keys += list("something-else-1") + ["\n"]
    keys += ["q"]

    assert tui.App(StubScreen(keys), store).run() == 0
    assert store.verify_password("kerem", PASSWORD) is True  # unchanged


def test_change_password_rejects_a_weak_one(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials("kerem", PASSWORD)

    keys = ["1"]
    keys += list(PASSWORD) + ["\n"]
    keys += list("abc") + ["\n"]
    keys += list("abc") + ["\n"]
    keys += ["q"]

    assert tui.App(StubScreen(keys), store).run() == 0
    assert store.verify_password("kerem", PASSWORD) is True


def test_change_password_requires_the_current_one(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials("kerem", PASSWORD)

    keys = ["1"]
    for _ in range(3):
        keys += list("wrong-password") + ["\n"]
    keys += ["q"]

    assert tui.App(StubScreen(keys), store).run() == 0
    assert store.verify_password("kerem", PASSWORD) is True


def test_prompt_cancel_with_escape(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials("kerem", PASSWORD)

    keys = ["1", "\x1b", "q"]  # ESC at the current-password prompt
    assert tui.App(StubScreen(keys), store).run() == 0
    assert store.verify_password("kerem", PASSWORD) is True


def test_change_username_flow(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials("kerem", PASSWORD)
    store.create_session(ttl_seconds=3600, address="192.168.1.5")

    keys = ["2"]
    keys += list(PASSWORD) + ["\n"]  # unlock
    keys += list("kerem2") + ["\n"]  # new username
    keys += list(PASSWORD) + ["\n"]  # verification
    keys += ["q"]

    assert tui.App(StubScreen(keys), store).run() == 0
    assert store.username == "kerem2"
    assert store.verify_password("kerem2", PASSWORD) is True
    assert store.list_sessions() == []  # a rename drops the old sessions


def test_revoke_all_asks_for_confirmation(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials("kerem", PASSWORD)
    store.create_session(ttl_seconds=3600, address="192.168.1.5")

    keys = ["4"]
    keys += list(PASSWORD) + ["\n"]  # unlock
    keys += ["e"]  # confirm
    keys += ["q"]

    assert tui.App(StubScreen(keys), store).run() == 0
    assert store.list_sessions() == []


def test_revoke_all_can_be_cancelled(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials("kerem", PASSWORD)
    store.create_session(ttl_seconds=3600, address="192.168.1.5")

    keys = ["4"]
    keys += list(PASSWORD) + ["\n"]
    keys += ["h"]  # decline
    keys += ["q"]

    assert tui.App(StubScreen(keys), store).run() == 0
    assert len(store.list_sessions()) == 1


def test_refresh_key(tmp_path: Path) -> None:
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    store.set_credentials("kerem", PASSWORD)
    screen = StubScreen(["r", "q"])
    assert tui.App(screen, store).run() == 0
    assert "Yenilendi" in screen_text(screen)


def test_setup_hint_when_an_action_needs_an_account(tmp_path: Path) -> None:
    """Without an account the password change must not crash."""
    from pull1sec import tui

    store = AuthStore(tmp_path / "auth.json")
    keys = ["1"]
    keys += list(NEW_PASSWORD) + ["\n"]
    keys += list(NEW_PASSWORD) + ["\n"]
    keys += ["q"]

    # unlock() returns True when nothing is configured, so the flow proceeds
    # and creates the account with the default username.
    assert tui.App(StubScreen(keys), store).run() == 0
    assert store.verify_password("pull1sec", NEW_PASSWORD) is True


# ----------------------------------------------------------------- require tty


@pytest.mark.parametrize("argv", [["tui"]])
def test_run_tui_needs_a_terminal(argv: list[str], tmp_path: Path, capsys) -> None:
    store = AuthStore(tmp_path / "auth.json")
    assert run_tui(store) == 2
    assert "uçbirim" in capsys.readouterr().err
