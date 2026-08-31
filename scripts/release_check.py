"""Fail a release when its Git tag, package version, and changelog disagree."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def project_version(pyproject: Path) -> str:
    match = re.search(
        r'^version\s*=\s*"([^"]+)"\s*$',
        pyproject.read_text(),
        flags=re.MULTILINE,
    )
    if match is None:
        raise ValueError(f"could not find project version in {pyproject}")
    return match.group(1)


def validate_release(
    tag: str,
    *,
    pyproject: Path = Path("pyproject.toml"),
    changelog: Path = Path("CHANGELOG.md"),
) -> list[str]:
    version = project_version(pyproject)
    expected_tag = f"v{version}"
    errors = []
    if tag != expected_tag:
        errors.append(f"tag is {tag!r}; package version requires {expected_tag!r}")

    heading = re.compile(
        rf"^## {re.escape(version)} - \d{{4}}-\d{{2}}-\d{{2}}$",
        flags=re.MULTILINE,
    )
    if heading.search(changelog.read_text()) is None:
        errors.append(f"CHANGELOG.md has no dated {version} release heading")
    return errors


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: release_check.py <tag>", file=sys.stderr)
        return 2
    errors = validate_release(args[0])
    if errors:
        for error in errors:
            print(f"release check failed: {error}", file=sys.stderr)
        return 1
    print(f"release check passed: {args[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
