from __future__ import annotations

from types import SimpleNamespace

import pytest

from appfit import devices
from appfit.devices import Device, Target, classify
from appfit.probe import BuildInfo


def test_device_derives_ipad_target():
    target = Device("u1", "Old iPad", "iPad6,11", "16.7.16").target()
    assert target == Target("16.7.16", "ipad", 2, "u1")


def test_device_derives_iphone_and_ipod_targets():
    assert classify("iPhone10,3") == ("iphone", 1)
    assert classify("iPod9,1") == ("iphone", 1)


def test_unknown_product_type_does_not_invent_a_family():
    assert classify("RealityDevice1,1") == ("ipad", None)


def test_build_family_is_part_of_fit():
    iphone_only = BuildInfo("16.0", "1.0", [1], "test")
    assert iphone_only.fits(Target.from_ios("16.7.16", "iphone"))
    assert not iphone_only.fits(Target.from_ios("16.7.16", "ipad"))


def test_unknown_build_family_does_not_reject():
    unknown = BuildInfo("16.0", "1.0", [], "metadata")
    assert unknown.fits(Target.from_ios("16.7.16", "ipad"))


def test_connected_adapts_async_pymobiledevice_backend(monkeypatch):
    class Lockdown:
        all_values = {
            "DeviceName": "Old iPad",
            "ProductType": "iPad6,11",
            "ProductVersion": "16.7.16",
        }

        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    lockdown = Lockdown()

    async def list_devices():
        return [SimpleNamespace(serial="udid-1")]

    async def create_using_usbmux(serial):
        assert serial == "udid-1"
        return lockdown

    monkeypatch.setattr(
        devices,
        "_require_backend",
        lambda: (create_using_usbmux, list_devices),
    )

    assert devices.connected() == [
        Device("udid-1", "Old iPad", "iPad6,11", "16.7.16")
    ]
    assert lockdown.closed


def test_connected_wraps_lockdown_socket_failure(monkeypatch):
    async def list_devices():
        return [SimpleNamespace(serial="udid-1")]

    async def create_using_usbmux(serial):
        raise RuntimeError("socket connection broken")

    monkeypatch.setattr(
        devices,
        "_require_backend",
        lambda: (create_using_usbmux, list_devices),
    )

    with pytest.raises(devices.DeviceConnectionError, match="socket connection broken"):
        devices.connected()
