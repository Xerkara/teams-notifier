"""CLI giriş noktası: python -m teams_notifier / teams-notifier."""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .auth import Auth
from .config import Config, data_dir, default_config_path, load_config, write_initial_config
from .errors import AuthRequired, NetworkError, TeamsNotifierError
from .graph import GraphClient
from .notify import Notifier, generate_topic
from .runner import RunResult, alert_auth_required, run
from .state import State

log = logging.getLogger(__name__)


def setup_logging() -> None:
    log_dir = data_dir() / "logs"
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "teams-notifier.log", maxBytes=512_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def _make_notifier(cfg: Config, dry_run: bool = False) -> Notifier:
    return Notifier(cfg.ntfy, dry_run=dry_run)


def cmd_test_notify(cfg: Config, args: argparse.Namespace) -> int:
    sent = _make_notifier(cfg).send(
        "✅ Teams bildirimcisi", "Deneme bildirimi: kurulum çalışıyor.", tags=("white_check_mark",)
    )
    print(f"Deneme bildirimi gönderildi ({sent} mesaj). Telefonunu kontrol et.")
    return 0


def _print_result(result: RunResult, dry_run: bool) -> None:
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"{prefix}{result.teams} sınıf tarandı, {result.notifications} bildirim.")
    if result.baselined:
        print(
            f"{prefix}İlk tarama (bildirim yok, mevcut dosyalar kaydedildi): "
            f"{len(result.baselined)} sınıf"
        )
    if result.failed_teams:
        print(f"Atlanan sınıflar (ayrıntı log'da): {', '.join(result.failed_teams)}", file=sys.stderr)


def cmd_run(cfg: Config, args: argparse.Namespace) -> int:
    auth = Auth(cfg.auth)
    client = GraphClient(auth.get_token)
    notifier = _make_notifier(cfg, dry_run=args.dry_run)

    with tempfile.TemporaryDirectory() as tmp:
        if args.dry_run:
            # Gerçek durumu bozmamak için state.db'nin kopyası üzerinde çalış.
            real = data_dir() / "state.db"
            path = Path(tmp) / "state.db"
            if real.exists():
                shutil.copyfile(real, path)
        else:
            path = None
        with State(path) as state:
            try:
                result = run(cfg, state, client, notifier)
            except AuthRequired:
                if not args.dry_run:
                    try:
                        alert_auth_required(cfg, state, notifier)
                    except TeamsNotifierError as exc:
                        log.error("Uyarı bildirimi gönderilemedi: %s", exc)
                raise
            except NetworkError as exc:
                # Ağ yok: sessizce çık, zamanlayıcı bir sonraki tetikte tekrar dener.
                log.warning("Ağ yok, çalıştırma atlandı: %s", exc)
                print(f"Ağa ulaşılamadı, atlandı: {exc}", file=sys.stderr)
                return 0
    _print_result(result, args.dry_run)
    return 0 if result.ok else 1


def cmd_setup(cfg: Config, args: argparse.Namespace) -> int:
    path = default_config_path()
    if not path.exists():
        topic = generate_topic()
        write_initial_config(path, topic)
        cfg = load_config()
        print(f"Config oluşturuldu: {path}")
    elif not cfg.ntfy.topic:
        print(f"{path} dosyasında [ntfy] topic boş. Bir topic yazıp tekrar çalıştır.", file=sys.stderr)
        return 1
    else:
        print(f"Mevcut config kullanılıyor: {path}")

    print("\nAndroid'de ntfy uygulamasını kur, '+' ile şu topic'e abone ol (gizli tut):")
    print(f"\n    {cfg.ntfy.topic}\n")
    if cfg.ntfy.server != "https://ntfy.sh":
        print(f"(Sunucu: {cfg.ntfy.server})")
    input("Abone olunca Enter'a bas... ")

    if Auth(cfg.auth).cached_username():
        print("Oturum zaten var, giriş atlandı.")
    else:
        cmd_login(cfg, argparse.Namespace(with_posts=False))

    cmd_test_notify(cfg, args)
    if input("Deneme bildirimi telefonuna geldi mi? [e/h] ").strip().lower() not in ("e", "evet"):
        print("Topic'i ve ntfy uygulamasını kontrol edip `teams-notifier test-notify` dene.")
        return 1

    print("\nMevcut dosyalar kaydediliyor (bunlar için bildirim gönderilmez)...")
    return cmd_run(cfg, argparse.Namespace(dry_run=False))


def cmd_login(cfg: Config, args: argparse.Namespace) -> int:
    auth = Auth(cfg.auth)
    result = auth.login(with_posts=args.with_posts)
    print(f"\n✅ Giriş başarılı: {result.username}")
    with State() as state:
        if result.extra_granted is True:
            state.set_meta("posts_permission", "granted")
            print("✅ Gönderi izni alındı.")
        elif result.extra_granted is False:
            state.set_meta("posts_permission", "denied")
            print("ℹ️  Gönderi izni alınamadı (yönetici onayı gerekli). Diğer özellikler çalışır.")
    return 0


def cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    auth = Auth(cfg.auth)
    user = auth.cached_username()
    print(f"Sürüm        : {__version__}")
    print(f"Veri klasörü : {data_dir()}")
    print(f"Config       : {cfg.path or '(dosya yok, varsayılanlar)'}")
    print(f"Oturum       : {user or 'yok — `teams-notifier login` çalıştır'}")
    with State() as state:
        teams = state.list_teams()
        print(f"Son çalışma  : {state.get_meta('last_run') or 'henüz çalışmadı'}")
        print(f"Takip edilen ders: {len(teams)}  (kayıtlı dosya: {state.count_files()})")
        posts = state.get_meta("posts_permission")
        if not cfg.posts.enabled:
            posts_text = "kapalı (config)"
        elif posts == "granted":
            posts_text = "açık"
        elif posts == "denied":
            posts_text = "izin yok (yönetici onayı gerekli)"
        else:
            posts_text = "denenmedi (`login --with-posts`)"
        print(f"Gönderiler   : {posts_text}")
    print(f"Ödevler      : {'açık' if cfg.assignments.enabled else 'kapalı (yönetici onayı gerekli)'}")
    print(f"Otomatik indirme: {'açık' if cfg.download.enabled else 'kapalı'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="teams-notifier", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Giriş / yeniden giriş")
    p_login.add_argument(
        "--with-posts", action="store_true", help="Gönderi (post) iznini de dene"
    )
    p_login.set_defaults(func=cmd_login)

    p_status = sub.add_parser("status", help="Durum özeti")
    p_status.set_defaults(func=cmd_status)

    p_run = sub.add_parser("run", help="Yeni dosyaları kontrol et ve bildir")
    p_run.add_argument(
        "--dry-run", action="store_true",
        help="Bildirim göndermeden ne gönderileceğini yaz, durumu değiştirme",
    )
    p_run.set_defaults(func=cmd_run)

    p_test = sub.add_parser("test-notify", help="Deneme bildirimi gönder")
    p_test.set_defaults(func=cmd_test_notify)

    p_setup = sub.add_parser("setup", help="İlk kurulum (config, ntfy, giriş, baseline)")
    p_setup.set_defaults(func=cmd_setup)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()
    try:
        cfg = load_config()
        return args.func(cfg, args)
    except TeamsNotifierError as exc:
        logging.getLogger(__name__).error("%s", exc)
        print(f"Hata: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nİptal edildi.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
