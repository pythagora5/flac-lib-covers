"""Regression tests for the macOS 'Too many open files' failure."""

import errno
import os

import pytest

from flaccovers import images
from flaccovers.cache import Cache
from flaccovers.config import Settings
from flaccovers.lookup import Finder
from flaccovers.scanner import scan_library

from .test_lookup_apply import FakeHttp

FD_DIR = "/dev/fd" if os.path.isdir("/dev/fd") else "/proc/self/fd"


def open_fds() -> int:
    return len(os.listdir(FD_DIR))


def test_repeated_scans_and_lookups_do_not_leak_files(library, tmp_path):
    cache = Cache(tmp_path / "c.db")
    s = Settings(use_discogs=False, scan_threads=8, lookup_threads=8)
    scan_library(str(library), s, cache)
    before = open_fds()
    for _ in range(15):  # each run makes fresh thread pools
        albums = scan_library(str(library), s, cache)
        f = Finder(s, cache, FakeHttp())
        for a in albums:
            if a.issue.name != "OK":
                f.find(a)
        f.close()
    assert open_fds() - before <= 3
    cache.close()


def test_cache_close_releases_files(tmp_path):
    before = open_fds()
    caches = [Cache(tmp_path / f"c{i}.db") for i in range(10)]
    for c in caches:
        c.get_scan("x", "y")
        c.close()
    assert open_fds() - before <= 1


def test_system_errors_are_not_mistaken_for_damaged_art(library, monkeypatch):
    def boom(*a, **k):
        raise OSError(errno.EMFILE, "Too many open files")

    monkeypatch.setattr(images.Image, "open", boom)
    with pytest.raises(OSError):
        scan_library(str(library), Settings())  # loud failure, not "damaged"


def test_decode_errors_still_count_as_damaged(tmp_path):
    p = tmp_path / "cover.jpg"
    p.write_bytes(b"\xff\xd8 not really a jpeg")
    assert images.inspect(str(p)).readable is False
