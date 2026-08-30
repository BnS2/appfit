"""On-disk cache of resolved builds.

Probing a build's minimum OS costs at least one authenticated round-trip and, in
the worst case, a full IPA download -- so results are worth keeping. The cache is
keyed by (bundle id, target iOS version) because that pair is what actually
determines the answer, and is shareable between machines: nothing in here is
account-specific or sensitive.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .accounts import config_dir

SCHEMA = 1


@dataclass
class Resolved:
    bundle_id: str
    ios_version: str
    external_version_id: str
    display_version: str
    minimum_os: str
    resolved_at: str


def _path() -> Path:
    return config_dir() / "cache.json"


def _read() -> dict:
    f = _path()
    if not f.exists():
        return {"schema": SCHEMA, "entries": {}}
    try:
        data = json.loads(f.read_text())
    except json.JSONDecodeError:
        return {"schema": SCHEMA, "entries": {}}
    if data.get("schema") != SCHEMA:
        return {"schema": SCHEMA, "entries": {}}
    return data


def _key(bundle_id: str, ios_version: str) -> str:
    return f"{bundle_id}@{ios_version}"


def get(bundle_id: str, ios_version: str) -> Resolved | None:
    entry = _read()["entries"].get(_key(bundle_id, ios_version))
    return Resolved(**entry) if entry else None


def put(resolved: Resolved) -> None:
    data = _read()
    data["entries"][_key(resolved.bundle_id, resolved.ios_version)] = asdict(resolved)
    _path().write_text(json.dumps(data, indent=2, sort_keys=True))


def record(
    bundle_id: str,
    ios_version: str,
    external_version_id: str,
    display_version: str,
    minimum_os: str,
) -> Resolved:
    resolved = Resolved(
        bundle_id=bundle_id,
        ios_version=ios_version,
        external_version_id=external_version_id,
        display_version=display_version,
        minimum_os=minimum_os,
        resolved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    put(resolved)
    return resolved


def clear() -> None:
    _path().unlink(missing_ok=True)


def entries() -> list[Resolved]:
    return [Resolved(**e) for e in _read()["entries"].values()]
