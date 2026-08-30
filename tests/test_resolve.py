"""Tests for the binary search over a title's build history.

The probe is injected, so the search logic is verified without credentials,
without network, and against build histories shaped to hit the awkward cases.
"""

from __future__ import annotations

import pytest

from appfit import cache, resolve as resolve_mod
from appfit.probe import BuildInfo
from appfit.resolve import (
    NoCompatibleBuild,
    estimate_probes,
    newest_compatible,
)

BUNDLE = "com.amazon.aiv.AIVApp"


class FakeProbe:
    """A probe over a synthetic history of (version_id, min_os)."""

    def __init__(self, history: list[tuple[str, str]]) -> None:
        self.history = dict(history)
        self.ids = [vid for vid, _ in history]
        self.calls: list[str] = []

    def __call__(self, version_id: str) -> BuildInfo:
        self.calls.append(version_id)
        return BuildInfo(
            minimum_os=self.history[version_id],
            display_version=f"v{version_id}",
            device_families=[1, 2],
            source="test",
        )


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Keep tests off the real ~/.config cache."""
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(resolve_mod.cache, "config_dir", lambda: tmp_path)
    yield


def history(count: int, bump_at: int, low: str = "16.0", high: str = "17.0"):
    """`count` builds, minimum OS jumping from `low` to `high` at index `bump_at`."""
    return [(f"{1000 + i}", low if i < bump_at else high) for i in range(count)]


def test_finds_last_build_before_the_bump():
    probe = FakeProbe(history(370, bump_at=350))
    result = newest_compatible(BUNDLE, "16.7.16", probe.ids, probe)
    assert result.external_version_id == "1349"
    assert result.minimum_os == "16.0"


def test_search_is_logarithmic_not_linear():
    """The whole reason for binary search: ~370 builds must not mean 370
    downloads, because each probe here is a real IPA."""
    probe = FakeProbe(history(370, bump_at=350))
    newest_compatible(BUNDLE, "16.7.16", probe.ids, probe)
    assert len(probe.calls) <= estimate_probes(370)
    assert len(probe.calls) < 20


def test_returns_latest_when_current_build_already_runs():
    probe = FakeProbe(history(370, bump_at=350))
    result = newest_compatible(BUNDLE, "18.0", probe.ids, probe)
    assert result.external_version_id == "1369"
    assert len(probe.calls) == 1


def test_raises_when_no_build_ever_supported_the_device():
    """The trap that started this project: say so instead of implying a version."""
    probe = FakeProbe(history(50, bump_at=0, high="17.0"))
    with pytest.raises(NoCompatibleBuild, match="never shipped"):
        newest_compatible(BUNDLE, "16.7.16", probe.ids, probe)


def test_handles_a_single_build_history():
    probe = FakeProbe([("1000", "16.0")])
    result = newest_compatible(BUNDLE, "16.7.16", probe.ids, probe)
    assert result.external_version_id == "1000"


def test_forward_scan_catches_a_lowered_deployment_target():
    """A developer raising then lowering min OS breaks the monotonicity the
    binary search assumes; the forward scan is what recovers the newer build."""
    builds = history(100, bump_at=60)
    builds[60] = ("1060", "17.0")
    builds[61] = ("1061", "16.0")  # dipped back down
    probe = FakeProbe(builds)
    result = newest_compatible(BUNDLE, "16.7.16", probe.ids, probe)
    assert result.external_version_id == "1061"


def test_probe_is_never_called_twice_for_the_same_build():
    """Each repeat would be another multi-hundred-megabyte download."""
    probe = FakeProbe(history(370, bump_at=350))
    newest_compatible(BUNDLE, "16.7.16", probe.ids, probe)
    assert len(probe.calls) == len(set(probe.calls))


def test_second_resolve_hits_the_cache_and_probes_nothing():
    first_probe = FakeProbe(history(370, bump_at=350))
    first = newest_compatible(BUNDLE, "16.7.16", first_probe.ids, first_probe)

    second_probe = FakeProbe(history(370, bump_at=350))
    second = newest_compatible(BUNDLE, "16.7.16", second_probe.ids, second_probe)

    assert second.from_cache
    assert second.external_version_id == first.external_version_id
    assert second_probe.calls == []


def test_no_cache_flag_forces_a_fresh_search():
    probe = FakeProbe(history(370, bump_at=350))
    newest_compatible(BUNDLE, "16.7.16", probe.ids, probe)

    fresh = FakeProbe(history(370, bump_at=350))
    result = newest_compatible(BUNDLE, "16.7.16", fresh.ids, fresh, use_cache=False)
    assert not result.from_cache
    assert fresh.calls != []


def test_cache_is_keyed_by_ios_version():
    """A different device must not inherit another device's answer."""
    # Three tiers: builds 0-99 need iOS 15, 100-199 need 16, 200+ need 17.
    tiers = [
        (f"{1000 + i}", "15.0" if i < 100 else "16.0" if i < 200 else "17.0")
        for i in range(300)
    ]

    newer = FakeProbe(tiers)
    on_16 = newest_compatible(BUNDLE, "16.7.16", newer.ids, newer)
    assert on_16.external_version_id == "1199"

    older = FakeProbe(tiers)
    on_15 = newest_compatible(BUNDLE, "15.8.3", older.ids, older)
    assert not on_15.from_cache
    assert on_15.external_version_id == "1099"
