"""Full-screen terminal UI for the account and the server.

Built on the standard library's ``curses`` so there is nothing extra to
install. Every mutation goes through :class:`~pull1sec.auth.AuthStore`, and the
current password is required before the credentials can be changed.
"""

from __future__ import annotations

import curses
import sys
import time

from . import __version__
from .auth import AuthError, AuthNotConfigured, AuthStore, PasswordPolicyError, validate_password
from .config import settings
from .utils import describe_user_agent, server_urls

MIN_HEIGHT = 16
MIN_WIDTH = 62


class Palette:
    """Colour pairs, or plain attributes when the terminal has no colours."""

    def __init__(self, enabled: bool) -> None:
        if not enabled:
            self.title = curses.A_BOLD
            self.dim = curses.A_DIM
            self.accent = curses.A_BOLD
            self.alert = curses.A_BOLD
            self.ok = curses.A_BOLD
            self.selected = curses.A_REVERSE | curses.A_BOLD
            return

        try:
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, curses.COLOR_RED, -1)
            curses.init_pair(4, curses.COLOR_GREEN, -1)
        except curses.error:
            # Terminal without colour support after all.
            self.__init__(False)
            return

        self.title = curses.color_pair(1) | curses.A_BOLD
        self.dim = curses.color_pair(0) | curses.A_DIM
        self.accent = curses.color_pair(2) | curses.A_BOLD
        self.ok = curses.color_pair(4)
        self.alert = curses.color_pair(3) | curses.A_BOLD
        self.selected = curses.color_pair(2) | curses.A_REVERSE | curses.A_BOLD


def terminal_has_colors() -> bool:
    """`curses.has_colors()` without exploding outside a live terminal."""
    try:
        return bool(curses.has_colors())
    except curses.error:
        return False


def set_cursor_visible(visible: bool) -> None:
    """curses only knows about the cursor once initscr() has run."""
    try:
        curses.curs_set(1 if visible else 0)
    except curses.error:
        pass


