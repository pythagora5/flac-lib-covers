import io
import os
import struct
from pathlib import Path

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _streaminfo() -> bytes:
    # 4096-sample blocks, 44.1 kHz, stereo, 16-bit, 0 samples, empty MD5
    sr, ch, bps, total = 44100, 2, 16, 0
    packed = (sr << 44) | ((ch - 1) << 41) | ((bps - 1) << 36) | total
    return struct.pack(">HH", 4096, 4096) + b"\0" * 6 + packed.to_bytes(8, "big") + b"\0" * 16


def make_flac(path: Path, tags: dict | None = None, picture: bytes | None = None) -> Path:
    from mutagen.flac import FLAC, Picture

    body = _streaminfo()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fLaC" + bytes([0x80]) + len(body).to_bytes(3, "big") + body)
    f = FLAC(path)
    if tags:
        f.add_tags()
        for k, v in tags.items():
            f.tags[k] = v
    if picture:
        p = Picture()
        p.type = 3
        p.mime = "image/jpeg"
        p.data = picture
        f.add_picture(p)
    f.save()
    return path


def make_image(size=(800, 800), fmt="JPEG", color=(200, 30, 30), **kw) -> bytes:
    im = Image.new("RGBA" if fmt == "PNG" else "RGB", size, color)
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FLACCOVERS_HOME", str(tmp_path / "apphome"))
    monkeypatch.setenv("DISCOGS_TOKEN", "")
    yield


@pytest.fixture
def library(tmp_path):
    """A small library covering every artwork situation."""
    root = tmp_path / "lib"

    def album(rel, n=3, tags=None, picture=None):
        d = root / rel
        for i in range(1, n + 1):
            make_flac(d / f"{i:02d} - Track {i}.flac", tags, picture if i == 1 else None)
        return d

    album("Good Artist/Good Album").joinpath("cover.jpg").write_bytes(make_image())
    album("Good Artist/Folder Named").joinpath("folder.jpg").write_bytes(make_image())
    album("Radiohead/OK Computer", tags={"album": "OK Computer", "albumartist": "Radiohead",
                                         "date": "1997-05-21"})
    album("Small/Tiny Art").joinpath("cover.jpg").write_bytes(make_image((300, 300)))
    album("Big/Huge Art").joinpath("cover.jpg").write_bytes(make_image((3000, 3000)))
    album("Named/Wrong Name").joinpath("AlbumArt_Large.jpg").write_bytes(make_image())
    album("Embedded/Only", picture=make_image((1000, 1000)))
    album("Broken/Damaged").joinpath("cover.jpg").write_bytes(b"not an image")
    album("Mismatch/PNG As JPG").joinpath("cover.jpg").write_bytes(make_image(fmt="PNG"))
    album("Various Artists/Now 1")
    hidden = root / ".Trashes" / "x"
    make_flac(hidden / "01.flac")
    (root / "Good Artist" / "Good Album" / "._cover.jpg").write_bytes(b"junk")
    return root
