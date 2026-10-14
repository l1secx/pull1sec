"""Command line interface: serve, manage the account, inspect sessions."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from datetime import datetime

from . import __version__
from .auth import (
    AuthError,
    AuthNotConfigured,
    AuthStore,
    AuthStorageError,
    PasswordPolicyError,
    validate_password,
    validate_username,
)
from .config import SESSION_TTL_PERSISTENT, settings
from .utils import describe_user_agent, is_loopback_host, server_urls

COMMANDS = ("serve", "user", "sessions", "url", "tui", "version")


# --------------------------------------------------------------------- output


def out(message: str = "") -> None:
    # Flush: the banner must be on screen before uvicorn takes over the terminal.
    print(message, flush=True)


def fail(message: str, code: int = 1) -> int:
    print(f"hata: {message}", file=sys.stderr, flush=True)
    return code


def open_store() -> AuthStore:
    return AuthStore(settings.auth_path)


def format_time(epoch: float | None) -> str:
    if not epoch:
        return "—"
    return datetime.fromtimestamp(epoch).strftime("%d.%m.%Y %H:%M")


def format_ago(epoch: float | None) -> str:
    if not epoch:
        return "—"
    delta = max(0, int(time.time() - epoch))
    if delta < 60:
        return "az önce"
    if delta < 3600:
        return f"{delta // 60} dk önce"
    if delta < 86400:
        return f"{delta // 3600} sa önce"
    return f"{delta // 86400} gün önce"


# --------------------------------------------------------------------- prompts


def ask_secret(prompt: str, *, hint: str | None = None) -> str:
    """Read a secret from the terminal, without echo."""
    if not sys.stdin.isatty():
        raise AuthError(
            hint
            or "Bu komut bir uçbirim gerektiriyor. Betiklerde --password-stdin kullan."
        )
    return getpass.getpass(prompt)


def read_new_password(*, username: str | None) -> str:
    """Ask twice and enforce the policy before anything is written."""
    while True:
        first = ask_secret("Yeni şifre: ")
        try:
            validate_password(first, username=username)
        except PasswordPolicyError as exc:
            out(f"  {exc}")
            continue
        second = ask_secret("Yeni şifre (tekrar): ")
        if first != second:
            out("  Şifreler aynı değil, baştan dene.")
            continue
        return first


def require_unlock(store: AuthStore, *, force: bool = False, attempts: int = 3) -> bool:
    """Prove the caller knows the current password before changing it."""
    if not store.configured or force:
        return True
    for attempt in range(attempts):
        password = ask_secret(
            "Mevcut şifre: ",
            hint=(
                "Mevcut şifreyi sormak için bir uçbirim gerekiyor. "
                "Betiklerde --force kullan (mevcut şifre sorulmaz)."
            ),
        )
        if store.verify_password(store.username or "", password):
            return True
        left = attempts - attempt - 1
        out(f"  Yanlış şifre. Kalan deneme: {left}")
    return False


# -------------------------------------------------------------------- commands


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings.ensure_dirs()
    store = open_store()

    urls = server_urls(settings.host, settings.port)
    on_network = bool(urls["lan"])

    if settings.require_auth and not store.configured and on_network:
        out()
        out("  Kurulum gerekli.")
        out("  Sunucu ağa açık ama henüz hesap yok; bu hâliyle herkes indirebilirdi.")
        out("  Önce bir hesap oluştur:")
        out()
        out("      pull1sec user set")
        out()
        out("  (Ağa açmadan denemek için: PULL1SEC_HOST=127.0.0.1 ./run.sh)")
        out()
        return 1

    _print_banner(store, urls)

    if not store.configured:
        out("  uyarı: hesap yok ve şifre istenmiyor — ağdaki herkes erişebilir.")
        out()

    uvicorn.run(
        "pull1sec.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
    return 0


def _print_banner(store: AuthStore, urls: dict[str, list[str]]) -> None:
    out()
    out(f"  Pull1sec {__version__}")
    out(f"    yerel     {urls['local'][0]}")
    for url in urls["lan"]:
        out(f"    ağ        {url}")
    if not urls["lan"]:
        out("    ağ        (kapalı — sadece bu makine)")

    if store.configured:
        ttl_days = settings.session_ttl_seconds / 86400
        remaining = f"{ttl_days:.0f} gün" if ttl_days >= 1 else f"{ttl_days * 24:.0f} saat"
        sessions = len(store.list_sessions())
        out(f"    kullanıcı {store.username}   ·   oturum ömrü {remaining}   ·   açık oturum {sessions}")
    else:
        out("    kullanıcı (tanımsız)")
    out()


def cmd_url(args: argparse.Namespace) -> int:
    urls = server_urls(settings.host, settings.port)
    out(f"yerel  {urls['local'][0]}")
    if urls["lan"]:
        for url in urls["lan"]:
            out(f"ağ     {url}")
    else:
        out("ağ     (kapalı)")
    return 0


def cmd_user_set(args: argparse.Namespace) -> int:
    settings.ensure_dirs()
    store = open_store()

    username = args.username or store.username
    if not username:
        if not sys.stdin.isatty():
            return fail("--username gerekli (uçbirim yok).")
        username = input(f"Kullanıcı adı [{getpass.getuser()}]: ").strip() or getpass.getuser()

    try:
        username = validate_username(username)
    except AuthError as exc:
        return fail(str(exc))

    try:
        if not require_unlock(store, force=args.force):
            return fail("Kimlik doğrulanamadı, değişiklik yapılmadı.")
    except AuthError as exc:
        return fail(str(exc))

    if args.password_stdin:
        password = sys.stdin.readline().strip()
        try:
            validate_password(password, username=username)
        except PasswordPolicyError as exc:
            return fail(str(exc))
    else:
        password = read_new_password(username=username)

    existed = store.configured
    store.set_credentials(username, password, keep_sessions=args.keep_sessions)

    out()
    out(f"  Kullanıcı adı : {username}")
    out(f"  Şifre         : güncellendi ({store.metadata()['algorithm']}, "
        f"{store.metadata()['iterations']} tur)")
    out(f"  Kayıt yeri    : {settings.auth_path}")
    if existed and not args.keep_sessions:
        out("  Oturumlar     : hepsi kapatıldı (diğer cihazlar tekrar giriş yapmalı)")
    elif args.keep_sessions:
        out("  Oturumlar     : korundu")
    out()
    return 0


def cmd_user_show(args: argparse.Namespace) -> int:
    store = open_store()
    meta = store.metadata()
    if not meta["configured"]:
        out("Hesap tanımlı değil.")
        out(f"Oluşturmak için: pull1sec user set")
        out(f"Kayıt yeri     : {settings.auth_path}")
        return 0

    out()
    out(f"  kullanıcı adı : {meta['username']}")
    out(f"  algoritma     : {meta['algorithm']}")
    out(f"  tur sayısı    : {meta['iterations']}")
    out(f"  tuz           : dosyada (kullanıcı adı ile birlikte saklanır)")
    out(f"  oluşturuldu   : {format_time(meta['created_at'])}")
    out(f"  güncellendi   : {format_time(meta['updated_at'])}")
    out(f"  açık oturum   : {meta['sessions']}")
    out(f"  kayıt yeri    : {meta['path']}")

    path = settings.auth_path
    if path.exists():
        mode = oct(path.stat().st_mode & 0o777)
        out(f"  izinler       : {mode} ({'yalnız sahibi' if mode == '0o600' else 'gevşek!'})")
    out()
    out("  Şifre dosyada yok; yalnızca tek yönlü PBKDF2-SHA256 özeti var.")
    out()
    return 0


def cmd_user_remove(args: argparse.Namespace) -> int:
    store = open_store()
    if not store.configured:
        return fail("Hesap zaten tanımlı değil.")
    if not args.yes:
        if not sys.stdin.isatty():
            return fail("Onay için --yes gerekli.")
        answer = input(f"'{store.username}' hesabı silinsin mi? Bu tüm oturumları kapatır. [e/H] ")
        if answer.strip().lower() not in {"e", "y", "evet", "yes"}:
            out("Vazgeçildi.")
            return 0
    store.clear()
    out("Hesap silindi.")
    out("Not: hesaplı bir sunucu bu durumda ağa açılmaz.")
    return 0


def cmd_sessions_list(args: argparse.Namespace) -> int:
    store = open_store()
    if not store.configured:
        return fail("Hesap tanımlı değil.")
    sessions = store.list_sessions()
    if not sessions:
        out("Açık oturum yok.")
        return 0

    out()
    out(f"  {'cihaz':<22} {'adres':<16} {'son görülme':<14} {'bitiş'}")
    out(f"  {'-' * 22} {'-' * 16} {'-' * 14} {'-' * 16}")
    for session in sessions:
        out(
            f"  {describe_user_agent(session.user_agent):<22} "
            f"{(session.address or '—'):<16} "
            f"{format_ago(session.last_seen_at):<14} "
            f"{format_time(session.expires_at)}"
        )
    out()
    out(f"  toplam: {len(sessions)}")
    out()
    return 0


def cmd_sessions_revoke_all(args: argparse.Namespace) -> int:
    store = open_store()
    if not store.configured:
        return fail("Hesap tanımlı değil.")
    count = store.revoke_all()
    out(f"{count} oturum kapatıldı. Bütün cihazlar tekrar giriş yapmalı.")
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    from .tui import run_tui

    return run_tui(open_store())


def cmd_version(args: argparse.Namespace) -> int:
    out(f"Pull1sec {__version__}")
    return 0


# ---------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pull1sec",
        description="Bağlantı yapıştır, videoyu al. Ağ üzerinde çalışır, giriş ister.",
    )
    parser.add_argument("--version", action="version", version=f"Pull1sec {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="sunucuyu başlat (varsayılan)")
    serve.set_defaults(func=cmd_serve)

    subparsers.add_parser("url", help="ağ adreslerini yazdır").set_defaults(func=cmd_url)

    user = subparsers.add_parser("user", help="hesabı yönet")
    user_sub = user.add_subparsers(dest="action")

    user_set = user_sub.add_parser("set", help="şifreyi belirle veya değiştir")
    user_set.add_argument("--username", help="kullanıcı adı (varsayılan: mevcut)")
    user_set.add_argument(
        "--password-stdin",
        action="store_true",
        help="şifreyi terminalden değil standart girdiden oku",
    )
    user_set.add_argument(
        "--keep-sessions",
        action="store_true",
        help="mevcut oturumları kapatma (kullanıcı adı değişirse yine kapatılır)",
    )
    user_set.add_argument("--force", action="store_true", help="mevcut şifreyi sormadan devam et")
    user_set.set_defaults(func=cmd_user_set)

    user_sub.add_parser("show", help="hesap bilgisi").set_defaults(func=cmd_user_show)

    user_remove = user_sub.add_parser("remove", help="hesabı sil")
    user_remove.add_argument("--yes", action="store_true", help="onay sormadan sil")
    user_remove.set_defaults(func=cmd_user_remove)

    user.set_defaults(func=lambda args: (user.print_help(), 0)[1])

    sessions = subparsers.add_parser("sessions", help="açık oturumlar")
    sessions_sub = sessions.add_subparsers(dest="action")
    sessions_sub.add_parser("list", help="oturumları listele").set_defaults(func=cmd_sessions_list)

    revoke = sessions_sub.add_parser("revoke-all", help="tüm oturumları kapat")
    revoke.set_defaults(func=cmd_sessions_revoke_all)
    sessions.set_defaults(func=cmd_sessions_list)

    subparsers.add_parser("tui", help="tam ekran arayüz").set_defaults(func=cmd_tui)
    subparsers.add_parser("version", help="sürüm").set_defaults(func=cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS and argv[0] not in {"-h", "--help", "--version"}:
        # `pull1sec` on its own (or with only flags) starts the server.
        argv = ["serve", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        out()
        return 130
    except AuthStorageError as exc:
        return fail(str(exc))
    except AuthError as exc:
        return fail(str(exc))
    except BrokenPipeError:
        os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
