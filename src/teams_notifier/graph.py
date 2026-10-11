"""Microsoft Graph istemcisi: sayfalama, 429/Retry-After, yeniden deneme, delta."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlparse

import requests

from .errors import GraphError, NetworkError

log = logging.getLogger(__name__)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GRAPH_HOST = "graph.microsoft.com"

RETRY_STATUSES = {429, 502, 503, 504}
MAX_WAIT_SECONDS = 120

TokenProvider = Callable[[bool], str]  # force_refresh -> access token


class GraphClient:
    def __init__(
        self,
        token_provider: TokenProvider,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 5,
        timeout: float = 30,
    ):
        self._token = token_provider
        self._session = session or requests.Session()
        self._sleep = sleep
        self._max_retries = max_retries
        self._timeout = timeout

    @staticmethod
    def _url(path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            parsed = urlparse(path_or_url)
            # Bearer token'ı yanlışlıkla başka bir sunucuya göndermemek için.
            if parsed.scheme != "https" or parsed.hostname != GRAPH_HOST:
                raise GraphError(0, "BadUrl", "Graph dışı adrese istek reddedildi.")
            return path_or_url
        return f"{GRAPH_ROOT}/{path_or_url.lstrip('/')}"

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2.0**attempt, 30.0)

    def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict:
        url = self._url(path_or_url)
        # Loglarda sorgu dizesi (delta token vb.) yer almasın.
        safe = urlparse(url).path
        refreshed = False
        force = False

        for attempt in range(self._max_retries + 1):
            try:
                resp = self._session.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {self._token(force)}"},
                    timeout=self._timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self._max_retries:
                    raise NetworkError(f"Graph'a ulaşılamadı: {type(exc).__name__}") from exc
                log.warning("Ağ hatası (%s), tekrar denenecek: %s", type(exc).__name__, safe)
                self._sleep(self._backoff(attempt))
                continue
            force = False

            if resp.status_code == 401 and not refreshed:
                refreshed = True
                force = True
                continue

            if resp.status_code in RETRY_STATUSES and attempt < self._max_retries:
                wait = self._backoff(attempt)
                header = resp.headers.get("Retry-After")
                if header and header.isdigit():
                    wait = float(header)
                if wait > MAX_WAIT_SECONDS:
                    raise GraphError(resp.status_code, "Throttled", "Retry-After çok uzun.")
                log.warning("Graph %s, %.0f sn beklenecek: %s", resp.status_code, wait, safe)
                self._sleep(wait)
                continue

            if resp.ok:
                return resp.json()
            raise self._error(resp)

        raise NetworkError("Graph isteği yeniden deneme sınırını aştı.")

    @staticmethod
    def _error(resp: requests.Response) -> GraphError:
        try:
            err = resp.json().get("error", {})
            return GraphError(resp.status_code, err.get("code", ""), err.get("message", ""))
        except ValueError:
            return GraphError(resp.status_code, "", resp.text[:200])

    def get_paged(
        self, path_or_url: str, params: dict[str, Any] | None = None
    ) -> Iterator[dict]:
        """`@odata.nextLink` zincirini izleyip `value` öğelerini tek tek verir."""
        page = self.get(path_or_url, params)
        while True:
            yield from page.get("value", [])
            next_link = page.get("@odata.nextLink")
            if not next_link:
                return
            page = self.get(next_link)

    def delta(
        self, path_or_url: str, params: dict[str, Any] | None = None
    ) -> tuple[list[dict], str]:
        """Delta zincirini sonuna kadar izler; (öğeler, @odata.deltaLink) döner.

        Delta token'ı geçersizse Graph 410 verir; çağıran taraf bunu GraphError
        olarak alıp baştan başlatabilir.
        """
        items: list[dict] = []
        page = self.get(path_or_url, params)
        while True:
            items.extend(page.get("value", []))
            if "@odata.nextLink" in page:
                page = self.get(page["@odata.nextLink"])
                continue
            delta_link = page.get("@odata.deltaLink")
            if not delta_link:
                raise GraphError(0, "NoDeltaLink", "Delta yanıtında deltaLink yok.")
            return items, delta_link
