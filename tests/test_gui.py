from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from appfit.apps import App
from appfit.devices import Device, Target
from appfit.gui.artwork import ArtworkLoader
from appfit.gui.window import (
    REGULAR_CONTROL_HEIGHT,
    AppfitWindow,
    SearchResultRow,
    SpaciousComboBox,
)
from appfit.store import Account
from appfit.workflows import BuildCandidate, ResolutionReport


APP = App(1, "com.example.app", "Example", "4.0", "18.0", "Example Co")
DEVICE = Device("udid-1", "Old iPad", "iPad6,11", "16.7.16")
CANDIDATE = BuildCandidate(
    history_index=12,
    external_version_id="123",
    display_version="2.0",
    release_date="2021-01-01",
    minimum_os="16.0",
    device_families=(1, 2),
    compatible=True,
    source="metadata",
    recommended=True,
)


class FakeStatus:
    path = None
    version = ""
    compatibility_metadata = None


class FakeWorkflow:
    def active_account(self):
        return Account("owner@example.com")

    def connected_devices(self):
        return [DEVICE]


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def make_window(application, monkeypatch):
    monkeypatch.setattr("appfit.gui.window.toolchain.status", lambda: FakeStatus())
    window = AppfitWindow(FakeWorkflow(), auto_refresh=False)
    window._environment_loaded(
        (FakeStatus(), Account("owner@example.com"), [DEVICE], "")
    )
    return window


def test_window_offers_detected_and_manual_targets(application, monkeypatch):
    window = make_window(application, monkeypatch)

    assert window.device_combo.count() == 1
    assert "Old iPad" in window.device_combo.currentText()
    target, device = window._selected_target()
    assert target == DEVICE.target()
    assert device == DEVICE

    window.target_mode.setCurrentIndex(1)
    window.manual_ios.setCurrentText("15.8.3")
    target, device = window._selected_target()
    assert target == Target.from_ios("15.8.3", "ipad")
    assert device is None
    window.close()


def test_search_result_and_recommendation_render(application, monkeypatch):
    window = make_window(application, monkeypatch)
    window._search_loaded([APP])

    assert window.current_app == APP
    assert "Current 4.0" in window.selected_app_label.text()
    assert window.claim_button.isEnabled()
    result_item = window.search_results.item(0)
    assert result_item.text().startswith("Example, by Example Co")
    assert "Example Co" in result_item.data(Qt.ItemDataRole.AccessibleTextRole)
    assert isinstance(window.search_results.itemWidget(result_item), SearchResultRow)
    assert window.search_results.height() == 72

    report = ResolutionReport(
        app=APP,
        target=DEVICE.target(),
        version_ids=tuple(str(number) for number in range(111, 124)),
        recommended=CANDIDATE,
        probes=5,
        from_cache=False,
        source="metadata",
        licence_claimed=True,
    )
    window._resolution_loaded(report)

    assert window.result_card.isVisibleTo(window.centralWidget())
    assert window.recommendation_title.text() == "✓ 2.0"
    assert "newest compatible historical version" in window.recommendation_detail.text()
    assert window.version_combo.currentData(Qt.ItemDataRole.UserRole) == CANDIDATE
    assert f"build {CANDIDATE.external_version_id}" in window.version_combo.currentText()
    assert window.activity_summary.text() == "Recommended Example 2.0"
    window.close()


