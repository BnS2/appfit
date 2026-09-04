from __future__ import annotations

import plistlib
import zipfile
from pathlib import Path

import pytest

from appfit import accounts, cache, workflows
from appfit.apps import App
from appfit.devices import Target
from appfit.probe import BuildInfo
from appfit.store import Account, BuildNotServed, WrongAccount
from appfit.workflows import BuildWorkflow, WorkflowError, target_from_manual


APP = App(
    1,
    "com.example.app",
    "Example",
    "4.0",
    "18.0",
    "Example Company",
)


def write_ipa(path: Path, version: str, minimum_os: str, families=(1, 2)) -> None:
    payload = plistlib.dumps(
        {
            "CFBundleShortVersionString": version,
            "MinimumOSVersion": minimum_os,
            "UIDeviceFamily": list(families),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Payload/Example.app/Info.plist", payload)


class FakeClient:
    compatibility_metadata_supported = None

    def __init__(self) -> None:
        self.account = Account("owner@example.com")
        self.ids = ["100", "101", "102", "103"]
        self.info = {
            "100": ("1.0", "15.0", "2020-01-01"),
            "101": ("2.0", "16.0", "2021-01-01"),
            "102": ("3.0", "17.0", "2023-01-01"),
            "103": ("4.0", "18.0", "2024-01-01"),
        }
        self.claimed = False
        self.downloads: list[str] = []

    def active_account(self):
        return self.account

    def require_account(self, email):
        if email.lower() != self.account.email:
            raise WrongAccount("wrong account")
        return self.account

    def purchase(self, bundle_id):
        first = not self.claimed
        self.claimed = True
        return first

    def version_ids(self, bundle_id):
        return self.ids

    def version_metadata(self, bundle_id, version_id):
        version, minimum_os, released = self.info[version_id]
        self.compatibility_metadata_supported = True
        return {
            "external_version_id": version_id,
            "display_version": version,
            "release_date": released,
            "minimum_os": minimum_os,
            "device_families": [1, 2],
        }

    def download(
        self,
        bundle_id,
        destination,
        platform,
        version_id=None,
        on_progress=None,
        **_kwargs,
    ):
        self.downloads.append(version_id)
        version, minimum_os, _released = self.info[version_id]
        write_ipa(destination, version, minimum_os)
        if on_progress:
            on_progress(destination.stat().st_size)
        return destination


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(accounts, "config_dir", lambda: tmp_path)


def test_manual_target_accepts_editable_patch_version():
    target = target_from_manual(" 16.7.16 ", "ipad")
    assert target == Target.from_ios("16.7.16", "ipad")


def test_version_choice_label_identifies_the_exact_store_build():
    candidate = workflows.BuildCandidate(
        history_index=1,
        external_version_id="123456",
        display_version="2.0",
        release_date="2021-01-01",
        minimum_os="16.0",
        device_families=(1, 2),
        compatible=True,
        source="metadata",
    )

    assert candidate.choice_label.endswith("· build 123456")


@pytest.mark.parametrize("value", ["", "iOS 16", "16.x", "16..7"])
def test_manual_target_rejects_ambiguous_versions(value):
    with pytest.raises(WorkflowError, match="iOS version"):
        target_from_manual(value, "ipad")


def test_resolve_returns_recommended_build_and_history_position(tmp_path):
    client = FakeClient()
    workflow = BuildWorkflow(client, tmp_path / "ipa")
    events = []

    report = workflow.resolve(
        APP,
        Target.from_ios("16.7.16", "ipad"),
        client.account.email,
        claim_licence=True,
        on_progress=events.append,
    )

    assert report.recommended.display_version == "2.0"
    assert report.recommended.external_version_id == "101"
    assert report.recommended.history_index == 1
    assert report.recommended.compatible
    assert report.licence_claimed
    assert any(event.stage == "complete" for event in events)


def test_older_candidates_are_lazy_and_verified(tmp_path):
    client = FakeClient()
    workflow = BuildWorkflow(client, tmp_path / "ipa")
    report = workflow.resolve(
        APP,
        Target.from_ios("16.7.16", "ipad"),
        client.account.email,
        claim_licence=True,
    )
    downloads_before = list(client.downloads)

    older = workflow.older_candidates(report, limit=10)

    assert [candidate.display_version for candidate in older] == ["1.0"]
    assert all(candidate.compatible for candidate in older)
    assert client.downloads == downloads_before


def test_prepare_downloads_exact_selection_and_verifies_ipa(tmp_path):
    client = FakeClient()
    workflow = BuildWorkflow(client, tmp_path / "ipa")
    report = workflow.resolve(
        APP,
        Target.from_ios("16.7.16", "ipad"),
        client.account.email,
        claim_licence=True,
    )

    prepared = workflow.prepare(
        APP,
        report.target,
        client.account.email,
        report.recommended,
    )

    assert prepared.path.name == "com.example.app-101.ipa"
    assert prepared.candidate.display_version == "2.0"
    assert prepared.candidate.source == "ipa"
    assert "101" in client.downloads


def test_prepare_fails_closed_if_downloaded_build_does_not_fit(tmp_path):
    client = FakeClient()
    workflow = BuildWorkflow(client, tmp_path / "ipa")
    report = workflow.resolve(
        APP,
        Target.from_ios("16.7.16", "ipad"),
        client.account.email,
        claim_licence=True,
    )
    destination = tmp_path / "ipa" / "com.example.app-101.ipa"
    write_ipa(destination, "2.0", "17.0")

    with pytest.raises(WorkflowError, match="does not fit"):
        workflow.prepare(
            APP,
            report.target,
            client.account.email,
            report.recommended,
        )


def test_resolve_preserves_account_gate(tmp_path):
    workflow = BuildWorkflow(FakeClient(), tmp_path / "ipa")
    with pytest.raises(WorkflowError, match="wrong account"):
        workflow.resolve(
            APP,
            Target.from_ios("16.7.16", "ipad"),
            "someone-else@example.com",
            claim_licence=True,
        )


def test_exact_search_uses_identifier_resolution(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(
        workflows,
        "resolve_app",
        lambda term: observed.append(term) or APP,
    )
    monkeypatch.setattr(
        workflows,
        "search_apps",
        lambda *_args, **_kwargs: pytest.fail("must not fuzzy search an identifier"),
    )

    assert BuildWorkflow(FakeClient(), tmp_path).search(APP.bundle_id) == [APP]
    assert observed == [APP.bundle_id]


def test_login_terminal_script_contains_no_credentials_beyond_email(
    tmp_path, monkeypatch
):
    binary = tmp_path / "ipatool"
    binary.write_bytes(b"helper")
    binary.chmod(0o755)
    calls = []
    monkeypatch.setattr(workflows, "selected_ipatool", lambda: (binary, "test"))
    monkeypatch.setattr(
        workflows.subprocess,
        "Popen",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    script = workflows.launch_login_terminal("owner@example.com")

    contents = script.read_text()
    assert "owner@example.com" in contents
    assert "--password" not in contents
    assert "--auth-code" not in contents
    assert calls[0][0][:3] == ["open", "-a", "Terminal"]


def test_refused_current_build_recovers_history_from_a_known_build(monkeypatch):
    """A build the store will not serve must not take the history with it.

    The store carries the version list on whichever build it hands back, so the
    implicit "newest build" request fails as a unit. Any build appfit already
    recorded reaches the same list, and those older builds are the whole point
    of the tool.
    """
    client = FakeClient()

    def refuse(bundle_id):
        raise BuildNotServed("invalid response")

    client.version_ids = refuse
    client.version_ids_from = lambda bundle_id, seed: (
        client.ids if seed == "101" else []
    )
    cache.put_version("com.example.app", "101", "2.0", "2021-01-01", "16.0", [1, 2])

    events = []
    recovered = BuildWorkflow(client=client)._version_ids(APP, events.append)

    assert recovered == client.ids
    assert any("current build" in event.message for event in events)


def test_refusal_surfaces_when_no_known_build_can_reopen_the_history():
    client = FakeClient()

    def refuse(bundle_id):
        raise BuildNotServed("the App Store served no build for com.example.app.")

    client.version_ids = refuse
    client.version_ids_from = lambda bundle_id, seed: []

    with pytest.raises(WorkflowError) as failure:
        BuildWorkflow(client=client)._version_ids(APP, lambda _e: None)

    message = str(failure.value)
    assert message.startswith("Apple is not offering Example for download")
    assert "Your device is not the reason" in message


def test_a_build_the_store_refuses_is_never_recommended():
    refused = BuildInfo(
        minimum_os="",
        display_version="",
        device_families=[],
        source="unavailable",
        available=False,
    )

    assert refused.runs_on("18.0") is False
    assert refused.fits(Target.from_ios("18.0", "ipad")) is False
