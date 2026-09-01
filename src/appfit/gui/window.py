"""A small macOS-oriented GUI for finding a compatible App Store build."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

from .. import accounts, toolchain
from ..apps import App
from ..devices import Device, Target
from ..store import Account
from ..workflows import (
    BuildCandidate,
    BuildWorkflow,
    PreparedIPA,
    ProgressEvent,
    ResolutionReport,
    WorkflowError,
    launch_login_terminal,
    target_from_manual,
)
from .artwork import ArtworkLoader


Task = Callable[[Callable[[ProgressEvent], None]], Any]

REGULAR_CONTROL_HEIGHT = 30
CONTROL_ROW_SPACING = 10


def _theme_colors() -> dict[str, str]:
    dark = QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    return (
        {
            "card": "#29292c",
            "strip": "#303034",
            "border": "#48484e",
            "text": "#f2f2f7",
            "secondary": "#c2c2c7",
            "good": "#30d158",
            "warning": "#ff9f0a",
            "accent": "#0a84ff",
            "accent_hover": "#1990ff",
            "accent_pressed": "#0070df",
            "control": "#46464b",
            "control_hover": "#515158",
            "control_pressed": "#3b3b40",
            "control_disabled": "#38383d",
            "disabled_text": "#85858d",
        }
        if dark
        else {
            "card": "#ffffff",
            "strip": "#f4f4f6",
            "border": "#d6d6da",
            "text": "#1d1d1f",
            "secondary": "#606067",
            "good": "#248a3d",
            "warning": "#ad5700",
            "accent": "#087ff5",
            "accent_hover": "#1689f7",
            "accent_pressed": "#0670d9",
            "control": "#eeeef1",
            "control_hover": "#e4e4e8",
            "control_pressed": "#d9d9de",
            "control_disabled": "#f2f2f4",
            "disabled_text": "#98989f",
        }
    )


def appfit_style() -> str:
    colors = _theme_colors()
    style = """
QWidget#workspace { background: palette(window); }
QFrame#surfaceCard {
    background: {colors["card"]};
    border: 1px solid {colors["border"]};
    border-radius: 12px;
}
QFrame#statusStrip {
    background: {colors["strip"]};
    border: 1px solid {colors["border"]};
    border-radius: 10px;
}
QFrame#statusChip {
    background: transparent;
    border: none;
}
QLabel#secondaryText { color: {colors["secondary"]}; }
QLabel#sectionTitle { font-weight: 600; }
QLabel#statusGood { color: {colors["good"]}; font-weight: 600; }
QLabel#statusWarning { color: {colors["warning"]}; font-weight: 600; }
QLabel#statusNeutral { color: {colors["secondary"]}; font-weight: 600; }
QLabel#artworkPlaceholder {
    background: {colors["strip"]};
    color: {colors["secondary"]};
    border: 1px solid {colors["border"]};
    border-radius: 10px;
    font-size: 22px;
}
QLineEdit {
    border: 1px solid {colors["border"]};
    border-radius: 7px;
    padding: 4px 10px;
    background: palette(base);
}
QLineEdit:focus { border-color: {colors["accent"]}; }
QPushButton {
    background: {colors["control"]};
    border: 1px solid {colors["border"]};
    border-radius: 7px;
    padding: 5px 12px;
}
QPushButton:hover { background: {colors["control_hover"]}; }
QPushButton:pressed { background: {colors["control_pressed"]}; }
QPushButton:disabled {
    color: {colors["disabled_text"]};
    background: {colors["control_disabled"]};
    border-color: {colors["border"]};
}
QPushButton#primaryButton {
    color: white;
    background: {colors["accent"]};
    border: 1px solid {colors["accent"]};
    border-radius: 7px;
    padding: 6px 14px;
    font-weight: 600;
}
QPushButton#primaryButton:hover { background: {colors["accent_hover"]}; }
QPushButton#primaryButton:pressed { background: {colors["accent_pressed"]}; }
QPushButton#primaryButton:disabled {
    color: palette(mid);
    background: palette(alternate-base);
    border-color: palette(midlight);
}
QPushButton#tertiaryButton {
    border: none;
    color: palette(link);
    background: transparent;
    padding: 6px 8px;
}
QPushButton#tertiaryButton:disabled { color: palette(mid); }
QListWidget#searchResults {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget#searchResults::item {
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 4px;
    margin: 2px 0;
}
QListWidget#searchResults::item:selected {
    background: palette(highlight);
    border-color: palette(highlight);
}
QPlainTextEdit#activityDetails {
    background: {colors["strip"]};
    border: none;
    border-radius: 8px;
    padding: 6px;
}
"""
    for name, value in colors.items():
        style = style.replace('{colors["' + name + '"]}', value)
    return style


def _heading_font(size: int) -> QFont:
    font = QFont()
    font.setPointSize(size)
    font.setWeight(QFont.Weight.DemiBold)
    return font


class ElidedLabel(QLabel):
    """Keep status text readable at narrow widths without losing its full name."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self.full_text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self._refresh_text()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API spelling
        """Preserve the complete value when callers use QLabel's normal API."""

        self.set_full_text(text)

    def _refresh_text(self) -> None:
        available = max(1, self.contentsRect().width())
        QLabel.setText(
            self,
            self.fontMetrics().elidedText(
                self.full_text, Qt.TextElideMode.ElideMiddle, available
            ),
        )

    def resizeEvent(self, event) -> None:
        self._refresh_text()
        super().resizeEvent(event)


