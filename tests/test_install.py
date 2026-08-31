from __future__ import annotations

from pathlib import Path

import pytest

from appfit import install as install_mod


class FakeLockdown:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeService:
    instances = []

    def __init__(self, lockdown):
        self.lockdown = lockdown
        self.path = None
        type(self).instances.append(self)

    def install_from_local(self, path, handler=None):
        self.path = path
        if handler:
            handler(25)
            handler(100)


class ExtraArgumentService(FakeService):
    def install_from_local(self, path, handler=None):
        self.path = path
        if handler:
            handler(25, ())
            handler(100, ())


def test_installs_through_proxy_and_reports_progress(tmp_path, monkeypatch):
    ipa = tmp_path / "app.ipa"
    ipa.write_bytes(b"placeholder")
    lockdown = FakeLockdown()
    monkeypatch.setattr(
        install_mod,
        "_require_backend",
        lambda: (lambda serial: lockdown, FakeService),
    )
    progress = []

    install_mod.install("udid-1", ipa, progress.append)

    assert FakeService.instances[-1].path == str(ipa)
    assert progress == [25, 100]
    assert lockdown.closed


def test_normalizes_backend_progress_extra_argument(tmp_path, monkeypatch):
    ipa = tmp_path / "app.ipa"
    ipa.write_bytes(b"placeholder")
    monkeypatch.setattr(
        install_mod,
        "_require_backend",
        lambda: (lambda serial: FakeLockdown(), ExtraArgumentService),
    )
    progress = []

    install_mod.install("udid-1", ipa, progress.append)

    assert progress == [25, 100]


def test_refuses_missing_ipa(tmp_path, monkeypatch):
    monkeypatch.setattr(
        install_mod,
        "_require_backend",
        lambda: (lambda serial: FakeLockdown(), FakeService),
    )
    with pytest.raises(install_mod.InstallError, match="does not exist"):
        install_mod.install("udid-1", tmp_path / "missing.ipa")


def test_wraps_backend_failure_and_closes_device(tmp_path, monkeypatch):
    class BrokenService(FakeService):
        def install_from_local(self, path, handler=None):
            raise RuntimeError("device refused package")

    ipa = tmp_path / "app.ipa"
    ipa.write_bytes(b"placeholder")
    lockdown = FakeLockdown()
    monkeypatch.setattr(
        install_mod,
        "_require_backend",
        lambda: (lambda serial: lockdown, BrokenService),
    )

    with pytest.raises(install_mod.InstallError, match="device refused package"):
        install_mod.install("udid-1", ipa)
    assert lockdown.closed


def test_adapts_async_pymobiledevice_backend(tmp_path, monkeypatch):
    class AsyncLockdown:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    class AsyncService:
        def __init__(self, lockdown):
            self.lockdown = lockdown

        async def install_from_local(self, path, handler=None):
            if handler:
                handler(100)

    ipa = tmp_path / "app.ipa"
    ipa.write_bytes(b"placeholder")
    lockdown = AsyncLockdown()

    async def create(serial):
        return lockdown

    monkeypatch.setattr(
        install_mod,
        "_require_backend",
        lambda: (create, AsyncService),
    )
    progress = []

    install_mod.install("udid-1", ipa, progress.append)

    assert progress == [100]
    assert lockdown.closed
