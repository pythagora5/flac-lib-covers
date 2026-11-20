"""Find replacement artwork for one album: local first, then online."""

from __future__ import annotations

import io
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Optional

from PIL import Image

from . import images, matcher, metadata
from .cache import Cache
from .config import Settings, get_discogs_token
from .http import HttpClient
from .models import (LOCAL_FIX_ISSUES, AlbumFolder, AlbumInfo, AlbumResult, Candidate,
                     Issue, Status)
from .sources import DeezerSource, DiscogsSource, ITunesSource, MusicBrainzSource, Source

THUMB_PX = 300
MAX_CANDIDATES = 10
THUMBS_TO_FETCH = 8
STRONG_MATCH = 0.92
GOOD_NAME = re.compile(r"front|cover|folder|album|art", re.I)
BAD_NAME = re.compile(r"back|cd\d*|disc|inlay|booklet|inside|tray|rear|label|matrix|spine", re.I)


def make_thumb(data: bytes, px: int = THUMB_PX) -> Optional[bytes]:
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.draft("RGB", (px, px))  # fast JPEG downscale while decoding
            im = im.convert("RGB")
            im.thumbnail((px, px))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            return buf.getvalue()
    except Exception:
        return None


class Finder:
    """Thread-safe; one instance shared by all lookup workers."""

    def __init__(self, settings: Settings, cache: Optional[Cache] = None,
                 http: Optional[HttpClient] = None):
        self.s = settings
        self.cache = cache
        self.http = http or HttpClient(settings.user_agent())
        self._pool = ThreadPoolExecutor(max_workers=12, thread_name_prefix="net")
        self.sources: list[Source] = []
        if settings.use_deezer:
            self.sources.append(DeezerSource(self.http))
        if settings.use_musicbrainz:
            self.sources.append(MusicBrainzSource(self.http))
        if settings.use_discogs:
            token = get_discogs_token()
            if token:
                self.sources.append(DiscogsSource(self.http, token))
        if settings.use_itunes:
            self.sources.append(ITunesSource(self.http, settings.itunes_country))

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ---- local candidates ---------------------------------------------------
    def local_candidates(self, folder: AlbumFolder, embedded: list[bytes]) -> list[Candidate]:
        s = self.s
        out: list[Candidate] = []
        cov = folder.cover
        if cov and cov.readable and folder.issue in LOCAL_FIX_ISSUES:
            out.append(Candidate(source="Existing file", local_path=cov.path,
                                 width=cov.width, height=cov.height, score=1.0,
                                 note="re-saved as cover.jpg"))
        for data in embedded:
            w, h = images.probe_bytes(data)
            if w:
                ok = min(w, h) >= s.min_size
                out.append(Candidate(source="Embedded in FLAC", data=data, width=w, height=h,
                                     score=1.0 if ok else 0.55))
        for name in folder.other_images:
            info = images.inspect(os.path.join(folder.path, name))
            if not info.readable or not info.width:
                continue
            squareish = abs(info.width - info.height) <= 0.1 * info.max_side
            if BAD_NAME.search(os.path.splitext(name)[0]):
                sc = 0.3
            elif GOOD_NAME.search(name) and squareish:
                sc = 0.95
            else:
                sc = 0.75 if squareish else 0.4
            if info.min_side < s.min_size:
                sc *= 0.6
            out.append(Candidate(source=f"Folder: {name}", local_path=info.path,
                                 width=info.width, height=info.height, score=round(sc, 3)))
        if cov and cov.readable and folder.issue == Issue.TOO_SMALL:
            out.append(Candidate(source="Existing file", local_path=cov.path, width=cov.width,
                                 height=cov.height, score=0.5, note="keeps the small image"))
        return out

    # ---- online -------------------------------------------------------------
    def _search_sources(self, sources: list[Source], info: AlbumInfo) -> list[Candidate]:
        if not sources:
            return []
        key = Cache.lookup_key(info.artist.lower(), info.album.lower(), info.year,
                               info.mb_release_id, info.mb_releasegroup_id, info.barcode,
                               ",".join(sorted(x.name for x in sources)), self.s.itunes_country)
        if self.cache:
            hit = self.cache.get_lookup(key, self.s.lookup_cache_days)
            if hit is not None:
                return [Candidate(**d) for d in hit]
        futures = [self._pool.submit(src.safe_search, info) for src in sources]
        found = [c for f in futures for c in f.result()]
        if self.cache:
            self.cache.put_lookup(key, [
                {k: v for k, v in asdict(c).items() if k not in ("data", "thumb")} for c in found
            ])
        return found

    def _fetch_thumb(self, c: Candidate) -> Candidate:
        if c.thumb is not None or not c.thumb_url:
            return c
        data = self.cache.get_thumb(c.thumb_url) if self.cache else None
        if data is None:
            raw = self.http.get_bytes(c.thumb_url, limit=4 * 1024 * 1024)
            data = make_thumb(raw) if raw else None
            if data and self.cache:
                self.cache.put_thumb(c.thumb_url, data)
        c.thumb = data or b""
        return c

    def search_online(self, info: AlbumInfo, all_sources: bool = False) -> list[Candidate]:
        """Query sources tier by tier, stopping once a strong match is found
        (unless fast_path is off or the user asked for all sources)."""
        s = self.s
        if all_sources or not s.fast_path:
            groups = [self.sources]
        else:
            by_tier: dict[int, list[Source]] = {}
            for src in self.sources:
                by_tier.setdefault(src.tier(info), []).append(src)
            groups = [by_tier[t] for t in sorted(by_tier)]
        cands: list[Candidate] = []
        for group in groups:
            found = self._search_sources(group, info)
            for c in found:
                c.score = matcher.score(c, info, s.min_size)
            cands += found
            if max((c.score for c in cands), default=0) >= STRONG_MATCH:
                break
        return cands

    # ---- whole album --------------------------------------------------------
    def find(self, folder: AlbumFolder, info_override: Optional[AlbumInfo] = None,
             all_sources: bool = False) -> AlbumResult:
        tags, embedded = metadata.read_tags(folder)
        info = info_override or metadata.album_info(folder, tags)
        res = AlbumResult(folder=folder, info=info)
        if folder.issue == Issue.MISSING and embedded:
            folder.issue = Issue.EMBEDDED_ONLY
        if folder.cover and folder.cover.readable:
            raw = _read(folder.cover.path)
            res.current_thumb = make_thumb(raw) if raw else None
        elif embedded:
            res.current_thumb = make_thumb(embedded[0])

        cands = self.local_candidates(folder, embedded)
        best_local = max((c.score for c in cands), default=0)
        if all_sources or best_local < 0.9:
            cands += self.search_online(info, all_sources)

        cands.sort(key=lambda c: (c.score, min(c.width, c.height)), reverse=True)
        cands = cands[:MAX_CANDIDATES]

        # Previews: local ones are made from the pixels; online ones downloaded
        # in parallel. Online results whose preview 404s (no art) are dropped.
        online = [c for c in cands if not c.is_local][:THUMBS_TO_FETCH]
        futures = [self._pool.submit(self._fetch_thumb, c) for c in online]
        for c in cands:
            if c.is_local:
                raw = c.data if c.data else _read(c.local_path)
                c.thumb = make_thumb(raw) if raw else b""
        for f in futures:
            f.result()
        cands = [c for c in cands if c.thumb]

        res.candidates = cands
        if not cands:
            res.status = Status.NOT_FOUND
            res.message = "No artwork found"
            return res
        res.chosen = 0
        res.approved = cands[0].score >= self.s.auto_approve_score
        res.status = Status.PROPOSED if res.approved else Status.NEEDS_REVIEW
        return res


def _read(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None
