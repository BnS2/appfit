from __future__ import annotations

import os

from appfit import cache, cli
from appfit.apps import App
from appfit.devices import Target


def test_cached_resolve_skips_store_history_call(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    cache.record(
        "com.example.app",
        "16.7.16",
        "123",
        "8.2",
        "16.0",
        platform="ipad",
    )

    class Client:
        called = False

        def version_ids(self, bundle_id):
            self.called = True
            raise AssertionError("cache hit must not ask the store for history")

    client = Client()
    store_app = App(1, "com.example.app", "Example", "10.0", "17.0", "Example")

    result = cli._do_resolve(
        client,
        store_app,
        Target.from_ios("16.7.16", "ipad"),
        yes=True,
    )

    assert result.from_cache
    assert result.external_version_id == "123"
    assert not client.called


def test_cache_prune_is_dry_run_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "ipa_dir", lambda: tmp_path / "ipa")
    ipa_dir = tmp_path / "ipa"
    ipa_dir.mkdir()
    stale = ipa_dir / "com.example.app-456.ipa"
    stale.write_bytes(b"stale")
    os.utime(stale, (100, 100))

    cli.cache_prune(yes=False, min_age=0)

    output = capsys.readouterr().out
    assert "dry run" in output
    assert "com.example.app-456.ipa" in output
    assert stale.exists()


def test_cache_prune_yes_deletes_displayed_candidates(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "ipa_dir", lambda: tmp_path / "ipa")
    ipa_dir = tmp_path / "ipa"
    ipa_dir.mkdir()
    stale = ipa_dir / "com.example.app-456.ipa"
    stale.write_bytes(b"stale")
    os.utime(stale, (100, 100))

    cli.cache_prune(yes=True, min_age=0)

    output = capsys.readouterr().out
    assert "pruned 1 IPA file" in output
    assert not stale.exists()
