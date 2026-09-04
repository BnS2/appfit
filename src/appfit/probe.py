"""Find a build's MinimumOSVersion as cheaply as possible.

Three strategies, tried in order:

1. METADATA  -- the store's own response may already carry a minimum-OS field.
   Free: no download at all.
2. RANGE     -- an IPA is a ZIP. Read the End of Central Directory from the tail,
   locate `Payload/<App>.app/Info.plist` in the central directory, then fetch and
   inflate just that one entry. Typically a few hundred KB instead of ~200 MB.
   Info.plist is *not* FairPlay-encrypted -- only the Mach-O executable is -- so
   this is readable on a normal store IPA.
3. DOWNLOAD  -- fall back to pulling the whole IPA. Correct but expensive, so it
   is last and its results are always cached.
"""

from __future__ import annotations

import io
import plistlib
import re
import struct
import zlib
from dataclasses import dataclass
from typing import Any

import requests

# Keys Apple has used for this over the years; checked case-insensitively.
_MIN_OS_KEYS = ("minimumOSVersion", "minimumOsVersion", "minimum_os_version", "softwareMinimumOSVersion")

_EOCD_SIG = b"PK\x05\x06"
_EOCD64_LOCATOR_SIG = b"PK\x06\x07"
_EOCD64_SIG = b"PK\x06\x06"
_CD_SIG = b"PK\x01\x02"

# Payload/<Something>.app/Info.plist -- the app's own plist, not a nested bundle's.
_INFO_PLIST_RE = re.compile(rb"^Payload/[^/]+\.app/Info\.plist$")


@dataclass
class BuildInfo:
    minimum_os: str
    display_version: str
    device_families: list[int]
    source: str  # which strategy answered
    # False when the store declined to serve this build at all. Such a build can
    # never be the answer -- it cannot be downloaded, let alone installed -- so
    # it fails every compatibility test regardless of what it requires.
    available: bool = True

    def runs_on(self, ios_version: str) -> bool:
        """Minimum-OS check alone. Enough when no hardware family is known."""
        if not self.available:
            return False
        return version_tuple(self.minimum_os) <= version_tuple(ios_version)

    def fits(self, target) -> bool:
        """Whether this build runs on `target`: minimum OS *and* hardware family.

        Minimum OS is the usual blocker, but it is not the only one -- an
        iPhone-only build declares UIDeviceFamily [1] and will not install on an
        iPad however old the deployment target is.

        Either side may be unknown: `device_families` is empty when the answer
        came from store metadata rather than an Info.plist, and
        `target.device_family` is None when the user typed --ios with no cable.
        Unknown never rejects a build -- it only means we cannot rule one out.
        """
        if not self.available or not self.runs_on(target.ios_version):
            return False
        if self.device_families and target.device_family is not None:
            return target.device_family in self.device_families
        return True


def version_tuple(v: str) -> tuple[int, ...]:
    """'16.7.16' -> (16, 7, 16). Tolerates junk and ragged lengths."""
    parts = []
    for chunk in str(v).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


class ProbeFailed(RuntimeError):
    pass


# ------------------------------------------------------------- strategy 1

def from_metadata(metadata: dict[str, Any]) -> str | None:
    lowered = {k.lower(): v for k, v in metadata.items()}
    for key in _MIN_OS_KEYS:
        if (value := lowered.get(key.lower())) is not None:
            return str(value)
    return None


# ------------------------------------------------------------- strategy 2

