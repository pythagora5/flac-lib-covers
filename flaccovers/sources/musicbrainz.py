"""MusicBrainz search + Cover Art Archive images."""

from __future__ import annotations

import re

from ..models import AlbumInfo, Candidate
from .base import Source

MB = "https://musicbrainz.org/ws/2/release/"
CAA = "https://coverartarchive.org"

_LUCENE = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def lucene(s: str) -> str:
    return _LUCENE.sub(r"\\\1", s)


def _artist_credit(rel: dict) -> str:
    parts = []
    for c in rel.get("artist-credit") or []:
        if isinstance(c, dict):
            parts.append(c.get("name", "") + c.get("joinphrase", ""))
    return "".join(parts)


class MusicBrainzSource(Source):
    name = "MusicBrainz"

    def tier(self, info: AlbumInfo) -> int:
        # An exact MusicBrainz ID in the tags beats any search.
        return 0 if (info.mb_release_id or info.mb_releasegroup_id) else 1

    def search(self, info: AlbumInfo) -> list[Candidate]:
        out: list[Candidate] = []
        # 1) Tagged with a MusicBrainz ID: exact, no search needed.
        if info.mb_release_id:
            out.append(self._caa(f"release/{info.mb_release_id}", info.artist, info.album,
                                 info.year, info.track_count, note="MusicBrainz ID in tags"))
        if info.mb_releasegroup_id:
            out.append(self._caa(f"release-group/{info.mb_releasegroup_id}", info.artist,
                                 info.album, info.year, info.track_count,
                                 note="MusicBrainz ID in tags"))
        if out:
            return out
        if not info.album:
            return []

        # 2) Search, de-duplicated by release group (one cover per album).
        q = f'release:"{lucene(info.album)}"'
        if info.artist:
            q += f' AND artist:"{lucene(info.artist)}"'
        if info.barcode:
            q = f"({q}) OR barcode:{lucene(info.barcode)}"
        data = self.http.get_json(MB, params={"query": q, "fmt": "json", "limit": 15})
        seen = set()
        for rel in (data or {}).get("releases") or []:
            if int(rel.get("score") or 0) < 60:
                continue
            rg = (rel.get("release-group") or {}).get("id")
            if not rg or rg in seen:
                continue
            seen.add(rg)
            out.append(self._caa(
                f"release-group/{rg}", _artist_credit(rel), rel.get("title", ""),
                (rel.get("date") or "")[:4], int(rel.get("track-count") or 0),
            ))
            if len(seen) >= 4:
                break
        return out

    def _caa(self, path: str, artist: str, album: str, year: str, tracks: int,
             note: str = "") -> Candidate:
        # The CAA redirects these to the right image; 404 means no art, in
        # which case the thumbnail download fails and the candidate is dropped.
        return Candidate(
            source=self.name, artist=artist, album=album, year=year, track_count=tracks,
            thumb_url=f"{CAA}/{path}/front-250",
            image_url=f"{CAA}/{path}/front-1200",
            fallback_urls=[f"{CAA}/{path}/front-500", f"{CAA}/{path}/front"],
            note=note,
        )
