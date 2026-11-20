"""Table model for the review list."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QPixmap

from ..models import AlbumResult, Issue, Status

COLS = ["Apply", "Current", "Proposed", "Artist", "Album", "Problem", "Proposal", "Status"]
C_APPLY, C_CUR, C_NEW, C_ARTIST, C_ALBUM, C_PROBLEM, C_PROPOSAL, C_STATUS = range(len(COLS))
ICON = 64


def pixmap(data: Optional[bytes], size: int = ICON) -> Optional[QPixmap]:
    if not data:
        return None
    pm = QPixmap()
    if not pm.loadFromData(data):
        return None
    return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class AlbumModel(QAbstractTableModel):
    # Emitted when the user edits Artist/Album in the table: (result, artist, album)
    infoEdited = Signal(object, str, str)

    def __init__(self):
        super().__init__()
        self.rows: list[AlbumResult] = []
        self._index: dict[str, int] = {}
        self._pix: dict[tuple, QPixmap] = {}

    # ---- data management --------------------------------------------------
    def clear(self) -> None:
        self.beginResetModel()
        self.rows, self._index, self._pix = [], {}, {}
        self.endResetModel()

    def upsert(self, res: AlbumResult) -> None:
        key = res.folder.path
        row = self._index.get(key)
        self._pix = {k: v for k, v in self._pix.items() if k[0] != key}
        if row is None:
            row = len(self.rows)
            self.beginInsertRows(QModelIndex(), row, row)
            self.rows.append(res)
            self._index[key] = row
            self.endInsertRows()
        else:
            self.rows[row] = res
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLS) - 1))

    def result(self, row: int) -> AlbumResult:
        return self.rows[row]

    def approved(self) -> list[AlbumResult]:
        return [r for r in self.rows if is_ready(r)]

    # ---- Qt model API -------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLS[section]
        return None

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        r = self.rows[index.row()]
        if index.column() == C_APPLY and r.choice is not None and not r.locked:
            f |= Qt.ItemIsUserCheckable
        if index.column() in (C_ARTIST, C_ALBUM) and not r.locked:
            f |= Qt.ItemIsEditable
        return f

    def _thumb(self, r: AlbumResult, which: str) -> Optional[QPixmap]:
        key = (r.folder.path, which, r.chosen)
        if key not in self._pix:
            data = r.current_thumb if which == "cur" else (r.choice.thumb if r.choice else None)
            pm = pixmap(data)
            if pm is None:
                return None
            self._pix[key] = pm
        return self._pix[key]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        col = index.column()
        if role == Qt.CheckStateRole and col == C_APPLY:
            if r.choice is None or r.locked:
                return None
            return Qt.Checked if r.approved else Qt.Unchecked
        if role == Qt.DecorationRole:
            if col == C_CUR:
                return self._thumb(r, "cur")
            if col == C_NEW:
                return self._thumb(r, "new")
        if role == Qt.EditRole and col in (C_ARTIST, C_ALBUM):
            return r.info.artist if col == C_ARTIST else r.info.album
        if role == Qt.DisplayRole:
            if col == C_CUR and r.current_thumb is None:
                return "none"
            if col == C_ARTIST:
                return r.info.artist or r.folder.folder_artist
            if col == C_ALBUM:
                return r.info.album or r.folder.folder_album
            if col == C_PROBLEM:
                return r.folder.issue.value
            if col == C_PROPOSAL:
                return r.choice.label() if r.choice else "—"
            if col == C_STATUS:
                return r.status.value + (f": {r.message}" if r.message and
                                          r.status in (Status.FAILED, Status.APPLIED) else "")
        if role == Qt.ToolTipRole:
            if col in (C_ARTIST, C_ALBUM):
                return f"{r.folder.path}\nDouble-click to correct and search again"
            if col == C_PROBLEM:
                return r.folder.detail or r.folder.issue.value
            if col == C_STATUS:
                return r.message or r.status.value
        if role == Qt.ForegroundRole and col == C_STATUS:
            return {
                Status.NEEDS_REVIEW: QColor("#c77700"),
                Status.NOT_FOUND: QColor("#c0392b"),
                Status.FAILED: QColor("#c0392b"),
                Status.APPLIED: QColor("#2e8b57"),
                Status.WRITING: QColor("#2e8b57"),
            }.get(r.status)
        if role == Qt.UserRole:  # sort key
            if col == C_PROPOSAL:
                return r.choice.score if r.choice else -1
            return str(self.data(index, Qt.DisplayRole) or "").lower()
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.EditRole and index.column() in (C_ARTIST, C_ALBUM):
            r = self.rows[index.row()]
            text = str(value).strip()
            artist = text if index.column() == C_ARTIST else r.info.artist
            album = text if index.column() == C_ALBUM else r.info.album
            if not text or (artist, album) == (r.info.artist, r.info.album):
                return False
            self.infoEdited.emit(r, artist, album)
            return True
        if role == Qt.CheckStateRole and index.column() == C_APPLY:
            r = self.rows[index.row()]
            r.approved = Qt.CheckState(value) == Qt.Checked
            if r.approved and r.status == Status.NEEDS_REVIEW:
                r.status = Status.PROPOSED
            self.dataChanged.emit(index, self.index(index.row(), len(COLS) - 1))
            return True
        return False


FILTERS = ["All found problems", "Needs review", "Ready to apply", "Done", "Failed / not found"]


def is_ready(r: AlbumResult) -> bool:
    return r.approved and r.choice is not None and not r.locked and r.status != Status.PENDING


class FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.mode = 0
        self.text = ""
        self.hidden: set[Issue] = set()
        self.setSortRole(Qt.UserRole)

    def _refilter(self, change) -> None:
        # Qt 6.10 replaced invalidateFilter() with begin/endFilterChange().
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
            change()
            self.endFilterChange()
        else:
            change()
            self.invalidateFilter()

    def set_hidden(self, hidden: set[Issue]) -> None:
        self._refilter(lambda: setattr(self, "hidden", set(hidden)))

    def is_hidden(self, r: AlbumResult) -> bool:
        return r.folder.issue in self.hidden and not r.locked

    def visible_results(self) -> list[AlbumResult]:
        src = self.sourceModel()
        return [src.rows[self.mapToSource(self.index(i, 0)).row()]
                for i in range(self.rowCount())]

    def set_mode(self, mode: int) -> None:
        self._refilter(lambda: setattr(self, "mode", mode))

    def set_text(self, text: str) -> None:
        self._refilter(lambda: setattr(self, "text", text.lower().strip()))

    def filterAcceptsRow(self, row, parent) -> bool:
        r: AlbumResult = self.sourceModel().rows[row]
        if self.is_hidden(r):
            return False
        if self.text and self.text not in r.folder.rel.lower():
            return False
        m = self.mode
        if m == 1:
            return r.status == Status.NEEDS_REVIEW or (not r.approved and r.choice is not None
                                                      and not r.locked)
        if m == 2:
            return r.approved and not r.locked
        if m == 3:
            return r.locked
        if m == 4:
            return r.status in (Status.FAILED, Status.NOT_FOUND)
        return True
