"""Uygulamanın ortak hata türleri."""
from __future__ import annotations


class TeamsNotifierError(Exception):
    """Tüm uygulama hatalarının tabanı."""


class ConfigError(TeamsNotifierError):
    """config.toml okunamadı veya geçersiz."""


class AuthRequired(TeamsNotifierError):
    """Oturum yok ya da süresi doldu; `teams-notifier login` gerekir."""


class NetworkError(TeamsNotifierError):
    """Ağa / Graph'a ulaşılamadı."""


class NotifyError(TeamsNotifierError):
    """ntfy bildirimi gönderilemedi."""


class GraphError(TeamsNotifierError):
    """Graph bir hata durumu döndürdü."""

    def __init__(self, status: int, code: str = "", message: str = ""):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(f"Graph {status} {code}: {message}".strip())
