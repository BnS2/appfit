from __future__ import annotations

import json
import os

import pytest

from appfit import cache


def test_schema_one_migration_preserves_expensive_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    legacy = {
        "schema": 1,
        "entries": {
            "com.example.app@16.7.16": {
                "bundle_id": "com.example.app",
                "ios_version": "16.7.16",
                "external_version_id": "123",
                "display_version": "8.2",
                "minimum_os": "16.0",
                "resolved_at": "2026-01-01T00:00:00+00:00",
            }
        },
    }
    (tmp_path / "cache.json").write_text(json.dumps(legacy))

    resolved = cache.get("com.example.app", "16.7.16", "ipad")

    assert resolved is not None
    assert resolved.external_version_id == "123"
    assert resolved.platform == "ipad"


def test_import_merges_without_overwriting_local_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    cache.record("com.example.app", "16.0", "local", "1.0", "15.0")
    incoming = {
        "schema": 2,
        "entries": {
            "com.example.app@16.0@ipad": {
                "bundle_id": "com.example.app",
                "ios_version": "16.0",
                "external_version_id": "remote",
                "display_version": "2.0",
                "minimum_os": "16.0",
                "resolved_at": "2026-01-01T00:00:00+00:00",
                "platform": "ipad",
            }
        },
        "versions": {
            "com.example.app": {
                "remote": {
                    "display_version": "2.0",
                    "release_date": "2024-01-01",
                }
            }
        },
    }

    added = cache.import_entries(incoming)

    assert added == (0, 1)
    assert cache.get("com.example.app", "16.0").external_version_id == "local"
    assert cache.get_version("com.example.app", "remote") is not None


def test_prune_candidates_protects_resolutions_and_ignores_unmanaged_files(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    ipa_dir = tmp_path / "ipa"
    ipa_dir.mkdir()
    cache.record("com.example.app", "16.0", "123", "1.0", "15.0")

    protected = ipa_dir / "com.example.app-123.ipa"
    stale = ipa_dir / "com.example.app-456.ipa"
    recent = ipa_dir / "com.example.app-789.ipa"
    unrelated = ipa_dir / "manually-named.ipa"
    for path in (protected, stale, recent, unrelated):
        path.write_bytes(path.name.encode())
    os.utime(protected, (100, 100))
    os.utime(stale, (100, 100))
    os.utime(unrelated, (100, 100))
    symlink = ipa_dir / "com.example.app-999.ipa"
    symlink.symlink_to(stale)

    candidates = cache.prune_candidates(
        ipa_dir,
        minimum_age_seconds=300,
        now=500,
    )

    assert [candidate.path.name for candidate in candidates] == [
        "com.example.app-456.ipa"
    ]


def test_prune_deletes_only_unchanged_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    ipa_dir = tmp_path / "ipa"
    ipa_dir.mkdir()
    stale = ipa_dir / "com.example.app-456.ipa"
    stale.write_bytes(b"stale")
    os.utime(stale, (100, 100))
    candidates = cache.prune_candidates(ipa_dir, minimum_age_seconds=0, now=500)

    removed = cache.prune_ipas(ipa_dir, candidates)

    assert removed == (1, 5)
    assert not stale.exists()


def test_prune_rechecks_cache_references_before_deleting(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    ipa_dir = tmp_path / "ipa"
    ipa_dir.mkdir()
    candidate = ipa_dir / "com.example.app-456.ipa"
    candidate.write_bytes(b"keep me")
    os.utime(candidate, (100, 100))
    plan = cache.prune_candidates(ipa_dir, minimum_age_seconds=0, now=500)

    cache.record("com.example.app", "16.0", "456", "1.0", "15.0")
    removed = cache.prune_ipas(ipa_dir, plan)

    assert removed == (0, 0)
    assert candidate.exists()


def test_prune_skips_a_file_replaced_after_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    ipa_dir = tmp_path / "ipa"
    ipa_dir.mkdir()
    candidate = ipa_dir / "com.example.app-456.ipa"
    candidate.write_bytes(b"old")
    os.utime(candidate, (100, 100))
    plan = cache.prune_candidates(ipa_dir, minimum_age_seconds=0, now=500)
    candidate.unlink()
    candidate.write_bytes(b"replacement")

    removed = cache.prune_ipas(ipa_dir, plan)

    assert removed == (0, 0)
    assert candidate.read_bytes() == b"replacement"


@pytest.mark.parametrize(
    "unsafe_cache",
    [
        "not json",
        json.dumps({"schema": 999, "entries": {}}),
        json.dumps({"schema": 2, "entries": ["not", "a", "mapping"]}),
    ],
)
def test_prune_fails_closed_when_cache_cannot_protect_references(
    tmp_path, monkeypatch, unsafe_cache
):
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    ipa_dir = tmp_path / "ipa"
    ipa_dir.mkdir()
    candidate = ipa_dir / "com.example.app-456.ipa"
    candidate.write_bytes(b"must survive")
    (tmp_path / "cache.json").write_text(unsafe_cache)

    with pytest.raises(cache.CacheSafetyError, match="cannot safely prune"):
        cache.prune_candidates(ipa_dir, minimum_age_seconds=0)

    assert candidate.exists()