class RemoteZip:
    """Enough ZIP reader to pull one small member over HTTP Range requests."""

    def __init__(self, url: str, session: requests.Session | None = None) -> None:
        self.url = url
        self.http = session or requests.Session()
        self._size: int | None = None

    def _range(self, start: int, end: int) -> bytes:
        """Inclusive byte range, as HTTP defines it."""
        resp = self.http.get(
            self.url, headers={"Range": f"bytes={start}-{end}"}, timeout=60
        )
        if resp.status_code != 206:
            raise ProbeFailed(
                f"server ignored Range request (HTTP {resp.status_code}); "
                "fall back to a full download"
            )
        return resp.content

    @property
    def size(self) -> int:
        if self._size is None:
            resp = self.http.head(self.url, timeout=30, allow_redirects=True)
            length = resp.headers.get("content-length")
            if not length:
                raise ProbeFailed("server did not report a content-length")
            self._size = int(length)
        return self._size

    def _find_central_directory(self) -> tuple[int, int]:
        """(offset, size) of the central directory."""
        tail_len = min(65536 + 22, self.size)
        tail = self._range(self.size - tail_len, self.size - 1)

        idx = tail.rfind(_EOCD_SIG)
        if idx < 0:
            raise ProbeFailed("no end-of-central-directory record found")

        cd_size, cd_offset = struct.unpack("<II", tail[idx + 12 : idx + 20])

        # 0xFFFFFFFF sentinels mean the real values live in the ZIP64 record.
        if cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
            loc = tail.rfind(_EOCD64_LOCATOR_SIG)
            if loc < 0:
                raise ProbeFailed("ZIP64 sentinel present but no locator")
            (eocd64_offset,) = struct.unpack("<Q", tail[loc + 8 : loc + 16])
            rec = self._range(eocd64_offset, eocd64_offset + 55)
            if not rec.startswith(_EOCD64_SIG):
                raise ProbeFailed("ZIP64 end-of-central-directory record malformed")
            cd_size, cd_offset = struct.unpack("<QQ", rec[40:56])

        return cd_offset, cd_size

    def _locate_member(self, pattern: re.Pattern[bytes]) -> tuple[int, int, int, int]:
        """(local_header_offset, compressed_size, uncompressed_size, method)."""
        cd_offset, cd_size = self._find_central_directory()
        cd = self._range(cd_offset, cd_offset + cd_size - 1)

        pos = 0
        while pos + 46 <= len(cd):
            if cd[pos : pos + 4] != _CD_SIG:
                break
            method, = struct.unpack("<H", cd[pos + 10 : pos + 12])
            csize, usize = struct.unpack("<II", cd[pos + 20 : pos + 28])
            name_len, extra_len, comment_len = struct.unpack(
                "<HHH", cd[pos + 28 : pos + 34]
            )
            (local_offset,) = struct.unpack("<I", cd[pos + 42 : pos + 46])
            name = cd[pos + 46 : pos + 46 + name_len]

            if pattern.match(name):
                if local_offset == 0xFFFFFFFF or csize == 0xFFFFFFFF:
                    extra = cd[pos + 46 + name_len : pos + 46 + name_len + extra_len]
                    usize, csize, local_offset = _zip64_extra(extra, usize, csize, local_offset)
                return local_offset, csize, usize, method

            pos += 46 + name_len + extra_len + comment_len

        raise ProbeFailed("Info.plist not found in the archive's central directory")

    def read_info_plist(self) -> dict[str, Any]:
        local_offset, csize, _usize, method = self._locate_member(_INFO_PLIST_RE)

        header = self._range(local_offset, local_offset + 29)
        name_len, extra_len = struct.unpack("<HH", header[26:30])
        data_start = local_offset + 30 + name_len + extra_len
        raw = self._range(data_start, data_start + csize - 1)

        if method == 0:
            payload = raw
        elif method == 8:
            payload = zlib.decompress(raw, -zlib.MAX_WBITS)
        else:
            raise ProbeFailed(f"unsupported ZIP compression method {method}")

        return plistlib.load(io.BytesIO(payload))


def _zip64_extra(
    extra: bytes, usize: int, csize: int, local_offset: int
) -> tuple[int, int, int]:
    """Pull the real 64-bit values out of the ZIP64 extra field."""
    pos = 0
    while pos + 4 <= len(extra):
        header_id, data_size = struct.unpack("<HH", extra[pos : pos + 4])
        body = extra[pos + 4 : pos + 4 + data_size]
        if header_id == 0x0001:
            values = list(struct.unpack(f"<{len(body) // 8}Q", body[: len(body) // 8 * 8]))
            if usize == 0xFFFFFFFF and values:
                usize = values.pop(0)
            if csize == 0xFFFFFFFF and values:
                csize = values.pop(0)
            if local_offset == 0xFFFFFFFF and values:
                local_offset = values.pop(0)
            break
        pos += 4 + data_size
    return usize, csize, local_offset


# ---------------------------------------------------------------- driver

def inspect(
    url: str, metadata: dict[str, Any] | None = None, allow_full_download: bool = False
) -> BuildInfo:
    """Cheapest available answer for one build."""
    metadata = metadata or {}

    if (min_os := from_metadata(metadata)) is not None:
        return BuildInfo(
            minimum_os=min_os,
            display_version=str(metadata.get("bundleShortVersionString", "")),
            device_families=[],
            source="metadata",
        )

    try:
        plist = RemoteZip(url).read_info_plist()
        return _from_plist(plist, source="range")
    except ProbeFailed:
        if not allow_full_download:
            raise

    return _from_plist(_full_download_plist(url), source="download")


def _from_plist(plist: dict[str, Any], source: str) -> BuildInfo:
    return BuildInfo(
        minimum_os=str(plist.get("MinimumOSVersion", "0")),
        display_version=str(plist.get("CFBundleShortVersionString", "")),
        device_families=[int(f) for f in plist.get("UIDeviceFamily", [])],
        source=source,
    )


def from_ipa_file(path) -> BuildInfo:
    """Read a build's requirements out of an IPA already on disk."""
    import zipfile

    with zipfile.ZipFile(path) as zf:
        name = next(
            (n for n in zf.namelist() if _INFO_PLIST_RE.match(n.encode())), None
        )
        if name is None:
            raise ProbeFailed(f"no app Info.plist inside {path}")
        return _from_plist(plistlib.loads(zf.read(name)), source="ipa")


def _full_download_plist(url: str) -> dict[str, Any]:
    import tempfile
    import zipfile

    with tempfile.NamedTemporaryFile(suffix=".ipa") as tmp:
        with requests.get(url, stream=True, timeout=600) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_content(chunk_size=1 << 20):
                tmp.write(chunk)
        tmp.flush()
        with zipfile.ZipFile(tmp.name) as zf:
            name = next(
                (n for n in zf.namelist() if _INFO_PLIST_RE.match(n.encode())), None
            )
            if name is None:
                raise ProbeFailed("no Info.plist in downloaded IPA")
            return plistlib.loads(zf.read(name))
