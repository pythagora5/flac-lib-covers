"""Entry point: ``python -m flaccovers``."""

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .config import APP_NAME
    from .gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
