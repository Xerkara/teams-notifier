"""config.toml okuma/doğrulama ve veri klasörü yolları."""
from __future__ import annotations

import os
import tomllib
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigError

# Microsoft Graph Command Line Tools (birinci taraf, genel istemci).
# config'te client_id boş bırakılırsa bu kullanılır.
DEFAULT_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"


def data_dir() -> Path:
    """Token önbelleği, state.db, loglar ve config burada durur (proje klasöründe değil)."""
    override = os.environ.get("TEAMS_NOTIFIER_HOME")
    if override:
        path = Path(override)
    elif os.name == "nt":
        path = Path(os.environ["LOCALAPPDATA"]) / "teams-notifier"
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / "teams-notifier"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_config_path() -> Path:
    return data_dir() / "config.toml"


@dataclass(frozen=True)
class AuthConfig:
    client_id: str = ""
    tenant: str = "organizations"


@dataclass(frozen=True)
class NtfyConfig:
    server: str = "https://ntfy.sh"
    topic: str = ""
    token: str = ""


@dataclass(frozen=True)
class ScheduleConfig:
    timezone: str = "Europe/Istanbul"


@dataclass(frozen=True)
class RemindersConfig:
    thresholds_days: list = field(default_factory=lambda: [3, 1, 0])
    notify_overdue: bool = True


@dataclass(frozen=True)
class FilesConfig:
    notify_updates: bool = False
    exclude_classes: list = field(default_factory=list)


@dataclass(frozen=True)
class PostsConfig:
    enabled: bool = True


@dataclass(frozen=True)
class AssignmentsConfig:
    # Ödevler okul yöneticisinin onayını gerektiriyor; izin alınana kadar kapalı.
    enabled: bool = False


@dataclass(frozen=True)
class DownloadConfig:
    enabled: bool = False
    folder: str = ""
    extensions: list = field(default_factory=list)
    max_size_mb: int = 200


@dataclass(frozen=True)
class Config:
    auth: AuthConfig
    ntfy: NtfyConfig
    schedule: ScheduleConfig
    reminders: RemindersConfig
    files: FilesConfig
    posts: PostsConfig
    assignments: AssignmentsConfig
    download: DownloadConfig
    path: Path | None = None

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.schedule.timezone)


_SECTIONS: dict[str, type] = {
    "auth": AuthConfig,
    "ntfy": NtfyConfig,
    "schedule": ScheduleConfig,
    "reminders": RemindersConfig,
    "files": FilesConfig,
    "posts": PostsConfig,
    "assignments": AssignmentsConfig,
    "download": DownloadConfig,
}


def _default_of(f) -> Any:
    if f.default is not MISSING:
        return f.default
    return f.default_factory()


def _type_ok(default: Any, value: Any) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, type(default))


def _build_section(name: str, cls: type, raw: Any):
    if not isinstance(raw, dict):
        raise ConfigError(f"[{name}] bir tablo olmalı.")
    known = {f.name: f for f in fields(cls)}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ConfigError(f"[{name}] bölümünde bilinmeyen alan(lar): {', '.join(unknown)}")
    for key, value in raw.items():
        default = _default_of(known[key])
        if not _type_ok(default, value):
            raise ConfigError(
                f"[{name}] {key}: beklenen tür {type(default).__name__}, "
                f"gelen {type(value).__name__}."
            )
    return cls(**raw)


def _validate(cfg: Config) -> None:
    try:
        ZoneInfo(cfg.schedule.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"[schedule] timezone geçersiz: {cfg.schedule.timezone!r}") from exc

    if not cfg.ntfy.server.startswith(("https://", "http://")):
        raise ConfigError("[ntfy] server http:// veya https:// ile başlamalı.")

    days = cfg.reminders.thresholds_days
    if not all(isinstance(d, int) and not isinstance(d, bool) and d >= 0 for d in days):
        raise ConfigError("[reminders] thresholds_days negatif olmayan tam sayılar listesi olmalı.")

    if cfg.download.max_size_mb <= 0:
        raise ConfigError("[download] max_size_mb 0'dan büyük olmalı.")


def write_initial_config(path: Path, topic: str) -> None:
    """İlk kurulumda yalnızca topic'i içeren asgari config yazar; kalanı varsayılan."""
    path.write_text(
        "# teams-notifier ayarları. Diğer seçenekler için proje klasöründeki "
        "config.example.toml'a bak.\n"
        "# DİKKAT: topic gizlidir, kimseyle paylaşma.\n"
        "[ntfy]\n"
        f'topic = "{topic}"\n',
        encoding="utf-8",
    )


def load_config(path: Path | None = None) -> Config:
    """Dosya yoksa varsayılanlarla döner (login/status config'siz de çalışsın diye)."""
    path = path or default_config_path()
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            with path.open("rb") as fh:
                raw = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path} okunamadı: {exc}") from exc

    unknown = sorted(set(raw) - set(_SECTIONS))
    if unknown:
        raise ConfigError(f"Bilinmeyen bölüm(ler): {', '.join(unknown)}")

    sections = {
        name: _build_section(name, cls, raw.get(name, {})) for name, cls in _SECTIONS.items()
    }
    if not sections["auth"].client_id:
        sections["auth"] = AuthConfig(
            client_id=DEFAULT_CLIENT_ID, tenant=sections["auth"].tenant
        )

    cfg = Config(**sections, path=path if path.exists() else None)
    _validate(cfg)
    return cfg
