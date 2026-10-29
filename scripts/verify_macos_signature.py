"""Reject ad-hoc, wrong-team, or unhardened public Mac applications."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


def validate_details(details: str, team: str) -> None:
    flags = re.search(r"\bflags=0x([0-9a-fA-F]+)", details)
    if (
        "Authority=Developer ID Application:" not in details
        or f"TeamIdentifier={team}\n" not in details
        or "Timestamp=" not in details
        or flags is None
        or not int(flags[1], 16) & 0x10000
    ):
        raise ValueError(
            "release app needs timestamped Developer ID signing, expected team, and hardened runtime"
        )


def validate_notarization(report: Path) -> None:
    result = json.loads(report.read_text())
    if result.get("status") != "Accepted":
        raise ValueError("Apple has not accepted notarization")


def main() -> None:
    bundle, team = sys.argv[1:]
    subprocess.run(
        ["codesign", "--verify", "--all-architectures", "--deep", "--strict", bundle],
        check=True,
    )
    result = subprocess.run(
        ["codesign", "--display", "--verbose=4", bundle],
        check=True, text=True, capture_output=True,
    )
    validate_details(result.stdout + result.stderr, team)
    print(result.stdout + result.stderr)


if __name__ == "__main__":
    main()
