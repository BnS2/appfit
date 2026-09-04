"""Compose GitHub Release notes from the changelog and the published assets.

Generated notes are a list of commit subjects, which tells a reader what was
touched but not what to download or why they would want it. The changelog
already answers the second question, and the release page is where the first
one is asked, so the notes lead with the assets and then quote the changelog
entry verbatim.

    python scripts/release_notes.py v0.3.1
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

INSTALL = """## Install

**Mac app** — download `appfit-{version}-arm64.dmg` (Apple silicon) or
`appfit-{version}-x86_64.dmg` (Intel), open it, and drag **appfit** to
**Applications**. Nothing else is required; the App Store helper is inside the
app. The app is not notarized, so the first launch needs right-click → **Open**.

**Terminal** — install `appfit-{version}-py3-none-any.whl` into a Python 3.10+
environment, then run `appfit ipatool install` (needs Go).

See the [README](https://github.com/BnS2/appfit/blob/{tag}/README.md) for both
paths in full.
"""


def changelog_section(version: str, changelog: Path = Path("CHANGELOG.md")) -> str:
    """The body of `## <version> - <date>`, up to the next release heading."""
    text = changelog.read_text()
    heading = re.compile(
        rf"^## {re.escape(version)} - \d{{4}}-\d{{2}}-\d{{2}}$", flags=re.MULTILINE
    )
    match = heading.search(text)
    if match is None:
        raise SystemExit(f"CHANGELOG.md has no dated {version} release heading")

    rest = text[match.end() :]
    following = re.search(r"^## ", rest, flags=re.MULTILINE)
    return rest[: following.start()].strip() if following else rest.strip()


def compose(tag: str, changelog: Path = Path("CHANGELOG.md")) -> str:
    version = tag[1:] if tag.startswith("v") else tag
    return (
        INSTALL.format(version=version, tag=tag)
        + "\n## Changes\n\n"
        + changelog_section(version, changelog)
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
