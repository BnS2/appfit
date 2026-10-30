from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "verify_macos_signature",
    Path(__file__).parents[1] / "scripts" / "verify_macos_signature.py",
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

DETAILS = (
    "CodeDirectory v=20500 size=100 flags=0x10000(runtime) hashes=1+1 location=embedded\n"
    "Authority=Developer ID Application: Example (EXAMPLETEAM)\n"
    "Timestamp=Oct 30, 2026 at 8:00:00 AM\n"
    "TeamIdentifier=EXAMPLETEAM\n"
)


def test_timestamped_developer_id_and_hardened_runtime_pass():
    module.validate_details(DETAILS, "EXAMPLETEAM")


@pytest.mark.parametrize("old,new", [
    ("Authority=Developer ID Application:", "Authority=Apple Development:"),
    ("TeamIdentifier=EXAMPLETEAM", "TeamIdentifier=OTHERTEAM"),
    ("Timestamp=", "Signed Time="),
    ("flags=0x10000(runtime)", "flags=0x2(adhoc)"),
])
def test_public_signature_gate_rejects_incomplete_signing(old, new):
    with pytest.raises(ValueError, match="release app needs"):
        module.validate_details(DETAILS.replace(old, new), "EXAMPLETEAM")


@pytest.mark.parametrize("status", ["Invalid", "In Progress", None])
def test_unaccepted_notary_report_blocks_release(tmp_path, status):
    report = tmp_path / "notary.json"
    report.write_text(json.dumps({"status": status}))
    with pytest.raises(ValueError, match="not accepted"):
        module.validate_notarization(report)


def test_apple_acceptance_report_passes(tmp_path):
    report = tmp_path / "notary.json"
    report.write_text('{"id": "example-submission", "status": "Accepted"}')
    module.validate_notarization(report)
