"""Render README screenshots of the Mac app from fabricated data.

Screenshots of a real session would carry an Apple ID, a device name, and a
UDID, and redacting those afterwards leaves black boxes over the parts a reader
most wants to see. Driving the window with stand-in data instead produces
publishable images with nothing to scrub, and re-running this after a UI change
keeps them honest.

    python scripts/capture_screenshots.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from appfit.apps import App  # noqa: E402
from appfit.devices import Device  # noqa: E402
from appfit.gui.window import AppfitWindow  # noqa: E402
from appfit.store import Account  # noqa: E402
from appfit.workflows import BuildCandidate, ResolutionReport  # noqa: E402

OUTPUT = ROOT / "assets" / "screenshots"
WINDOW = QSize(980, 720)
# Vertical space left around a card when a screenshot is framed on one.
GAP = 14
ARTWORK = "https://itunes.apple.com/lookup"

# Deliberately generic: a device named after its model rather than its owner,
# and the Apple ID placeholder used throughout the documentation.
ACCOUNT = Account("you@example.com", "")
DEVICE = Device(
    udid="00000000000000000000000000000000000000000",
    name="iPad",
    product_type="iPad6,11",
    ios_version="16.7.16",
)

RESULTS = [
    App(549039908, "com.crystalnix.ServerAuditor", "Termius - SSH Client", "7.6.1", "17.0", "Termius Corporation"),
    App(650377962, "org.videolan.vlc-ios", "VLC media player", "3.7.3", "9.0", "VideoLAN"),
    App(1133348139, "com.netflix.Speedtest", "FAST Speed Test", "1.1.1", "7.0", "Netflix, Inc."),
]

RECOMMENDED = BuildCandidate(
    history_index=214,
    external_version_id="877527781",
    display_version="6.3.0",
    release_date="2025-08-25",
    minimum_os="16.0",
    device_families=(1, 2),
    compatible=True,
    source="metadata",
    recommended=True,
)

OLDER = [
    BuildCandidate(
        history_index=213,
        external_version_id="876914402",
        display_version="6.2.1",
        release_date="2025-08-04",
        minimum_os="16.0",
        device_families=(1, 2),
        compatible=True,
        source="metadata",
    ),
    BuildCandidate(
        history_index=212,
        external_version_id="875660118",
        display_version="6.1.7",
        release_date="2025-06-30",
        minimum_os="16.0",
        device_families=(1, 2),
        compatible=True,
        source="metadata",
    ),
    BuildCandidate(
        history_index=211,
        external_version_id="874203551",
        display_version="6.0.4",
        release_date="2025-05-19",
        minimum_os="17.0",
        device_families=(1, 2),
        compatible=False,
        source="metadata",
    ),
]


class StubStatus:
    """A helper that is present and compatibility-aware, as a reader's would be."""

    path = Path("/Applications/appfit.app/Contents/Frameworks/appfit/bin/ipatool")
    source = "appfit-bundled"
    version = "ipatool version v2.4.0-appfit"
    compatibility_metadata = True


class StubWorkflow:
    """Answers the window's environment probe without touching the network."""

    def active_account(self) -> Account:
        return ACCOUNT

    def connected_devices(self) -> list[Device]:
        return [DEVICE]


def report() -> ResolutionReport:
    return ResolutionReport(
        app=RESULTS[0],
        target=DEVICE.target(),
        version_ids=tuple(str(index) for index in range(278)),
        recommended=RECOMMENDED,
        probes=9,
        from_cache=False,
        source="metadata",
        licence_claimed=False,
    )


def load_artwork() -> None:
    """Fill in real icon URLs so the result rows are not grey placeholders.

    The store lookup is public and unauthenticated. If it is unavailable the
    rows fall back to their placeholder, which is a worse screenshot but not a
    failed run.
    """
    import json
    import urllib.request

    ids = ",".join(str(app.app_id) for app in RESULTS)
    try:
        with urllib.request.urlopen(f"{ARTWORK}?id={ids}&entity=software", timeout=20) as reply:
            found = {
                int(result["trackId"]): result.get("artworkUrl100", "")
                for result in json.load(reply).get("results", [])
                if "trackId" in result
            }
    except OSError:
        return
    for app in RESULTS:
        app.artwork_url = found.get(app.app_id, "")


def settle(application: QApplication, rounds: int = 40) -> None:
    """Let queued layout, paint, and artwork replies finish before a grab."""
    import time

    for _ in range(rounds):
        application.processEvents()
        time.sleep(0.05)


def enclosing_card(widget):
    """The `surfaceCard` panel a control sits in, for framing on card edges."""
    node = widget
    while node is not None and node.objectName() != "surfaceCard":
        node = node.parentWidget()
    return node or widget


def offset(window: AppfitWindow, widget) -> int:
    """`widget`'s y position within the scrolled page."""
    area: QScrollArea = window.centralWidget()
    return widget.mapTo(area.widget(), widget.rect().topLeft()).y()


def capture(
    window: AppfitWindow,
    application: QApplication,
    name: str,
    *,
    top=None,
    bottom=None,
    above: int = 28,
    below: int = 20,
) -> Path:
    """Grab the window, framed on the step the screenshot is meant to show.

    `top` scrolls that widget's card into view and `bottom` trims the image
    just under the last thing worth showing, so no screenshot ends on a card
    sliced through the middle.
    """
    settle(application)
    if top is not None:
        area: QScrollArea = window.centralWidget()
        area.verticalScrollBar().setValue(max(0, offset(window, top) - above))
        settle(application, rounds=8)

    image = window.grab()
    start = 0
    if top is not None:
        # Start on the gap between cards rather than a few stray pixels of the
        # card above, which reads as a rendering fault in a documentation image.
        card = enclosing_card(top)
        start = max(0, card.mapTo(window, card.rect().topLeft()).y() - GAP)
    end = image.height()
    if bottom is not None:
        end = min(bottom.mapTo(window, bottom.rect().bottomLeft()).y() + below, end)
    image = image.copy(0, start, image.width(), end - start)

    destination = OUTPUT / f"{name}.png"
    image.save(str(destination))
    return destination


def main() -> None:
    import appfit.gui.window as window_module

    window_module.toolchain.status = lambda: StubStatus()

    OUTPUT.mkdir(parents=True, exist_ok=True)
    load_artwork()
    application = QApplication.instance() or QApplication([])

    window = AppfitWindow(StubWorkflow(), auto_refresh=False)
    window.resize(WINDOW)
    # Offscreen draws the menu bar inside the window; a Mac puts it in the
    # system bar, so hiding it keeps the screenshot true to what a reader sees.
    window.menuBar().setVisible(False)
    window.show()
    window._environment_loaded((StubStatus(), ACCOUNT, [DEVICE], ""))

    window.search_input.setText("termius")
    window._search_loaded(RESULTS)
    written = [
        capture(window, application, "search", bottom=window.selected_app_label)
    ]

    window._resolution_loaded(report())
    window._older_loaded(OLDER)
    written.append(
        capture(
            window,
            application,
            "recommendation",
            top=window.recommendation_title,
            above=70,
            bottom=window.download_button,
        )
    )

    window.close()
    for path in written:
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
