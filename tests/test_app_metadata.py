from appfit.apps import App, _from_result


def test_store_result_keeps_artwork_without_changing_exact_match_default():
    app = _from_result(
        {
            "trackId": 1,
            "bundleId": "com.example.app",
            "trackName": "Example",
            "version": "4.0",
            "minimumOsVersion": "18.0",
            "sellerName": "Example Co",
            "artworkUrl100": "https://example.invalid/artwork.png",
        }
    )

    assert app.artwork_url == "https://example.invalid/artwork.png"
    assert app.matched_exactly


def test_existing_positional_exactness_argument_remains_compatible():
    app = App(1, "a.b", "Example", "1", "16", "Example Co", False)

    assert not app.matched_exactly
    assert app.artwork_url == ""