def test_status_strip_and_contextual_primary_action(application, monkeypatch):
    window = make_window(application, monkeypatch)

    assert window.helper_status.text() == "App Store access unavailable"
    assert window.account_status.text() == "owner@example.com"
    assert window.device_status.text() == "Old iPad connected"

    window._search_loaded([APP])
    assert window.find_button.isDefault()
    window._resolution_loaded(
        ResolutionReport(
            app=APP,
            target=DEVICE.target(),
            version_ids=(CANDIDATE.external_version_id,),
            recommended=CANDIDATE,
            probes=1,
            from_cache=False,
            source="metadata",
            licence_claimed=True,
        )
    )
    assert window.install_button.objectName() == "primaryButton"
    assert window.install_button.isDefault()
    assert "Old iPad" in window.install_button.text()
    assert window.download_button.objectName() == "secondaryButton"

    window.target_mode.setCurrentIndex(1)
    window._resolution_loaded(
        ResolutionReport(
            app=APP,
            target=Target.from_ios("16.7.16", "ipad"),
            version_ids=(CANDIDATE.external_version_id,),
            recommended=CANDIDATE,
            probes=1,
            from_cache=False,
            source="metadata",
            licence_claimed=True,
        )
    )
    assert window.install_button.isHidden()
    assert window.download_button.objectName() == "primaryButton"
    assert window.download_button.isDefault()
    window.close()


def test_activity_details_and_empty_artwork_fallback(application, monkeypatch):
    window = make_window(application, monkeypatch)
    assert window.activity.isHidden()

    summary = "A deliberately long activity message with a useful recovery step"
    window.activity_summary.resize(90, window.activity_summary.height())
    window.activity_summary.setText(summary)
    assert window.activity_summary.full_text == summary
    assert window.activity_summary.toolTip() == summary
    assert window.activity_summary.accessibleName() == summary
    assert window.activity_summary.text() != summary

    collapsed_size = window.activity_toggle.size()
    collapsed_icon = window.activity_toggle.icon().cacheKey()
    window.activity_toggle.setChecked(True)
    assert not window.activity.isHidden()
    assert window.activity_action.isChecked()
    assert window.activity_toggle.text() == "Hide details"
    assert window.activity_toggle.size() == collapsed_size
    assert window.activity_toggle.iconSize() == QSize(16, 12)
    assert window.activity_toggle.icon().cacheKey() != collapsed_icon

    window.activity_toggle.setChecked(False)
    assert window.activity.isHidden()
    assert not window.activity_action.isChecked()
    assert window.activity_toggle.text() == "Show details"
    assert window.activity_toggle.size() == collapsed_size

    received = []
    loader = ArtworkLoader(window)
    loader.load("", received.append)
    assert received == [None]

    cached = QPixmap(2, 2)
    cached.fill(QColor("blue"))
    loader._memory["https://example.invalid/icon.png"] = cached
    loader.load("https://example.invalid/icon.png", received.append)
    assert received[-1].size().width() == 2
    window.close()


def test_primary_controls_share_roomier_metrics(application, monkeypatch):
    window = make_window(application, monkeypatch)

    controls = (
        window.refresh_button,
        window.target_mode,
        window.device_combo,
        window.manual_ios,
        window.platform_combo,
        window.search_input,
        window.search_button,
        window.find_button,
        window.version_combo,
        window.load_older_button,
        window.install_button,
        window.download_button,
        window.claim_button,
        window.activity_toggle,
    )
    assert all(control.minimumHeight() >= REGULAR_CONTROL_HEIGHT for control in controls)
    assert window.search_input.textMargins().left() == 8
    assert window.search_input.textMargins().right() == 8
    assert all(
        isinstance(control, SpaciousComboBox)
        for control in (
            window.target_mode,
            window.device_combo,
            window.manual_ios,
            window.platform_combo,
            window.version_combo,
        )
    )
    window.manual_ios.resize(240, REGULAR_CONTROL_HEIGHT)
    assert window.manual_ios.lineEdit().geometry().right() <= 210
    assert window.manual_ios.lineEdit().textMargins().left() == 0

    window.show()
    application.processEvents()
    QTest.mouseClick(window.target_mode, Qt.MouseButton.LeftButton)
    application.processEvents()
    assert window.target_mode.view().isVisible()
    window.target_mode.hidePopup()
    window.close()


