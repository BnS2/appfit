"""Authenticated App Store operations, delegated to the `ipatool` binary.

Why not speak the protocol directly: Apple signs these requests. The endpoints
come from a "bag" config (init.itunes.apple.com/bag.xml) rather than fixed
hostnames, and unsigned POSTs to the authenticate endpoint return a bare HTTP
403 with an empty body -- verified from both python-requests and curl, so it is
not a TLS-fingerprint issue. ipatool implements the signing and is maintained,
so appfit drives it instead of racing Apple's changes.

The cost of this choice: ipatool never exposes the signed IPA download URL, so
the cheap HTTP-Range probe in probe.py cannot be pointed at Apple. Determining a
build's minimum OS therefore means downloading it. See resolve.py for how that
is kept tolerable.

Account handling: ipatool stores exactly one session at a time. appfit
refuses to act when the signed-in account is not the one paired to the target
device, rather than silently claiming a licence on the wrong Apple ID.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

IPATOOL = "ipatool"


class StoreError(RuntimeError):
    pass


class IpatoolMissing(StoreError):
    def __init__(self) -> None:
        super().__init__(
            "ipatool is not installed. Install it with:\n  brew install ipatool"
        )


class WrongAccount(StoreError):
    """The signed-in Apple ID is not the one this device is paired to."""


@dataclass
class Account:
    email: str
    name: str = ""

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>" if self.name else self.email


def _run(args: list[str], timeout: int = 900) -> dict:
    """Run ipatool with JSON output and return the parsed result."""
    if shutil.which(IPATOOL) is None:
        raise IpatoolMissing()

    proc = subprocess.run(
        [IPATOOL, *args, "--format", "json", "--non-interactive"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    # ipatool emits one JSON object per line; the last is the result.
    payload: dict = {}
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

    if proc.returncode != 0 or payload.get("success") is False:
        raise StoreError(
            payload.get("error")
            or (proc.stderr or "").strip()
            or f"ipatool {' '.join(args)} failed (exit {proc.returncode})"
        )
    return payload


class StoreClient:
    """Authenticated operations against the currently signed-in Apple ID."""

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
        """Display version and release date for one build. Cheap: no download.

        Note this does NOT include the minimum OS -- that is the whole reason
        resolve.py has to download.
        """
        data = _run(
            ["get-version-metadata", "-b", bundle_id, "--external-version-id", version_id],
            timeout=120,
        )
        return {
            "external_version_id": str(data.get("externalVersionID", version_id)),
            "display_version": str(data.get("displayVersion", "")),
            "release_date": str(data.get("releaseDate", ""))[:10],
        }

    def download(
        self, bundle_id: str, dest: Path, version_id: str | None = None,
        platform: str = "ipad", purchase: bool = False,
    ) -> Path:
        """Download one build to `dest`. Expensive: a real IPA, often 100-300 MB."""
        args = ["download", "-b", bundle_id, "-o", str(dest), "--platform", platform]
        if version_id:
            args += ["--external-version-id", str(version_id)]
        if purchase:
            args += ["--purchase"]
        _run(args, timeout=3600)
        if not dest.exists():
            raise StoreError(f"ipatool reported success but {dest} is missing")
        return dest


def login_interactively(email: str) -> int:
    """Hand the terminal to ipatool so it can prompt for password and 2FA.

    Deliberately not captured: the password prompt needs a real TTY, and
    appfit never sees or stores the password.
    """
    if shutil.which(IPATOOL) is None:
        raise IpatoolMissing()
    return subprocess.run([IPATOOL, "auth", "login", "-e", email]).returncode
