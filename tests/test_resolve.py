"""Tests for the binary search over a title's build history.

The probe is injected, so the search logic is verified without credentials,
without network, and against build histories shaped to hit the awkward cases.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from appfit import cache, resolve as resolve_mod
from appfit.devices import Target
from appfit.probe import BuildInfo
from appfit.resolve import (
    NoCompatibleBuild,
    date_hint,
    estimate_probes,
    metadata_probe,
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


def test_cache_is_keyed_by_platform():
    probe = FakeProbe(history(20, bump_at=10))
    ipad = Target.from_ios("16.7.16", "ipad")
    first = newest_compatible(BUNDLE, ipad.ios_version, probe.ids, probe, target=ipad)

    fresh = FakeProbe(history(20, bump_at=10))
    iphone = Target.from_ios("16.7.16", "iphone")
    second = newest_compatible(
        BUNDLE, iphone.ios_version, fresh.ids, fresh, target=iphone
    )

    assert first.external_version_id == second.external_version_id
    assert not second.from_cache
    assert fresh.calls


class FakeMetadataClient:
    def __init__(self, ids: list[str], start: date = date(2020, 1, 1)):
        self.releases = {
            version_id: start + timedelta(days=index)
            for index, version_id in enumerate(ids)
        }
        self.calls: list[str] = []

    def version_metadata(self, bundle_id: str, version_id: str) -> dict:
        self.calls.append(version_id)
        return {
            "display_version": f"v{version_id}",
            "release_date": self.releases[version_id].isoformat(),
        }


def test_date_hint_finds_last_build_before_cutoff():
    ids = [str(1000 + i) for i in range(370)]
    client = FakeMetadataClient(ids)
    hint = date_hint(client, BUNDLE, date(2020, 1, 1) + timedelta(days=350))

    assert hint(ids) == 349
    assert len(client.calls) <= 10


def test_date_seed_preserves_answer_and_reduces_downloads():
    builds = history(370, bump_at=350)
    baseline = FakeProbe(builds)
    expected = newest_compatible(
        BUNDLE, "16.7.16", baseline.ids, baseline, use_cache=False
    )

    seeded = FakeProbe(builds)
    client = FakeMetadataClient(seeded.ids)
    hint = date_hint(
        client,
        BUNDLE,
        date(2020, 1, 1) + timedelta(days=350),
    )
    actual = newest_compatible(
        BUNDLE,
        "16.7.16",
        seeded.ids,
        seeded,
        use_cache=False,
        hint=hint,
    )

    assert actual.external_version_id == expected.external_version_id
    assert len(seeded.calls) < len(baseline.calls)


def test_known_incompatible_latest_avoids_downloading_current_build():
    probe = FakeProbe(history(100, bump_at=80))
    latest = BuildInfo("17.0", "current", [], "store")

    result = newest_compatible(
        BUNDLE,
        "16.7.16",
        probe.ids,
        probe,
        use_cache=False,
        latest_info=latest,
    )

    assert result.external_version_id == "1079"
    assert probe.ids[-1] not in probe.calls


def test_fitting_hint_avoids_downloading_oldest_boundary():
    probe = FakeProbe(history(100, bump_at=80))
    latest = BuildInfo("17.0", "current", [], "store")

    result = newest_compatible(
        BUNDLE,
        "16.7.16",
        probe.ids,
        probe,
        use_cache=False,
        hint=lambda _: 70,
        latest_info=latest,
    )

    assert result.external_version_id == "1079"
    assert probe.ids[0] not in probe.calls


@pytest.mark.parametrize("hinted", [10, 200, 360, None])
def test_bad_or_missing_hint_never_changes_the_answer(hinted):
    builds = history(370, bump_at=350)
    probe = FakeProbe(builds)
    hint = (lambda _: hinted) if hinted is not None else (lambda _: None)

    result = newest_compatible(
        BUNDLE,
        "16.7.16",
        probe.ids,
        probe,
        use_cache=False,
        hint=hint,
    )

    assert result.external_version_id == "1349"


def test_date_hint_uses_cached_metadata():
    ids = [str(1000 + i) for i in range(32)]
    first = FakeMetadataClient(ids)
    cutoff = date(2020, 1, 16)
    assert date_hint(first, BUNDLE, cutoff)(ids) == 14
    assert first.calls

    second = FakeMetadataClient(ids)
    assert date_hint(second, BUNDLE, cutoff)(ids) == 14
    assert second.calls == []


def test_date_hint_degrades_to_none_when_metadata_fails():
    class BrokenClient:
        def version_metadata(self, bundle_id, version_id):
            raise RuntimeError("rate limited")

    hint = date_hint(BrokenClient(), BUNDLE, date(2020, 1, 1))
    assert hint(["1", "2", "3"]) is None


def test_metadata_probe_avoids_full_download_when_fields_are_exposed():
    class Client:
        compatibility_metadata_supported = None

        def version_metadata(self, bundle_id, version_id):
            self.compatibility_metadata_supported = True
            return {
                "display_version": "8.2",
                "release_date": "2023-01-01",
                "minimum_os": "16.0",
                "device_families": [1, 2],
            }

    fallback_calls = []
    probe = metadata_probe(
        Client(),
        BUNDLE,
        lambda version_id: fallback_calls.append(version_id),
    )

    info = probe("123")

    assert info == BuildInfo("16.0", "8.2", [1, 2], "metadata")
    assert fallback_calls == []


def test_metadata_probe_falls_back_after_client_reports_fields_unsupported():
    class Client:
        compatibility_metadata_supported = False

        def version_metadata(self, bundle_id, version_id):
            raise AssertionError("known unsupported client must not be called")

    expected = BuildInfo("16.0", "8.2", [1, 2], "ipa")
    fallback_calls = []

    def fallback(version_id):
        fallback_calls.append(version_id)
        return expected

    probe = metadata_probe(Client(), BUNDLE, fallback)

    assert probe("123") is expected
    assert fallback_calls == ["123"]
