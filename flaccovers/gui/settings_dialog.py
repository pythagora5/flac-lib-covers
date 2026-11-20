from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QLabel, QLineEdit, QSpinBox, QVBoxLayout)

from ..config import Settings, get_discogs_token, set_discogs_token


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.s = settings
        lay = QVBoxLayout(self)

        # --- Output
        g = QGroupBox("Eversolo cover.jpg")
        f = QFormLayout(g)
        self.target = QComboBox()
        self.target.addItems(["500", "800", "1000"])
        self.target.setCurrentText(str(settings.target_size))
        self.target.setToolTip("Eversolo recommends 500×500 or 800×800")
        f.addRow("Output size (px):", self.target)
        self.quality = QSpinBox(minimum=60, maximum=100, value=settings.jpeg_quality)
        f.addRow("JPEG quality:", self.quality)
        self.max_out = QSpinBox(minimum=100, maximum=5000, value=settings.max_output_kb,
                                suffix=" KB")
        f.addRow("Max file size:", self.max_out)
        lay.addWidget(g)

        # --- Checks
        g = QGroupBox("When is existing artwork OK?")
        f = QFormLayout(g)
        self.min_size = QSpinBox(minimum=100, maximum=3000, value=settings.min_size, suffix=" px")
        f.addRow("Smallest acceptable side:", self.min_size)
        self.max_size = QSpinBox(minimum=500, maximum=10000, value=settings.max_size, suffix=" px")
        f.addRow("Largest acceptable side:", self.max_size)
        self.max_file = QSpinBox(minimum=100, maximum=50000, value=settings.max_file_kb,
                                 suffix=" KB")
        f.addRow("Largest acceptable file:", self.max_file)
        self.prog = QCheckBox("Treat progressive JPEGs as a problem")
        self.prog.setChecked(settings.flag_progressive_jpeg)
        f.addRow(self.prog)
        self.png = QCheckBox("Treat PNG covers as a problem (convert to JPEG)")
        self.png.setChecked(settings.flag_png_cover)
        f.addRow(self.png)
        lay.addWidget(g)

        # --- Sources
        g = QGroupBox("Internet sources")
        f = QFormLayout(g)
        self.mb = QCheckBox("MusicBrainz / Cover Art Archive")
        self.mb.setChecked(settings.use_musicbrainz)
        self.dz = QCheckBox("Deezer")
        self.dz.setChecked(settings.use_deezer)
        self.it = QCheckBox("Apple Music (iTunes Search)")
        self.it.setChecked(settings.use_itunes)
        self.dc = QCheckBox("Discogs")
        self.dc.setChecked(settings.use_discogs)
        for w in (self.mb, self.dz, self.it, self.dc):
            f.addRow(w)
        self.token = QLineEdit(get_discogs_token())
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("Discogs personal access token")
        f.addRow("Discogs token:", self.token)
        f.addRow(QLabel("<small>Stored in your macOS Keychain.</small>"))
        self.country = QLineEdit(settings.itunes_country)
        self.country.setMaxLength(2)
        f.addRow("Apple Music store country:", self.country)
        self.contact = QLineEdit(settings.contact)
        self.contact.setPlaceholderText("optional – e-mail or URL")
        self.contact.setToolTip("MusicBrainz asks API users to identify themselves; optional")
        f.addRow("Contact for MusicBrainz:", self.contact)
        lay.addWidget(g)

        # --- Performance
        g = QGroupBox("Performance and matching")
        f = QFormLayout(g)
        self.scan_threads = QSpinBox(minimum=1, maximum=32, value=settings.scan_threads)
        self.scan_threads.setToolTip("2–4 for USB hard drives, 8+ for SSDs")
        f.addRow("Scan threads:", self.scan_threads)
        self.lookup_threads = QSpinBox(minimum=1, maximum=32, value=settings.lookup_threads)
        f.addRow("Lookup threads:", self.lookup_threads)
        self.fast = QCheckBox("Stop searching once a strong match is found (faster)")
        self.fast.setChecked(settings.fast_path)
        f.addRow(self.fast)
        self.auto = QDoubleSpinBox(minimum=0.5, maximum=1.0, singleStep=0.01, decimals=2,
                                   value=settings.auto_approve_score)
        f.addRow("Pre-tick matches scoring at least:", self.auto)
        self.appledouble = QCheckBox("Remove macOS ._ files next to cover.jpg")
        self.appledouble.setChecked(settings.remove_appledouble)
        f.addRow(self.appledouble)
        lay.addWidget(g)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def accept(self) -> None:
        s = self.s
        s.target_size = int(self.target.currentText())
        s.jpeg_quality = self.quality.value()
        s.max_output_kb = self.max_out.value()
        s.min_size = self.min_size.value()
        s.max_size = self.max_size.value()
        s.max_file_kb = self.max_file.value()
        s.flag_progressive_jpeg = self.prog.isChecked()
        s.flag_png_cover = self.png.isChecked()
        s.use_musicbrainz = self.mb.isChecked()
        s.use_deezer = self.dz.isChecked()
        s.use_itunes = self.it.isChecked()
        s.use_discogs = self.dc.isChecked()
        s.itunes_country = (self.country.text().strip() or "US").upper()
        s.contact = self.contact.text().strip()
        s.scan_threads = self.scan_threads.value()
        s.lookup_threads = self.lookup_threads.value()
        s.fast_path = self.fast.isChecked()
        s.auto_approve_score = self.auto.value()
        s.remove_appledouble = self.appledouble.isChecked()
        s.save()
        set_discogs_token(self.token.text().strip())
        super().accept()