def test_new_search_clears_stale_selection_and_actions(application, monkeypatch):
    window = make_window(application, monkeypatch)
    window._search_loaded([APP])

    window.search_input.setText("another app")
    monkeypatch.setattr(window, "_start_task", lambda *args, **kwargs: None)
    window.search()

    assert window.current_app is None
    assert window.selected_app_label.text() == "No app selected"
    assert not window.find_button.isEnabled()
    assert not window.claim_button.isEnabled()
    window.close()


def test_busy_state_blocks_overlapping_keyboard_and_menu_actions(
    application, monkeypatch
):
    window = make_window(application, monkeypatch)
    window._search_loaded([APP])

    window._busy = 1
    window._update_enabled_state()

    assert not window.search_input.isEnabled()
    assert not window.search_results.isEnabled()
    assert not window.focus_search_action.isEnabled()
    assert not window.refresh_action.isEnabled()
    assert not window.sign_in_action.isEnabled()
    assert not window.target_mode.isEnabled()
    assert not window.version_combo.isEnabled()

    window._busy = 0
    window._update_enabled_state()
    assert window.search_input.isEnabled()
    assert window.refresh_action.isEnabled()
    window.close()


def test_invalid_manual_target_updates_readiness_status(application, monkeypatch):
    window = make_window(application, monkeypatch)
    window.target_mode.setCurrentIndex(1)
    window.manual_ios.setCurrentText("sixteen")

    assert window.device_status.text() == "Invalid manual target"
    assert "16.7.16" in window.target_detail.text()
    window.close()


def test_tab_order_includes_the_visible_target_branch(application, monkeypatch):
    window = make_window(application, monkeypatch)
    window.show()
    application.processEvents()

    window.target_mode.setCurrentIndex(0)
    window.target_mode.setFocus()
    assert window.focusNextChild()
    assert application.focusWidget() is window.device_combo

    window.target_mode.setCurrentIndex(1)
    window.target_mode.setFocus()
    assert window.focusNextChild()
    assert application.focusWidget() in (window.manual_ios, window.manual_ios.lineEdit())
    assert window.focusNextChild()
    assert application.focusWidget() is window.platform_combo
    assert window.focusNextChild()
    assert application.focusWidget() is window.search_input

    window._search_loaded([APP])
    window.activity_toggle.setFocus()
    assert window.focusNextChild()
    assert application.focusWidget() is window.refresh_button
    window.close()


def test_incompatible_older_build_is_displayed_but_disabled(
    application, monkeypatch
):
    window = make_window(application, monkeypatch)
    incompatible = BuildCandidate(
        history_index=11,
        external_version_id="122",
        display_version="1.9",
        release_date="2020-12-01",
        minimum_os="17.0",
        device_families=(1, 2),
        compatible=False,
        source="metadata",
    )
    window._older_loaded([incompatible])

    item = window.version_combo.model().item(0)
    assert "Incompatible" in window.version_combo.itemText(0)
    assert not item.isEnabled()
    window.close()


def test_pairing_during_install_preserves_resolution(application, monkeypatch):
    window = make_window(application, monkeypatch)
    window._search_loaded([APP])
    report = ResolutionReport(
        app=APP,
        target=DEVICE.target(),
        version_ids=(CANDIDATE.external_version_id,),
        recommended=CANDIDATE,
        probes=1,
        from_cache=False,
        source="metadata",
        licence_claimed=True,
    )
    window._resolution_loaded(report)
    paired = []
    started = []
    monkeypatch.setattr("appfit.gui.window.accounts.account_for_device", lambda _udid: None)
    monkeypatch.setattr(
        "appfit.gui.window.accounts.pair",
        lambda udid, account: paired.append((udid, account)),
    )
    monkeypatch.setattr(
        "appfit.gui.window.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(window, "_confirm_action", lambda _verb: True)
    monkeypatch.setattr(
        window,
        "_start_task",
        lambda task, on_success, **kwargs: started.append((task, on_success, kwargs)),
    )

    window.install_selected()

    assert paired == [(DEVICE.udid, "owner@example.com")]
    assert window.current_report is report
    assert started
    assert "Paired with owner@example.com" in window.target_detail.text()
    window.close()
