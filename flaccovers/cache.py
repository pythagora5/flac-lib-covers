"""SQLite caches: scan results, online lookup results and preview thumbnails.

All caches are safe to delete; they only make repeat runs faster."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import weakref
from pathlib import Path
from typing import Optional

from .config import app_dir


class Cache:
    """One shared SQLite connection guarded by a lock.

    (A connection per thread leaked file handles: every worker thread that
    touched the cache kept 1-3 files open, and macOS only allows 256.)"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else app_dir("cache") / "cache.sqlite3"
        self._lock = threading.RLock()
        self._db: Optional[sqlite3.Connection] = sqlite3.connect(
            self.path, timeout=30, isolation_level=None, check_same_thread=False)
        self._finalizer = weakref.finalize(self, self._db.close)
        with self._lock:
            c = self._db
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute(
                "CREATE TABLE IF NOT EXISTS scan ("
                " path TEXT PRIMARY KEY, sig TEXT NOT NULL, data TEXT NOT NULL)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS lookup ("
                " key TEXT PRIMARY KEY, created REAL NOT NULL, data TEXT NOT NULL)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS thumb ("
                " url TEXT PRIMARY KEY, created REAL NOT NULL, data BLOB NOT NULL)"
            )

    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError("cache is closed")
        return self._db

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._finalizer()
                self._db = None

    def _one(self, sql: str, args: tuple):
        with self._lock:
            return self._conn().execute(sql, args).fetchone()

    # ---- scan -------------------------------------------------------------
    def get_scan(self, path: str, sig: str) -> Optional[dict]:
        row = self._one("SELECT data FROM scan WHERE path=? AND sig=?", (path, sig))
        return json.loads(row[0]) if row else None

    def put_scans(self, rows: list[tuple[str, str, dict]]) -> None:
        if not rows:
            return
        with self._lock:
            c = self._conn()
            c.execute("BEGIN")
            c.executemany(
                "INSERT OR REPLACE INTO scan(path, sig, data) VALUES (?,?,?)",
                [(p, s, json.dumps(d)) for p, s, d in rows],
            )
            c.execute("COMMIT")

    def forget_scan(self, path: str) -> None:
        with self._lock:
            self._conn().execute("DELETE FROM scan WHERE path=?", (path,))

    # ---- lookup -----------------------------------------------------------
    @staticmethod
    def lookup_key(*parts: str) -> str:
        return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()

    def get_lookup(self, key: str, max_age_days: float) -> Optional[list]:
        row = self._one("SELECT created, data FROM lookup WHERE key=?", (key,))
        if not row or time.time() - row[0] > max_age_days * 86400:
            return None
        return json.loads(row[1])

    def put_lookup(self, key: str, data: list) -> None:
        with self._lock:
            self._conn().execute(
                "INSERT OR REPLACE INTO lookup(key, created, data) VALUES (?,?,?)",
                (key, time.time(), json.dumps(data)),
            )

    # ---- thumbnails ---------------------------------------------------------
    def get_thumb(self, url: str) -> Optional[bytes]:
        row = self._one("SELECT data FROM thumb WHERE url=?", (url,))
        return bytes(row[0]) if row else None

    def put_thumb(self, url: str, data: bytes) -> None:
        with self._lock:
            self._conn().execute(
                "INSERT OR REPLACE INTO thumb(url, created, data) VALUES (?,?,?)",
                (url, time.time(), sqlite3.Binary(data)),
            )

    def clear(self) -> None:
        with self._lock:
            c = self._conn()
            for table in ("scan", "lookup", "thumb"):
                c.execute(f"DELETE FROM {table}")
            c.execute("VACUUM")
