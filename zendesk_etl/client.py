from __future__ import annotations

import threading
import time
from typing import Any, Iterator

import requests

from .config import settings


class OAuthToken:
    """client_credentials token'ını tutar ve süresi dolmadan yeniler (thread-safe)."""

    # Token'ı bitiminden bu kadar saniye önce yenile (uzun koşularda kenar durumu önler).
    SKEW = 120

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0
        self.refresh_count = 0

    def _fetch(self) -> None:
        resp = requests.post(
            settings.oauth_token_url,
            json={
                "grant_type": "client_credentials",
                "client_id": settings.oauth_client_id,
                "client_secret": settings.oauth_client_secret,
                "scope": settings.oauth_scope,
            },
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._expires_at = time.monotonic() + int(data.get("expires_in", 1800))
        self.refresh_count += 1
        if self.refresh_count == 1:
            print(f"  [oauth] token alındı (scope={settings.oauth_scope}, {data.get('expires_in')}s)")
        else:
            print(f"  [oauth] token yenilendi (#{self.refresh_count})")

    def get(self, force: bool = False) -> str:
        with self._lock:
            if force or not self._token or time.monotonic() >= self._expires_at - self.SKEW:
                self._fetch()
            return self._token  # type: ignore[return-value]


class RateLimiter:
    """Basit token-bucket: dakikadaki istek sayısını sınırlar."""

    def __init__(self, rpm: int) -> None:
        self.min_interval = 60.0 / max(rpm, 1)
        self._last = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.monotonic()


class ZendeskClient:
    def __init__(self) -> None:
        settings.validate()
        self.base = settings.base_url
        self.session = requests.Session()
        # Accept başlığı zorunlu: /search/export gibi .json uzantısı taşımayan
        # endpoint'ler bu başlık olmadan 415 döner.
        self.session.headers.update({"Accept": "application/json"})
        self.token = OAuthToken()
        self.limiter = RateLimiter(settings.max_requests_per_minute)

    def _auth_header(self, force: bool = False) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token.get(force=force)}"}

    def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Tek GET; 429 (rate limit) ve 5xx için Retry-After'a saygılı yeniden dener."""
        url = path_or_url if path_or_url.startswith("http") else f"{self.base}/{path_or_url.lstrip('/')}"
        forced = False
        for attempt in range(6):
            self.limiter.wait()
            try:
                resp = self.session.get(
                    url, params=params, timeout=60, headers=self._auth_header(force=forced)
                )
                forced = False
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                # Geçici ağ hatası (Connection reset, timeout) -> backoff ile yeniden dene
                wait = 2 ** attempt
                print(f"  [ağ hatası] {type(exc).__name__}; {wait}s sonra yeniden deneniyor...")
                time.sleep(wait)
                continue
            if resp.status_code == 401:
                # Token düştü -> bir sonraki denemede zorla yenile.
                forced = True
                continue
            if resp.status_code == 403:
                raise RuntimeError(
                    f"403 Forbidden: {resp.text[:200]}\n"
                    "İpucu: ZENDESK_OAUTH_SCOPE değeri 'read' olmalı; granüler liste "
                    "sessizce sıfır yetkili token üretir."
                )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "60"))
                print(f"  [rate-limit] {retry_after}s bekleniyor...")
                time.sleep(retry_after)
                continue
            if resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"6 denemeden sonra başarısız: {url}")

    # ---- Pagination stratejileri ----

    def paginate_cursor(
        self, path: str, params: dict[str, Any] | None = None, data_key: str = "results"
    ) -> Iterator[dict[str, Any]]:
        """Cursor-based pagination (Search Export & modern endpoint'ler)."""
        params = dict(params or {})
        url: str | None = f"{self.base}/{path.lstrip('/')}"
        while url:
            page = self.get(url, params=params)
            params = None  # sonraki sayfalar tam URL üzerinden gelir
            for item in page.get(data_key, []):
                yield item
            meta = page.get("meta", {})
            links = page.get("links", {})
            if meta.get("has_more") and links.get("next"):
                url = links["next"]
            else:
                url = None

    def search_export(self, query: str, page_size: int = 1000) -> Iterator[dict[str, Any]]:
        """Search Export (cursor); search.json'daki 1000 sonuç sınırı yoktur."""
        yield from self.paginate_cursor(
            "search/export",
            params={"query": query, "filter[type]": "ticket", "page[size]": page_size},
            data_key="results",
        )

    def count(self, query: str) -> int:
        """search.json 'count' alanı — sonuçları çekmeden toplamı öğrenmenin ucuz yolu."""
        return self.get("search.json", params={"query": query, "filter[type]": "ticket"}).get("count", 0)

    def paginate_incremental(
        self, path: str, start_time: int, data_key: str = "tickets"
    ) -> Iterator[dict[str, Any]]:
        """Incremental Export (cursor.json) — büyük veri setleri için sınırsız akış."""
        url: str | None = f"{self.base}/{path.lstrip('/')}"
        params: dict[str, Any] | None = {"start_time": start_time}
        while url:
            page = self.get(url, params=params)
            params = None
            for item in page.get(data_key, []):
                yield item
            if page.get("end_of_stream"):
                break
            url = page.get("after_url") or page.get("next_page")
            if not url:
                break
