"""Install and locate appfit's compatibility-aware ipatool helper.

The released ipatool already range-reads each historical IPA's Info.plist, but
does not emit the two compatibility values appfit needs.  Building a tiny,
pinned patch is preferable to maintaining a fork or downloading opaque
binaries: the source revision, patch, and Go module checksums all ship with the
appfit release.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable, Iterator

from . import accounts

IPATOOL_REPOSITORY = "https://github.com/majd/ipatool.git"
IPATOOL_RELEASE = "v2.4.0"
IPATOOL_REVISION = "abd86cb01a295be2be92d528bb56996861ab620c"
IPATOOL_ENV = "APPFIT_IPATOOL"
PATCH_NAME = "ipatool-compatibility-metadata.patch"


class ToolchainError(RuntimeError):
    pass


@dataclass(frozen=True)
class IpatoolStatus:
    path: Path | None
    source: str
    version: str = ""
    compatibility_metadata: bool | None = None


def managed_ipatool_path() -> Path:
    return (
        accounts.config_dir()
        / "tools"
        / "ipatool"
        / IPATOOL_RELEASE
        / "ipatool"
    )


def _manifest_path() -> Path:
    return managed_ipatool_path().with_name("manifest.json")


def bundled_ipatool_path() -> Path:
    """Architecture-specific helper shipped inside a desktop app, if present."""
    architecture = platform.machine().lower()
    if architecture in {"aarch64", "arm64"}:
        architecture = "arm64"
    elif architecture in {"amd64", "x86_64"}:
        architecture = "x86_64"
    return Path(__file__).resolve().parent / "bin" / architecture / "ipatool"


def _executable(command: str | Path) -> Path | None:
    found = shutil.which(str(command))
    return Path(found).resolve() if found else None


def selected_ipatool() -> tuple[Path | None, str]:
    """Resolve ipatool without caching so a just-installed helper is visible."""
    override = os.environ.get(IPATOOL_ENV)
    if override:
        return _executable(override), "environment"

    bundled = bundled_ipatool_path()
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return bundled, "appfit-bundled"

    managed = managed_ipatool_path()
    if managed.is_file() and os.access(managed, os.X_OK):
        return managed, "appfit-managed"

    return _executable("ipatool"), "PATH"


def _version(binary: Path) -> str:
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else ""


def status() -> IpatoolStatus:
    binary, source = selected_ipatool()
    if binary is None:
        return IpatoolStatus(None, "missing")

    compatibility: bool | None = None
    if source in {"appfit-managed", "appfit-bundled"}:
        try:
            manifest_path = (
                binary.with_name("manifest.json")
                if source == "appfit-bundled"
                else _manifest_path()
            )
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if (
            manifest.get("revision") == IPATOOL_REVISION
            and manifest.get("compatibility_metadata") is True
        ):
            compatibility = True

    return IpatoolStatus(binary, source, _version(binary), compatibility)


@contextmanager
def _patch_file() -> Iterator[Path]:
    patch = resources.files("appfit").joinpath("data", PATCH_NAME)
    with resources.as_file(patch) as path:
        yield path


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 1800,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ToolchainError(f"required build tool is missing: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolchainError(f"timed out while running: {' '.join(argv)}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ToolchainError(detail or f"failed: {' '.join(argv)}")
    return result


def install_managed_ipatool(
    *,
    force: bool = False,
    on_step: Callable[[str], None] | None = None,
) -> Path:
    """Build the pinned patched helper and install it atomically.

    The destination is versioned, so a failed build cannot damage an existing
    helper.  The exact source commit is checked after clone before the bundled
    patch is applied.
    """
    destination = managed_ipatool_path()
    if destination.is_file() and not force:
        current = status()
        if current.path == destination and current.compatibility_metadata is True:
            return destination

    missing = [name for name in ("git", "go") if shutil.which(name) is None]
    if missing:
        joined = " and ".join(missing)
        raise ToolchainError(
            f"cannot build optimized ipatool: install {joined} first"
        )

    report = on_step or (lambda _message: None)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="appfit-ipatool-") as temporary:
        root = Path(temporary)
        source = root / "source"
        built = root / "ipatool"

        report(f"fetching official ipatool {IPATOOL_RELEASE}")
        _run(
            [
                "git",
                "clone",
                "--quiet",
                "--branch",
                IPATOOL_RELEASE,
                "--depth",
                "1",
                IPATOOL_REPOSITORY,
                str(source),
            ]
        )
        revision = _run(
            ["git", "rev-parse", "HEAD"], cwd=source, timeout=30
        ).stdout.strip()
        if revision != IPATOOL_REVISION:
            raise ToolchainError(
                f"ipatool {IPATOOL_RELEASE} resolved to unexpected commit "
                f"{revision}; expected {IPATOOL_REVISION}"
            )

        report("applying appfit compatibility metadata patch")
        with _patch_file() as patch:
            _run(
                ["git", "apply", "--unidiff-zero", "--check", str(patch)],
                cwd=source,
                timeout=30,
            )
            _run(
                ["git", "apply", "--unidiff-zero", str(patch)],
                cwd=source,
                timeout=30,
            )

        report("building optimized ipatool")
        version_symbol = "github.com/majd/ipatool/v2/cmd.version"
        _run(
            [
                "go",
                "build",
                "-trimpath",
                "-ldflags",
                f"-X {version_symbol}={IPATOOL_RELEASE}-appfit",
                "-o",
                str(built),
                ".",
            ],
            cwd=source,
        )
        if not built.is_file():
            raise ToolchainError("Go build succeeded but produced no ipatool binary")

        report("installing appfit-managed helper")
        staged = destination.with_suffix(".new")
        shutil.copy2(built, staged)
        staged.chmod(0o755)
        os.replace(staged, destination)

    manifest = {
        "compatibility_metadata": True,
        "release": IPATOOL_RELEASE,
        "repository": IPATOOL_REPOSITORY,
        "revision": IPATOOL_REVISION,
    }
    staged_manifest = _manifest_path().with_suffix(".json.new")
    staged_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(staged_manifest, _manifest_path())
    return destination
