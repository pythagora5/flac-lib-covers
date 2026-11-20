from __future__ import annotations

from ..models import AlbumInfo, Candidate
from .base import Source

API = "https://api.deezer.com/search/album"


def _q(s: str) -> str:
    return s.replace('"', " ")


class DeezerSource(Source):
    name = "Deezer"
    base_tier = 0  # 10 requests/second allowed

    def search(self, info: AlbumInfo) -> list[Candidate]:
        if not info.album:
            return []
        if info.is_various:
            queries = [f'album:"{_q(info.album)}"']
        else:
            queries = [f'artist:"{_q(info.artist)}" album:"{_q(info.album)}"',
                       f"{info.artist} {info.album}"]
        for q in queries:
            data = self.http.get_json(API, params={"q": q, "limit": 10})
            items = (data or {}).get("data") or []
            if items:
                return [self._cand(it) for it in items if it.get("cover_xl")]
        return []

    @staticmethod
    def _cand(it: dict) -> Candidate:
        return Candidate(
            source=DeezerSource.name,
            artist=(it.get("artist") or {}).get("name", ""),
            album=it.get("title", ""),
            track_count=int(it.get("nb_tracks") or 0),
            thumb_url=it.get("cover_medium") or it.get("cover_big", ""),
            image_url=it["cover_xl"],
            fallback_urls=[u for u in (it.get("cover_big"),) if u],
            width=1000, height=1000,
        )
