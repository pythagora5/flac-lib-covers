"""Score how well an online result matches the album on disk."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import AlbumInfo, Candidate

_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_EDITION = re.compile(
    r"\b(remaster(ed)?|deluxe|expanded|edition|anniversary|bonus tracks?|"
    r"reissue|special|collector'?s|version|mono|stereo|\d{4})\b",
    re.I,
)
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
VARIOUS = {"various artists", "various", "va", "v a", "verschiedene interpreten", "multi artistes"}


def normalize(s: str, strip_editions: bool = True) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("&", " and ")
    if strip_editions:
        s = _BRACKETS.sub(" ", s)
        s = re.sub(r"\s[-–:]\s.*(remaster|edition|deluxe).*$", " ", s)
        s = _EDITION.sub(" ", s)
    s = _NON_ALNUM.sub(" ", s)
    s = re.sub(r"^the\s+", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    if na in nb or nb in na:
        shorter, longer = sorted((len(na), len(nb)))
        ratio = max(ratio, 0.75 + 0.2 * shorter / longer)
    return ratio


def score(c: Candidate, info: AlbumInfo, min_size: int = 500) -> float:
    if c.note == "MusicBrainz ID in tags":
        return 1.0
    album = similarity(c.album, info.album)
    if info.is_various:
        artist = 1.0 if normalize(c.artist) in VARIOUS else 0.6
    elif c.artist:
        artist = similarity(c.artist, info.artist)
    else:
        artist = 0.5
    if c.track_count and info.track_count:
        diff = abs(c.track_count - info.track_count)
        tracks = 1.0 if diff == 0 else 0.6 if diff <= 2 else 0.2
    else:
        tracks = 0.5
    if c.year and info.year:
        year = 1.0 if c.year == info.year else 0.4
    else:
        year = 0.5
    total = 0.6 * album + 0.3 * artist + 0.1 * (0.6 * tracks + 0.4 * year)
    # Wrong artist or album => never a confident match.
    if album < 0.6 or artist < 0.5:
        total = min(total, 0.6)
    if c.width and min(c.width, c.height) < min_size:
        total *= 0.8
    return round(total, 3)
