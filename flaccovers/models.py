"""Plain data classes shared by the scanner, lookup, GUI and applier."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Issue(str, Enum):
    OK = "OK"
    MISSING = "No artwork"
    EMBEDDED_ONLY = "Artwork only embedded in FLAC"
    WRONG_NAME = "Artwork has a name the Eversolo ignores"
    TOO_SMALL = "Artwork too small"
    TOO_LARGE = "Artwork too large"
    UNREADABLE = "Artwork file is damaged"
    WRONG_FORMAT = "Artwork format mismatch"


# Problems that can be fixed from the existing image without the internet.
LOCAL_FIX_ISSUES = {Issue.TOO_LARGE, Issue.WRONG_FORMAT}


@dataclass
class ImageInfo:
    path: str
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    fmt: str = ""            # JPEG / PNG ... as decoded by Pillow
    progressive: bool = False
    readable: bool = True

    @property
    def min_side(self) -> int:
        return min(self.width, self.height)

    @property
    def max_side(self) -> int:
        return max(self.width, self.height)

    def describe(self) -> str:
        if not self.readable:
            return "unreadable"
        return f"{self.width}×{self.height} {self.fmt} {self.size_bytes // 1024} KB"


@dataclass
class AlbumFolder:
    path: str                      # absolute folder path
    rel: str                       # path relative to the library root
    flacs: list[str]               # file names (not paths), sorted
    cover: Optional[ImageInfo]     # the Eversolo-recognised image, if any
    other_images: list[str]        # other image file names in the folder
    issue: Issue = Issue.OK
    detail: str = ""

    @property
    def folder_artist(self) -> str:
        parts = self.rel.replace("\\", "/").split("/")
        return parts[-2] if len(parts) >= 2 else ""

    @property
    def folder_album(self) -> str:
        return self.rel.replace("\\", "/").split("/")[-1]


@dataclass
class AlbumInfo:
    artist: str = ""
    album: str = ""
    year: str = ""
    track_count: int = 0
    mb_release_id: str = ""
    mb_releasegroup_id: str = ""
    barcode: str = ""
    catalog: str = ""
    track_artist: str = ""
    from_tags: bool = False

    @property
    def is_various(self) -> bool:
        return self.artist.strip().lower() in {"various artists", "various", "va", "v.a.", "v/a"}


@dataclass
class Candidate:
    source: str                    # "Embedded", "Folder", "MusicBrainz", "Deezer", ...
    artist: str = ""
    album: str = ""
    year: str = ""
    track_count: int = 0
    thumb_url: str = ""
    image_url: str = ""            # full-size download (online sources)
    fallback_urls: list[str] = field(default_factory=list)
    local_path: str = ""           # image file on disk (local sources)
    data: Optional[bytes] = None   # embedded picture bytes
    width: int = 0                 # 0 = unknown until downloaded
    height: int = 0
    score: float = 0.0
    thumb: Optional[bytes] = None  # preview bytes (filled during lookup)
    note: str = ""

    @property
    def is_local(self) -> bool:
        return bool(self.local_path or self.data)

    def label(self) -> str:
        size = f"{self.width}×{self.height}" if self.width else "size ?"
        bits = [self.source, size, f"{self.score:.0%}"]
        return " · ".join(bits)


class Status(str, Enum):
    PENDING = "Searching…"
    NOT_SEARCHED = "Hidden – not searched"
    PROPOSED = "Proposed"
    NEEDS_REVIEW = "Needs review"
    NOT_FOUND = "Nothing found"
    WRITING = "Writing…"
    APPLIED = "Done"
    FAILED = "Failed"
    SKIPPED = "Skipped"


@dataclass
class AlbumResult:
    folder: AlbumFolder
    info: AlbumInfo = field(default_factory=AlbumInfo)
    candidates: list[Candidate] = field(default_factory=list)
    chosen: int = -1               # index into candidates
    approved: bool = False
    status: Status = Status.PENDING
    message: str = ""
    current_thumb: Optional[bytes] = None

    @property
    def locked(self) -> bool:
        """Being written or already written: no more edits."""
        return self.status in (Status.WRITING, Status.APPLIED)

    @property
    def choice(self) -> Optional[Candidate]:
        if 0 <= self.chosen < len(self.candidates):
            return self.candidates[self.chosen]
        return None
