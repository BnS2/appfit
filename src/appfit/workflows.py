"""GUI-safe orchestration for finding, downloading, and installing builds.

The command line originally owned this orchestration and mixed domain failures
with Typer output.  This module keeps the synchronous backend (which is useful
for both CLI and desktop worker threads) while returning structured results and
progress events that any presentation layer can render.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from . import accounts, cache, devices
from .apps import App, resolve as resolve_app, search as search_apps
from .install import InstallError, install as install_ipa
from .ios_releases import successors
from .probe import BuildInfo, ProbeFailed, from_ipa_file, version_tuple
from .resolve import (
    NoCompatibleBuild,
    date_hint,
    download_probe,
    estimate_probes,
    metadata_probe,
    newest_compatible,
)
from .store import IpatoolMissing, StoreClient, StoreError
from .toolchain import selected_ipatool

IOS_VERSION = re.compile(r"^\d+(?:\.\d+){0,3}$")
_BUNDLE_ID = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")
_STORE_URL = re.compile(r"/id\d+")


class WorkflowError(RuntimeError):
    """An actionable failure safe to present in either CLI or GUI."""


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    message: str
    current: int | None = None
    total: int | None = None


@dataclass(frozen=True)
class BuildCandidate:
    history_index: int
    external_version_id: str
    display_version: str
    release_date: str
    minimum_os: str
    device_families: tuple[int, ...]
    compatible: bool
    source: str
    recommended: bool = False

    @property
    def label(self) -> str:
        version = self.display_version or f"build {self.external_version_id}"
        detail = f"requires iOS {self.minimum_os}"
        if self.release_date:
            detail += f" · {self.release_date}"
        return f"{version} — {detail}"

    @property
    def choice_label(self) -> str:
        """Unambiguous label for a control that selects one exact store build."""
        return f"{self.label} · build {self.external_version_id}"


@dataclass(frozen=True)
class ResolutionReport:
    app: App
    target: devices.Target
    version_ids: tuple[str, ...]
    recommended: BuildCandidate
    probes: int
    from_cache: bool
    source: str
    licence_claimed: bool

    @property
    def current_compatible(self) -> bool:
        return version_tuple(self.app.minimum_os) <= version_tuple(
            self.target.ios_version
        )


@dataclass(frozen=True)
class PreparedIPA:
    app: App
    target: devices.Target
    candidate: BuildCandidate
    path: Path
    reused: bool


ProgressCallback = Callable[[ProgressEvent], None]


def _ignore_progress(_event: ProgressEvent) -> None:
    pass


def validate_ios_version(value: str) -> str:
    """Return a trimmed manual target version or raise an actionable error."""
    value = value.strip()
    if not IOS_VERSION.fullmatch(value):
        raise WorkflowError(
            "Enter an iOS version such as 16, 16.7, or 16.7.16."
        )
    return value


def target_from_manual(ios_version: str, platform: str) -> devices.Target:
    ios_version = validate_ios_version(ios_version)
    if platform not in {"ipad", "iphone"}:
        raise WorkflowError("Choose either iPad or iPhone.")
    return devices.Target.from_ios(ios_version, platform)


def ipa_dir() -> Path:
    directory = accounts.config_dir() / "ipa"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class BuildWorkflow:
    """Synchronous application service intended to run in a worker thread."""

    def __init__(
        self,
        client: StoreClient | None = None,
        directory: Path | None = None,
    ) -> None:
        self.client = client or StoreClient()
        self.directory = Path(directory) if directory else ipa_dir()

    def active_account(self):
        return self.client.active_account()

    def search(self, term: str, limit: int = 10) -> list[App]:
        term = term.strip()
        if not term:
            return []
        try:
            if term.isdigit() or _BUNDLE_ID.fullmatch(term) or _STORE_URL.search(term):
                return [resolve_app(term)]
            return search_apps(term, limit=limit)
        except Exception as exc:  # requests errors become presentation-safe.
            raise WorkflowError(f"App Store search failed: {exc}") from exc

    def connected_devices(self) -> list[devices.Device]:
        try:
            return devices.connected()
        except devices.DeviceError as exc:
            raise WorkflowError(str(exc)) from exc

    def resolve(
        self,
        app: App,
        target: devices.Target,
        account: str,
        *,
        claim_licence: bool,
        on_progress: ProgressCallback | None = None,
    ) -> ResolutionReport:
        """Find the newest compatible build and retain its history position."""
        report = on_progress or _ignore_progress
        try:
            self.client.require_account(account)
            claimed = self.client.purchase(app.bundle_id) if claim_licence else False
            report(
                ProgressEvent(
                    "licence",
                    (
                        "Licence claimed"
                        if claimed
                        else "Licence already held"
                        if claim_licence
                        else "Licence check skipped"
                    ),
                )
            )
            version_ids = self.client.version_ids(app.bundle_id)
        except (IpatoolMissing, StoreError) as exc:
            raise WorkflowError(str(exc)) from exc

        if not version_ids:
            raise WorkflowError(f"The store lists no builds for {app.bundle_id}.")

        cached = cache.get(app.bundle_id, target.ios_version, target.platform)
        if cached is None:
            report(
                ProgressEvent(
                    "resolve",
                    f"Checking up to about {estimate_probes(len(version_ids))} "
                    f"of {len(version_ids)} historical builds",
                    0,
                    estimate_probes(len(version_ids)),
                )
            )

        try:
            cutoffs = successors(target.ios_version, count=1)
            hint = None
            if cutoffs:
                hint = date_hint(
                    self.client,
                    app.bundle_id,
                    cutoffs[0],
                    on_step=lambda number, message: report(
                        ProgressEvent("date", message, number)
                    ),
                )
            full_probe = download_probe(
                self.client,
                app.bundle_id,
                self.directory,
                target.platform,
                on_progress=lambda current: report(
                    ProgressEvent("download", "Downloading candidate build", current)
                ),
            )
            resolution = newest_compatible(
                app.bundle_id,
                target.ios_version,
                version_ids,
                probe=metadata_probe(self.client, app.bundle_id, full_probe),
                on_probe=lambda number, message: report(
                    ProgressEvent("probe", message, number)
                ),
                hint=hint,
                target=target,
                latest_info=BuildInfo(
                    minimum_os=app.minimum_os,
                    display_version=app.current_version,
                    device_families=[],
                    source="store",
                ),
            )
        except (NoCompatibleBuild, ProbeFailed, StoreError) as exc:
            raise WorkflowError(str(exc)) from exc

        try:
            winner_index = version_ids.index(resolution.external_version_id)
        except ValueError as exc:
            raise WorkflowError("The resolved build disappeared from store history.") from exc

        meta = cache.get_version(app.bundle_id, resolution.external_version_id)
        candidate = BuildCandidate(
            history_index=winner_index,
            external_version_id=resolution.external_version_id,
            display_version=resolution.display_version,
            release_date=meta.release_date if meta else "",
            minimum_os=resolution.minimum_os,
            device_families=tuple(meta.device_families if meta else []),
            compatible=True,
            source=resolution.source,
            recommended=True,
        )
        report(ProgressEvent("complete", f"Recommended {candidate.label}"))
        return ResolutionReport(
            app=app,
            target=target,
            version_ids=tuple(version_ids),
            recommended=candidate,
            probes=resolution.probes,
            from_cache=resolution.from_cache,
            source=resolution.source,
            licence_claimed=claimed,
        )

    def older_candidates(
        self,
        result: ResolutionReport,
        *,
        before_index: int | None = None,
        limit: int = 10,
        on_progress: ProgressCallback | None = None,
    ) -> list[BuildCandidate]:
        """Verify a small page of older builds, newest first.

        Every row is probed before display.  With appfit's patched helper this is
        a cheap partial-ZIP metadata request; an ordinary helper may need a full
        IPA, so callers should request only a small page.
        """
        if limit < 1:
            return []
        report = on_progress or _ignore_progress
        start = (
            result.recommended.history_index - 1
            if before_index is None
            else min(before_index - 1, result.recommended.history_index - 1)
        )
        if start < 0:
            return []

        full_probe = download_probe(
            self.client,
            result.app.bundle_id,
            self.directory,
            result.target.platform,
            on_progress=lambda current: report(
                ProgressEvent("download", "Downloading candidate build", current)
            ),
        )
        probe = metadata_probe(self.client, result.app.bundle_id, full_probe)
        candidates: list[BuildCandidate] = []
        for index in range(start, max(-1, start - limit), -1):
            version_id = result.version_ids[index]
            try:
                info = probe(version_id)
            except (ProbeFailed, StoreError) as exc:
                raise WorkflowError(str(exc)) from exc
            meta = cache.get_version(result.app.bundle_id, version_id)
            candidate = BuildCandidate(
                history_index=index,
                external_version_id=version_id,
                display_version=info.display_version,
                release_date=meta.release_date if meta else "",
                minimum_os=info.minimum_os,
                device_families=tuple(info.device_families),
                compatible=info.fits(result.target),
                source=info.source,
            )
            candidates.append(candidate)
            report(
                ProgressEvent(
                    "versions",
                    candidate.label,
                    len(candidates),
                    min(limit, start + 1),
                )
            )
        return candidates

    def prepare(
        self,
        app: App,
        target: devices.Target,
        account: str,
        candidate: BuildCandidate,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> PreparedIPA:
        """Download and authoritatively verify the selected store build."""
        report = on_progress or _ignore_progress
        try:
            self.client.require_account(account)
            self.client.purchase(app.bundle_id)
        except (IpatoolMissing, StoreError) as exc:
            raise WorkflowError(str(exc)) from exc

        destination = self.directory / (
            f"{app.bundle_id}-{candidate.external_version_id}.ipa"
        )
        reused = destination.exists()
        try:
            if not reused:
                self.client.download(
                    app.bundle_id,
                    destination,
                    platform=target.platform,
                    version_id=candidate.external_version_id,
                    on_progress=lambda current: report(
                        ProgressEvent("download", "Downloading selected build", current)
                    ),
                )
            info = from_ipa_file(destination)
        except (StoreError, ProbeFailed) as exc:
            raise WorkflowError(str(exc)) from exc

        if not info.fits(target):
            raise WorkflowError(
                f"Downloaded {info.display_version or candidate.display_version} does "
                f"not fit {target.platform} on iOS {target.ios_version}; it requires "
                f"iOS {info.minimum_os} and device families "
                f"{info.device_families or 'unknown'}."
            )
        verified = replace(
            candidate,
            display_version=info.display_version or candidate.display_version,
            minimum_os=info.minimum_os,
            device_families=tuple(info.device_families),
            compatible=True,
            source="ipa",
        )
        report(ProgressEvent("verify", f"Verified {verified.label}"))
        return PreparedIPA(app, target, verified, destination, reused)

    def install(
        self,
        prepared: PreparedIPA,
        udid: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        report = on_progress or _ignore_progress
        try:
            install_ipa(
                udid,
                prepared.path,
                on_progress=lambda percent: report(
                    ProgressEvent("install", f"Installing {percent}%", percent, 100)
                ),
            )
        except (devices.DeviceError, InstallError) as exc:
            raise WorkflowError(str(exc)) from exc

    def claim(self, app: App, account: str) -> bool:
        try:
            self.client.require_account(account)
            return self.client.purchase(app.bundle_id)
        except (IpatoolMissing, StoreError) as exc:
            raise WorkflowError(str(exc)) from exc


def launch_login_terminal(email: str) -> Path:
    """Open ipatool's password/2FA prompt in Terminal without capturing it."""
    email = email.strip()
    if not email or "\n" in email or "\r" in email:
        raise WorkflowError("Enter a valid Apple ID email address.")
    binary, _source = selected_ipatool()
    if binary is None:
        raise WorkflowError(str(IpatoolMissing()))

    script = accounts.config_dir() / "sign-in.command"
    command = " ".join(
        [shlex.quote(str(binary)), "auth", "login", "-e", shlex.quote(email)]
    )
    script.write_text(
        "#!/bin/zsh\n"
        "script_path=$0\n"
        "rm -f -- \"$script_path\"\n"
        f"{command}\n"
        "status=$?\n"
        "echo\n"
        "if [ $status -eq 0 ]; then\n"
        "  echo 'Sign-in complete. You can return to appfit.'\n"
        "else\n"
        "  echo 'Sign-in failed. Review the message above.'\n"
        "fi\n"
        "read -k 1 '?Press any key to close this window.'\n"
        "exit $status\n"
    )
    script.chmod(0o700)
    try:
        subprocess.Popen(
            ["open", "-a", "Terminal", str(script)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise WorkflowError(f"Could not open Terminal: {exc}") from exc
    return script
