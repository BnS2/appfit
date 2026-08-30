"""Tests for the cheap-probe path.

The RemoteZip reader is the riskiest piece of appfit: it parses ZIP
structures by hand over HTTP Range requests. These tests exercise it against a
synthetic IPA served by a local range-capable server, so the parsing is verified
without depending on Apple's CDN or on anyone's credentials.
"""

from __future__ import annotations

import io
import os
import plistlib
import re
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from appfit.probe import (
    BuildInfo,
    ProbeFailed,
    RemoteZip,
    from_metadata,
    inspect,
    version_tuple,
)

INFO = {
    "CFBundleShortVersionString": "10.132",
    "CFBundleIdentifier": "com.amazon.aiv.AIVApp",
    "MinimumOSVersion": "16.0",
    "UIDeviceFamily": [1, 2],
}


def build_ipa(info: dict | None = None, compress: bool = True) -> bytes:
    """A zip shaped like a real IPA: nested bundle first, app plist later."""
    buf = io.BytesIO()
    mode = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buf, "w", mode) as zf:
        # Padding so the plist is not trivially in the tail we fetch. Must be
        # incompressible, or deflate shrinks the "IPA" to a few hundred bytes
        # and the range-vs-whole-file comparison becomes meaningless.
        zf.writestr("Payload/Prime.app/assets.bin", os.urandom(400_000))
        # A nested bundle's Info.plist must NOT be picked up.
        zf.writestr(
            "Payload/Prime.app/Frameworks/Other.framework/Info.plist",
            plistlib.dumps({"MinimumOSVersion": "99.0"}),
        )
        zf.writestr("Payload/Prime.app/Info.plist", plistlib.dumps(info or INFO))
    return buf.getvalue()


class RangeHandler(BaseHTTPRequestHandler):
    payload = b""
    honour_range = True

    def log_message(self, *args):  # silence test output
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        rng = self.headers.get("Range")
        if rng and self.honour_range:
            start, end = re.match(r"bytes=(\d+)-(\d+)", rng).groups()
            chunk = self.payload[int(start) : int(end) + 1]
            self.send_response(206)
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.payload)))
            self.end_headers()
            self.wfile.write(self.payload)


@pytest.fixture
def serve():
    servers = []

    def _serve(payload: bytes, honour_range: bool = True) -> str:
        handler = type(
            "H", (RangeHandler,), {"payload": payload, "honour_range": honour_range}
        )
        httpd = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_port}/app.ipa"

    yield _serve
    for httpd in servers:
        httpd.shutdown()


# ------------------------------------------------------------------ version

@pytest.mark.parametrize(
    "raw,expected",
    [("16.7.16", (16, 7, 16)), ("17.0", (17, 0, 0)), ("9", (9, 0, 0)), ("", (0, 0, 0))],
)
def test_version_tuple(raw, expected):
    assert version_tuple(raw) == expected


def test_version_ordering_is_numeric_not_lexical():
    # The bug this guards: "9.0" > "16.0" as strings.
    assert version_tuple("9.0") < version_tuple("16.0")
    assert not version_tuple("16.7.16") < version_tuple("16.7.2")


def test_runs_on():
    info = BuildInfo("16.0", "10.132", [1, 2], "test")
    assert info.runs_on("16.7.16")
    assert info.runs_on("16.0")
    assert not info.runs_on("15.8.3")


# ----------------------------------------------------------------- metadata

def test_metadata_strategy_finds_key_case_insensitively():
    assert from_metadata({"minimumOsVersion": "16.0"}) == "16.0"
    assert from_metadata({"MinimumOSVersion": "15.0"}) == "15.0"


def test_metadata_strategy_returns_none_when_absent():
    assert from_metadata({"bundleShortVersionString": "10.1"}) is None


# ----------------------------------------------------------------- remotezip

def test_reads_info_plist_over_range(serve):
    url = serve(build_ipa())
    plist = RemoteZip(url).read_info_plist()
    assert plist["MinimumOSVersion"] == "16.0"
    assert plist["CFBundleShortVersionString"] == "10.132"


def test_reads_stored_uncompressed_entries(serve):
    url = serve(build_ipa(compress=False))
    assert RemoteZip(url).read_info_plist()["MinimumOSVersion"] == "16.0"


def test_ignores_nested_framework_plists(serve):
    """A framework's Info.plist must not be mistaken for the app's."""
    url = serve(build_ipa())
    assert RemoteZip(url).read_info_plist()["MinimumOSVersion"] != "99.0"


def test_range_read_transfers_far_less_than_the_whole_file(serve):
    """The entire point: don't download 200 MB to read one plist."""
    payload = build_ipa()
    url = serve(payload)

    transferred = 0
    original = RemoteZip._range

    def counting(self, start, end):
        nonlocal transferred
        data = original(self, start, end)
        transferred += len(data)
        return data

    RemoteZip._range = counting
    try:
        RemoteZip(url).read_info_plist()
    finally:
        RemoteZip._range = original

    assert transferred < len(payload) / 4


def test_raises_when_server_ignores_range(serve):
    url = serve(build_ipa(), honour_range=False)
    with pytest.raises(ProbeFailed, match="ignored Range"):
        RemoteZip(url).read_info_plist()


# -------------------------------------------------------------------- driver

def test_inspect_prefers_metadata_and_makes_no_request():
    info = inspect(
        "http://127.0.0.1:1/never-fetched",
        {"minimumOSVersion": "16.0", "bundleShortVersionString": "10.132"},
    )
    assert info.source == "metadata"
    assert info.minimum_os == "16.0"


def test_inspect_falls_back_to_range_when_metadata_silent(serve):
    url = serve(build_ipa())
    info = inspect(url, {"bundleShortVersionString": "10.132"})
    assert info.source == "range"
    assert info.minimum_os == "16.0"
    assert info.device_families == [1, 2]


def test_inspect_refuses_full_download_unless_allowed(serve):
    url = serve(build_ipa(), honour_range=False)
    with pytest.raises(ProbeFailed):
        inspect(url, {})


def test_inspect_full_download_fallback(serve):
    url = serve(build_ipa(), honour_range=False)
    info = inspect(url, {}, allow_full_download=True)
    assert info.source == "download"
    assert info.minimum_os == "16.0"
