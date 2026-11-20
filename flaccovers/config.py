"""Settings, paths and Eversolo artwork rules.

Eversolo's music-library guide says the player reads an image placed in the
album folder named ``cover``, ``folder`` or ``front`` (jpg or png), and
recommends 500x500 or 800x800 pixels.  This app always writes ``cover.jpg``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "FLAC Cover Fixer"
APP_VERSION = "1.0.0"
BUNDLE_ID = "local.flaccovers.app"

# ---- Eversolo rules -------------------------------------------------------
COVER_FILENAME = "cover.jpg"
# Names the Eversolo recognises, in the order this app prefers them.
RECOGNISED_STEMS = ("cover", "folder", "front")
RECOGNISED_EXTS = (".jpg", ".jpeg", ".png")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff")
AUDIO_EXT = ".flac"


def _platform_dir(kind: str) -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        base = {
            "support": home / "Library" / "Application Support",
            "cache": home / "Library" / "Caches",
            "logs": home / "Library" / "Logs",
        }[kind]
    else:  # Linux / tests
        base = {
            "support": Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")),
            "cache": Path(os.environ.get("XDG_CACHE_HOME", home / ".cache")),
            "logs": Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state")),
        }[kind]
    return base / APP_NAME


def app_dir(kind: str) -> Path:
    """Return (and create) the support / cache / logs directory.

    ``FLACCOVERS_HOME`` overrides everything (used by the tests)."""
    override = os.environ.get("FLACCOVERS_HOME")
    path = Path(override) / kind if override else _platform_dir(kind)
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir() -> Path:
    path = app_dir("support") / "Backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    library_path: str = "/Volumes/2TB"
    # Output image
    target_size: int = 800          # Eversolo recommendation (500 or 800)
    jpeg_quality: int = 90
    max_output_kb: int = 900
    # What counts as "existing art is fine"
    min_size: int = 500             # smaller than this -> look for better art
    max_size: int = 1600            # bigger than this -> shrink to target_size
    max_file_kb: int = 1500         # bigger file than this -> shrink
    flag_progressive_jpeg: bool = False
    flag_png_cover: bool = False    # PNG is supported, so off by default
    # Performance
    scan_threads: int = 4           # USB hard drives dislike lots of seeking
    lookup_threads: int = 8
    fast_path: bool = True          # stop searching once a strong match is found
    # Sources
    use_musicbrainz: bool = True
    use_deezer: bool = True
    use_itunes: bool = True
    use_discogs: bool = True
    itunes_country: str = "US"
    contact: str = ""               # optional, added to the MusicBrainz User-Agent
    # Matching
    auto_approve_score: float = 0.85
    auto_apply: bool = True         # write confident matches without waiting
    # Housekeeping
    remove_appledouble: bool = True
    lookup_cache_days: int = 30
    hidden_issues: list = field(default_factory=list)   # Issue names hidden in review
    extra: dict = field(default_factory=dict)

    # ---- persistence ----------------------------------------------------
    @staticmethod
    def path() -> Path:
        return app_dir("support") / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(cls.path().read_text())
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        os.replace(tmp, self.path())

    def user_agent(self) -> str:
        contact = f" ( {self.contact} )" if self.contact.strip() else ""
        return f"FLACCoverFixer/{APP_VERSION}{contact}"


# ---- Discogs token in the macOS Keychain -----------------------------------
_KEYRING_USER = "discogs-token"


def get_discogs_token() -> str:
    env = os.environ.get("DISCOGS_TOKEN")
    if env:
        return env
    try:
        import keyring

        return keyring.get_password(APP_NAME, _KEYRING_USER) or ""
    except Exception:  # no keychain backend (e.g. CI)
        return ""


def set_discogs_token(token: str) -> bool:
    try:
        import keyring

        if token:
            keyring.set_password(APP_NAME, _KEYRING_USER, token)
        else:
            try:
                keyring.delete_password(APP_NAME, _KEYRING_USER)
            except Exception:
                pass
        return True
    except Exception:
        return False
