from __future__ import annotations

from appfit import store


def test_download_growth_does_not_double_count_temp_and_final_files(tmp_path):
    existing = tmp_path / "existing.ipa"
    existing.write_bytes(b"x" * 100)
    baseline = store._dir_snapshot(tmp_path)
    existing.write_bytes(b"x" * 110)
    (tmp_path / "download.tmp").write_bytes(b"x" * 50)
    (tmp_path / "download.ipa").write_bytes(b"x" * 40)

    assert store._dir_growth(tmp_path, baseline) == 50


def test_download_threads_platform_version_and_progress(tmp_path, monkeypatch):
    destination = tmp_path / "app.ipa"
    observed = {}

    def fake_run(args, timeout, watch, on_progress):
        observed.update(
            args=args,
            timeout=timeout,
            watch=watch,
            on_progress=on_progress,
        )
        destination.write_bytes(b"ipa")
        on_progress(3)
        return {"success": True}

    monkeypatch.setattr(store, "_run", fake_run)
    progress = []

    result = store.StoreClient().download(
        "com.example.app",
        destination,
        platform="iphone",
        version_id="123",
        purchase=True,
        on_progress=progress.append,
    )

    assert result == destination
    assert "--platform" in observed["args"]
    assert observed["args"][observed["args"].index("--platform") + 1] == "iphone"
    assert "--external-version-id" in observed["args"]
    assert "--purchase" in observed["args"]
    assert observed["watch"] == tmp_path
    assert progress == [3]


def test_version_metadata_parses_optional_compatibility_fields(monkeypatch):
    monkeypatch.setattr(
        store,
        "_run",
        lambda args, timeout: {
            "externalVersionID": "123",
            "displayVersion": "8.2",
            "releaseDate": "2023-01-01T00:00:00Z",
            "minimumOSVersion": "16.0",
            "deviceFamilies": [1, 2],
        },
    )
    client = store.StoreClient()

    result = client.version_metadata("com.example.app", "123")

    assert result["minimum_os"] == "16.0"
    assert result["device_families"] == [1, 2]
    assert client.compatibility_metadata_supported is True


def test_version_metadata_marks_released_ipatool_as_unsupported(monkeypatch):
    monkeypatch.setattr(
        store,
        "_run",
        lambda args, timeout: {
            "externalVersionID": "123",
            "displayVersion": "8.2",
            "releaseDate": "2023-01-01T00:00:00Z",
        },
    )
    client = store.StoreClient()

    result = client.version_metadata("com.example.app", "123")

    assert result["minimum_os"] == ""
    assert client.compatibility_metadata_supported is False
