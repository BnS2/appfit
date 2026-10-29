from __future__ import annotations

import hashlib
import ssl
import sys
from collections import namedtuple

import pytest

from appfit import _bundle_check


@pytest.fixture
def supported_runtime(monkeypatch):
    version = namedtuple("Version", "major minor micro releaselevel serial")
    monkeypatch.setattr(sys, "version_info", version(3, 12, 16, "final", 0))
    monkeypatch.setattr(_bundle_check.certifi, "__version__", "2026.10.23")
    return version


def test_current_bundle_runtime_and_ca_store_pass(supported_runtime):
    result = _bundle_check.check()
    assert result["python"] == "3.12.16"
    assert result["certifi"] == "2026.10.23"
    assert len(result["ca_sha256"]) == 64


@pytest.mark.parametrize("version,level", [
    ((3, 12, 15), "final"),
    ((3, 13, 12), "final"),
    ((3, 14, 10), "final"),
    ((3, 12, 16), "candidate"),
])
def test_builder_requires_the_patched_312_baseline(monkeypatch, supported_runtime, version, level):
    monkeypatch.setattr(sys, "version_info", supported_runtime(*version, level, 0))
    with pytest.raises(RuntimeError, match="Python 3.12.16"):
        _bundle_check.check()


@pytest.mark.parametrize("version", ["2026.7.22", "2026.10.18", "2026.10.19rc1"])
def test_builder_rejects_old_or_prerelease_certifi(monkeypatch, supported_runtime, version):
    monkeypatch.setattr(_bundle_check.certifi, "__version__", version)
    with pytest.raises(RuntimeError, match="certifi 2026.10.19"):
        _bundle_check.check()


def test_declared_version_does_not_hide_a_distrusted_root(monkeypatch, supported_runtime):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=_bundle_check.certifi.where())
    root = context.get_ca_certs(binary_form=True)[0]
    monkeypatch.setattr(_bundle_check, "_DISTRUSTED_ROOTS", {hashlib.sha256(root).hexdigest()})
    with pytest.raises(RuntimeError, match="distrusted emSign"):
        _bundle_check.check()
