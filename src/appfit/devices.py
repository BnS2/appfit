"""Read connected iOS devices over USB, and describe what a build has to fit.

Optional: the claim+resolve half of appfit works with a hand-typed iOS
version and no cable. This module only adds convenience (and, in phase 2, the
install path), so an absent pymobiledevice3 degrades to a clear message rather
than an import error at startup.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass

# UIDeviceFamily values, as Info.plist declares them.
FAMILY_IPHONE = 1  # iPhone and iPod touch
FAMILY_IPAD = 2

# ipatool's --platform vocabulary, and the device family each implies.
_PLATFORM_FAMILY = {"iphone": FAMILY_IPHONE, "ipad": FAMILY_IPAD}

# What we ask the store for when nothing better is known. Matches the behaviour
# appfit had when the platform was hardcoded.
DEFAULT_PLATFORM = "ipad"
DISCOVERY_TIMEOUT = 10
CONNECTION_TIMEOUT = 15


@dataclass
class Target:
    """What a build has to satisfy: an iOS version and a hardware family.

    `device_family` of None means unknown -- from `--ios` with no cable, or an
    unrecognised product type. Unknown must never be used to *reject* a build;
    see BuildInfo.fits.
    """

    ios_version: str
    platform: str = DEFAULT_PLATFORM
    device_family: int | None = None
    udid: str | None = None

    @classmethod
    def from_ios(cls, ios_version: str, platform: str = DEFAULT_PLATFORM) -> "Target":
        """A target described by hand, with no device attached."""
        return cls(
            ios_version=ios_version,
            platform=platform,
            device_family=_PLATFORM_FAMILY.get(platform),
        )


def classify(product_type: str) -> tuple[str, int | None]:
    """'iPad6,11' -> ('ipad', 2). Unknown hardware keeps the default platform
    but reports an unknown family, so it constrains nothing."""
    model = (product_type or "").lower()
    if model.startswith("ipad"):
        return "ipad", FAMILY_IPAD
    if model.startswith(("iphone", "ipod")):
        return "iphone", FAMILY_IPHONE
    return DEFAULT_PLATFORM, None


@dataclass
class Device:
    udid: str
    name: str
    product_type: str  # e.g. iPad6,11
    ios_version: str  # e.g. 16.7.16

    def __str__(self) -> str:
        return f"{self.name} · {self.product_type} · iOS {self.ios_version}"

    def target(self) -> Target:
        platform, family = classify(self.product_type)
        return Target(
            ios_version=self.ios_version,
            platform=platform,
            device_family=family,
            udid=self.udid,
        )


class DeviceError(RuntimeError):
    pass


class DeviceSupportUnavailable(DeviceError):
    """pymobiledevice3 isn't installed."""


class DeviceConnectionError(DeviceError):
    """usbmux saw a device but could not establish lockdown."""


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

    async def discover() -> list[Device]:
        listed = list_devices()
        muxed_devices = (
            await asyncio.wait_for(listed, DISCOVERY_TIMEOUT)
            if inspect.isawaitable(listed)
            else listed
        )
        found: list[Device] = []
        for muxed in muxed_devices:
            udid = muxed.serial
            created = create_using_usbmux(serial=udid)
            lockdown = (
                await asyncio.wait_for(created, CONNECTION_TIMEOUT)
                if inspect.isawaitable(created)
                else created
            )
            try:
                values = lockdown.all_values
                found.append(
                    Device(
                        udid=udid,
                        name=values.get("DeviceName", "(unnamed)"),
                        product_type=values.get("ProductType", "?"),
                        ios_version=values.get("ProductVersion", "?"),
                    )
                )
            finally:
                closed = lockdown.close()
                if inspect.isawaitable(closed):
                    await closed
        return found

    try:
        return asyncio.run(discover())
    except TimeoutError as exc:
        raise DeviceConnectionError(
            "timed out connecting to the iOS device; unlock it, reconnect USB, "
            "and accept Trust This Computer if prompted"
        ) from exc
    except DeviceError:
        raise
    except Exception as exc:
        raise DeviceConnectionError(
            f"lost the iOS device connection: {exc}. Unlock and reconnect it, "
            "then try again"
        ) from exc


def get(udid: str) -> Device | None:
    return next((d for d in connected() if d.udid == udid), None)
