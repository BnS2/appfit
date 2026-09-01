"""Desktop entry point for appfit's compatible-build finder."""

from __future__ import annotations


def main() -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise SystemExit(
            "The GUI needs PySide6 and USB support. Install with:\n"
            "  pip install 'appfit[gui]'"
        ) from exc

    from .window import AppfitWindow

    application = QApplication.instance() or QApplication([])
    application.setApplicationName("appfit")
    application.setOrganizationName("appfit")
    window = AppfitWindow()
    window.show()
    raise SystemExit(application.exec())


__all__ = ["main"]
