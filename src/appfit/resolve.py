"""Find the newest build of an app that a given iOS version can actually run.

Apple exposes every build an account is entitled to, oldest first -- a title
like Prime Video has ~370 of them. Binary search cuts that to ~9 probes.

That matters more than it looks, because a probe is expensive here. ipatool
does not expose the signed download URL (see store.py), so establishing a
build's MinimumOSVersion means downloading the IPA. Hence:

  * results are cached, and the cache is safe to share -- nothing in it is
    account-specific;
  * the probe is injected rather than assumed, so a caller with a cheaper
    source (a signed URL and probe.RemoteZip, a seeded cache) can supply it;
  * callers are expected to warn before a cold resolve.

In phase 2 the cost largely disappears: an install downloads an IPA anyway, so
the probe that identified the build is the same fetch that installs it.

Assumption: MinimumOSVersion is non-decreasing across a title's history. That is
how releases normally go but nothing enforces it, so after the search converges
we scan a few builds forward to catch a lowered deployment target.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from . import cache
from .probe import BuildInfo

# How far past the binary-search result to check for non-monotonic bumps.
FORWARD_SCAN = 3

Probe = Callable[[str], BuildInfo]


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
) -> Resolution:
    if use_cache and (hit := cache.get(bundle_id, ios_version)):
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

    # Fast path: if the current build runs, there was never anything to resolve.
    if check(len(version_ids) - 1).runs_on(ios_version):
        best = len(version_ids) - 1
    else:
        if not check(0).runs_on(ios_version):
            raise NoCompatibleBuild(
                f"{bundle_id} has never shipped a build supporting iOS "
                f"{ios_version} — its oldest build needs iOS "
                f"{seen[version_ids[0]].minimum_os}"
            )

        # Invariant: version_ids[lo] runs, version_ids[hi] does not.
        lo, hi = 0, len(version_ids) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if check(mid).runs_on(ios_version):
                lo = mid
            else:
                hi = mid
        best = lo

        # Guard the monotonicity assumption.
        for offset in range(1, FORWARD_SCAN + 1):
            ahead = best + offset
            if ahead >= len(version_ids):
                break
            if check(ahead).runs_on(ios_version):
                best = ahead

    info = seen[version_ids[best]]
    cache.record(
        bundle_id=bundle_id,
        ios_version=ios_version,
        external_version_id=version_ids[best],
        display_version=info.display_version,
        minimum_os=info.minimum_os,
    )
    return Resolution(
        external_version_id=version_ids[best],
        display_version=info.display_version,
        minimum_os=info.minimum_os,
        probes=probes,
        from_cache=False,
        source=info.source,
    )


def download_probe(client, bundle_id: str, workdir, platform: str = "ipad") -> Probe:
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
            client.download(bundle_id, dest, version_id=version_id, platform=platform)
        return from_ipa_file(dest)

    return _probe