class App:
    def __init__(self, stdscr: "curses.window", store: AuthStore) -> None:
        self.screen = stdscr
        self.store = store
        self.colours = Palette(terminal_has_colors())
        self.notice = ""
        self.notice_alert = False
        self.view = "menu"  # "menu" or "sessions"
        self.sessions: list = []

    # -------------------------------------------------------------- primitives

    def write(self, row: int, column: int, text: str, attr: int = 0) -> None:
        """Draw rarely: curses raises when the text would touch the last cell."""
        height, width = self.screen.getmaxyx()
        if row < 0 or row >= height or column >= width:
            return
        room = width - column - 1
        if room <= 0:
            return
        try:
            self.screen.addstr(row, column, text[:room], attr)
        except curses.error:
            pass

    def refresh(self) -> None:
        self.screen.refresh()

    def too_small(self) -> bool:
        height, width = self.screen.getmaxyx()
        if height >= MIN_HEIGHT and width >= MIN_WIDTH:
            return False
        self.screen.erase()
        self.write(1, 2, "terminal penceresi çok küçük", self.colours.alert)
        self.write(3, 2, f"en az {MIN_WIDTH}x{MIN_HEIGHT} gerekiyor", self.colours.dim)
        self.write(5, 2, "q ile çık", self.colours.dim)
        self.refresh()
        return True

    def prompt(self, label: str, *, secret: bool = False) -> str | None:
        """Read a line at the bottom. Returns None when the user pressed ESC."""
        height, width = self.screen.getmaxyx()
        row = height - 2
        prompt_label = f" {label} "

        buffer = ""
        set_cursor_visible(True)
        try:
            while True:
                shown = "*" * len(buffer) if secret else buffer
                self.write(row, 0, " " * (width - 1))
                self.write(row, 1, prompt_label, self.colours.accent)
                self.write(row, 1 + len(prompt_label), shown)
                self.refresh()

                try:
                    key = self.screen.get_wch()
                except curses.error:
                    continue

                if not isinstance(key, str):
                    if key == curses.KEY_BACKSPACE:
                        buffer = buffer[:-1]
                    continue
                if key in ("\n", "\r", "\x0a"):
                    self.write(row, 0, " " * (width - 1))
                    return buffer
                if key == "\x1b":  # ESC
                    self.write(row, 0, " " * (width - 1))
                    return None
                if key in ("\x7f", "\x08"):
                    buffer = buffer[:-1]
                elif key.isprintable():
                    buffer += key
        finally:
            set_cursor_visible(False)

    def confirm(self, question: str) -> bool:
        self.write(self.screen.getmaxyx()[0] - 2, 1, question + " [e/H] ", self.colours.alert)
        self.refresh()
        try:
            key = self.screen.getkey()
        except curses.error:
            return False
        return key in ("e", "E", "y", "Y")

    # ------------------------------------------------------------------ render

    def draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()

        self.write(1, 2, f"Pull1sec {__version__}", self.colours.title)
        self.write(1, width - 14, "q  çıkış", self.colours.dim)

        urls = server_urls(settings.host, settings.port)
        target = urls["lan"][0] if urls["lan"] else urls["local"][0]
        label = "ağ adresi " if urls["lan"] else "adres     "

        self.write(3, 2, label, self.colours.dim)
        self.write(3, 14, target, self.colours.ok if urls["lan"] else self.colours.dim)

        if self.store.configured:
            meta = self.store.metadata()
            sessions = len(self.store.list_sessions())
            self.write(4, 2, "kullanıcı ", self.colours.dim)
            self.write(4, 14, f"{meta['username']}   ·   açık oturum {sessions}", 0)

            updated = time.strftime("%d.%m.%Y %H:%M", time.localtime(meta["updated_at"]))
            self.write(5, 2, "şifre     ", self.colours.dim)
            self.write(
                5,
                14,
                f"{meta['algorithm']} · {meta['iterations']} tur · {updated}",
                self.colours.dim,
            )
        else:
            self.write(4, 2, "kullanıcı ", self.colours.dim)
            self.write(4, 14, "tanımsız — önce şifre belirle (2)", self.colours.alert)

        self.write(7, 2, "─" * (width - 4), self.colours.dim)

        if self.view == "sessions":
            self.draw_sessions()
        else:
            self.draw_menu()

        if self.notice:
            attr = self.colours.alert if self.notice_alert else self.colours.ok
            self.write(height - 3, 2, self.notice, attr)

        self.write(height - 1, 2, "seçim: ", self.colours.dim)
        self.refresh()

    def draw_menu(self) -> None:
        items = [
            ("1", "Şifreyi değiştir"),
            ("2", "Kullanıcı adını değiştir"),
            ("3", "Oturumları görüntüle"),
            ("4", "Tüm oturumları kapat"),
            ("r", "Yenile"),
        ]
        for index, (key, label) in enumerate(items):
            row = 9 + index
            self.write(row, 4, key, self.colours.accent)
            self.write(row, 8, label, 0)

    def draw_sessions(self) -> None:
        self.write(9, 2, "Açık oturumlar", self.colours.title)
        self.write(9, 40, "herhangi bir tuş: geri", self.colours.dim)

        if not self.sessions:
            self.write(11, 4, "Kayıtlı oturum yok.", self.colours.dim)
            return

        self.write(11, 4, f"{'cihaz':<22}{'adres':<17}{'son görülme'}", self.colours.dim)
        for index, session in enumerate(self.sessions[:10]):
            row = 12 + index
            device = describe_user_agent(session.user_agent)[:21]
            address = (session.address or "—")[:16]
            seen = time.strftime("%d.%m %H:%M", time.localtime(session.last_seen_at))
            self.write(row, 4, f"{device:<22}{address:<17}{seen}")

    # ----------------------------------------------------------------- actions

    def unlock(self) -> bool:
        """Ask for the current password before any credential change."""
        if not self.store.configured:
            return True
        for _ in range(3):
            password = self.prompt("Mevcut şifre:", secret=True)
            if password is None:
                self.set_notice("İptal edildi.")
                return False
            if self.store.verify_password(self.store.username or "", password):
                return True
            self.set_notice("Yanlış şifre.", alert=True)
        return False

    def set_notice(self, message: str, *, alert: bool = False) -> None:
        self.notice = message
        self.notice_alert = alert

    def change_password(self) -> None:
        if not self.unlock():
            return

        password = self.prompt("Yeni şifre:", secret=True)
        if password is None:
            self.set_notice("İptal edildi.")
            return
        repeat = self.prompt("Yeni şifre (tekrar):", secret=True)
        if repeat is None:
            self.set_notice("İptal edildi.")
            return
        if password != repeat:
            self.set_notice("Şifreler aynı değil.", alert=True)
            return

        try:
            validate_password(password, username=self.store.username)
        except PasswordPolicyError as exc:
            self.set_notice(str(exc), alert=True)
            return

        username = self.store.username or "pull1sec"
        try:
            self.store.set_credentials(username, password)
        except AuthError as exc:
            self.set_notice(str(exc), alert=True)
            return
        self.set_notice("Şifre güncellendi. Tüm cihazlar çıkış yaptı.")

    def change_username(self) -> None:
        if not self.unlock():
            return

        current = self.store.username or ""
        username = self.prompt(f"Yeni kullanıcı adı [{current}]:")
        if username is None:
            self.set_notice("İptal edildi.")
            return
        username = username.strip() or current
        if not username:
            self.set_notice("Kullanıcı adı boş olamaz.", alert=True)
            return

        # A rename needs a password to write a fresh record.
        password = self.prompt("Şifre (doğrulama için):", secret=True)
        if password is None:
            self.set_notice("İptal edildi.")
            return
        if not self.store.verify_password(current, password):
            self.set_notice("Yanlış şifre.", alert=True)
            return

        try:
            self.store.set_credentials(username, password)
        except AuthError as exc:
            self.set_notice(str(exc), alert=True)
            return
        self.set_notice(f"Kullanıcı adı '{username}' olarak değişti. Oturumlar kapatıldı.")

    def show_sessions(self) -> None:
        self.sessions = self.store.list_sessions()
        self.view = "sessions"

    def revoke_all(self) -> None:
        if not self.unlock():
            return
        if not self.confirm("Tüm oturumlar kapatılsın mı?"):
            self.set_notice("Vazgeçildi.")
            return
        count = self.store.revoke_all()
        self.set_notice(f"{count} oturum kapatıldı.")

    # -------------------------------------------------------------------- loop

    def run(self) -> int:
        while True:
            if self.too_small():
                key = self.screen.getkey()
                if key in ("q", "Q"):
                    return 0
                continue

            self.draw()
            try:
                key = self.screen.getkey()
            except curses.error:
                continue

            if self.view == "sessions":
                self.view = "menu"
                continue

            if key in ("q", "Q"):
                return 0
            if key == "1":
                self.change_password()
            elif key == "2":
                self.change_username()
            elif key == "3":
                self.show_sessions()
            elif key == "4":
                self.revoke_all()
            elif key in ("r", "R"):
                self.set_notice("Yenilendi.")


def _run(stdscr: "curses.window", store: AuthStore) -> int:
    set_cursor_visible(False)
    stdscr.keypad(True)
    curses.noecho()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    return App(stdscr, store).run()


def run_tui(store: AuthStore) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("hata: tui bir uçbirim (tty) gerektiriyor.", file=sys.stderr)
        return 2
    try:
        return curses.wrapper(_run, store)
    except curses.error as exc:
        print(f"hata: uçbirim arayüzü başlatılamadı: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
