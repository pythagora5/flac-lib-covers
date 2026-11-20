from __future__ import annotations

from ..http import HttpClient
from ..models import AlbumInfo, Candidate


class Source:
    name = "base"
    # Search order when fast_path is on: tier 0 first, later tiers only if
    # earlier ones found no strong match.  Based on each API's rate limit.
    base_tier = 1

    def tier(self, info: AlbumInfo) -> int:
        return self.base_tier

    def __init__(self, http: HttpClient):
        self.http = http

    def search(self, info: AlbumInfo) -> list[Candidate]:  # pragma: no cover
        raise NotImplementedError

    def safe_search(self, info: AlbumInfo) -> list[Candidate]:
        try:
            return self.search(info)
        except Exception:
            return []
