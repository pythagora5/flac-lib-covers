"""Fast library scan: find album folders and check their artwork.

Performance notes
* Uses ``os.scandir`` (one directory read per folder, no per-file ``stat``
  except for image files).
* Never opens FLAC files; only image *headers* are read.
* Each top-level folder (artist) is walked in a thread pool. Keep the pool
  small for spinning USB disks; 4 is a good default.
* Results are cached in SQLite keyed by folder mtime + image size/mtime, so a
  re-scan of an unchanged library only lists directories.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Callable, Iterable, Optional

from . import images
from .cache import Cache
from .config import AUDIO_EXT, IMAGE_EXTS, RECOGNISED_EXTS, RECOGNISED_STEMS, Settings
from .models import AlbumFolder, ImageInfo, Issue

SKIP_DIRS = {
    "$RECYCLE.BIN",
    "System Volume Information",
    "lost+found",
    "@eaDir",            # Synology thumbnails
    "#recycle",
}

ProgressFn = Callable[[int, str], None]


def _is_hidden(name: str) -> bool:
    return name.startswith(".") or name in SKIP_DIRS


def recognised_rank(name: str) -> Optional[int]:
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    stem = stem.lower()
    if ext not in RECOGNISED_EXTS or stem not in RECOGNISED_STEMS:
        return None
    # cover < folder < front, and jpg before png
    return RECOGNISED_STEMS.index(stem) * 10 + (0 if ext in (".jpg", ".jpeg") else 1)


def classify(cover: Optional[ImageInfo], other_images: list[str], s: Settings) -> tuple[Issue, str]:
    """Decide whether an album's artwork is fine for the Eversolo."""
    if cover is None:
        if other_images:
            return Issue.WRONG_NAME, ", ".join(other_images[:3])
        return Issue.MISSING, ""
    name = os.path.basename(cover.path)
    if not cover.readable:
        return Issue.UNREADABLE, name
    ext = os.path.splitext(name)[1].lower()
    expect = "PNG" if ext == ".png" else "JPEG"
    if cover.fmt and cover.fmt != expect:
        return Issue.WRONG_FORMAT, f"{name} is really {cover.fmt}"
    if cover.min_side < s.min_size:
        return Issue.TOO_SMALL, f"{name} {cover.width}×{cover.height}"
    if cover.max_side > s.max_size or cover.size_bytes > s.max_file_kb * 1024:
        return Issue.TOO_LARGE, f"{name} {cover.describe()}"
    if s.flag_progressive_jpeg and cover.progressive:
        return Issue.WRONG_FORMAT, f"{name} is progressive JPEG"
    if s.flag_png_cover and cover.fmt == "PNG":
        return Issue.WRONG_FORMAT, f"{name} is PNG"
    return Issue.OK, cover.describe()


def _walk(top: str, recurse: bool = True) -> Iterable[tuple[str, int, list[str], list[os.DirEntry]]]:
    """Yield (dir, dir_mtime_ns, flac_names, image_entries) for album dirs."""
    stack = [top]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        flacs: list[str] = []
        imgs: list[os.DirEntry] = []
        with it:
            for e in it:
                name = e.name
                if name.startswith("._"):
                    continue  # macOS AppleDouble junk on exFAT/FAT drives
                try:
                    if e.is_dir(follow_symlinks=False):
                        if recurse and not _is_hidden(name):
                            stack.append(e.path)
                        continue
                except OSError:
                    continue
                low = name.lower()
                if low.endswith(AUDIO_EXT):
                    flacs.append(name)
                elif low.endswith(IMAGE_EXTS):
                    imgs.append(e)
        if flacs:
            try:
                mtime = os.stat(d).st_mtime_ns
            except OSError:
                mtime = 0
            yield d, mtime, flacs, imgs


def _assess(root: str, d: str, mtime: int, flacs: list[str], imgs: list[os.DirEntry],
            s: Settings, cache: Optional[Cache], pending: list) -> AlbumFolder:
    stats = []
    for e in imgs:
        try:
            st = e.stat()
            stats.append((e.name, st.st_size, st.st_mtime_ns))
        except OSError:
            stats.append((e.name, 0, 0))
    sig = f"{mtime}|" + "|".join(f"{n}:{sz}:{mt}" for n, sz, mt in sorted(stats))

    cached = cache.get_scan(d, sig) if cache else None
    if cached is not None:
        cover = ImageInfo(**cached["cover"]) if cached["cover"] else None
        others = cached["others"]
    else:
        ranked = sorted(
            ((recognised_rank(n), n, sz) for n, sz, _ in stats if recognised_rank(n) is not None)
        )
        cover = None
        if ranked:
            _, name, size = ranked[0]
            cover = images.inspect(os.path.join(d, name), size)
            cover.path = os.path.join(d, name)
        others = sorted(n for n, _, _ in stats if recognised_rank(n) is None)
        pending.append((d, sig, {"cover": asdict(cover) if cover else None, "others": others}))

    issue, detail = classify(cover, others, s)
    rel = os.path.relpath(d, root)
    return AlbumFolder(path=d, rel=rel, flacs=sorted(flacs), cover=cover,
                       other_images=others, issue=issue, detail=detail)


def scan_library(root: str, settings: Settings, cache: Optional[Cache] = None,
                 progress: Optional[ProgressFn] = None,
                 cancel: Optional[threading.Event] = None) -> list[AlbumFolder]:
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise FileNotFoundError(f"Library folder not found: {root}")

    # Split work by top-level folder (normally one per artist).
    tops: list[str] = []
    albums: list[AlbumFolder] = []
    pending: list = []
    lock = threading.Lock()
    found = 0

    def run(top: str, recurse: bool) -> list[AlbumFolder]:
        nonlocal found
        out: list[AlbumFolder] = []
        local_pending: list = []
        walker = _walk(top, recurse)
        for d, mtime, flacs, imgs in walker:
            if cancel is not None and cancel.is_set():
                break
            out.append(_assess(root, d, mtime, flacs, imgs, settings, cache, local_pending))
            with lock:
                found += 1
                n = found
            if progress and n % 25 == 0:
                progress(n, os.path.relpath(d, root))
        with lock:
            pending.extend(local_pending)
        return out

    try:
        with os.scandir(root) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False) and not _is_hidden(e.name):
                    tops.append(e.path)
    except OSError as exc:
        raise OSError(f"Cannot read {root}: {exc}") from exc

    with ThreadPoolExecutor(max_workers=max(1, settings.scan_threads)) as pool:
        futures = [pool.submit(run, t, True) for t in tops]
        futures.append(pool.submit(run, root, False))  # FLACs directly in root
        for f in as_completed(futures):
            albums.extend(f.result())

    if cache:
        cache.put_scans(pending)
    if progress:
        progress(len(albums), "")
    albums.sort(key=lambda a: a.rel.lower())
    return albums
