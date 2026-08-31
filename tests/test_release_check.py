from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "release_check.py"
SPEC = importlib.util.spec_from_file_location("appfit_release_check", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
validate_release = MODULE.validate_release


def test_release_check_accepts_matching_tag_version_and_changelog(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    changelog = tmp_path / "CHANGELOG.md"
    pyproject.write_text('[project]\nversion = "0.2.0"\n')
    changelog.write_text("## 0.2.0 - 2026-08-31\n")

    assert validate_release(
        "v0.2.0", pyproject=pyproject, changelog=changelog
    ) == []


def test_release_check_rejects_wrong_tag_and_missing_changelog_entry(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    changelog = tmp_path / "CHANGELOG.md"
    pyproject.write_text('[project]\nversion = "0.2.0"\n')
    changelog.write_text("## Unreleased\n")

    errors = validate_release("v0.3.0", pyproject=pyproject, changelog=changelog)

    assert errors == [
        "tag is 'v0.3.0'; package version requires 'v0.2.0'",
        "CHANGELOG.md has no dated 0.2.0 release heading",
    ]
