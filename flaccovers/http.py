"""Shared HTTP client with per-host rate limiting, retries and connection reuse.

Published limits:
* MusicBrainz: 1 request/second per client, meaningful User-Agent required
* Discogs: 60 requests/minute with a personal access token
* iTunes Search API: roughly 20 requests/minute
* Deezer: 50 requests / 5 seconds
"""

from __future__ import annotations

import threading
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

MIN_INTERVAL = {
    "musicbrainz.org": 1.1,
    "api.discogs.com": 1.05,
    "itunes.apple.com": 3.1,
    "api.deezer.com": 0.12,
}

MAX_DOWNLOAD = 20 * 1024 * 1024


class RateLimiter:
    def __init__(self, interval: float):
        self.interval = interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


class HttpClient:
    def __init__(self, user_agent: str, timeout: float = 15.0):
        self.user_agent = user_agent
        self.timeout = timeout
        self._limiters = {h: RateLimiter(i) for h, i in MIN_INTERVAL.items()}
        self._local = threading.local()

    def _session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            retry = Retry(
                total=3, backoff_factor=0.5, backoff_max=8,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=("GET",), respect_retry_after_header=True,
            )
            adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            s.headers["User-Agent"] = self.user_agent
            self._local.session = s
        return s

    def _throttle(self, url: str) -> None:
        lim = self._limiters.get(urlparse(url).hostname or "")
        if lim:
            lim.wait()

    def get_json(self, url: str, params: Optional[dict] = None,
                 headers: Optional[dict] = None) -> Optional[dict]:
        self._throttle(url)
        try:
            r = self._session().get(url, params=params, headers=headers, timeout=self.timeout)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def get_bytes(self, url: str, headers: Optional[dict] = None,
                  limit: int = MAX_DOWNLOAD) -> Optional[bytes]:
        self._throttle(url)
        try:
            with self._session().get(url, headers=headers, timeout=self.timeout, stream=True) as r:
                if r.status_code != 200:
                    return None
                chunks, total = [], 0
                for chunk in r.iter_content(65536):
                    total += len(chunk)
                    if total > limit:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except requests.RequestException:
            return None
