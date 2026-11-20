"""Entry point: ``python -m flaccovers``."""

import sys


def raise_open_file_limit(target: int = 4096) -> None:
    """macOS gives apps only 256 open files by default; ask for more."""
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        want = target if hard == resource.RLIM_INFINITY else min(target, hard)
        if soft < want:
            resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
    except (ImportError, ValueError, OSError):
        pass


def main() -> int:
    raise_open_file_limit()
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