class DisclosureButton(QToolButton):
    """A disclosure control whose footprint stays fixed between states."""

    _LABELS = ("Show details", "Hide details")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("disclosureButton")
        self.setCheckable(True)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        # The wider icon box gives both chevrons the same deliberate text gap.
        self.setIconSize(QSize(16, 12))
        self._icons = {
            False: self._chevron_icon(expanded=False),
            True: self._chevron_icon(expanded=True),
        }

        sizes = []
        for expanded in (False, True):
            self.set_expanded(expanded)
            sizes.append(super().sizeHint())
        self.set_expanded(False)
        self.setFixedSize(
            max(size.width() for size in sizes),
            max(REGULAR_CONTROL_HEIGHT, *(size.height() for size in sizes)),
        )

    def set_expanded(self, expanded: bool) -> None:
        self.setIcon(self._icons[expanded])
        self.setText(self._LABELS[expanded])

    def _chevron_icon(self, *, expanded: bool) -> QIcon:
        """Draw optically matched chevrons on equal high-DPI canvases."""

        pixmap = QPixmap(32, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.palette().buttonText().color(), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        if expanded:
            path.moveTo(4, 8)
            path.lineTo(10, 16)
            path.lineTo(16, 8)
        else:
            path.moveTo(8, 6)
            path.lineTo(16, 12)
            path.lineTo(8, 18)
        painter.drawPath(path)
        painter.end()
        pixmap.setDevicePixelRatio(2)
        return QIcon(pixmap)


class SpaciousComboBox(QComboBox):
    """A clean selector face with a native popup and keyboard behavior."""

    _ARROW_AREA = 30

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def setEditable(self, editable: bool) -> None:  # noqa: N802 - Qt API spelling
        super().setEditable(editable)
        if editor := self.lineEdit():
            editor.setFrame(False)
            editor.setStyleSheet(
                "QLineEdit { background: transparent; border: none; padding: 0; }"
            )
            editor.setTextMargins(0, 0, 0, 0)
            self._position_editor()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_editor()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            QTimer.singleShot(0, self.showPopup)
            event.accept()
            return
        super().mousePressEvent(event)

    def _position_editor(self) -> None:
        if editor := self.lineEdit():
            editor.setGeometry(
                11,
                1,
                max(1, self.width() - self._ARROW_AREA - 12),
                max(1, self.height() - 2),
            )

    def showPopup(self) -> None:  # noqa: N802 - Qt API spelling
        super().showPopup()
        self.update()

    def hidePopup(self) -> None:  # noqa: N802 - Qt API spelling
        super().hidePopup()
        self.update()

    def paintEvent(self, event) -> None:
        colors = _theme_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)

        if not self.isEnabled():
            background = QColor(colors["control_disabled"])
        elif self.view().isVisible():
            background = QColor(colors["control_pressed"])
        elif self.underMouse():
            background = QColor(colors["control_hover"])
        else:
            background = QColor(colors["control"])

        border = QColor(colors["accent"] if self.hasFocus() else colors["border"])
        painter.setPen(QPen(border, 2 if self.hasFocus() else 1))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 7, 7)

        text_color = (
            QColor(colors["text"])
            if self.isEnabled()
            else QColor(colors["disabled_text"])
        )
        if not self.isEditable():
            text_rect = rect.adjusted(10, 0, -self._ARROW_AREA, 0)
            text = self.fontMetrics().elidedText(
                self.currentText(),
                Qt.TextElideMode.ElideRight,
                max(1, text_rect.width()),
            )
            painter.setPen(text_color)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

        arrow_x = rect.right() - 14
        arrow_y = rect.center().y()
        arrow = QPainterPath()
        arrow.moveTo(arrow_x - 4, arrow_y - 2)
        arrow.lineTo(arrow_x, arrow_y + 2)
        arrow.lineTo(arrow_x + 4, arrow_y - 2)
        arrow_pen = QPen(text_color, 1.5)
        arrow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        arrow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(arrow_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(arrow)
        painter.end()


class StatusChip(QFrame):
    """Compact, text-backed status that never communicates through color alone."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusChip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.indicator = QLabel("●")
        self.indicator.setFixedWidth(12)
        self.text = ElidedLabel(label)
        self.text.setMinimumWidth(100)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.indicator)
        layout.addWidget(self.text, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_state(label, "neutral")

    def set_state(self, text: str, state: str) -> None:
        symbol = {"good": "✓", "warning": "!", "neutral": "●"}.get(state, "●")
        object_name = {
            "good": "statusGood",
            "warning": "statusWarning",
            "neutral": "statusNeutral",
        }.get(state, "statusNeutral")
        self.indicator.setText(symbol)
        self.indicator.setObjectName(object_name)
        self.indicator.style().unpolish(self.indicator)
        self.indicator.style().polish(self.indicator)
        self.text.set_full_text(text)
        self.setAccessibleName(text)


class SearchResultRow(QWidget):
    """Readable App Store result with optional asynchronously loaded artwork."""

    def __init__(self, app: App, loader: ArtworkLoader, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(12)
        self.artwork = QLabel("▦")
        self.artwork.setObjectName("artworkPlaceholder")
        self.artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork.setFixedSize(48, 48)
        self.artwork.setAccessibleName(f"{app.name} artwork")
        layout.addWidget(self.artwork)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        name = QLabel(app.name)
        name.setFont(_heading_font(13))
        detail = QLabel(
            f"{app.seller}  ·  Current {app.current_version}  ·  Requires iOS {app.minimum_os}"
        )
        detail.setObjectName("secondaryText")
        identifier = QLabel(app.bundle_id)
        identifier.setObjectName("secondaryText")
        copy.addWidget(name)
        copy.addWidget(detail)
        copy.addWidget(identifier)
        layout.addLayout(copy, 1)
        self.setAccessibleName(
            f"{app.name}, by {app.seller}, current {app.current_version}, "
            f"requires iOS {app.minimum_os}"
        )
        loader.load(app.artwork_url, self._set_artwork)

    def _set_artwork(self, pixmap: QPixmap | None) -> None:
        if pixmap is None:
            return
        target = pixmap.scaled(
            48,
            48,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        rounded = QPixmap(48, 48)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, 48, 48, 10, 10)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, target)
        painter.end()
        self.artwork.setText("")
        self.artwork.setPixmap(rounded)


class SearchResultDelegate(QStyledItemDelegate):
    """Paint selection only; retain item text for accessibility, not display."""

    def paint(self, painter, option, index) -> None:
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            selection = option.palette.highlight().color()
            selection.setAlpha(46)
            painter.setBrush(selection)
            painter.drawRoundedRect(option.rect.adjusted(2, 2, -2, -2), 10, 10)
            painter.restore()


class TaskThread(QThread):
    """Run one blocking backend operation without freezing the window."""

    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Task, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.task = task

    def run(self) -> None:
        try:
            result = self.task(self.progress.emit)
        except Exception as exc:  # normalized at the GUI boundary
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.succeeded.emit(result)


class AppfitWindow(QMainWindow):
    def __init__(
        self,
        workflow: BuildWorkflow | None = None,
        *,
        auto_refresh: bool = True,
    ) -> None:
        super().__init__()
        self.workflow = workflow or BuildWorkflow()
        self.current_account: Account | None = None
        self.current_app: App | None = None
        self.current_report: ResolutionReport | None = None
        self._threads: set[TaskThread] = set()
        self._busy = 0
        self.artwork_loader = ArtworkLoader(self)

        self.setWindowTitle("appfit")
        self.setMinimumSize(720, 620)
        self.resize(860, 720)
        self.setStyleSheet(appfit_style())
        self._build_menus()
        self._build_ui()
        self._set_initial_state()
        if auto_refresh:
            self.refresh_environment()

    # --------------------------------------------------------------- layout

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self.setStyleSheet(appfit_style())
        super().changeEvent(event)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        close_action = QAction("Close Window", self)
        close_action.setShortcut(QKeySequence.StandardKey.Close)
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)

        edit_menu = self.menuBar().addMenu("Edit")
        self.focus_search_action = QAction("Find App", self)
        self.focus_search_action.setShortcut(QKeySequence.StandardKey.Find)
        self.focus_search_action.triggered.connect(lambda: self.search_input.setFocus())
        edit_menu.addAction(self.focus_search_action)

        view_menu = self.menuBar().addMenu("View")
        self.refresh_action = QAction("Refresh Status", self)
        self.refresh_action.setShortcut(QKeySequence("Ctrl+R"))
        self.refresh_action.triggered.connect(self.refresh_environment)
        view_menu.addAction(self.refresh_action)
        self.activity_action = QAction("Show Activity Details", self)
        self.activity_action.setCheckable(True)
        self.activity_action.toggled.connect(self._toggle_activity)
        view_menu.addAction(self.activity_action)

        account_menu = self.menuBar().addMenu("Account")
        self.sign_in_action = QAction("Sign In…", self)
        self.sign_in_action.triggered.connect(self.sign_in)
        account_menu.addAction(self.sign_in_action)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("workspace")
        root.setMinimumWidth(660)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(18)

        title = QLabel("Install an app that fits")
        title.setFont(_heading_font(24))
        subtitle = QLabel(
            "Choose an iPhone or iPad, then find the newest App Store version "
            "that still runs on it."
        )
        subtitle.setObjectName("secondaryText")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        layout.addWidget(self._status_strip())
        layout.addWidget(self._target_card())
        layout.addWidget(self._search_card())
        self.compatibility_card = self._result_section()
        layout.addWidget(self.compatibility_card)
        layout.addWidget(self._activity_card())
        layout.addStretch(1)

        regular_controls = (
            self.refresh_button,
            self.sign_in_button,
            self.target_mode,
            self.device_combo,
            self.manual_ios,
            self.platform_combo,
            self.search_input,
            self.search_button,
            self.find_button,
            self.version_combo,
            self.load_older_button,
            self.install_button,
            self.download_button,
            self.claim_button,
        )
        for control in regular_controls:
            control.setMinimumHeight(REGULAR_CONTROL_HEIGHT)
        self.search_input.setTextMargins(8, 0, 8, 0)

        scroll = QScrollArea()
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

        # Keep both target branches in one chain. Qt skips the hidden page, so
        # connected mode moves from the device chooser to search while manual
        # mode naturally includes its editable iOS and device-family fields.
        QWidget.setTabOrder(self.sign_in_button, self.refresh_button)
        QWidget.setTabOrder(self.refresh_button, self.target_mode)
        QWidget.setTabOrder(self.target_mode, self.device_combo)
        QWidget.setTabOrder(self.device_combo, self.manual_ios)
        QWidget.setTabOrder(self.manual_ios, self.platform_combo)
        QWidget.setTabOrder(self.platform_combo, self.search_input)
        QWidget.setTabOrder(self.search_input, self.search_button)
        QWidget.setTabOrder(self.search_button, self.search_results)
        QWidget.setTabOrder(self.search_results, self.find_button)
        QWidget.setTabOrder(self.find_button, self.version_combo)
        QWidget.setTabOrder(self.version_combo, self.load_older_button)
        QWidget.setTabOrder(self.load_older_button, self.install_button)
        QWidget.setTabOrder(self.install_button, self.download_button)
        QWidget.setTabOrder(self.download_button, self.claim_button)
        QWidget.setTabOrder(self.claim_button, self.activity_toggle)
        QWidget.setTabOrder(self.activity_toggle, self.sign_in_button)

    @staticmethod
    def _card() -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("surfaceCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        return card, layout

    def _status_strip(self) -> QFrame:
        strip = QFrame()
        strip.setObjectName("statusStrip")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(14, 9, 10, 9)
        layout.setSpacing(16)
        self.helper_chip = StatusChip("Checking App Store…")
        self.account_chip = StatusChip("Checking Apple ID…")
        self.device_chip = StatusChip("Checking devices…")
        self.helper_status = self.helper_chip.text
        self.account_status = self.account_chip.text
        self.device_status = self.device_chip.text
        self.refresh_button = QPushButton("Refresh")
        self.sign_in_button = QPushButton("Sign in…")
        self.refresh_button.clicked.connect(self.refresh_environment)
        self.sign_in_button.clicked.connect(self.sign_in)
        layout.addWidget(self.helper_chip, 3)
        layout.addWidget(self.account_chip, 4)
        layout.addWidget(self.device_chip, 3)
        layout.addWidget(self.sign_in_button)
        layout.addWidget(self.refresh_button)
        return strip

    def _target_card(self) -> QFrame:
        card, layout = self._card()
        heading_row = QHBoxLayout()
        heading = QLabel("Target device")
        heading.setObjectName("sectionTitle")
        heading.setFont(_heading_font(15))
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self.target_mode = SpaciousComboBox()
        self.target_mode.setAccessibleName("Target source")
        self.target_mode.addItem("Connected device")
        self.target_mode.addItem("Manual iOS target")
        self.target_mode.currentIndexChanged.connect(self._target_mode_changed)
        heading_row.addWidget(self.target_mode)
        layout.addLayout(heading_row)

        self.target_stack = QStackedWidget()
        device_page = QWidget()
        device_layout = QHBoxLayout(device_page)
        device_layout.setContentsMargins(0, 0, 0, 0)
        self.device_combo = SpaciousComboBox()
        self.device_combo.setAccessibleName("Connected device")
        self.device_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.device_combo.currentIndexChanged.connect(self._target_changed)
        device_layout.addWidget(self.device_combo)

        manual_page = QWidget()
        manual_layout = QHBoxLayout(manual_page)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(CONTROL_ROW_SPACING)
        self.manual_ios = SpaciousComboBox()
        self.manual_ios.setAccessibleName("Target iOS version")
        self.manual_ios.setEditable(True)
        self.manual_ios.addItems(["16.7.16", "15.8.3", "14", "13", "12.5.7"])
        self.manual_ios.currentTextChanged.connect(self._target_changed)
        self.platform_combo = SpaciousComboBox()
        self.platform_combo.setAccessibleName("Target device family")
        self.platform_combo.addItem("iPad", "ipad")
        self.platform_combo.addItem("iPhone", "iphone")
        self.platform_combo.currentIndexChanged.connect(self._target_changed)
        manual_layout.addWidget(QLabel("iOS version"))
        manual_layout.addWidget(self.manual_ios, 1)
        manual_layout.addSpacing(4)
        manual_layout.addWidget(QLabel("Device family"))
        manual_layout.addWidget(self.platform_combo, 1)

        self.target_stack.addWidget(device_page)
        self.target_stack.addWidget(manual_page)
        layout.addWidget(self.target_stack)
        self.target_detail = QLabel()
        self.target_detail.setObjectName("secondaryText")
        self.target_detail.setWordWrap(True)
        layout.addWidget(self.target_detail)
        return card

    def _search_card(self) -> QFrame:
        card, layout = self._card()
        heading = QLabel("Find an app")
        heading.setObjectName("sectionTitle")
        heading.setFont(_heading_font(15))
        layout.addWidget(heading)
        row = QHBoxLayout()
        row.setSpacing(CONTROL_ROW_SPACING)
        self.search_input = QLineEdit()
        self.search_input.setAccessibleName("App Store search")
        self.search_input.setPlaceholderText(
            "Name, bundle ID, App Store ID, or App Store URL"
        )
        self.search_input.returnPressed.connect(self.search)
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.search)
        row.addWidget(self.search_input, 1)
        row.addWidget(self.search_button)
        layout.addLayout(row)

        self.search_results = QListWidget()
        self.search_results.setObjectName("searchResults")
        self.search_results.setAccessibleName("App Store search results")
        self.search_results.setItemDelegate(SearchResultDelegate(self.search_results))
        self.search_results.setMaximumHeight(204)
        self.search_results.itemSelectionChanged.connect(self._app_selected)
        layout.addWidget(self.search_results)
        self.selected_app_label = QLabel("No app selected")
        self.selected_app_label.setObjectName("secondaryText")
        self.selected_app_label.setWordWrap(True)
        layout.addWidget(self.selected_app_label)
        return card

    def _result_section(self) -> QFrame:
        outer_card, layout = self._card()
        heading_row = QHBoxLayout()
        heading = QLabel("Compatible version")
        heading.setObjectName("sectionTitle")
        heading.setFont(_heading_font(15))
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self.find_button = QPushButton("Find newest compatible version")
        self.find_button.setObjectName("primaryButton")
        self.find_button.clicked.connect(self.resolve_selected)
        heading_row.addWidget(self.find_button)
        layout.addLayout(heading_row)

        self.result_card = QFrame()
        result_layout = QVBoxLayout(self.result_card)
        result_layout.setContentsMargins(0, 4, 0, 0)
        result_layout.setSpacing(10)
        self.recommendation_title = QLabel()
        self.recommendation_title.setFont(_heading_font(17))
        self.recommendation_detail = QLabel()
        self.recommendation_detail.setObjectName("secondaryText")
        self.recommendation_detail.setWordWrap(True)
        result_layout.addWidget(self.recommendation_title)
        result_layout.addWidget(self.recommendation_detail)

        version_row = QHBoxLayout()
        version_row.setSpacing(CONTROL_ROW_SPACING)
        version_row.addWidget(QLabel("Version"))
        self.version_combo = SpaciousComboBox()
        self.version_combo.setAccessibleName("Verified app version")
        self.version_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.load_older_button = QPushButton("Load older versions")
        self.load_older_button.clicked.connect(self.load_older_versions)
        version_row.addWidget(self.version_combo, 1)
        version_row.addWidget(self.load_older_button)
        result_layout.addLayout(version_row)

        actions = QHBoxLayout()
        actions.setSpacing(CONTROL_ROW_SPACING)
        actions.addStretch(1)
        self.install_button = QPushButton("Install on device")
        self.download_button = QPushButton("Download IPA")
        self.claim_button = QPushButton("Claim licence only")
        self.claim_button.setObjectName("tertiaryButton")
        self.install_button.clicked.connect(self.install_selected)
        self.download_button.clicked.connect(self.download_selected)
        self.claim_button.clicked.connect(self.claim_selected)
        actions.addWidget(self.install_button)
        actions.addWidget(self.download_button)
        actions.addWidget(self.claim_button)
        result_layout.addLayout(actions)
        layout.addWidget(self.result_card)
        return outer_card

    def _activity_card(self) -> QFrame:
        card, layout = self._card()
        row = QHBoxLayout()
        self.activity_summary = ElidedLabel("Ready")
        self.activity_summary.setObjectName("secondaryText")
        row.addWidget(self.activity_summary, 1)
        self.activity_toggle = DisclosureButton()
        self.activity_toggle.toggled.connect(self._toggle_activity)
        row.addWidget(self.activity_toggle)
        layout.addLayout(row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.hide()
        self.activity = QPlainTextEdit()
        self.activity.setObjectName("activityDetails")
        self.activity.setReadOnly(True)
        self.activity.setMaximumHeight(120)
        self.activity.setPlaceholderText("Ready")
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.activity)
        self.activity.hide()
        return card

    def _toggle_activity(self, visible: bool) -> None:
        self.activity.setVisible(visible)
        self.activity_toggle.blockSignals(True)
        self.activity_toggle.setChecked(visible)
        self.activity_toggle.set_expanded(visible)
        self.activity_toggle.blockSignals(False)
        self.activity_action.blockSignals(True)
        self.activity_action.setChecked(visible)
        self.activity_action.blockSignals(False)

    # -------------------------------------------------------------- state

    def _set_initial_state(self) -> None:
        self.compatibility_card.hide()
        self.result_card.hide()
        self.search_results.hide()
        self.selected_app_label.hide()
        self.find_button.setEnabled(False)
        self.claim_button.setEnabled(False)
        self._target_mode_changed()

    def _target_mode_changed(self) -> None:
        self.target_stack.setCurrentIndex(self.target_mode.currentIndex())
        self._target_changed()

    def _target_changed(self) -> None:
        self.current_report = None
        self.result_card.hide()
        self.find_button.setVisible(self.current_app is not None)
        self._update_enabled_state()
        try:
            target, device = self._selected_target()
        except WorkflowError as exc:
            self.target_detail.setText(str(exc))
            if self.target_mode.currentIndex() == 1:
                self.device_chip.set_state("Invalid manual target", "warning")
            else:
                self.device_chip.set_state("No device connected", "warning")
            return
        if device:
            paired = accounts.account_for_device(device.udid)
            pairing = f"Paired with {paired}" if paired else "Not paired yet"
            self.target_detail.setText(
                f"{device.product_type}  ·  iOS {target.ios_version}  ·  {pairing}"
            )
            self.device_chip.set_state(f"{device.name} connected", "good")
        else:
            self.target_detail.setText(
                "Manual targets can be resolved and downloaded. Select a connected "
                "device to install over USB."
            )
            self.device_chip.set_state(
                f"Manual {target.platform} · iOS {target.ios_version}", "neutral"
            )

    def _selected_target(self) -> tuple[Target, Device | None]:
        if self.target_mode.currentIndex() == 0:
            device = self.device_combo.currentData(Qt.ItemDataRole.UserRole)
            if not isinstance(device, Device):
                raise WorkflowError(
                    "Connect, unlock, and trust an iPhone or iPad, then refresh."
                )
            return device.target(), device
        target = target_from_manual(
            self.manual_ios.currentText(), self.platform_combo.currentData()
        )
        return target, None

    def _selected_candidate(self) -> BuildCandidate:
        candidate = self.version_combo.currentData(Qt.ItemDataRole.UserRole)
        if not isinstance(candidate, BuildCandidate):
            raise WorkflowError("Choose a verified compatible version.")
        if not candidate.compatible:
            raise WorkflowError("That build is not compatible with this target.")
        return candidate

    def _app_selected(self) -> None:
        items = self.search_results.selectedItems()
        self.current_app = (
            items[0].data(Qt.ItemDataRole.UserRole) if items else None
        )
        if self.current_app:
            app = self.current_app
            self.selected_app_label.setText(
                f"Selected {app.name}  ·  Current {app.current_version}  ·  "
                f"Requires iOS {app.minimum_os}"
            )
            self.selected_app_label.show()
            self.compatibility_card.show()
        else:
            self.selected_app_label.setText("No app selected")
            self.selected_app_label.hide()
            self.compatibility_card.hide()
        self.current_report = None
        self.result_card.hide()
        self.find_button.setVisible(self.current_app is not None)
        self._update_enabled_state()

    # ------------------------------------------------------------ workers

    def _start_task(
        self,
        task: Task,
        on_success: Callable[[Any], None],
        *,
        description: str,
    ) -> None:
        thread = TaskThread(task, self)
        self._threads.add(thread)
        self._busy += 1
        self._update_enabled_state()
        self.progress_bar.show()
        self.progress_bar.setRange(0, 0)
        self.activity_summary.setText(description)
        self.activity.appendPlainText(description)
        thread.progress.connect(self._show_progress)
        thread.succeeded.connect(on_success)
        thread.failed.connect(self._show_error)

        def finished() -> None:
            self._threads.discard(thread)
            self._busy = max(0, self._busy - 1)
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.progress_bar.hide()
            self._update_enabled_state()

        thread.finished.connect(finished)
        thread.start()

    def closeEvent(self, event) -> None:
        if any(thread.isRunning() for thread in self._threads):
            event.ignore()
            QMessageBox.information(
                self,
                "Operation still running",
                "Wait for the current App Store or device operation to finish "
                "before closing appfit.",
            )
            return
        super().closeEvent(event)

    def _show_progress(self, event: ProgressEvent) -> None:
        self.activity_summary.setText(event.message)
        self.activity.appendPlainText(event.message)
        if event.total is not None and event.current is not None and event.total > 0:
            self.progress_bar.setRange(0, event.total)
            self.progress_bar.setValue(min(event.current, event.total))

    def _show_error(self, message: str) -> None:
        self.activity_summary.setText(f"Could not continue — {message}")
        self.activity.appendPlainText(f"Error: {message}")
        self._toggle_activity(True)
        QMessageBox.critical(self, "appfit could not continue", message)

    def _update_enabled_state(self) -> None:
        ready = self._busy == 0
        self.focus_search_action.setEnabled(ready)
        self.refresh_action.setEnabled(ready)
        self.sign_in_action.setEnabled(ready)
        self.search_input.setEnabled(ready)
        self.search_results.setEnabled(ready)
        self.search_button.setEnabled(ready)
        self.refresh_button.setEnabled(ready)
        self.sign_in_button.setEnabled(ready)
        self.target_mode.setEnabled(ready)
        self.device_combo.setEnabled(ready)
        self.manual_ios.setEnabled(ready)
        self.platform_combo.setEnabled(ready)
        self.version_combo.setEnabled(ready)
        self.find_button.setEnabled(ready and self.current_app is not None)
        has_report = ready and self.current_report is not None
        self.download_button.setEnabled(has_report)
        self.claim_button.setEnabled(ready and self.current_app is not None)
        try:
            _target, device = self._selected_target()
        except WorkflowError:
            device = None
        connected = device is not None
        self.install_button.setVisible(connected)
        self.install_button.setEnabled(has_report and connected)
        self.install_button.setText(
            f"Install on {device.name}" if device is not None else "Install on device"
        )
        self.install_button.setObjectName("primaryButton")
        self.download_button.setObjectName(
            "secondaryButton" if connected else "primaryButton"
        )
        for button in (self.install_button, self.download_button):
            button.style().unpolish(button)
            button.style().polish(button)
        self.search_button.setDefault(self.current_app is None)
        self.find_button.setDefault(
            self.current_app is not None and self.current_report is None
        )
        self.install_button.setDefault(has_report and connected)
        self.download_button.setDefault(has_report and not connected)
        self.load_older_button.setEnabled(
            has_report
            and self.current_report is not None
            and self._oldest_loaded_index() > 0
        )

    # ---------------------------------------------------------- readiness

    def refresh_environment(self) -> None:
        def task(_progress):
            status = toolchain.status()
            active = self.workflow.active_account() if status.path else None
            device_error = ""
            try:
                found = self.workflow.connected_devices()
            except WorkflowError as exc:
                found = []
                device_error = str(exc)
            return status, active, found, device_error

        self._start_task(task, self._environment_loaded, description="Refreshing status…")

    def _environment_loaded(self, result) -> None:
        status, active, found, device_error = result
        if status.path:
            self.helper_chip.set_state("App Store ready", "good")
        else:
            self.helper_chip.set_state("App Store access unavailable", "warning")
        self.current_account = active
        if active:
            self.account_chip.set_state(active.email, "good")
            self.sign_in_button.hide()
            self.sign_in_action.setText("Change Account…")
        else:
            self.account_chip.set_state("Not signed in", "warning")
            self.sign_in_button.setText("Sign in…")
            self.sign_in_button.show()
            self.sign_in_action.setText("Sign In…")

        previous = None
        current = self.device_combo.currentData(Qt.ItemDataRole.UserRole)
        if isinstance(current, Device):
            previous = current.udid
        self.device_combo.clear()
        if not found:
            self.device_combo.addItem("No connected devices")
            self.device_chip.set_state("No device connected", "warning")
        for device in found:
            self.device_combo.addItem(str(device), device)
            if device.udid == previous:
                self.device_combo.setCurrentIndex(self.device_combo.count() - 1)
        if device_error:
            self.target_detail.setText(device_error)
            self.device_chip.set_state("Device check failed", "warning")
        else:
            self._target_changed()
        self.activity_summary.setText("Ready to find a compatible app")
        self._update_enabled_state()

    def sign_in(self) -> None:
        email, accepted = QInputDialog.getText(
            self,
            "Sign in to the App Store",
            "Apple ID used for App Store purchases on the target device:",
        )
        if not accepted:
            return
        try:
            launch_login_terminal(email)
        except WorkflowError as exc:
            self._show_error(str(exc))
            return
        QMessageBox.information(
            self,
            "Complete sign-in in Terminal",
            "Enter the password and two-factor code in the Terminal window. "
            "appfit does not capture them. Return here and click Refresh when done.",
        )

    # -------------------------------------------------------------- search

    def search(self) -> None:
        term = self.search_input.text().strip()
        if not term:
            self._show_error("Enter an app name, identifier, or App Store URL.")
            return
        self.search_results.clear()
        self.search_results.hide()
        self.current_app = None
        self.current_report = None
        self.compatibility_card.hide()
        self.find_button.hide()
        self.selected_app_label.setText("No app selected")
        self.selected_app_label.hide()
        self.result_card.hide()
        self._update_enabled_state()
        self._start_task(
            lambda _progress: self.workflow.search(term),
            self._search_loaded,
            description=f"Searching for {term!r}…",
        )

    def _search_loaded(self, results: list[App]) -> None:
        if not results:
            self.selected_app_label.setText("No App Store results found")
            self.selected_app_label.show()
            self.activity_summary.setText("No App Store results found")
            return
        for app in results:
            accessible_text = (
                f"{app.name}, by {app.seller}, current {app.current_version}, "
                f"requires iOS {app.minimum_os}, {app.bundle_id}"
            )
            item = QListWidgetItem(accessible_text)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, accessible_text)
            item.setData(Qt.ItemDataRole.UserRole, app)
            item.setSizeHint(QSize(0, 66))
            self.search_results.addItem(item)
            self.search_results.setItemWidget(
                item, SearchResultRow(app, self.artwork_loader, self.search_results)
            )
        self.search_results.setFixedHeight(min(204, max(72, len(results) * 68)))
        self.search_results.show()
        self.search_results.setCurrentRow(0)
        self.activity_summary.setText(
            f"Found {len(results)} App Store {'result' if len(results) == 1 else 'results'}"
        )

    # ------------------------------------------------------------- resolve

    def resolve_selected(self) -> None:
        if not self.current_app:
            self._show_error("Select an app first.")
            return
        if not self.current_account:
            self._show_error("Sign in with the target device's Apple ID first.")
            return
        try:
            target, _device = self._selected_target()
        except WorkflowError as exc:
            self._show_error(str(exc))
            return
        app = self.current_app
        account = self.current_account.email
        answer = QMessageBox.question(
            self,
            "Check historical versions?",
            f"To inspect {app.name}'s historical builds, appfit may need to add "
            f"this free app to {account}'s Purchased history. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._start_task(
            lambda progress: self.workflow.resolve(
                app, target, account, claim_licence=True, on_progress=progress
            ),
            self._resolution_loaded,
            description=f"Finding the newest {app.name} build for iOS {target.ios_version}…",
        )

    def _resolution_loaded(self, report: ResolutionReport) -> None:
        self.current_report = report
        candidate = report.recommended
        self.version_combo.clear()
        self.version_combo.addItem(
            f"{candidate.choice_label} · Recommended", candidate
        )
        self.recommendation_title.setText(
            f"✓ {candidate.display_version or candidate.external_version_id}"
        )
        cache_note = "cached result" if report.from_cache else f"{report.probes} build probes"
        current_note = (
            "The current App Store version already works."
            if report.current_compatible
            else "This is the newest compatible historical version."
        )
        self.recommendation_detail.setText(
            f"{candidate.label}\n{current_note} · {cache_note}"
        )
        self.find_button.hide()
        self.result_card.show()
        self.activity_summary.setText(
            f"Recommended {report.app.name} {candidate.display_version or candidate.external_version_id}"
        )
        self._update_enabled_state()

    def _oldest_loaded_index(self) -> int:
        indexes = []
        for index in range(self.version_combo.count()):
            candidate = self.version_combo.itemData(index)
            if isinstance(candidate, BuildCandidate):
                indexes.append(candidate.history_index)
        return min(indexes) if indexes else 0

    def load_older_versions(self) -> None:
        if not self.current_report:
            return
        before = self._oldest_loaded_index()
        report = self.current_report
        self._start_task(
            lambda progress: self.workflow.older_candidates(
                report, before_index=before, limit=10, on_progress=progress
            ),
            self._older_loaded,
            description="Loading and verifying older versions…",
        )

    def _older_loaded(self, candidates: list[BuildCandidate]) -> None:
        if not candidates:
            self.activity.appendPlainText("No more older versions")
            self.activity_summary.setText("No more older versions are available")
            return
        model = self.version_combo.model()
        for candidate in candidates:
            suffix = "" if candidate.compatible else " · Incompatible"
            self.version_combo.addItem(candidate.choice_label + suffix, candidate)
            item = model.item(self.version_combo.count() - 1)
            if item is not None and not candidate.compatible:
                item.setEnabled(False)
        self._update_enabled_state()
        self.activity_summary.setText(
            f"Loaded {len(candidates)} older {'version' if len(candidates) == 1 else 'versions'}"
        )

    # -------------------------------------------------------------- actions

    def _confirm_action(self, verb: str) -> bool:
        if not self.current_app or not self.current_account:
            self._show_error("Select an app and sign in first.")
            return False
        candidate = self._selected_candidate()
        answer = QMessageBox.question(
            self,
            f"{verb} {self.current_app.name}?",
            f"{verb} {self.current_app.name} {candidate.display_version} "
            f"(build {candidate.external_version_id}) using "
            f"{self.current_account.email}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def download_selected(self) -> None:
        if not self.current_report or not self._confirm_action("Download"):
            return
        app = self.current_report.app
        target = self.current_report.target
        account = self.current_account.email
        candidate = self._selected_candidate()
        self._start_task(
            lambda progress: self.workflow.prepare(
                app, target, account, candidate, on_progress=progress
            ),
            self._download_complete,
            description=f"Downloading {app.name} {candidate.display_version}…",
        )

    def _download_complete(self, prepared: PreparedIPA) -> None:
        action = "Reused" if prepared.reused else "Downloaded"
        self.activity.appendPlainText(f"{action} {prepared.path}")
        self.activity_summary.setText(
            f"{action} and verified {prepared.app.name} {prepared.candidate.display_version}"
        )
        QMessageBox.information(
            self,
            "Download complete",
            f"{action} and verified:\n{prepared.path}",
        )

    def install_selected(self) -> None:
        if not self.current_report:
            return
        try:
            _target, device = self._selected_target()
        except WorkflowError as exc:
            self._show_error(str(exc))
            return
        if device is None:
            self._show_error("Select a connected device to install over USB.")
            return
        if not self.current_account:
            self._show_error("Sign in first.")
            return
        paired = accounts.account_for_device(device.udid)
        if paired is None:
            answer = QMessageBox.question(
                self,
                "Pair device with Apple ID?",
                f"Confirm that {self.current_account.email} is the App Store "
                f"purchases account currently signed in on {device.name}. Pair them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            accounts.pair(device.udid, self.current_account.email)
            paired = self.current_account.email
            self.target_detail.setText(
                f"{device.product_type} · {device.target().platform} · "
                f"Paired with {paired}"
            )
        if paired.lower() != self.current_account.email.lower():
            self._show_error(
                f"This device is paired with {paired}, but appfit is signed in as "
                f"{self.current_account.email}. Switch accounts before installing."
            )
            return
        if not self._confirm_action("Install"):
            return

        report = self.current_report
        candidate = self._selected_candidate()
        account = self.current_account.email

        def task(progress):
            prepared = self.workflow.prepare(
                report.app, report.target, account, candidate, on_progress=progress
            )
            self.workflow.install(prepared, device.udid, on_progress=progress)
            return prepared

        self._start_task(
            task,
            self._install_complete,
            description=f"Preparing and installing {report.app.name}…",
        )

    def _install_complete(self, prepared: PreparedIPA) -> None:
        self.activity.appendPlainText(f"Installed {prepared.app.name}")
        self.activity_summary.setText(
            f"Installed {prepared.app.name} {prepared.candidate.display_version}"
        )
        QMessageBox.information(
            self,
            "Installation complete",
            f"Installed {prepared.app.name} {prepared.candidate.display_version}.",
        )

    def claim_selected(self) -> None:
        if not self.current_app or not self.current_account:
            self._show_error("Select an app and sign in first.")
            return
        app = self.current_app
        account = self.current_account.email
        answer = QMessageBox.question(
            self,
            "Claim free app licence?",
            f"Add {app.name} to {account}'s App Store Purchased history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_task(
            lambda _progress: self.workflow.claim(app, account),
            lambda claimed: self._claim_complete(app, account, claimed),
            description=f"Claiming {app.name}…",
        )

    def _claim_complete(self, app: App, account: str, claimed: bool) -> None:
        state = "Licence claimed" if claimed else "Licence already held"
        instructions = (
            f"{state}.\n\nOn the device signed in as {account}:\n"
            "App Store → your avatar → Purchased → Not on this Device → "
            f"{app.name} → cloud download. Accept Apple's older-version offer if shown."
        )
        self.activity.appendPlainText(state)
        self.activity_summary.setText(f"{state}: {app.name}")
        QMessageBox.information(self, "On-device installation", instructions)
