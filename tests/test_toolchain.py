from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from appfit import toolchain


def _executable(path: Path, content: bytes = b"helper") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o755)
    return path


def test_selected_ipatool_prefers_environment_then_managed(tmp_path, monkeypatch):
    monkeypatch.setattr(toolchain.accounts, "config_dir", lambda: tmp_path)
    path_binary = _executable(tmp_path / "path" / "ipatool")
    managed = _executable(toolchain.managed_ipatool_path())
    override = _executable(tmp_path / "override" / "ipatool")
    monkeypatch.setattr(
        toolchain.shutil,
        "which",
        lambda command: str(path_binary) if command == "ipatool" else command,
    )

    assert toolchain.selected_ipatool() == (managed, "appfit-managed")

    monkeypatch.setenv(toolchain.IPATOOL_ENV, str(override))
    selected, source = toolchain.selected_ipatool()
    assert selected == override.resolve()
    assert source == "environment"


def test_install_managed_ipatool_pins_source_and_writes_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(toolchain.accounts, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(toolchain.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []

    def fake_run(argv, *, cwd=None, timeout=1800):
        calls.append((argv, cwd))
        if argv[:2] == ["git", "clone"]:
            Path(argv[-1]).mkdir(parents=True)
        elif argv[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout=f"{toolchain.IPATOOL_REVISION}\n", stderr=""
            )
        elif argv[0] == "go" and argv[1] == "build":
            Path(argv[argv.index("-o") + 1]).write_bytes(b"optimized")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(toolchain, "_run", fake_run)
    steps = []

    result = toolchain.install_managed_ipatool(on_step=steps.append)

    assert result.read_bytes() == b"optimized"
    assert result.stat().st_mode & 0o111
    manifest = json.loads(result.with_name("manifest.json").read_text())
    assert manifest["release"] == toolchain.IPATOOL_RELEASE
    assert manifest["revision"] == toolchain.IPATOOL_REVISION
    assert manifest["compatibility_metadata"] is True
    clone = calls[0][0]
    assert clone[clone.index("--branch") + 1] == toolchain.IPATOOL_RELEASE
    build = next(argv for argv, _cwd in calls if argv[:2] == ["go", "build"])
    assert "-trimpath" in build
    apply_calls = [argv for argv, _cwd in calls if argv[:2] == ["git", "apply"]]
    assert apply_calls
    assert all("--unidiff-zero" in argv for argv in apply_calls)
    assert steps[-1] == "installing appfit-managed helper"


def test_install_rejects_moved_release_tag(tmp_path, monkeypatch):
    monkeypatch.setattr(toolchain.accounts, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(toolchain.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(argv, *, cwd=None, timeout=1800):
        if argv[:2] == ["git", "clone"]:
            Path(argv[-1]).mkdir(parents=True)
        if argv[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(argv, 0, stdout="unexpected\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(toolchain, "_run", fake_run)

    with pytest.raises(toolchain.ToolchainError, match="unexpected commit"):
        toolchain.install_managed_ipatool()

    assert not toolchain.managed_ipatool_path().exists()


def test_status_trusts_only_matching_managed_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(toolchain.accounts, "config_dir", lambda: tmp_path)
    binary = _executable(toolchain.managed_ipatool_path())
    binary.with_name("manifest.json").write_text(
        json.dumps(
            {
                "revision": toolchain.IPATOOL_REVISION,
                "compatibility_metadata": True,
            }
        )
    )
    monkeypatch.setattr(toolchain, "_version", lambda _binary: "ipatool version test")

    current = toolchain.status()

    assert current.path == binary
    assert current.source == "appfit-managed"
    assert current.version == "ipatool version test"
    assert current.compatibility_metadata is True


def test_version_tolerates_a_silent_binary(tmp_path, monkeypatch):
    binary = _executable(tmp_path / "ipatool")
    monkeypatch.setattr(
        toolchain.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )

    assert toolchain._version(binary) == ""
