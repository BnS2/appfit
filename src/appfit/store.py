"""Authenticated App Store operations, delegated to the `ipatool` binary.

Why not speak the protocol directly: Apple signs these requests. The endpoints
come from a "bag" config (init.itunes.apple.com/bag.xml) rather than fixed
hostnames, and unsigned POSTs to the authenticate endpoint return a bare HTTP
403 with an empty body -- verified from both python-requests and curl, so it is
not a TLS-fingerprint issue. ipatool implements the signing and is maintained,
so appfit drives it instead of racing Apple's changes.

The cost of this choice: ipatool never exposes the signed IPA download URL, so
the HTTP-Range probe in probe.py cannot be pointed at Apple. appfit's managed
helper exposes compatibility values from ipatool's own partial ZIP read; an
ordinary upstream binary remains supported through a full-IPA fallback.

Account handling: ipatool stores exactly one session at a time. appfit
refuses to act when the signed-in account is not the one paired to the target
device, rather than silently claiming a licence on the wrong Apple ID.
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .toolchain import selected_ipatool

# How often the download watcher reports bytes-on-disk.
PROGRESS_INTERVAL = 0.5


class StoreError(RuntimeError):
    pass


class IpatoolMissing(StoreError):
    def __init__(self) -> None:
        super().__init__(
            "ipatool is not installed. Install appfit's optimized helper with:\n"
            "  appfit ipatool install\n"
            "or use the ordinary release with:\n"
            "  brew install ipatool"
        )


class WrongAccount(StoreError):
    """The signed-in Apple ID is not the one this device is paired to."""


@dataclass
class Account:
    email: str
    name: str = ""

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>" if self.name else self.email


def _dir_snapshot(directory: Path) -> dict[Path, int]:
    """File sizes in a directory, ignoring races with the download writer."""
    sizes = {}
    try:
        for entry in directory.iterdir():
            try:
                if entry.is_file():
                    sizes[entry] = entry.stat().st_size
            except OSError:
                continue
    except OSError:
        return {}
    return sizes


def _dir_growth(directory: Path, baseline: dict[Path, int]) -> int:
    """Largest single-file growth since baseline.

    ipatool may briefly keep both a temporary file and the final destination.
    Summing the directory double-counts that handoff; the largest individual
    growth tracks the one download without inflating the displayed byte count.
    """
    current = _dir_snapshot(directory)
    return max(
        (max(0, size - baseline.get(path, 0)) for path, size in current.items()),
        default=0,
    )


def _run_watched(
    argv: list[str], watch: Path, on_progress: Callable[[int], None], timeout: int
) -> tuple[str, str, int]:
    """Run ipatool while reporting bytes landing in `watch`.

    ipatool gives no machine-readable progress under --format json, and we do not
    want to parse its human progress bar. Watching the destination directory grow
    works whatever it names its in-flight file, which matters because a 300 MB
    download with no output at all reads as a hang.
    """
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    baseline = _dir_snapshot(watch)
    stop = threading.Event()

    def poll() -> None:
        high_water = 0
        while not stop.wait(PROGRESS_INTERVAL):
            current = _dir_growth(watch, baseline)
            if current > high_water:
                high_water = current
                on_progress(high_water)

    watcher = threading.Thread(target=poll, daemon=True)
    watcher.start()
    try:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
    finally:
        stop.set()
        watcher.join(timeout=1)
    return out, err, proc.returncode


def _run(
    args: list[str],
    timeout: int = 900,
    watch: Path | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> dict:
    """Run ipatool with JSON output and return the parsed result."""
    binary, _source = selected_ipatool()
    if binary is None:
        raise IpatoolMissing()

    argv = [str(binary), *args, "--format", "json", "--non-interactive"]
    if watch is not None and on_progress is not None:
        stdout, stderr, returncode = _run_watched(argv, watch, on_progress, timeout)
    else:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        stdout, stderr, returncode = proc.stdout, proc.stderr, proc.returncode

    # ipatool emits one JSON object per line; the last is the result.
    payload: dict = {}
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

    if returncode != 0 or payload.get("success") is False:
        raise StoreError(
            payload.get("error")
            or (stderr or "").strip()
            or f"ipatool {' '.join(args)} failed (exit {returncode})"
        )
    return payload


class StoreClient:
    """Authenticated operations against the currently signed-in Apple ID."""

    def __init__(self) -> None:
        # None until get-version-metadata has been exercised. Current ipatool
        # range-reads Info.plist but emits only version/date; a future/upstream
        # build can expose minimumOSVersion and deviceFamilies at near-zero cost.
        self.compatibility_metadata_supported: bool | None = None

    # ------------------------------------------------------------- account

    def active_account(self) -> Account | None:
        """Whoever ipatool is currently signed in as, or None."""
        try:
            data = _run(["auth", "info"], timeout=60)
        except IpatoolMissing:
            raise
        except StoreError:
            return None
        email = data.get("email")
        return Account(email=email, name=data.get("name", "")) if email else None

    def require_account(self, email: str) -> Account:
        """Fail loudly unless `email` is the signed-in account.

        This is the guard that stops a licence landing on the wrong Apple ID --
        the single most damaging mistake this tool could make, because it ties
        someone else's app to your purchase history for every future update.
        """
        active = self.active_account()
        if active is None:
            raise WrongAccount(
                f"not signed in. Run:\n  appfit accounts use {email}"
            )
        if active.email.lower() != email.lower():
            raise WrongAccount(
                f"signed in as {active.email}, but this device is paired to {email}.\n"
                f"  Switch with:  appfit accounts use {email}"
            )
        return active

    # ------------------------------------------------------------- licence

    def purchase(self, bundle_id: str) -> bool:
        """Claim a free licence. True if newly claimed, False if already owned."""
        data = _run(["purchase", "-b", bundle_id], timeout=180)
        return not bool(data.get("alreadyOwned"))

    # -------------------------------------------------------------- builds

    def version_ids(self, bundle_id: str) -> list[str]:
        """Every build available to the signed-in account, oldest first."""
        data = _run(["list-versions", "-b", bundle_id], timeout=180)
        return [str(v) for v in data.get("externalVersionIdentifiers", [])]

    def version_metadata(self, bundle_id: str, version_id: str) -> dict:
        """Range-read metadata for one build through ipatool.

        Released ipatool versions emit only display version and release date,
        despite reading the app Info.plist. Patched/future versions may also
        emit the compatibility fields parsed below.
        """
        data = _run(
            ["get-version-metadata", "-b", bundle_id, "--external-version-id", version_id],
            timeout=120,
        )
        minimum_os = next(
            (
                str(data[key])
                for key in ("minimumOSVersion", "minimumOsVersion", "MinimumOSVersion")
                if data.get(key) not in (None, "")
            ),
            "",
        )
        raw_families = data.get("deviceFamilies", data.get("UIDeviceFamily", []))
        if not isinstance(raw_families, list):
            raw_families = []
        device_families = [int(value) for value in raw_families]
        self.compatibility_metadata_supported = bool(minimum_os)

        return {
            "external_version_id": str(data.get("externalVersionID", version_id)),
            "display_version": str(data.get("displayVersion", "")),
            "release_date": str(data.get("releaseDate", ""))[:10],
            "minimum_os": minimum_os,
            "device_families": device_families,
        }

    def download(
        self,
        bundle_id: str,
        dest: Path,
        platform: str,
        version_id: str | None = None,
        purchase: bool = False,
        on_progress: Callable[[int], None] | None = None,
    ) -> Path:
        """Download one build to `dest`. Expensive: a real IPA, often 100-300 MB.

        `platform` is required rather than defaulted: it decides whether the
        store hands back the iPhone or the iPad binary, and guessing it wrong
        produces a build that cannot install on the target at all.
        """
        args = ["download", "-b", bundle_id, "-o", str(dest), "--platform", platform]
        if version_id:
            args += ["--external-version-id", str(version_id)]
        if purchase:
            args += ["--purchase"]
        _run(args, timeout=3600, watch=dest.parent, on_progress=on_progress)
        if not dest.exists():
            raise StoreError(f"ipatool reported success but {dest} is missing")
        return dest


def login_interactively(email: str) -> int:
    """Hand the terminal to ipatool so it can prompt for password and 2FA.

    Deliberately not captured: the password prompt needs a real TTY, and
    appfit never sees or stores the password.
    """
    binary, _source = selected_ipatool()
    if binary is None:
        raise IpatoolMissing()
    return subprocess.run([str(binary), "auth", "login", "-e", email]).returncode
