"""Absolute-import entry point used by desktop bundlers."""

from appfit.gui import main


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "--check-bundle-runtime":
        import json
        from pathlib import Path

        from PySide6.QtCore import qVersion
        from PySide6.QtWidgets import QApplication

        from appfit._bundle_check import check

        report = check()
        application = QApplication([])
        application.processEvents()
        report["qt"] = qVersion()
        Path(sys.argv[2]).write_text(json.dumps(report, indent=2) + "\n")
    else:
        main()
