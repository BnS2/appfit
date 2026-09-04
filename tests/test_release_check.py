from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load(name: str):
    script = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"appfit_{name}", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load("release_check")
release_notes = _load("release_notes")
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


def test_release_notes_match_the_shape_of_earlier_releases(tmp_path):
    """Earlier releases are the changelog entry plus a Full Changelog link.

    A body in a different shape reads as a mistake next to the ones above it,
    so the composed notes carry no headings of their own and unwrap the
    changelog's bullets, which a release page rewraps for itself.
    """
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n"
        "## 1.2.3 - 2026-01-02\n\n"
        "### Fixed\n\n"
        "- Something that was broken across\n  two wrapped lines.\n\n"
        "## 1.2.2 - 2025-12-01\n\n"
        "### Added\n\n- An older entry that must not leak in.\n"
    )

    notes = release_notes.compose("v1.2.3", changelog)

    assert notes.startswith("### Fixed")
    assert "- Something that was broken across two wrapped lines." in notes
    assert "older entry" not in notes
    assert notes.rstrip().endswith(
        "**Full Changelog**: https://github.com/BnS2/appfit/compare/v1.2.2...v1.2.3"
    )


def test_release_notes_list_commits_when_there_is_no_earlier_release(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## 1.0.0 - 2026-01-01\n\n- First.\n")

    notes = release_notes.compose("v1.0.0", changelog)

    assert notes.rstrip().endswith(
        "**Full Changelog**: https://github.com/BnS2/appfit/commits/v1.0.0"
    )


def test_release_notes_refuse_a_version_the_changelog_does_not_describe(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## 1.0.0 - 2026-01-01\n\n- First.\n")

    with pytest.raises(SystemExit):
        release_notes.compose("v9.9.9", changelog)
