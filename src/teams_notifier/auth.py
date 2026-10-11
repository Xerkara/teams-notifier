"""MSAL ile device code girişi ve şifreli token önbelleği.

Yenileme token'ı Windows'ta DPAPI ile şifrelenir (msal-extensions). Şifreleme
kurulamazsa açık metne düşülmez, hata verilir.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import msal
import requests
from msal_extensions import PersistedTokenCache, build_encrypted_persistence

from .config import AuthConfig, data_dir
from .errors import AuthRequired, NetworkError, TeamsNotifierError

log = logging.getLogger(__name__)

# Temel özellikler (sınıf listesi + dosyalar). Dosya delta'sı için ayrıca
# Files.Read.All gerekmedi; istemci tarafında önceden onaylı izinler yetiyor.
BASE_SCOPES = ["User.Read", "Team.ReadBasic.All"]
POST_SCOPES = ["ChannelMessage.Read.All"]
ASSIGNMENT_SCOPES = ["EduAssignments.ReadBasic"]


@dataclass(frozen=True)
class LoginResult:
    username: str
    extra_granted: bool | None = None  # None: ek izin denenmedi


class Auth:
    def __init__(self, cfg: AuthConfig, cache_path: Path | None = None):
        self._cfg = cfg
        self._cache_path = cache_path or data_dir() / "token_cache.bin"
        self._app: msal.PublicClientApplication | None = None

    def _get_app(self) -> msal.PublicClientApplication:
        if self._app is None:
            try:
                persistence = build_encrypted_persistence(str(self._cache_path))
            except Exception as exc:  # şifreleme yoksa açık metne düşme
                raise TeamsNotifierError(
                    f"Şifreli token önbelleği kurulamadı: {exc}"
                ) from exc
            self._app = msal.PublicClientApplication(
                self._cfg.client_id,
                authority=f"https://login.microsoftonline.com/{self._cfg.tenant}",
                token_cache=PersistedTokenCache(persistence),
            )
        return self._app

    def cached_username(self) -> str | None:
        accounts = self._get_app().get_accounts()
        return accounts[0].get("username") if accounts else None

    def _device_flow(self, scopes: list[str], announce) -> dict:
        app = self._get_app()
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise AuthRequired(
                f"Giriş başlatılamadı: {flow.get('error_description') or flow.get('error')}"
            )
        announce(flow["message"])
        try:
            return app.acquire_token_by_device_flow(flow)
        except requests.RequestException as exc:
            raise NetworkError(f"Giriş sırasında ağ hatası: {exc}") from exc

    def login(self, announce=print, with_posts: bool = False) -> LoginResult:
        """Temel izinlerle giriş. with_posts ise gönderi izni ayrı denenir; reddedilirse
        temel giriş bozulmaz."""
        result = self._device_flow(BASE_SCOPES, announce)
        if "access_token" not in result:
            raise AuthRequired(
                f"Giriş başarısız: {result.get('error')}: {result.get('error_description')}"
            )
        username = (result.get("id_token_claims") or {}).get("preferred_username") or (
            self.cached_username() or "?"
        )

        extra: bool | None = None
        if with_posts:
            extra_result = self._device_flow(BASE_SCOPES + POST_SCOPES, announce)
            extra = "access_token" in extra_result
            if not extra:
                log.info("Gönderi izni alınamadı: %s", extra_result.get("error"))
        return LoginResult(username=username, extra_granted=extra)

    def get_token(self, force_refresh: bool = False) -> str:
        app = self._get_app()
        accounts = app.get_accounts()
        if not accounts:
            raise AuthRequired("Oturum yok.")
        try:
            result = app.acquire_token_silent(
                BASE_SCOPES, account=accounts[0], force_refresh=force_refresh
            )
        except requests.RequestException as exc:
            raise NetworkError(f"Token yenilenemedi (ağ): {exc}") from exc
        if not result or "access_token" not in result:
            reason = (result or {}).get("error", "bilinmiyor")
            raise AuthRequired(f"Oturum süresi doldu ({reason}).")
        return result["access_token"]
