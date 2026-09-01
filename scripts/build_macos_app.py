"""Build an architecture-specific, self-contained appfit macOS application.

The build deliberately stages the pinned patched ipatool inside the Python
package before invoking PyInstaller with Qt support. The staged binary and
generated deployment files are ignored by git.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
DEPLOYMENT = ROOT / "deployment"
ICON_SOURCE = ROOT / "assets" / "appfit-icon-1024.png"


def architecture() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    raise SystemExit(f"unsupported Mac architecture: {machine}")


def stage_helper() -> Path:
    sys.path.insert(0, str(SOURCE))
    from appfit import toolchain

    helper = toolchain.install_managed_ipatool()
    destination = SOURCE / "appfit" / "bin" / architecture() / "ipatool"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(helper, destination)
    destination.chmod(0o755)
    manifest = {
        "compatibility_metadata": True,
        "release": toolchain.IPATOOL_RELEASE,
        "repository": toolchain.IPATOOL_REPOSITORY,
        "revision": toolchain.IPATOOL_REVISION,
    }
    destination.with_name("manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return destination


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("the desktop bundle is currently macOS-only")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="print the PyInstaller command only"
    )
    parser.add_argument(
        "--skip-helper",
        action="store_true",
        help="reuse an already staged architecture-specific ipatool",
    )
    args = parser.parse_args()

    helper = SOURCE / "appfit" / "bin" / architecture() / "ipatool"
    if not args.skip_helper:
        helper = stage_helper()
    if not helper.is_file():
        raise SystemExit(f"bundled helper is missing: {helper}")

    deploy = Path(sys.executable).with_name("pyinstaller")
    if not deploy.is_file():
        raise SystemExit("PyInstaller is missing; install appfit[package]")
    generated = DEPLOYMENT / "generated"
    work = ROOT / "build" / "pyinstaller"
    if not ICON_SOURCE.is_file():
        raise SystemExit(f"app icon source is missing: {ICON_SOURCE}")
    command = [
        str(deploy),
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "appfit",
        "--icon",
        str(ICON_SOURCE),
        "--paths",
        str(SOURCE),
        "--distpath",
        str(generated),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        "--hidden-import",
        "keyring.backends.macOS",
        "--exclude-module",
        "pymobiledevice3.cli",
        "--exclude-module",
        "IPython",
        "--add-data",
        f"{ROOT / 'THIRD_PARTY_NOTICES.md'}:.",
        "--add-data",
        f"{SOURCE / 'appfit' / 'data'}:appfit/data",
        "--add-binary",
        f"{helper}:appfit/bin/{architecture()}",
        "--add-data",
        f"{helper.with_name('manifest.json')}:appfit/bin/{architecture()}",
        "--osx-bundle-identifier",
        "io.github.bns2.appfit",
        str(SOURCE / "appfit" / "gui_main.py"),
    ]
    if args.dry_run:
        print(" ".join(command))
        return
    environment = dict(os.environ)
    environment["PYINSTALLER_CONFIG_DIR"] = str(
        ROOT / "build" / "pyinstaller-cache"
    )
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    applications = sorted(generated.glob("*.app"))
    if len(applications) != 1:
        raise SystemExit(
            f"expected one generated application in {generated}, found {applications}"
        )
    destination = DEPLOYMENT / f"appfit-{architecture()}.app"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(applications[0]), destination)

    with (ROOT / "pyproject.toml").open("rb") as source:
        import tomllib

        version = tomllib.load(source)["project"]["version"]
    info_path = destination / "Contents" / "Info.plist"
    with info_path.open("rb") as source:
        info = plistlib.load(source)
    info.update(
        {
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "LSMinimumSystemVersion": "13.0",
            "NSHumanReadableCopyright": "Copyright © 2026 appfit contributors",
        }
    )
    with info_path.open("wb") as output:
        plistlib.dump(info, output)
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(destination)],
        check=True,
    )
    print(destination)


if __name__ == "__main__":
    main()
