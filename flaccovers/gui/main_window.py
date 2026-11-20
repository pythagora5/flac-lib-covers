"""Main window: scan → automatic lookup → review → apply."""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QSplitter, QTableView, QVBoxLayout, QWidget)

from .. import images
from ..applier import Applier, last_run, undo_run
from ..cache import Cache
from ..config import APP_NAME, APP_VERSION, Settings, app_dir, backups_dir
from ..lookup import Finder, make_thumb
from ..metadata import album_info
from ..models import AlbumInfo, AlbumResult, Candidate, Issue, Status
from . import workers
from .model import (C_ALBUM, C_APPLY, C_ARTIST, C_CUR, C_NEW, C_PROBLEM, C_PROPOSAL, C_STATUS,
                    FILTERS, ICON, AlbumModel, FilterProxy, pixmap)
from .settings_dialog import SettingsDialog

class MainWindow(QMainWindow):
    def __init__(self, settings: Optional[Settings] = None, cache: Optional[Cache] = None):
        super().__init__()
        self.s = settings or Settings.load()
        self.cache = cache or Cache()
        self.job: Optional[workers.Job] = None
        self.finder: Optional[Finder] = None
        self.current: Optional[AlbumResult] = None
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 860)
        self._build_menu()
        self._build_ui()
        self._set_busy(False)

    # ---- UI construction --------------------------------------------------
    def _build_menu(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        a = QAction("Choose Library Folder…", self, shortcut=QKeySequence.Open)
        a.triggered.connect(self.choose_library)
        m.addAction(a)
        a = QAction("Scan", self, shortcut=QKeySequence("Ctrl+R"))
        a.triggered.connect(self.scan)
        m.addAction(a)
        a = QAction("Settings…", self, shortcut=QKeySequence.Preferences)
        a.setMenuRole(QAction.PreferencesRole)
        a.triggered.connect(self.open_settings)
        m.addAction(a)

        m = mb.addMenu("&Tools")
        a = QAction("Undo Last Apply…", self)
        a.triggered.connect(self.undo_last)
        m.addAction(a)
        a = QAction("Show Backups in Finder", self)
        a.triggered.connect(lambda: self._reveal(str(backups_dir())))
        m.addAction(a)
        a = QAction("Show Change Log in Finder", self)
        a.triggered.connect(lambda: self._reveal(str(app_dir("logs"))))
        m.addAction(a)
        m.addSeparator()
        a = QAction("Clear Caches", self)
        a.triggered.connect(self.clear_caches)
        m.addAction(a)

        m = mb.addMenu("&Help")
        a = QAction(f"About {APP_NAME}", self)
        a.setMenuRole(QAction.AboutRole)
        a.triggered.connect(lambda: QMessageBox.about(
            self, APP_NAME,
            f"<b>{APP_NAME}</b> {APP_VERSION}<br>Creates Eversolo-compatible cover.jpg files "
            "for FLAC albums.<br><br>Artwork sources: MusicBrainz / Cover Art Archive, Deezer, "
            "Apple Music, Discogs."))
        m.addAction(a)

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)

        # Top bar
        top = QHBoxLayout()
        top.addWidget(QLabel("Library:"))
        self.path_edit = QLineEdit(self.s.library_path)
        top.addWidget(self.path_edit, 1)
        b = QPushButton("Choose…")
        b.clicked.connect(self.choose_library)
        top.addWidget(b)
        self.scan_btn = QPushButton("Scan Library")
        self.scan_btn.setDefault(True)
        self.scan_btn.clicked.connect(self.scan)
        top.addWidget(self.scan_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop)
        top.addWidget(self.stop_btn)
        b = QPushButton("Settings")
        b.clicked.connect(self.open_settings)
        top.addWidget(b)
        outer.addLayout(top)

        status = QHBoxLayout()
        self.summary = QLabel("Choose your library folder and click Scan Library.")
        status.addWidget(self.summary, 1)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(320)
        self.progress.setTextVisible(True)
        status.addWidget(self.progress)
        outer.addLayout(status)

        # Filter row
        fl = QHBoxLayout()
        fl.addWidget(QLabel("Show:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(FILTERS)
        fl.addWidget(self.filter_combo)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by folder name…")
        self.search.setClearButtonEnabled(True)
        fl.addWidget(self.search, 1)
        outer.addLayout(fl)

        # Table + detail
        split = QSplitter(Qt.Horizontal)
        self.model = AlbumModel()
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)
        self.filter_combo.currentIndexChanged.connect(self.proxy.set_mode)
        self.search.textChanged.connect(self.proxy.set_text)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setIconSize(QSize(ICON, ICON))
        self.table.verticalHeader().setDefaultSectionSize(ICON + 8)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        for col, w in ((C_APPLY, 50), (C_CUR, ICON + 16), (C_NEW, ICON + 16), (C_ARTIST, 160),
                       (C_PROBLEM, 170), (C_PROPOSAL, 200), (C_STATUS, 120)):
            self.table.setColumnWidth(col, w)
        h.setSectionResizeMode(C_ALBUM, QHeaderView.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self._row_changed)
        split.addWidget(self.table)
        split.addWidget(self._build_detail())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([980, 420])
        outer.addWidget(split, 1)

        # Bottom bar
        bottom = QHBoxLayout()
        b = QPushButton("Tick All Proposed")
        b.clicked.connect(lambda: self._bulk_approve(True))
        bottom.addWidget(b)
        b = QPushButton("Untick All")
        b.clicked.connect(lambda: self._bulk_approve(False))
        bottom.addWidget(b)
        bottom.addStretch(1)
        self.apply_btn = QPushButton("Apply Ticked")
        self.apply_btn.clicked.connect(self.apply)
        bottom.addWidget(self.apply_btn)
        outer.addLayout(bottom)

        self.setCentralWidget(root)
        self.model.dataChanged.connect(lambda *_: self._update_counts())
        self.model.rowsInserted.connect(lambda *_: self._update_counts())
        self.model.modelReset.connect(self._update_counts)

    def _build_detail(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.d_title = QLabel("Select an album")
        self.d_title.setWordWrap(True)
        self.d_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.d_title)

        pics = QHBoxLayout()
        self.d_cur, self.d_new = QLabel(), QLabel()
        for lbl, cap in ((self.d_cur, "Current"), (self.d_new, "Selected")):
            col = QVBoxLayout()
            c = QLabel(f"<b>{cap}</b>")
            c.setAlignment(Qt.AlignCenter)
            col.addWidget(c)
            lbl.setFixedSize(190, 190)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("border: 1px solid palette(mid);")
            col.addWidget(lbl)
            pics.addLayout(col)
        v.addLayout(pics)
        self.d_info = QLabel()
        self.d_info.setWordWrap(True)
        v.addWidget(self.d_info)

        v.addWidget(QLabel("<b>Candidates</b> (click one to use it)"))
        self.cands = QListWidget()
        self.cands.setViewMode(QListWidget.IconMode)
        self.cands.setIconSize(QSize(110, 110))
        self.cands.setResizeMode(QListWidget.Adjust)
        self.cands.setMovement(QListWidget.Static)
        self.cands.setWordWrap(True)
        self.cands.setGridSize(QSize(130, 160))
        self.cands.itemClicked.connect(self._cand_clicked)
        v.addWidget(self.cands, 1)

        form = QFormLayout()
        self.e_artist, self.e_album = QLineEdit(), QLineEdit()
        form.addRow("Artist:", self.e_artist)
        form.addRow("Album:", self.e_album)
        v.addLayout(form)
        row = QHBoxLayout()
        self.research_btn = QPushButton("Search Again (all sources)")
        self.research_btn.clicked.connect(self.research)
        row.addWidget(self.research_btn)
        b = QPushButton("Use Image File…")
        b.clicked.connect(self.choose_file)
        row.addWidget(b)
        v.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("Show in Finder")
        b.clicked.connect(lambda: self.current and self._reveal(self.current.folder.path))
        row.addWidget(b)
        self.skip_btn = QPushButton("Don't Change This Album")
        self.skip_btn.clicked.connect(self.skip_current)
        row.addWidget(self.skip_btn)
        v.addLayout(row)
        w.setMinimumWidth(380)
        return w

    # ---- helpers --------------------------------------------------------------
    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.scan_btn.setEnabled(not busy)
        self.apply_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)
        self.research_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
        if not busy:
            self.progress.setFormat("")
        elif text:
            self.progress.setFormat(text)

    def _reveal(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _update_counts(self) -> None:
        n = len(self.model.approved())
        self.apply_btn.setText(f"Apply Ticked ({n})")

    def _on_progress(self, done: int, total: int, text: str) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.progress.setFormat(f"{done}/{total}")
        else:
            self.progress.setRange(0, 0)  # busy indicator
        if text:
            self.statusBar().showMessage(text, 3000)

    def _make_finder(self) -> Finder:
        if self.finder:
            self.finder.close()
        self.finder = Finder(self.s, self.cache)
        return self.finder

    # ---- actions --------------------------------------------------------------
    def choose_library(self) -> None:
        start = self.path_edit.text() or "/Volumes"
        d = QFileDialog.getExistingDirectory(self, "Choose music library folder", start)
        if d:
            self.path_edit.setText(d)

    def open_settings(self) -> None:
        SettingsDialog(self.s, self).exec()

    def stop(self) -> None:
        if self.job:
            self.job.cancel.set()
            self.summary.setText("Stopping…")

    def scan(self) -> None:
        root = self.path_edit.text().strip()
        if not os.path.isdir(root):
            QMessageBox.warning(self, APP_NAME, f"Folder not found:\n{root}\n\n"
                                "Is the drive connected?")
            return
        self.s.library_path = root
        self.s.save()
        self.model.clear()
        self._show(None)
        self.summary.setText("Scanning…")
        self._set_busy(True, "Scanning…")
        self.progress.setRange(0, 0)
        job = workers.Job(workers.scan_job, root, self.s, self.cache)
        job.signals.progress.connect(lambda n, _t, p: (
            self.summary.setText(f"Scanning… {n} albums"), self.statusBar().showMessage(p, 2000)))
        job.signals.finished.connect(self._scan_done)
        job.signals.failed.connect(self._failed)
        self.job = workers.start(job)

    def _scan_done(self, payload) -> None:
        albums, secs = payload
        problems = [a for a in albums if a.issue != Issue.OK]
        by_issue: dict[str, int] = {}
        for a in problems:
            by_issue[a.issue.value] = by_issue.get(a.issue.value, 0) + 1
        detail = ", ".join(f"{n} {k.lower()}" for k, n in sorted(by_issue.items(),
                                                                   key=lambda kv: -kv[1]))
        self.summary.setText(
            f"{len(albums)} albums scanned in {secs:.1f}s · {len(albums) - len(problems)} OK · "
            f"{len(problems)} need attention" + (f" ({detail})" if detail else ""))
        if self.job and self.job.cancel.is_set():
            self._set_busy(False)
            return
        if not problems:
            self._set_busy(False)
            QMessageBox.information(self, APP_NAME, "All albums already have suitable artwork.")
            return
        for a in problems:  # show rows straight away; they fill in as lookups finish
            self.model.upsert(AlbumResult(folder=a, info=album_info(a)))
        self._set_busy(True, "Finding artwork…")
        self.progress.setRange(0, len(problems))
        self.progress.setValue(0)
        job = workers.Job(workers.lookup_job, problems, self._make_finder(),
                          self.s.lookup_threads)
        job.signals.item.connect(self._result_ready)
        job.signals.progress.connect(self._on_progress)
        job.signals.finished.connect(self._lookup_done)
        job.signals.failed.connect(self._failed)
        self.job = workers.start(job)

    def _result_ready(self, res: AlbumResult) -> None:
        self.model.upsert(res)
        if self.current and self.current.folder.path == res.folder.path:
            self._show(res)

    def _lookup_done(self, _n) -> None:
        self._set_busy(False)
        rows = self.model.rows
        ready = sum(1 for r in rows if r.approved)
        review = sum(1 for r in rows if r.status == Status.NEEDS_REVIEW)
        missing = sum(1 for r in rows if r.status in (Status.NOT_FOUND, Status.FAILED))
        self.statusBar().showMessage(
            f"Lookup finished: {ready} ready to apply, {review} need review, "
            f"{missing} not found.")
        if self.table.currentIndex().row() < 0 and self.proxy.rowCount():
            self.table.selectRow(0)

    def _failed(self, msg: str) -> None:
        self._set_busy(False)
        QMessageBox.critical(self, APP_NAME, msg)

    def _bulk_approve(self, on: bool) -> None:
        for r in self.model.rows:
            if r.choice is not None and r.status != Status.APPLIED:
                r.approved = on
        self.model.layoutChanged.emit()
        self._update_counts()
        self._show(self.current)

    def apply(self) -> None:
        todo = self.model.approved()
        if not todo:
            QMessageBox.information(self, APP_NAME, "Nothing is ticked.")
            return
        ok = QMessageBox.question(
            self, APP_NAME,
            f"Write cover.jpg into {len(todo)} album folder(s)?\n\n"
            "Existing cover/folder/front images are moved to a backup folder first, and "
            "Tools ▸ Undo Last Apply can put them back.")
        if ok != QMessageBox.Yes:
            return
        self._set_busy(True, "Writing artwork…")
        applier = Applier(self.s, self.finder.http if self.finder else None)
        job = workers.Job(workers.apply_job, todo, applier, self.cache)
        job.signals.item.connect(self._result_ready)
        job.signals.progress.connect(self._on_progress)
        job.signals.finished.connect(lambda n: (
            self._set_busy(False),
            QMessageBox.information(
                self, APP_NAME,
                f"Wrote {n} of {len(todo)} cover.jpg files.\n\nOn the Eversolo, rescan the "
                "library and turn on 'Priority local image' if covers still show online art.")))
        job.signals.failed.connect(self._failed)
        self.job = workers.start(job)

    def undo_last(self) -> None:
        run = last_run()
        if not run:
            QMessageBox.information(self, APP_NAME, "There is nothing to undo.")
            return
        if QMessageBox.question(self, APP_NAME, f"Undo the changes made in run {run.name}?"
                                ) != QMessageBox.Yes:
            return
        n = undo_run(run)
        for r in self.model.rows:
            if r.status == Status.APPLIED:
                self.cache.forget_scan(r.folder.path)
        QMessageBox.information(self, APP_NAME, f"Restored {n} album folder(s). Rescan to "
                                "refresh the list.")

    def clear_caches(self) -> None:
        self.cache.clear()
        self.statusBar().showMessage("Caches cleared", 3000)

    # ---- detail panel ---------------------------------------------------------
    def _row_changed(self, cur, _prev) -> None:
        if not cur.isValid():
            self._show(None)
            return
        self._show(self.model.result(self.proxy.mapToSource(cur).row()))

    def _show(self, res: Optional[AlbumResult]) -> None:
        self.current = res
        self.cands.clear()
        if res is None:
            self.d_title.setText("Select an album")
            self.d_cur.clear()
            self.d_new.clear()
            self.d_info.clear()
            self.e_artist.clear()
            self.e_album.clear()
            return
        f = res.folder
        self.d_title.setText(f"<b>{res.info.artist}</b> — {res.info.album}"
                             f"<br><small>{f.path}</small>")
        cur = pixmap(res.current_thumb, 190)
        if cur:
            self.d_cur.setPixmap(cur)
        else:
            self.d_cur.setText("No artwork")
        ch = res.choice
        new = pixmap(ch.thumb, 190) if ch else None
        if new:
            self.d_new.setPixmap(new)
        else:
            self.d_new.setText("Nothing selected")
        lines = [f"<b>Problem:</b> {f.issue.value}" + (f" ({f.detail})" if f.detail else ""),
                 f"<b>Status:</b> {res.status.value}" + (f" – {res.message}" if res.message else ""),
                 f"<b>Tracks:</b> {res.info.track_count}" + (f" · <b>Year:</b> {res.info.year}"
                                                            if res.info.year else "")]
        if ch:
            lines.append(f"<b>Selected:</b> {ch.source} – {ch.artist} – {ch.album} "
                         f"({ch.score:.0%} match)" if ch.album else f"<b>Selected:</b> {ch.source}")
        self.d_info.setText("<br>".join(lines))
        self.e_artist.setText(res.info.artist)
        self.e_album.setText(res.info.album)
        for i, c in enumerate(res.candidates):
            pm = pixmap(c.thumb, 110)
            size = f"{max(c.width, c.height)}px · " if c.width else ""
            text = f"{c.source}\n{size}{c.score:.0%}"
            item = QListWidgetItem(QIcon(pm) if pm else QIcon(), text)
            item.setData(Qt.UserRole, i)
            item.setToolTip(f"{c.artist} – {c.album} {c.year}\n{c.note}".strip())
            if i == res.chosen:
                item.setSelected(True)
            self.cands.addItem(item)

    def _cand_clicked(self, item: QListWidgetItem) -> None:
        res = self.current
        if not res or res.status == Status.APPLIED:
            return
        res.chosen = item.data(Qt.UserRole)
        res.approved = True
        if res.status in (Status.NEEDS_REVIEW, Status.SKIPPED):
            res.status = Status.PROPOSED
        self.model.upsert(res)
        self._show(res)

    def skip_current(self) -> None:
        res = self.current
        if res and res.status != Status.APPLIED:
            res.approved = False
            res.status = Status.SKIPPED
            self.model.upsert(res)
            self._show(res)

    def choose_file(self) -> None:
        res = self.current
        if not res:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose cover image", res.folder.path,
                                              "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)")
        if not path:
            return
        info = images.inspect(path)
        if not info.readable:
            QMessageBox.warning(self, APP_NAME, "That file isn't a readable image.")
            return
        with open(path, "rb") as fh:
            thumb = make_thumb(fh.read())
        c = Candidate(source="Chosen file", local_path=path, width=info.width,
                      height=info.height, score=1.0, thumb=thumb, note=path)
        res.candidates.insert(0, c)
        res.chosen = 0
        res.approved = True
        res.status = Status.PROPOSED
        self.model.upsert(res)
        self._show(res)

    def research(self) -> None:
        res = self.current
        if not res:
            return
        info = AlbumInfo(**{**res.info.__dict__,
                            "artist": self.e_artist.text().strip(),
                            "album": self.e_album.text().strip(),
                            "mb_release_id": "", "mb_releasegroup_id": ""})
        if (info.artist, info.album) == (res.info.artist, res.info.album):
            info.mb_release_id = res.info.mb_release_id
            info.mb_releasegroup_id = res.info.mb_releasegroup_id
        self._set_busy(True, "Searching…")
        self.progress.setRange(0, 0)
        finder = self.finder or self._make_finder()
        job = workers.Job(workers.research_job, res, info, finder)
        job.signals.finished.connect(lambda new: (self._result_ready(new), self._set_busy(False)))
        job.signals.failed.connect(self._failed)
        self.job = workers.start(job)

    def closeEvent(self, ev) -> None:
        if self.job:
            self.job.cancel.set()
        if self.finder:
            self.finder.close()
        super().closeEvent(ev)
