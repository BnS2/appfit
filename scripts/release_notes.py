"""Compose GitHub Release notes from the changelog entry for a tag.

Generated notes are a list of commit subjects, which says what was touched but
not what changed for anyone using the thing. The changelog already answers that,
so the release body is its entry for this version, reflowed: the changelog wraps
its bullets to fit a text file, while a release page wraps them itself and hard
breaks read as ragged. A `Full Changelog` link closes it, matching the releases
that came before.

    python scripts/release_notes.py v0.3.1
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPOSITORY = "https://github.com/BnS2/appfit"
HEADING = re.compile(r"^## (\d+\.\d+\.\d+) - \d{4}-\d{2}-\d{2}$", flags=re.MULTILINE)


def versions(text: str) -> list[str]:
    """Released versions, newest first, as the changelog orders them."""
    return HEADING.findall(text)


def section(version: str, text: str) -> str:
    """The body under `## <version> - <date>`, up to the next release heading."""
    for match in HEADING.finditer(text):
        if match.group(1) != version:
            continue
        rest = text[match.end() :]
        following = re.search(r"^## ", rest, flags=re.MULTILINE)
        return (rest[: following.start()] if following else rest).strip()
    raise SystemExit(f"CHANGELOG.md has no dated {version} release heading")


def unwrap(body: str) -> str:
    """Join each bullet onto one line, leaving headings and blanks alone.

    The changelog is wrapped for reading in a text editor. A release page adds
    its own wrapping, so those hard breaks survive as mid-sentence ragged edges.
    """
    lines: list[str] = []
    for line in body.splitlines():
        continuation = line.startswith("  ") and lines and lines[-1].startswith("-")
        if continuation:
            lines[-1] = f"{lines[-1]} {line.strip()}"
        else:
            lines.append(line.rstrip())
    return "\n".join(lines)


def changelog_link(version: str, all_versions: list[str]) -> str:
    """Compare against the previous release, or list commits for the first."""
    tag = f"v{version}"
    position = all_versions.index(version)
    if position + 1 < len(all_versions):
        previous = f"v{all_versions[position + 1]}"
        return f"**Full Changelog**: {REPOSITORY}/compare/{previous}...{tag}"
    return f"**Full Changelog**: {REPOSITORY}/commits/{tag}"


def compose(tag: str, changelog: Path = Path("CHANGELOG.md")) -> str:
    version = tag[1:] if tag.startswith("v") else tag
    text = changelog.read_text()
    return (
        unwrap(section(version, text))
        + "\n\n"
        + changelog_link(version, versions(text))
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: release_notes.py <tag>", file=sys.stderr)
        return 2
    print(compose(args[0]), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
