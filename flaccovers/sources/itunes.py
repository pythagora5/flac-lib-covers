from __future__ import annotations

from ..models import AlbumInfo, Candidate
from .base import Source

API = "https://itunes.apple.com/search"


class ITunesSource(Source):
    name = "Apple Music"
    base_tier = 2  # only ~20 requests/minute allowed

    def __init__(self, http, country: str = "US"):
        super().__init__(http)
        self.country = country or "US"

    def search(self, info: AlbumInfo) -> list[Candidate]:
        if not info.album:
            return []
        term = info.album if info.is_various else f"{info.artist} {info.album}"
        data = self.http.get_json(API, params={
            "term": term, "entity": "album", "media": "music",
            "limit": 10, "country": self.country,
        })
        out = []
        for it in (data or {}).get("results") or []:
            art = it.get("artworkUrl100") or ""
            if not art:
                continue
            out.append(Candidate(
                source=self.name,
                artist=it.get("artistName", ""),
                album=it.get("collectionName", ""),
                year=(it.get("releaseDate") or "")[:4],
                track_count=int(it.get("trackCount") or 0),
                thumb_url=art.replace("100x100bb", "300x300bb"),
                image_url=art.replace("100x100bb", "1200x1200bb"),
                fallback_urls=[art.replace("100x100bb", "600x600bb")],
                width=1200, height=1200,
            ))
        return out
