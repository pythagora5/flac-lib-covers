"""Work out an album's artist / title / year from FLAC tags and folder names."""

from __future__ import annotations

import os
import re
from typing import Optional

from .models import AlbumFolder, AlbumInfo

try:
    from mutagen.flac import FLAC, Picture
except ImportError:  # pragma: no cover
    FLAC = None  # type: ignore
    Picture = None  # type: ignore

YEAR_RE = re.compile(r"(?<!\d)(19[0-9]{2}|20[0-9]{2})(?!\d)")
# Bracketed noise often found in folder names: [FLAC], (24-96), {WEB}, (Remastered 2011) ...
NOISE_RE = re.compile(
    r"[\[\(\{][^\]\)\}]*?(flac|mp3|web|cd|vinyl|lp|24[ -]?bit|16[ -]?bit|\d{2}[ -/]\d{2,3}|khz|hi-?res|"
    r"remaster\w*|deluxe|edition|expanded|anniversary|bonus|disc|reissue|mono|stereo|sacd|"
    r"dsd|mqa|\d{4})[^\]\)\}]*[\]\)\}]",
    re.I,
)
LEAD_YEAR_RE = re.compile(r"^\s*[\[\(]?(19\d{2}|20\d{2})[\]\)]?\s*[-–.]\s*")


def clean_album_folder(name: str) -> tuple[str, str]:
    """'1997 - OK Computer [FLAC 24-96]' -> ('OK Computer', '1997')."""
    year = ""
    m = LEAD_YEAR_RE.match(name)
    if m:
        year = m.group(1)
        name = name[m.end():]
    if not year:
        m = YEAR_RE.search(name)
        if m:
            year = m.group(1)
    cleaned = NOISE_RE.sub("", name)
    cleaned = re.sub(r"\s*[-–]\s*$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -_.")
    return (cleaned or name.strip()), year


def clean_artist_folder(name: str) -> str:
    return re.sub(r"\s{2,}", " ", NOISE_RE.sub("", name)).strip(" -_.") or name


def _first(tags, *keys: str) -> str:
    if tags is None:
        return ""
    for k in keys:
        try:
            v = tags.get(k)
        except Exception:
            v = None
        if v:
            val = v[0] if isinstance(v, list) else v
            val = str(val).strip()
            if val:
                return val
    return ""


def read_tags(folder: AlbumFolder, max_files: int = 3) -> tuple[AlbumInfo, list[bytes]]:
    """Read tags (and embedded front-cover pictures) from up to ``max_files``
    FLACs.  Mutagen only parses the metadata blocks at the start of the file,
    so this is fast even for large hi-res files."""
    info = AlbumInfo()
    pictures: list[bytes] = []
    if FLAC is None:
        return info, pictures
    for name in folder.flacs[:max_files]:
        try:
            f = FLAC(os.path.join(folder.path, name))
        except Exception:
            continue
        t = f.tags
        info.artist = info.artist or _first(t, "albumartist", "album artist", "album_artist")
        info.album = info.album or _first(t, "album")
        if not info.year:
            raw = _first(t, "originaldate", "originalyear", "date", "year")
            m = YEAR_RE.search(raw)
            info.year = m.group(1) if m else ""
        info.mb_release_id = info.mb_release_id or _first(t, "musicbrainz_albumid")
        info.mb_releasegroup_id = info.mb_releasegroup_id or _first(t, "musicbrainz_releasegroupid")
        info.barcode = info.barcode or _first(t, "barcode", "upc", "ean")
        info.catalog = info.catalog or _first(t, "catalognumber", "labelno")
        info.track_artist = info.track_artist or _first(t, "artist")
        if not pictures and f.pictures:
            fronts = [p for p in f.pictures if p.type == 3] or list(f.pictures)
            pictures = [p.data for p in fronts[:1]]
        if info.album and info.artist and pictures:
            break
    info.from_tags = bool(info.album)
    return info, pictures


def album_info(folder: AlbumFolder, tags: Optional[AlbumInfo] = None) -> AlbumInfo:
    """Merge tags with what the Artist/Album folder names say.

    Precedence: ALBUMARTIST tag > artist folder name > ARTIST tag;
    ALBUM tag > album folder name."""
    tags = tags or AlbumInfo()
    f_album, f_year = clean_album_folder(folder.folder_album)
    f_artist = clean_artist_folder(folder.folder_artist)
    info = AlbumInfo(
        artist=tags.artist or f_artist or tags.track_artist,
        album=tags.album or f_album,
        year=tags.year or f_year,
        track_count=len(folder.flacs),
        mb_release_id=tags.mb_release_id,
        mb_releasegroup_id=tags.mb_releasegroup_id,
        barcode=tags.barcode,
        catalog=tags.catalog,
        from_tags=tags.from_tags,
    )
    return info
