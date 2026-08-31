"""Find the newest build of an app that a given iOS version can actually run.

Apple exposes every build an account is entitled to, oldest first -- a title
like Prime Video has ~370 of them. Binary search makes the number logarithmic.

That matters because the cost of a probe depends on the installed helper.
appfit's managed ipatool emits compatibility values from a partial ZIP read;
ordinary upstream ipatool does not, so establishing a build's MinimumOSVersion
then means downloading the IPA. Hence:

  * results are cached, and the cache is safe to share -- nothing in it is
    account-specific;
  * the probe is injected rather than assumed, so metadata, a signed URL and
    probe.RemoteZip, a seeded cache, or the full-IPA fallback can supply it;
  * release-date metadata can seed the lower bound, but is never trusted as a
    compatibility answer;
  * callers are expected to warn before a cold resolve.

Assumption: MinimumOSVersion is non-decreasing across a title's history. That is
how releases normally go but nothing enforces it, so after the search converges
we scan a few builds forward to catch a lowered deployment target.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import time
from typing import Callable, Sequence

from . import cache
from .devices import DEFAULT_PLATFORM, Target
from .probe import BuildInfo

# How far past the binary-search result to check for non-monotonic bumps.
FORWARD_SCAN = 3

Probe = Callable[[str], BuildInfo]
Hint = Callable[[Sequence[str]], int | None]


class NoCompatibleBuild(RuntimeError):
    """Not even the oldest build runs on this device."""


@dataclass
class Resolution:
    external_version_id: str
    display_version: str
    minimum_os: str
    probes: int
    from_cache: bool
    source: str

    def __str__(self) -> str:
        return f"{self.display_version} (min iOS {self.minimum_os})"


def estimate_probes(build_count: int) -> int:
    """Worst-case probe count, for warning the user before a cold resolve."""
    if build_count <= 1:
        return build_count
    import math

    return 2 + math.ceil(math.log2(build_count)) + FORWARD_SCAN


def newest_compatible(
    bundle_id: str,
    ios_version: str,
    version_ids: Sequence[str],
    probe: Probe,
    on_probe: Callable[[int, str], None] | None = None,
    use_cache: bool = True,
    hint: Hint | None = None,
    target: Target | None = None,
    latest_info: BuildInfo | None = None,
) -> Resolution:
    platform = target.platform if target else DEFAULT_PLATFORM
    if use_cache and (hit := cache.get(bundle_id, ios_version, platform)):
        return Resolution(
            external_version_id=hit.external_version_id,
            display_version=hit.display_version,
            minimum_os=hit.minimum_os,
            probes=0,
            from_cache=True,
            source="cache",
        )

    if not version_ids:
        raise NoCompatibleBuild(f"the store lists no builds for {bundle_id}")

    probes = 0
    seen: dict[str, BuildInfo] = {}
    if latest_info is not None:
        seen[version_ids[-1]] = latest_info

    def check(index: int) -> BuildInfo:
        nonlocal probes
        version_id = version_ids[index]
        if version_id not in seen:
            seen[version_id] = probe(version_id)
            probes += 1
            if on_probe:
                info = seen[version_id]
                on_probe(
                    probes,
                    f"{info.display_version or version_id} → min iOS {info.minimum_os}",
                )
        return seen[version_id]

    def fits(info: BuildInfo) -> bool:
        return info.fits(target) if target else info.runs_on(ios_version)

    # Fast path: if the current build runs, there was never anything to resolve.
    if fits(check(len(version_ids) - 1)):
        best = len(version_ids) - 1
    else:
        # Establish a compatible lower bound. A dated candidate is only a
        # starting point; probing remains the source of truth. If it fits, the
        # oldest build never needs downloading at all.
        lo: int | None = None
        hi = len(version_ids) - 1
        if hint is not None:
            hinted = hint(version_ids)
            if hinted is not None and 0 <= hinted < hi:
                if fits(check(hinted)):
                    lo = hinted
                else:
                    hi = hinted

        if lo is None:
            if not fits(check(0)):
                raise NoCompatibleBuild(
                    f"{bundle_id} has never shipped a build supporting iOS "
                    f"{ios_version} — its oldest build needs iOS "
                    f"{seen[version_ids[0]].minimum_os}"
                )
            lo = 0

        # Invariant: version_ids[lo] fits, version_ids[hi] does not.
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if fits(check(mid)):
                lo = mid
            else:
                hi = mid
        best = lo

        # Guard the monotonicity assumption.
        for offset in range(1, FORWARD_SCAN + 1):
            ahead = best + offset
            if ahead >= len(version_ids):
                break
            if fits(check(ahead)):
                best = ahead

    info = seen[version_ids[best]]
    cache.record(
        bundle_id=bundle_id,
        ios_version=ios_version,
        external_version_id=version_ids[best],
        display_version=info.display_version,
        minimum_os=info.minimum_os,
        platform=platform,
    )
    return Resolution(
        external_version_id=version_ids[best],
        display_version=info.display_version,
        minimum_os=info.minimum_os,
        probes=probes,
        from_cache=False,
        source=info.source,
    )


def date_hint(
    client,
    bundle_id: str,
    cutoff: date,
    on_step: Callable[[int, str], None] | None = None,
) -> Hint:
    """Return a cheap release-date search to seed the expensive build search.

    The returned function finds the newest build released before ``cutoff``.
    Store metadata is cached because release dates are immutable and safe to
    share. Any malformed or unavailable response returns no hint; compatibility
    probing then falls back to the normal full-range binary search.
    """

    steps = 0

    def metadata(version_id: str):
        nonlocal steps
        if hit := cache.get_version(bundle_id, version_id):
            return hit

        for attempt in range(2):
            try:
                raw = client.version_metadata(bundle_id, version_id)
                cache.put_version(
                    bundle_id,
                    version_id,
                    raw.get("display_version", ""),
                    raw.get("release_date", ""),
                    raw.get("minimum_os", ""),
                    raw.get("device_families", []),
                )
                return cache.VersionMeta(
                    display_version=raw.get("display_version", ""),
                    release_date=raw.get("release_date", ""),
                    minimum_os=raw.get("minimum_os", ""),
                    device_families=raw.get("device_families", []),
                )
            except Exception:  # Store failures are advisory on this path.
                if attempt == 0:
                    time.sleep(0.25)
        return None

    def find(version_ids: Sequence[str]) -> int | None:
        nonlocal steps
        if not version_ids:
            return None

        lo, hi = 0, len(version_ids)
        while lo < hi:
            mid = (lo + hi) // 2
            meta = metadata(version_ids[mid])
            steps += 1
            if meta is None:
                return None
            try:
                released = date.fromisoformat(meta.release_date)
            except (TypeError, ValueError):
                return None
            if on_step:
                label = meta.display_version or version_ids[mid]
                on_step(steps, f"{label} → {released.isoformat()}")
            if released < cutoff:
                lo = mid + 1
            else:
                hi = mid
        return lo - 1 if lo else None

    return find


def metadata_probe(client, bundle_id: str, fallback: Probe) -> Probe:
    """Use ipatool's partial Info.plist read when compatibility is exposed.

    The released binary currently discards these fields, in which case one
    observed metadata response disables this path for the rest of the resolve
    and the full-download probe remains authoritative.
    """

    def probe(version_id: str) -> BuildInfo:
        supported = getattr(client, "compatibility_metadata_supported", None)
        if supported is False:
            return fallback(version_id)

        hit = cache.get_version(bundle_id, version_id)
        if hit is not None and hit.minimum_os:
            return BuildInfo(
                minimum_os=hit.minimum_os,
                display_version=hit.display_version,
                device_families=hit.device_families,
                source="metadata",
            )

        try:
            raw = client.version_metadata(bundle_id, version_id)
        except Exception:
            return fallback(version_id)

        cache.put_version(
            bundle_id,
            version_id,
            raw.get("display_version", ""),
            raw.get("release_date", ""),
            raw.get("minimum_os", ""),
            raw.get("device_families", []),
        )
        if raw.get("minimum_os"):
            return BuildInfo(
                minimum_os=raw["minimum_os"],
                display_version=raw.get("display_version", ""),
                device_families=raw.get("device_families", []),
                source="metadata",
            )
        return fallback(version_id)

    return probe


def download_probe(
    client,
    bundle_id: str,
    workdir,
    platform: str,
    on_progress: Callable[[int], None] | None = None,
) -> Probe:
    """A probe that downloads each candidate build and reads its Info.plist.

    The expensive path, and currently the only one that works against Apple.
    Downloaded IPAs are kept in `workdir` so a later install can reuse them
    instead of fetching the same bytes twice.
    """
    from pathlib import Path

    from .probe import from_ipa_file

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    def _probe(version_id: str) -> BuildInfo:
        dest = workdir / f"{bundle_id}-{version_id}.ipa"
        if not dest.exists():
            client.download(
                bundle_id,
                dest,
                platform=platform,
                version_id=version_id,
                on_progress=on_progress,
            )
        return from_ipa_file(dest)

    return _probe
