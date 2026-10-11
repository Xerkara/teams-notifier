"""ntfy bildirimleri: JSON ile yayın (Türkçe karakterler için), mesaj bölme, öncelik, click."""
from __future__ import annotations

import logging
import secrets
from collections.abc import Callable, Sequence
from urllib.parse import urlparse

import requests

from .config import NtfyConfig
from .errors import NetworkError, NotifyError

log = logging.getLogger(__name__)

# ntfy mesaj sınırı 4096 bayt; JSON/başlık payı için aşağıda kalıyoruz.
MAX_MESSAGE_BYTES = 3500


def generate_topic() -> str:
    """ntfy.sh topic'leri herkese açıktır; tahmin edilemez bir ad üretir (iyte- + 32 karakter)."""
    return "iyte-" + secrets.token_urlsafe(24)


def split_message(text: str, limit: int = MAX_MESSAGE_BYTES) -> list[str]:
    """Metni satır sınırlarından, UTF-8 bayt sınırını aşmayacak parçalara böler."""
    parts: list[str] = []
    current: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            parts.append("\n".join(current))
            current, size = [], 0

    for line in text.split("\n"):
        # Tek başına sınırı aşan satırı karakter sınırından kes.
        while len(line.encode("utf-8")) > limit:
            cut = len(line)
            while len(line[:cut].encode("utf-8")) > limit:
                cut -= 1
            flush()
            parts.append(line[:cut])
            line = line[cut:]
        add = len(line.encode("utf-8")) + (1 if current else 0)
        if size + add > limit:
            flush()
            add = len(line.encode("utf-8"))
        current.append(line)
        size += add
    flush()
    return parts or [""]


class Notifier:
    def __init__(
        self,
        cfg: NtfyConfig,
        *,
        session: requests.Session | None = None,
        dry_run: bool = False,
        out: Callable[[str], None] = print,
        timeout: float = 15,
    ):
        self._cfg = cfg
        self._session = session or requests.Session()
        self._dry_run = dry_run
        self._out = out
        self._timeout = timeout

    def send(
        self,
        title: str,
        message: str,
        *,
        priority: int = 3,
        tags: Sequence[str] = (),
        click: str | None = None,
    ) -> int:
        """Bildirimi gönderir (gerekirse parçalara böler). Gönderilen parça sayısını döner."""
        if not 1 <= priority <= 5:
            raise ValueError("priority 1-5 arasında olmalı")
        if not self._cfg.topic and not self._dry_run:
            raise NotifyError("ntfy topic ayarlanmamış (config.toml → [ntfy] topic).")
        if click and urlparse(click).scheme not in ("http", "https"):
            click = None

        parts = split_message(message)
        for i, part in enumerate(parts, start=1):
            part_title = title if len(parts) == 1 else f"{title} ({i}/{len(parts)})"
            if self._dry_run:
                self._out(f"[DRY-RUN] ntfy öncelik={priority}: {part_title}\n{part}\n")
                continue
            payload: dict = {
                "topic": self._cfg.topic,
                "title": part_title,
                "message": part,
                "priority": priority,
            }
            if tags:
                payload["tags"] = list(tags)
            if click:
                payload["click"] = click
            self._publish(payload)
        return len(parts)

    def _publish(self, payload: dict) -> None:
        headers = {}
        if self._cfg.token:
            headers["Authorization"] = f"Bearer {self._cfg.token}"
        try:
            resp = self._session.post(
                self._cfg.server.rstrip("/") + "/",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise NetworkError(f"ntfy'ye ulaşılamadı: {type(exc).__name__}") from exc
        if not resp.ok:
            # Topic gizli; hata metnine ve loga koyma.
            raise NotifyError(f"ntfy {resp.status_code} döndürdü.")
