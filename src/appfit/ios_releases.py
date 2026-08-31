"""When each major iOS version shipped.

Used to choose a plausible lower bound in a title's build history without
downloading anything. A build released before iOS N shipped almost never
*requires* iOS N. There is deliberately no corresponding upper-bound claim:
real apps may retain old-iOS support for years after a major release.

This is only ever a hint. resolve.py verifies the candidate and binary-searches
from it, so a poor or missing date never changes the answer. That is why a static
table is acceptable: it cannot go stale in a way that breaks correctness.

Note the 2025 renumbering -- Apple went from iOS 18 straight to iOS 26 -- which
is why "the next major" is looked up by table order and never by adding one.
"""

from __future__ import annotations

from datetime import date

# Public release date of each major version's .0, newest last.
RELEASES: list[tuple[int, date]] = [
    (6, date(2012, 9, 19)),
    (7, date(2013, 9, 18)),
    (8, date(2014, 9, 17)),
    (9, date(2015, 9, 16)),
    (10, date(2016, 9, 13)),
    (11, date(2017, 9, 19)),
    (12, date(2018, 9, 17)),
    (13, date(2019, 9, 19)),
    (14, date(2020, 9, 16)),
    (15, date(2021, 9, 20)),
    (16, date(2022, 9, 12)),
    (17, date(2023, 9, 18)),
    (18, date(2024, 9, 16)),
    (26, date(2025, 9, 15)),  # Apple's renumbering: 18 -> 26, no 19..25
]


def major(ios_version: str) -> int | None:
    """'16.7.16' -> 16."""
    head = str(ios_version).split(".", 1)[0]
    digits = "".join(c for c in head if c.isdigit())
    return int(digits) if digits else None


def successors(ios_version: str, count: int = 2) -> list[date]:
    """Release dates of the next `count` majors after `ios_version`.

    Returns fewer (possibly none) when the target is at or near the newest known
    release -- callers must treat a short list as "no hint available" rather than
    padding it with a guess.
    """
    target = major(ios_version)
    if target is None:
        return []
    later = [when for number, when in RELEASES if number > target]
    return later[:count]
