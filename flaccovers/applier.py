"""Write cover.jpg into album folders, with backup and undo.

* The new image is written to a temp file and atomically renamed.
* Any other Eversolo-recognised image (cover.png, folder.jpg, front.jpg ...)
  is *moved* to the backup folder so the player can only pick the new one.
  Other images (back.jpg, booklet scans ...) are never touched.
* Every run gets a timestamped backup folder with a manifest.json for undo.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from . import images
from .config import COVER_FILENAME, Settings, app_dir, backups_dir
from .http import HttpClient
from .models import AlbumResult, Candidate
from .scanner import recognised_rank


class ApplyError(Exception):
    pass


def fetch_full_image(c: Candidate, http: HttpClient) -> bytes:
    if c.data:
        return c.data
    if c.local_path:
        with open(c.local_path, "rb") as fh:
            return fh.read()
    for url in [c.image_url, *c.fallback_urls]:
        if not url:
            continue
        data = http.get_bytes(url)
        if data and images.probe_bytes(data)[0]:
            return data
    raise ApplyError(f"Could not download image from {c.source}")


class Applier:
    def __init__(self, settings: Settings, http: Optional[HttpClient] = None,
                 run_dir: Optional[Path] = None):
        self.s = settings
        self.http = http or HttpClient(settings.user_agent())
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.run_dir = run_dir or backups_dir() / stamp
        self.manifest: list[dict] = []
        self.log_path = app_dir("logs") / "changes.log"

    def apply(self, res: AlbumResult) -> str:
        c = res.choice
        if c is None:
            raise ApplyError("No image chosen")
        raw = fetch_full_image(c, self.http)
        jpeg = images.to_cover_jpeg(raw, self.s.target_size, self.s.jpeg_quality,
                                    self.s.max_output_kb)
        folder = res.folder.path
        target = os.path.join(folder, COVER_FILENAME)

        # Back up every recognised artwork file in the folder (incl. old cover.jpg).
        entry = {"folder": folder, "rel": res.folder.rel, "moved": [], "created": target}
        backup = self.run_dir / res.folder.rel
        for name in sorted(os.listdir(folder)):
            if name.startswith("._") or recognised_rank(name) is None:
                continue
            src = os.path.join(folder, name)
            backup.mkdir(parents=True, exist_ok=True)
            dst = backup / name
            if name.lower() == COVER_FILENAME:
                shutil.copy2(src, dst)          # replaced in place below
            else:
                shutil.move(src, dst)
            entry["moved"].append({"from": src, "backup": str(dst)})

        tmp = os.path.join(folder, ".cover.jpg.partial")
        with open(tmp, "wb") as fh:
            fh.write(jpeg)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)

        if self.s.remove_appledouble:
            for junk in (".cover.jpg.partial", "._cover.jpg", "._.cover.jpg.partial"):
                try:
                    os.remove(os.path.join(folder, junk))
                except OSError:
                    pass

        self.manifest.append(entry)
        self._write_manifest()
        w, h = images.probe_bytes(jpeg)
        msg = f"cover.jpg {w}×{h} {len(jpeg) // 1024} KB from {c.source}"
        with open(self.log_path, "a") as log:
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{res.folder.rel}\t{msg}\n")
        return msg

    def _write_manifest(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "manifest.json").write_text(json.dumps(self.manifest, indent=1))


def last_run() -> Optional[Path]:
    runs = sorted(p for p in backups_dir().iterdir()
                  if p.is_dir() and (p / "manifest.json").exists() and not (p / "UNDONE").exists())
    return runs[-1] if runs else None


def undo_run(run_dir: Path) -> int:
    """Delete created cover.jpg files and put the backed-up files back."""
    manifest = json.loads((run_dir / "manifest.json").read_text())
    for entry in reversed(manifest):
        try:
            os.remove(entry["created"])
        except OSError:
            pass
        for m in entry["moved"]:
            try:
                shutil.copy2(m["backup"], m["from"])
            except OSError:
                pass
    (run_dir / "UNDONE").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
    return len(manifest)
