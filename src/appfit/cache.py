"""On-disk cache of resolved builds and build release dates.

Probing a build's minimum OS costs at least one authenticated round-trip and, in
the worst case, a full IPA download -- so results are worth keeping. The cache
contains no credentials, Apple ID, or App Store session data, though exported
files do reveal bundle IDs and target versions. See `export_entries` and
`import_entries`.

Two sections:

* `entries`  -- (bundle id, iOS version, platform) -> the build that fits. The
  platform is part of the key because the store ships different binaries for
  iPhone and iPad and they do not have the same compatibility history.
* `versions` -- (bundle id, external version id) -> display version and release
  date. Immutable facts, and what lets a second resolve of the same title for a
  different iOS target skip the metadata round-trips entirely.
"""

from __future__ import annotations

import json
import re
import stat
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .accounts import config_dir
from .devices import DEFAULT_PLATFORM

SCHEMA = 2
_MANAGED_IPA = re.compile(r"^.+-\d+\.ipa$")


class CacheSafetyError(RuntimeError):
    """Pruning cannot prove which IPA files are still referenced."""


@dataclass
class Resolved:
    bundle_id: str
    ios_version: str
    external_version_id: str
    display_version: str
    minimum_os: str
    resolved_at: str
    platform: str = DEFAULT_PLATFORM


@dataclass
class VersionMeta:
    display_version: str
    release_date: str  # ISO date, "" when the store did not say
    minimum_os: str = ""
    device_families: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class PruneCandidate:
    path: Path
    size: int
    modified_ns: int
    inode: int


def _path() -> Path:
    return config_dir() / "cache.json"


def _empty() -> dict:
    return {"schema": SCHEMA, "entries": {}, "versions": {}}


def _migrate(data: dict) -> dict:
    """Bring an older cache file forward, keeping what it already paid for.

    Discarding on a schema bump would throw away exactly the expensive data --
    resolutions that cost hundreds of megabytes to obtain. Schema 1 keyed
    entries by (bundle, iOS) and always meant the iPad binary, because that is
    what v1 hardcoded, so the platform can be filled in rather than guessed.
    """
    version = data.get("schema")
    if version == SCHEMA:
        data.setdefault("entries", {})
        data.setdefault("versions", {})
        return data
    if version == 1:
        migrated = _empty()
        for entry in (data.get("entries") or {}).values():
            try:
                entry = {**entry, "platform": DEFAULT_PLATFORM}
                resolved = Resolved(**entry)
            except TypeError:
                continue
            migrated["entries"][_key(resolved.bundle_id, resolved.ios_version, resolved.platform)] = asdict(resolved)
        return migrated
    # Unknown or future schema: start clean rather than misread it.
    return _empty()


def _read() -> dict:
    f = _path()
    if not f.exists():
        return _empty()
    try:
        data = json.loads(f.read_text())
    except json.JSONDecodeError:
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    return _migrate(data)


def _write(data: dict) -> None:
    _path().write_text(json.dumps(data, indent=2, sort_keys=True))


def _key(bundle_id: str, ios_version: str, platform: str) -> str:
    return f"{bundle_id}@{ios_version}@{platform}"


# ----------------------------------------------------------------- entries

def get(bundle_id: str, ios_version: str, platform: str = DEFAULT_PLATFORM) -> Resolved | None:
    entry = _read()["entries"].get(_key(bundle_id, ios_version, platform))
    return Resolved(**entry) if entry else None


def put(resolved: Resolved) -> None:
    data = _read()
    data["entries"][_key(resolved.bundle_id, resolved.ios_version, resolved.platform)] = asdict(resolved)
    _write(data)


def record(
    bundle_id: str,
    ios_version: str,
    external_version_id: str,
    display_version: str,
    minimum_os: str,
    platform: str = DEFAULT_PLATFORM,
) -> Resolved:
    resolved = Resolved(
        bundle_id=bundle_id,
        ios_version=ios_version,
        external_version_id=external_version_id,
        display_version=display_version,
        minimum_os=minimum_os,
        resolved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        platform=platform,
    )
    put(resolved)
    return resolved


def clear() -> None:
    _path().unlink(missing_ok=True)


def entries() -> list[Resolved]:
    return [Resolved(**e) for e in _read()["entries"].values()]


# -------------------------------------------------------------- IPA files

def _referenced_ipa_names() -> set[str]:
    """Exact filenames protected by the cache, failing closed if it is unsafe."""
    source = _path()
    if not source.exists():
        return set()
    try:
        data = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CacheSafetyError(
            f"cannot safely prune because {source} is unreadable or invalid"
        ) from exc
    if not isinstance(data, dict) or data.get("schema") not in {1, SCHEMA}:
        raise CacheSafetyError(
            f"cannot safely prune because {source} has an unsupported schema"
        )

    raw_entries = data.get("entries", {})
    if not isinstance(raw_entries, dict):
        raise CacheSafetyError(
            f"cannot safely prune because {source} has malformed entries"
        )

    protected = set()
    for raw in raw_entries.values():
        if not isinstance(raw, dict):
            raise CacheSafetyError(
                f"cannot safely prune because {source} has a malformed entry"
            )
        bundle_id = raw.get("bundle_id")
        version_id = raw.get("external_version_id")
        if not isinstance(bundle_id, str) or not isinstance(version_id, str):
            raise CacheSafetyError(
                f"cannot safely prune because {source} has a malformed entry"
            )
        protected.add(f"{bundle_id}-{version_id}.ipa")
    return protected


