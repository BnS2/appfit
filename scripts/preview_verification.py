#!/usr/bin/env python3
"""Preview appfit's Apple verification dialog without contacting Apple."""

from __future__ import annotations

try:
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
except ImportError as exc:
    raise SystemExit(
        "The preview needs PySide6. Install the GUI development dependencies first."
    ) from exc

from appfit.gui.window import VerificationCodeDialog, appfit_style


def main() -> int:
    application = QApplication.instance() or QApplication([])
    application.setApplicationName("appfit verification preview")
    application.setOrganizationName("appfit")
    application.setStyleSheet(appfit_style())

    rejected = False
    while True:
        dialog = VerificationCodeDialog("Claude", rejected=rejected)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return 0

        # Exercise the same one-time read and immediate clearing as the real flow.
        code = dialog.take_code()
        code = ""
        if not rejected:
            rejected = True
            continue
        break

    QMessageBox.information(
        None,
        "Verification preview complete",
        "The second mock code was accepted. In the real flow, appfit now "
        "resumes the interrupted install action.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
