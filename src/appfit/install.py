"""Install an App Store IPA on a connected stock iOS device.

pymobiledevice3's InstallationProxyService owns the AFC upload and install
protocol. This module deliberately stays a thin seam around it so the rest of
appfit can be tested without USB hardware.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Callable

from .devices import DeviceSupportUnavailable


class InstallError(RuntimeError):
    pass


def _require_backend():
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.installation_proxy import (
            InstallationProxyService,
        )
    except ImportError as exc:
        raise DeviceSupportUnavailable(
            "USB device support needs pymobiledevice3:\n"
            "  pip install 'appfit[device]'"
        ) from exc
    return create_using_usbmux, InstallationProxyService


def install(
    udid: str,
    ipa_path: Path,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    """Upload and install ``ipa_path`` on ``udid``.

    The IPA remains FairPlay-bound to the Apple ID that obtained it. The CLI's
    account gate is therefore not just purchase-history hygiene: it is required
    for the installed app to launch.
    """
    create_using_usbmux, InstallationProxyService = _require_backend()

    ipa_path = Path(ipa_path)
    if not ipa_path.is_file():
        raise InstallError(f"IPA does not exist: {ipa_path}")

    async def run() -> None:
        lockdown = None
        try:
            created = create_using_usbmux(serial=udid)
            lockdown = (
                await asyncio.wait_for(created, 15)
                if inspect.isawaitable(created)
                else created
            )
            service = InstallationProxyService(lockdown)

            def progress(percent: int, *_backend_args) -> None:
                # pymobiledevice3 11.x currently forwards an internal empty
                # args tuple as a second positional argument. Keep appfit's
                # public callback stable at one integer.
                if on_progress is not None:
                    on_progress(percent)

            installed = service.install_from_local(
                str(ipa_path),
                handler=progress if on_progress is not None else None,
            )
            if inspect.isawaitable(installed):
                await installed
        finally:
            if lockdown is not None and hasattr(lockdown, "close"):
                try:
                    closed = lockdown.close()
                    if inspect.isawaitable(closed):
                        await closed
                except Exception:
                    pass

    try:
        asyncio.run(run())
    except Exception as exc:
        raise InstallError(f"could not install on {udid}: {exc}") from exc
