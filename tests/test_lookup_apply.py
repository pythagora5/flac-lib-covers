import io
import json
import os

from PIL import Image

from flaccovers import applier as applier_mod
from flaccovers.applier import Applier, last_run, undo_run
from flaccovers.cache import Cache
from flaccovers.config import Settings
from flaccovers.lookup import Finder
from flaccovers.models import Issue, Status
from flaccovers.scanner import scan_library

from .conftest import make_image


class FakeHttp:
    """Serves canned API responses; records every URL requested."""

    def __init__(self):
        self.urls = []
        self.user_agent = "test"
        self.img = make_image((1000, 1000), color=(10, 200, 10))

    def get_json(self, url, params=None, headers=None):
        self.urls.append(url)
        if "deezer" in url:
            return {"data": [{
                "title": "OK Computer", "nb_tracks": 3, "artist": {"name": "Radiohead"},
                "cover_medium": "https://img/dz-250.jpg", "cover_big": "https://img/dz-500.jpg",
                "cover_xl": "https://img/dz-1000.jpg"}]}
        if "musicbrainz" in url:
            return {"releases": []}
        if "itunes" in url:
            return {"results": []}
        return None

    def close(self):
        pass

    def get_bytes(self, url, headers=None, limit=0):
        self.urls.append(url)
        ok = url.startswith(("https://img/", "https://coverartarchive.org/"))
        return self.img if ok else None


def _albums(library, tmp_path):
    s = Settings(use_discogs=False)
    cache = Cache(tmp_path / "c.db")
    return s, cache, {a.rel: a for a in scan_library(str(library), s, cache)}


def test_local_fixes_need_no_internet(library, tmp_path):
    s, cache, albums = _albums(library, tmp_path)
    http = FakeHttp()
    f = Finder(s, cache, http)
    for rel, src in [("Embedded/Only", "Copied from FLAC"), ("Big/Huge Art", "Existing file"),
                     ("Named/Wrong Name", "Folder: AlbumArt_Large.jpg"),
                     ("Mismatch/PNG As JPG", "Existing file")]:
        res = f.find(albums[rel])
        assert res.choice.source == src, rel
        assert res.approved and res.status == Status.PROPOSED
    assert albums["Embedded/Only"].issue == Issue.EMBEDDED_ONLY
    assert http.urls == []


def test_online_fast_path_and_cache(library, tmp_path):
    s, cache, albums = _albums(library, tmp_path)
    http = FakeHttp()
    res = Finder(s, cache, http).find(albums["Radiohead/OK Computer"])
    assert res.choice.source == "Deezer"
    assert res.approved
    assert not any("musicbrainz" in u or "itunes" in u for u in http.urls)  # fast path

    http2 = FakeHttp()
    res2 = Finder(s, cache, http2).find(albums["Radiohead/OK Computer"])
    assert res2.choice.source == "Deezer"
    assert http2.urls == []  # lookup + thumbnail served from cache


def test_musicbrainz_id_in_tags_wins_without_searching(tmp_path):
    from .conftest import make_flac
    d = tmp_path / "lib" / "Daft Punk" / "Discovery"
    make_flac(d / "01.flac", {"album": "Discovery", "albumartist": "Daft Punk",
                              "musicbrainz_releasegroupid": "rg-123"})
    s = Settings(use_discogs=False)
    http = FakeHttp()
    (album,) = scan_library(str(tmp_path / "lib"), s)
    res = Finder(s, Cache(tmp_path / "c.db"), http).find(album)
    assert res.choice.source == "MusicBrainz" and res.choice.score == 1.0
    assert "release-group/rg-123" in res.choice.image_url
    assert not any("itunes" in u for u in http.urls)  # later tiers skipped


def test_weak_match_needs_review(library, tmp_path):
    s, cache, albums = _albums(library, tmp_path)
    res = Finder(s, cache, FakeHttp()).find(albums["Various Artists/Now 1"])
    assert res.status in (Status.NEEDS_REVIEW, Status.NOT_FOUND)
    assert not res.approved


def test_apply_writes_eversolo_cover_with_backup_and_undo(library, tmp_path):
    s, cache, albums = _albums(library, tmp_path)
    http = FakeHttp()
    finder = Finder(s, cache, http)
    big = finder.find(albums["Big/Huge Art"])
    online = finder.find(albums["Radiohead/OK Computer"])
    small_dir = library / "Small" / "Tiny Art"
    (small_dir / "folder.png").write_bytes(make_image((200, 200), fmt="PNG"))
    rescanned = {a.rel: a for a in scan_library(str(library), s)}
    small = finder.find(rescanned["Small/Tiny Art"])
    small.chosen = 0  # the existing (small) cover is the only local option

    ap = Applier(s, http)
    for r in (big, online, small):
        ap.apply(r)

    for d in (library / "Big" / "Huge Art", library / "Radiohead" / "OK Computer"):
        im = Image.open(d / "cover.jpg")
        assert im.format == "JPEG" and im.size == (800, 800)
        assert not im.info.get("progressive")
        assert os.path.getsize(d / "cover.jpg") <= s.max_output_kb * 1024
    # the other recognised file was moved away so the player can't pick it
    assert not (small_dir / "folder.png").exists()

    run = last_run()
    manifest = json.loads((run / "manifest.json").read_text())
    assert len(manifest) == 3
    assert undo_run(run) == 3
    assert not (library / "Radiohead" / "OK Computer" / "cover.jpg").exists()
    assert Image.open(library / "Big" / "Huge Art" / "cover.jpg").size == (3000, 3000)
    assert (small_dir / "folder.png").exists()
    assert last_run() is None


def test_flac_files_are_never_modified(library, tmp_path):
    import hashlib
    s, cache, albums = _albums(library, tmp_path)
    d = library / "Embedded" / "Only"
    before = {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in d.glob("*.flac")}
    res = Finder(s, cache, FakeHttp()).find(albums["Embedded/Only"])
    Applier(s, FakeHttp()).apply(res)
    after = {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in d.glob("*.flac")}
    assert before == after
    assert Image.open(d / "cover.jpg").size == (800, 800)  # folder art made from the FLAC art


def test_to_cover_jpeg_handles_odd_inputs():
    from flaccovers.images import to_cover_jpeg
    rgba = make_image((900, 880), fmt="PNG", color=(0, 0, 0, 0))
    out = Image.open(io.BytesIO(to_cover_jpeg(rgba, 800, 90, 900)))
    assert out.size == (800, 800) and out.mode == "RGB"
    assert out.getpixel((10, 10)) == (255, 255, 255)
    small = Image.open(io.BytesIO(to_cover_jpeg(make_image((400, 400)), 800, 90, 900)))
    assert small.size == (400, 400)  # never upscaled
    cmyk = io.BytesIO()
    Image.new("CMYK", (1200, 1200)).save(cmyk, "JPEG")
    assert Image.open(io.BytesIO(to_cover_jpeg(cmyk.getvalue(), 800, 90, 900))).mode == "RGB"


def test_fetch_falls_back_to_smaller_image():
    from flaccovers.models import Candidate

    class H(FakeHttp):
        def get_bytes(self, url, headers=None, limit=0):
            return None if "1200" in url else self.img

    c = Candidate("MusicBrainz", image_url="https://x/front-1200",
                  fallback_urls=["https://x/front-500"])
    assert applier_mod.fetch_full_image(c, H()) is not None
