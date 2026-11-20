import pytest

from flaccovers.matcher import normalize, score, similarity
from flaccovers.metadata import album_info, clean_album_folder, read_tags
from flaccovers.models import AlbumFolder, AlbumInfo, Candidate

from .conftest import make_flac


@pytest.mark.parametrize("name,album,year", [
    ("OK Computer", "OK Computer", ""),
    ("1997 - OK Computer", "OK Computer", "1997"),
    ("OK Computer (1997)", "OK Computer", "1997"),
    ("OK Computer [FLAC 24-96]", "OK Computer", ""),
    ("(2011) Let England Shake {WEB}", "Let England Shake", "2011"),
    ("Abbey Road (Remastered 2009)", "Abbey Road", "2009"),
    ("1999", "1999", "1999"),
])
def test_clean_album_folder(name, album, year):
    assert clean_album_folder(name) == (album, year)


def test_tags_override_folder(tmp_path):
    d = tmp_path / "radiohead" / "okc"
    make_flac(d / "01 - Airbag.flac", {"album": "OK Computer", "albumartist": "Radiohead",
                                         "date": "1997-05-21", "musicbrainz_albumid": "abc"})
    folder = AlbumFolder(path=str(d), rel="radiohead/okc", flacs=["01 - Airbag.flac"],
                         cover=None, other_images=[])
    tags, pics = read_tags(folder)
    info = album_info(folder, tags)
    assert (info.artist, info.album, info.year, info.mb_release_id) == \
        ("Radiohead", "OK Computer", "1997", "abc")
    assert pics == []


def test_folder_artist_beats_track_artist(tmp_path):
    d = tmp_path / "Various Artists" / "Now 1"
    make_flac(d / "01.flac", {"artist": "Somebody feat. Other", "album": "Now 1"})
    folder = AlbumFolder(path=str(d), rel="Various Artists/Now 1", flacs=["01.flac"],
                         cover=None, other_images=[])
    info = album_info(folder, read_tags(folder)[0])
    assert info.artist == "Various Artists"
    assert info.is_various


def test_normalize():
    assert normalize("The Beatles") == "beatles"
    assert normalize("Abbey Road (Remastered 2009)") == "abbey road"
    assert normalize("Sigur Rós") == "sigur ros"
    assert normalize("Simon & Garfunkel") == "simon and garfunkel"


def test_scores_rank_sensibly():
    info = AlbumInfo(artist="Radiohead", album="OK Computer", year="1997", track_count=12)
    exact = Candidate("x", artist="Radiohead", album="OK Computer", year="1997", track_count=12)
    deluxe = Candidate("x", artist="Radiohead", album="OK Computer OKNOTOK 1997 2017",
                       track_count=23)
    wrong = Candidate("x", artist="Radiohead", album="Kid A", year="2000", track_count=10)
    cover_band = Candidate("x", artist="Easy Star All-Stars", album="Radiodread")
    assert score(exact, info) >= 0.95
    assert score(exact, info) > score(deluxe, info) > score(wrong, info)
    assert score(wrong, info) < 0.85
    assert score(cover_band, info) < 0.6
    assert similarity("OK Computer", "OK Computer (Collector's Edition)") == 1.0


def test_various_artists_scoring():
    info = AlbumInfo(artist="Various Artists", album="Pulp Fiction OST", track_count=16)
    good = Candidate("x", artist="Various Artists", album="Pulp Fiction OST", track_count=16)
    meh = Candidate("x", artist="Dick Dale", album="Pulp Fiction OST", track_count=16)
    assert score(good, info) > score(meh, info)
    assert score(good, info) >= 0.85
