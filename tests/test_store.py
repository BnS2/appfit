from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_empty_store_response_becomes_a_distinct_recoverable_failure(monkeypatch):
    """Apple reports "I will not serve this build" as a success with no package.

    ipatool renders that as the bare word "invalid response"; appfit has to be
    able to tell it apart from a genuine store error, because it is the one
    failure another build of the same app can recover from.
    """

    def fake_selected():
        return Path("/usr/bin/true"), "test"

    monkeypatch.setattr(store, "selected_ipatool", fake_selected)
    monkeypatch.setattr(
        store.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            stdout='{"level":"error","error":"invalid response","success":false}',
            stderr="",
            returncode=1,
        ),
    )

    with pytest.raises(store.BuildNotServed):
        store._run(["list-versions", "-b", "com.example.app"])


def test_refused_history_explains_itself_instead_of_repeating_ipatool(monkeypatch):
    def refuse(args, timeout):
        raise store.BuildNotServed("invalid response")

    monkeypatch.setattr(store, "_run", refuse)

    with pytest.raises(store.BuildNotServed) as failure:
        store.StoreClient().version_ids("com.example.app")

    message = str(failure.value)
    assert "com.example.app" in message
    assert "no package" in message
    assert "version history" in message


def test_history_can_be_read_off_one_known_build(monkeypatch):
    monkeypatch.setattr(
        store,
        "_run",
        lambda args, timeout: {"externalVersionIdentifiers": [100, 101, 102]},
    )

    assert store.StoreClient().version_ids_from("com.example.app", "101") == [
        "100",
        "101",
        "102",
    ]


def test_auth_code_demand_becomes_a_distinct_failure(monkeypatch):
    """ipatool's silent re-login cannot ask for a code.

    Treated as an ordinary error, every retry sent another "Allow" prompt to
    the account's devices, so callers need to recognise it and stop.
    """
    monkeypatch.setattr(
        store, "selected_ipatool", lambda: (Path("/usr/bin/true"), "test")
    )
    monkeypatch.setattr(
        store.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            stdout='{"level":"error","error":"auth code is required","success":false}',
            stderr="",
            returncode=1,
        ),
    )

    with pytest.raises(store.AuthCodeRequired) as failure:
        store.StoreClient().purchase("com.example.app")

    assert "six-digit code" in str(failure.value)


def test_interactive_purchase_leaves_the_terminal_to_ipatool(monkeypatch):
    calls = []
    monkeypatch.setattr(
        store, "selected_ipatool", lambda: (Path("/usr/bin/ipatool"), "test")
    )
    monkeypatch.setattr(
        store.subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs))
        or SimpleNamespace(returncode=0),
    )

    assert store.purchase_interactively("com.example.app") == 0

    argv, kwargs = calls[0]
    assert argv == ["/usr/bin/ipatool", "purchase", "-b", "com.example.app"]
    assert "--non-interactive" not in argv
    assert "capture_output" not in kwargs


def test_gui_purchase_sends_the_code_only_over_stdin(monkeypatch):
    observed = {}

    def fake_run(args, timeout, stdin_text):
        observed.update(args=args, timeout=timeout, stdin_text=stdin_text)
        return {"alreadyOwned": False}

    monkeypatch.setattr(store, "_run", fake_run)

    claimed = store.StoreClient().purchase_with_auth_code(
        "com.example.app", "123456"
    )

    assert claimed is True
    assert observed["args"] == [
        "purchase",
        "-b",
        "com.example.app",
        "--auth-code-stdin",
    ]
    assert "123456" not in observed["args"]
    assert observed["stdin_text"] == "123456\n"


@pytest.mark.parametrize("code", ["", "12345", "1234567", "12 345", "abcdef"])
def test_gui_purchase_rejects_malformed_codes_before_ipatool(code, monkeypatch):
    monkeypatch.setattr(
        store,
        "_run",
        lambda *args, **kwargs: pytest.fail("malformed code reached ipatool"),
    )

    with pytest.raises(store.StoreError, match="six-digit"):
        store.StoreClient().purchase_with_auth_code("com.example.app", code)
