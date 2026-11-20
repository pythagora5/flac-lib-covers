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


def _window(app, library, tmp_path, monkeypatch, **settings):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    http = FakeHttp()
    real_finder = mw_mod.Finder
    monkeypatch.setattr(mw_mod, "Finder", lambda s, c: real_finder(s, c, http))
    s = Settings(library_path=str(library), use_discogs=False, **settings)
    w = mw_mod.MainWindow(s, Cache(tmp_path / "c.db"))
    w.show()
    w.scan()
    assert _wait(app, lambda: w.model.rows and not w._lookup_running
                 and all(r.status != Status.PENDING for r in w.model.rows))
    return w


def test_hidden_problem_type_is_not_searched_or_applied(app, library, tmp_path, monkeypatch):
    from flaccovers.models import Issue
    w = _window(app, library, tmp_path, monkeypatch, hidden_issues=["TOO_SMALL"])
    rows = {r.folder.rel: r for r in w.model.rows}
    small = rows["Small/Tiny Art"]
    assert small.status == Status.NOT_SEARCHED and not small.candidates
    assert small not in w.proxy.visible_results()
    assert small not in w._to_apply()
    assert "1 hidden" in w.issue_btn.text()

    w.issue_actions[Issue.TOO_SMALL].setChecked(True)   # show it again
    assert _wait(app, lambda: small.folder.path in [r.folder.path for r in w.proxy.visible_results()]
                 and w.model.rows[w.model._index[small.folder.path]].status != Status.PENDING
                 and not w._lookup_running)
    assert w.model.rows[w.model._index[small.folder.path]].status != Status.NOT_SEARCHED
    assert Settings.load().hidden_issues == []
    w.close()


def test_editing_artist_album_searches_again(app, library, tmp_path, monkeypatch):
    from flaccovers.gui.model import C_ALBUM, C_ARTIST
    w = _window(app, library, tmp_path, monkeypatch)
    row = next(i for i, r in enumerate(w.model.rows) if r.folder.rel == "Various Artists/Now 1")
    assert w.model.rows[row].choice is None or not w.model.rows[row].approved

    w.model.setData(w.model.index(row, C_ARTIST), "Radiohead")
    w.model.setData(w.model.index(row, C_ALBUM), "OK Computer")
    res = lambda: w.model.rows[row]  # noqa: E731
    assert _wait(app, lambda: not w._searches)
    assert (res().info.artist, res().info.album) == ("Radiohead", "OK Computer")
    assert res().choice.source == "Deezer" and res().approved
    assert res().status == Status.PROPOSED
    w.close()


def _select(w, rels):
    from PySide6.QtCore import QItemSelectionModel
    sm = w.table.selectionModel()
    sm.clearSelection()
    first = True
    for i in range(w.proxy.rowCount()):
        r = w.proxy.visible_results()[i]
        if r.folder.rel in rels:
            idx = w.proxy.index(i, 0)
            flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
            if first:
                sm.setCurrentIndex(idx, flags)
                first = False
            else:
                sm.select(idx, flags)


def test_candidate_click_applies_to_all_selected_rows(app, library, tmp_path, monkeypatch):
    w = _window(app, library, tmp_path, monkeypatch)
    rels = ["Radiohead/OK Computer", "Various Artists/Now 1", "Small/Tiny Art"]
    _select(w, rels)
    assert len(w._selected()) == 3
    assert "3 albums selected" in w.d_title.text()
    item = w.cands.item(0)
    chosen = w.current.candidates[item.data(0x0100)]
    w._cand_clicked(item)
    rows = {r.folder.rel: r for r in w.model.rows}
    for rel in rels:
        assert rows[rel].approved and rows[rel].status == Status.PROPOSED
        assert w._ckey(rows[rel].choice) == w._ckey(chosen)
    w.skip_current()
    assert all(rows[rel].status == Status.SKIPPED and not rows[rel].approved for rel in rels)
    w.close()


def test_search_again_shares_results_with_selected_rows(app, library, tmp_path, monkeypatch):
    w = _window(app, library, tmp_path, monkeypatch)
    rels = ["Various Artists/Now 1", "Named/Wrong Name"]
    _select(w, rels)
    w.e_artist.setText("Radiohead")
    w.e_album.setText("OK Computer")
    w.research()
    assert _wait(app, lambda: not w._searches)
    rows = {r.folder.rel: r for r in w.model.rows}
    for rel in rels:
        r = rows[rel]
        assert (r.info.artist, r.info.album) == ("Radiohead", "OK Computer")
        assert any(c.source == "Deezer" for c in r.candidates)
    # the other album keeps its own local image as an option too
    assert any(c.source.startswith("Folder:") for c in rows["Named/Wrong Name"].candidates)
    assert rows["Named/Wrong Name"].info.track_count == 3
    w.close()
