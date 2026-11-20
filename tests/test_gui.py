"""Smoke test the GUI off-screen: scan → lookup → apply, no network."""

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from flaccovers.cache import Cache  # noqa: E402
from flaccovers.config import Settings  # noqa: E402
from flaccovers.gui import main_window as mw_mod  # noqa: E402
from flaccovers.models import Status  # noqa: E402

from .test_lookup_apply import FakeHttp  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_full_flow(app, library, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    http = FakeHttp()
    real_finder = mw_mod.Finder
    monkeypatch.setattr(mw_mod, "Finder", lambda s, c: real_finder(s, c, http))

    s = Settings(library_path=str(library), use_discogs=False)
    w = mw_mod.MainWindow(s, Cache(tmp_path / "c.db"))
    w.show()
    w.scan()
    assert _wait(app, lambda: w.stop_btn.isEnabled() is False and w.model.rows
                 and all(r.status != Status.PENDING for r in w.model.rows))
    rels = {r.folder.rel: r for r in w.model.rows}
    assert "Good Artist/Good Album" not in rels
    assert rels["Radiohead/OK Computer"].approved
    assert "need attention" in w.summary.text()

    w.table.selectRow(0)
    assert w.current is not None and w.cands.count() >= 1

    n = len(w.model.approved())
    assert n >= 5
    w.apply()
    assert _wait(app, lambda: sum(r.status == Status.APPLIED for r in w.model.rows) == n)
    assert (library / "Radiohead" / "OK Computer" / "cover.jpg").exists()
    w.close()
