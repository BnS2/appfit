"""Verify the runtime and CA store that a Mac bundle actually loads."""

from __future__ import annotations

import hashlib
import re
import ssl
import sys
from pathlib import Path

import certifi


_DISTRUSTED_ROOTS = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
    "bc4d809b15189d78db3e1d8cf4f9726a795da1643ca5f1358e1ddb0edc0d7eb3",
}


def check() -> dict[str, str]:
    if (
        sys.version_info[:2] != (3, 12)
        or sys.version_info < (3, 12, 16)
        or sys.version_info.releaselevel != "final"
    ):
        raise RuntimeError("Mac bundles require final Python 3.12.16 or newer in 3.12")
    version = certifi.__version__
    if (
        not re.fullmatch(r"\d{4}\.\d{1,2}\.\d{1,2}", version)
        or tuple(map(int, version.split("."))) < (2026, 10, 19)
    ):
        raise RuntimeError("Mac bundles require certifi 2026.10.19 or newer; refresh Requests")
    ca_file = Path(certifi.where())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(ca_file))
    fingerprints = {
        hashlib.sha256(der).hexdigest()
        for der in context.get_ca_certs(binary_form=True)
    }
    if fingerprints & _DISTRUSTED_ROOTS:
        raise RuntimeError("certifi still trusts distrusted emSign ECC G3/C3 roots")
    return {
        "python": ".".join(map(str, sys.version_info[:3])),
        "certifi": version,
        "ca_sha256": hashlib.sha256(ca_file.read_bytes()).hexdigest(),
    }
