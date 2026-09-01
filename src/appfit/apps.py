"""Turn whatever the user typed into a concrete App Store title.

Accepts a bundle ID, a numeric App Store ID, a store URL, or a plain search
term. Uses the public iTunes lookup/search API, which needs no authentication --
so this half of the tool works before anyone has signed in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests

LOOKUP = "https://itunes.apple.com/lookup"
SEARCH = "https://itunes.apple.com/search"

_BUNDLE_RE = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){1,}$")
_URL_ID_RE = re.compile(r"/id(\d+)")


@dataclass
class App:
    app_id: int
    bundle_id: str
    name: str
    current_version: str
    minimum_os: str
    seller: str
    # False when the app came from a fuzzy text search rather than an exact
    # identifier. Callers that are about to claim a licence must confirm first:
    # the store returns *something* for almost any nonsense term, and claiming
    # blindly puts a stranger's app in the user's purchase history for good.
    matched_exactly: bool = True
    artwork_url: str = ""

    def __str__(self) -> str:
        return f"{self.name} ({self.bundle_id}, id {self.app_id})"


class AppNotFound(LookupError):
    pass


def _from_result(r: dict) -> App:
    return App(
        app_id=int(r["trackId"]),
        bundle_id=r["bundleId"],
        name=r["trackName"],
        current_version=r.get("version", ""),
        minimum_os=r.get("minimumOsVersion", ""),
        seller=r.get("sellerName", ""),
        artwork_url=r.get("artworkUrl100", ""),
    )


def _lookup(**params) -> list[App]:
    resp = requests.get(
        LOOKUP, params={"country": "US", "entity": "software", **params}, timeout=30
    )
    resp.raise_for_status()
    return [_from_result(r) for r in resp.json().get("results", []) if "bundleId" in r]


def resolve(query: str, country: str = "US") -> App:
    """Best single match for `query`, or raise AppNotFound."""
    query = query.strip()

    exact = True
    if m := _URL_ID_RE.search(query):
        found = _lookup(id=m.group(1), country=country)
    elif query.isdigit():
        found = _lookup(id=query, country=country)
    elif _BUNDLE_RE.match(query):
        found = _lookup(bundleId=query, country=country)
    else:
        found = search(query, country=country, limit=1)
        exact = False

    if not found:
        raise AppNotFound(f"no App Store title matched {query!r}")

    app = found[0]
    app.matched_exactly = exact
    return app


def search(term: str, country: str = "US", limit: int = 10) -> list[App]:
    resp = requests.get(
        SEARCH,
        params={
            "term": term,
            "country": country,
            "entity": "software",
            "limit": limit,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return [_from_result(r) for r in resp.json().get("results", []) if "bundleId" in r]
