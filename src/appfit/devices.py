"""Read connected iOS devices over USB.

Optional: the claim+resolve half of appfit works with a hand-typed iOS
version and no cable. This module only adds convenience (and, in phase 2, the
install path), so an absent pymobiledevice3 degrades to a clear message rather
than an import error at startup.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Device:
    udid: str
    name: str
    product_type: str  # e.g. iPad6,11
    ios_version: str  # e.g. 16.7.16

    def __str__(self) -> str:
        return f"{self.name} · {self.product_type} · iOS {self.ios_version}"


class DeviceSupportUnavailable(RuntimeError):
    """pymobiledevice3 isn't installed."""


def _require_backend():
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.usbmux import list_devices
    except ImportError as exc:  # noqa: BLE001
        raise DeviceSupportUnavailable(
            "USB device support needs pymobiledevice3:\n"
            "  pip install 'appfit[device]'"
        ) from exc
    return create_using_usbmux, list_devices


def connected() -> list[Device]:
    """Every device currently attached over USB."""
    create_using_usbmux, list_devices = _require_backend()

    found: list[Device] = []
    for muxed in list_devices():
        udid = muxed.serial
        lockdown = create_using_usbmux(serial=udid)
        values = lockdown.all_values
        found.append(
            Device(
                udid=udid,
                name=values.get("DeviceName", "(unnamed)"),
                product_type=values.get("ProductType", "?"),
                ios_version=values.get("ProductVersion", "?"),
            )
        )
    return found


def get(udid: str) -> Device | None:
    return next((d for d in connected() if d.udid == udid), None)
