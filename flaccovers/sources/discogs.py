from __future__ import annotations

from ..models import AlbumInfo, Candidate
from .base import Source

API = "https://api.discogs.com/database/search"


class DiscogsSource(Source):
    name = "Discogs"

    def __init__(self, http, token: str):
        super().__init__(http)
        self.token = token

    def _headers(self) -> dict:
        return {"Authorization": f"Discogs token={self.token}"}

    def search(self, info: AlbumInfo) -> list[Candidate]:
        if not self.token or not info.album:
            return []
        params = {"release_title": info.album, "per_page": 8}
        if info.artist and not info.is_various:
            params["artist"] = info.artist
        if info.barcode:
            params = {"barcode": info.barcode, "per_page": 8}
        out: list[Candidate] = []
        for kind in ("master", "release"):
            data = self.http.get_json(API, params={**params, "type": kind}, headers=self._headers())
            for it in (data or {}).get("results") or []:
                img = it.get("cover_image") or ""
                if not img or img.endswith("spacer.gif"):
                    continue
                title = it.get("title", "")
                artist, _, album = title.partition(" - ")
                if not album:
                    artist, album = "", title
                out.append(Candidate(
                    source=self.name, artist=artist.strip(), album=album.strip(),
                    year=str(it.get("year") or ""),
                    thumb_url=it.get("thumb") or img, image_url=img,
                ))
            if out:
                break
        return out
