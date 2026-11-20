"""Online artwork sources. Each returns a list of :class:`Candidate`."""

from .base import Source
from .deezer import DeezerSource
from .discogs import DiscogsSource
from .itunes import ITunesSource
from .musicbrainz import MusicBrainzSource

__all__ = ["Source", "DeezerSource", "DiscogsSource", "ITunesSource", "MusicBrainzSource"]
