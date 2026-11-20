from flaccovers.cache import Cache
from flaccovers.config import Settings
from flaccovers.models import Issue
from flaccovers.scanner import recognised_rank, scan_library


def _by_rel(albums):
    return {a.rel: a for a in albums}


def test_scan_classifies_every_case(library, tmp_path):
    albums = _by_rel(scan_library(str(library), Settings(), Cache(tmp_path / "c.db")))
    assert albums["Good Artist/Good Album"].issue == Issue.OK
    assert albums["Good Artist/Folder Named"].issue == Issue.OK
    assert albums["Radiohead/OK Computer"].issue == Issue.MISSING
    assert albums["Small/Tiny Art"].issue == Issue.TOO_SMALL
    assert albums["Big/Huge Art"].issue == Issue.TOO_LARGE
    assert albums["Named/Wrong Name"].issue == Issue.WRONG_NAME
    assert albums["Embedded/Only"].issue == Issue.MISSING  # refined during lookup
    assert albums["Broken/Damaged"].issue == Issue.UNREADABLE
    assert albums["Mismatch/PNG As JPG"].issue == Issue.WRONG_FORMAT
    assert albums["Various Artists/Now 1"].issue == Issue.MISSING
    assert not any(".Trashes" in rel for rel in albums)
    assert len(albums["Good Artist/Good Album"].flacs) == 3


def test_scan_cache_is_used_and_invalidated(library, tmp_path, monkeypatch):
    cache = Cache(tmp_path / "c.db")
    s = Settings()
    scan_library(str(library), s, cache)

    import flaccovers.images as images_mod
    calls = []
    real = images_mod.inspect
    monkeypatch.setattr(images_mod, "inspect", lambda *a, **k: calls.append(a) or real(*a, **k))
    scan_library(str(library), s, cache)
    assert calls == []  # nothing re-read on an unchanged library

    (library / "Small" / "Tiny Art" / "cover.jpg").write_bytes(
        (library / "Good Artist" / "Good Album" / "cover.jpg").read_bytes() + b"\0" * 10)
    albums = _by_rel(scan_library(str(library), s, cache))
    assert len(calls) == 1
    assert albums["Small/Tiny Art"].issue == Issue.OK


def test_thresholds_apply_to_cached_results(library, tmp_path):
    cache = Cache(tmp_path / "c.db")
    scan_library(str(library), Settings(), cache)
    albums = _by_rel(scan_library(str(library), Settings(min_size=200), cache))
    assert albums["Small/Tiny Art"].issue == Issue.OK


def test_recognised_names():
    assert recognised_rank("cover.jpg") < recognised_rank("folder.jpg") < recognised_rank("front.png")
    assert recognised_rank("Cover.JPG") is not None
    assert recognised_rank("back.jpg") is None
    assert recognised_rank("cover.webp") is None
