"""Run long jobs off the UI thread and report back through Qt signals."""

from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..applier import Applier
from ..cache import Cache
from ..config import Settings
from ..lookup import Finder
from ..models import AlbumFolder, AlbumInfo, AlbumResult, Issue, Status
from ..scanner import scan_library


class Signals(QObject):
    progress = Signal(int, int, str)     # done, total, text
    item = Signal(object)                # one AlbumResult finished
    finished = Signal(object)            # final payload
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, fn: Callable, *args):
        super().__init__()
        self.fn = fn
        self.args = args
        self.signals = Signals()
        self.cancel = threading.Event()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.fn(self, *self.args)
            self.signals.finished.emit(result)
        except Exception as exc:  # report to the UI instead of crashing
            traceback.print_exc()
            self.signals.failed.emit(str(exc))


def start(job: Job) -> Job:
    QThreadPool.globalInstance().start(job)
    return job


# ---- jobs -------------------------------------------------------------------
def scan_job(job: Job, root: str, settings: Settings, cache: Cache):
    t0 = time.monotonic()
    albums = scan_library(
        root, settings, cache,
        progress=lambda n, path: job.signals.progress.emit(n, 0, path),
        cancel=job.cancel,
    )
    return albums, time.monotonic() - t0


def lookup_job(job: Job, folders: list[AlbumFolder], finder: Finder, threads: int):
    total = len(folders)
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, threads), thread_name_prefix="lookup") as pool:
        futures = {pool.submit(_safe_find, finder, f): f for f in folders}
        for fut in as_completed(futures):
            if job.cancel.is_set():
                for other in futures:
                    other.cancel()
                break
            done += 1
            res = fut.result()
            job.signals.item.emit(res)
            job.signals.progress.emit(done, total, res.folder.rel)
    return done


def _safe_find(finder: Finder, folder: AlbumFolder) -> AlbumResult:
    try:
        return finder.find(folder)
    except Exception as exc:
        return AlbumResult(folder=folder, status=Status.FAILED, message=str(exc))


def research_job(job: Job, res: AlbumResult, info: AlbumInfo, finder: Finder):
    new = finder.find(res.folder, info_override=info, all_sources=True)
    # keep any image the user picked from disk
    extra = [c for c in res.candidates if c.source == "Chosen file"]
    new.candidates = extra + new.candidates
    if extra:
        new.chosen, new.approved, new.status = 0, True, Status.PROPOSED
    return new


def apply_job(job: Job, results: list[AlbumResult], applier: Applier, cache: Cache):
    total, ok = len(results), 0
    for i, res in enumerate(results, 1):
        if job.cancel.is_set():
            break
        try:
            res.message = applier.apply(res)
            res.status = Status.APPLIED
            res.approved = False
            res.folder.issue = Issue.OK
            cache.forget_scan(res.folder.path)
            ok += 1
        except Exception as exc:
            res.status = Status.FAILED
            res.message = str(exc)
        job.signals.item.emit(res)
        job.signals.progress.emit(i, total, res.folder.rel)
    return ok