def prune_candidates(
    directory: Path,
    *,
    minimum_age_seconds: int = 300,
    now: float | None = None,
) -> list[PruneCandidate]:
    """Plan removal of old, managed-looking IPAs not used by any resolution.

    Symlinks and unrelated files are never candidates. Recent files are left
    alone so a concurrent ipatool download cannot be mistaken for stale data.
    """
    if minimum_age_seconds < 0:
        raise ValueError("minimum_age_seconds cannot be negative")
    if not directory.is_dir():
        return []

    protected = _referenced_ipa_names()
    current_time = time.time() if now is None else now
    candidates: list[PruneCandidate] = []
    for path in directory.iterdir():
        if path.name in protected or not _MANAGED_IPA.fullmatch(path.name):
            continue
        try:
            info = path.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        if current_time - info.st_mtime < minimum_age_seconds:
            continue
        candidates.append(
            PruneCandidate(
                path=path,
                size=info.st_size,
                modified_ns=info.st_mtime_ns,
                inode=info.st_ino,
            )
        )
    return sorted(candidates, key=lambda candidate: candidate.path.name)


def prune_ipas(directory: Path, candidates: list[PruneCandidate]) -> tuple[int, int]:
    """Delete a previously reviewed plan, returning (files, bytes).

    Cache references and file identity are checked again immediately before
    deletion. Files replaced or newly referenced since the dry-run are skipped.
    """
    protected = _referenced_ipa_names()
    removed_files = 0
    removed_bytes = 0
    for candidate in candidates:
        path = candidate.path
        if path.parent != directory or path.name in protected:
            continue
        if not _MANAGED_IPA.fullmatch(path.name):
            continue
        try:
            current = path.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(current.st_mode):
            continue
        if (
            current.st_ino != candidate.inode
            or current.st_mtime_ns != candidate.modified_ns
            or current.st_size != candidate.size
        ):
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed_files += 1
        removed_bytes += candidate.size
    return removed_files, removed_bytes


# ---------------------------------------------------------------- versions

def get_version(bundle_id: str, version_id: str) -> VersionMeta | None:
    meta = _read()["versions"].get(bundle_id, {}).get(str(version_id))
    return VersionMeta(**meta) if meta else None


def put_version(
    bundle_id: str,
    version_id: str,
    display_version: str,
    release_date: str,
    minimum_os: str = "",
    device_families: list[int] | None = None,
) -> None:
    data = _read()
    data["versions"].setdefault(bundle_id, {})[str(version_id)] = asdict(
        VersionMeta(
            display_version=display_version,
            release_date=release_date,
            minimum_os=minimum_os,
            device_families=device_families or [],
        )
    )
    _write(data)


def version_count(bundle_id: str) -> int:
    return len(_read()["versions"].get(bundle_id, {}))


def known_version_ids(bundle_id: str) -> list[str]:
    """Build identifiers appfit has already seen for `bundle_id`, newest first.

    Only useful as *seeds*: any one of them can be handed back to the store to
    re-read the full history when the current build is refused. Newest first
    because a recent build is the most likely to still be served, and because
    the identifiers are assigned in ascending order.
    """
    known = _read()["versions"].get(bundle_id, {})
    resolved = _read()["entries"]
    seeds = set(known)
    for entry in resolved.values():
        if entry.get("bundle_id") == bundle_id and entry.get("external_version_id"):
            seeds.add(str(entry["external_version_id"]))
    return sorted(seeds, key=lambda value: (len(value), value), reverse=True)


# ------------------------------------------------------------------ share

def export_entries() -> dict:
    """Return account-free build facts; callers should review app IDs before sharing."""
    return _read()


def import_entries(incoming: dict) -> tuple[int, int]:
    """Merge a shared cache in. Returns (resolutions added, versions added).

    Existing local entries win: a resolution this machine verified itself is
    better evidence than one that arrived in a file.
    """
    data = _read()
    merged = _migrate(incoming if isinstance(incoming, dict) else {})

    added_entries = 0
    for key, entry in merged["entries"].items():
        if key not in data["entries"]:
            data["entries"][key] = entry
            added_entries += 1

    added_versions = 0
    for bundle_id, builds in merged["versions"].items():
        local = data["versions"].setdefault(bundle_id, {})
        for version_id, meta in builds.items():
            if version_id not in local:
                local[version_id] = meta
                added_versions += 1

    _write(data)
    return added_entries, added_versions
