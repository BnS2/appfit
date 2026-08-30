"""Identifier resolution.

The `matched_exactly` flag matters more than it looks: `get` claims a licence,
and a claim is permanent. The App Store returns a plausible-looking result for
almost any nonsense string, so anything that came from a text search has to be
confirmed before it is acted on.
"""

from __future__ import annotations

import pytest

from appfit.apps import App, AppNotFound, resolve

pytestmark = pytest.mark.network

PRIME = "com.amazon.aiv.AIVApp"


@pytest.mark.parametrize(
    "query",
    [
        PRIME,
        "545519333",
        "https://apps.apple.com/us/app/amazon-prime-video/id545519333",
    ],
)
def test_identifiers_resolve_exactly(query):
    app = resolve(query)
    assert app.bundle_id == PRIME
    assert app.matched_exactly


def test_text_search_is_flagged_inexact():
    app = resolve("prime video")
    assert app.bundle_id == PRIME
    assert not app.matched_exactly


def test_nonsense_search_is_flagged_inexact():
    """The bug this guards: a typo silently claimed a licence for an unrelated
    app, which then sits in the account's purchase history for good."""
    app = resolve("zzzznotanapp-qwerty")
    assert not app.matched_exactly


def test_unknown_bundle_id_raises_rather_than_guessing():
    with pytest.raises(AppNotFound):
        resolve("com.example.definitely.not.a.real.bundle.id")


def test_app_defaults_to_exact():
    """Only the search path may downgrade confidence."""
    assert App(1, "a.b", "n", "1.0", "16.0", "s").matched_exactly
