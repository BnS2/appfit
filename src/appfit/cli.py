"""appfit command line."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from . import accounts, cache, devices, toolchain
from .apps import App, AppNotFound, resolve as resolve_app, search as search_apps
from .install import InstallError, install as install_ipa
from .ios_releases import successors
from .probe import BuildInfo, ProbeFailed, from_ipa_file, version_tuple
from .resolve import (
    NoCompatibleBuild,
    Resolution,
    date_hint,
    download_probe,
    estimate_probes,
    metadata_probe,
    newest_compatible,
)
from .workflows import refusal_message
from .store import (
    BuildNotServed,
    IpatoolMissing,
    StoreClient,
    StoreError,
    login_interactively,
)

app = typer.Typer(
    help="Get modern apps onto aged-out iOS devices.",
    no_args_is_help=True,
    add_completion=False,
)
accounts_app = typer.Typer(help="Apple ID logins.", no_args_is_help=True)
cache_app = typer.Typer(help="Resolved-build cache.", no_args_is_help=True)
ipatool_app = typer.Typer(help="Manage the App Store protocol helper.", no_args_is_help=True)
app.add_typer(accounts_app, name="accounts")
app.add_typer(cache_app, name="cache")
app.add_typer(ipatool_app, name="ipatool")


def _err(message: str) -> None:
    """Fail with an explanation that can run to more than one line.

    Some store failures need a paragraph to be actionable, so continuation
    lines are indented under the marker instead of starting at column zero and
    reading as separate errors.
    """
    headline, _, rest = message.partition("\n")
    typer.secho(f"✗ {headline}", fg=typer.colors.RED, err=True)
    for line in rest.splitlines():
        typer.secho(f"  {line}" if line.strip() else "", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _ok(message: str) -> None:
    typer.secho(f"✓ {message}", fg=typer.colors.GREEN)


def _warn(message: str) -> None:
    typer.secho(f"! {message}", fg=typer.colors.YELLOW)


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def ipa_dir() -> Path:
    d = accounts.config_dir() / "ipa"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------- ipatool

@ipatool_app.command("status")
def ipatool_status() -> None:
    """Show which ipatool appfit will use and whether fast probes are enabled."""
    current = toolchain.status()
    if current.path is None:
        typer.echo("ipatool is not installed")
        typer.echo("  install optimized helper: appfit ipatool install")
        raise typer.Exit(1)

    typer.echo(f"  path    {current.path}")
    typer.echo(f"  source  {current.source}")
    if current.version:
        typer.echo(f"  version {current.version}")
    if current.compatibility_metadata is True:
        _ok("compatibility metadata enabled — historical probes use partial ZIP reads")
    else:
        _warn(
            "compatibility metadata not guaranteed — cold resolution may download "
            "candidate IPAs"
        )
        typer.echo("  optimize with: appfit ipatool install")


@ipatool_app.command("install")
def ipatool_install(
    force: bool = typer.Option(False, "--force", help="Rebuild an existing helper"),
) -> None:
    """Build appfit's pinned compatibility-aware ipatool from official source."""
    try:
        destination = toolchain.install_managed_ipatool(
            force=force,
            on_step=lambda message: typer.echo(f"  {message}…"),
        )
    except toolchain.ToolchainError as exc:
        _err(f"could not install optimized ipatool: {exc}")
    _ok(f"optimized ipatool ready at {destination}")


# --------------------------------------------------------------- accounts

@accounts_app.command("use")
def accounts_use(email: str) -> None:
    """Sign in as an Apple ID (hands off to ipatool for password and 2FA)."""
    try:
        code = login_interactively(email)
    except IpatoolMissing as exc:
        _err(str(exc))
    if code != 0:
        _err("login failed")
    accounts.remember(email)
    _ok(f"signed in as {email}")


@accounts_app.command("whoami")
def accounts_whoami() -> None:
    """Show which Apple ID is currently signed in."""
    try:
        active = StoreClient().active_account()
    except IpatoolMissing as exc:
        _err(str(exc))
    typer.echo(str(active) if active else "not signed in")


@accounts_app.command("list")
def accounts_list() -> None:
    """Show known Apple IDs and their paired devices."""
    try:
        active = StoreClient().active_account()
    except IpatoolMissing as exc:
        _err(str(exc))
    active_email = active.email.lower() if active else ""

    known = accounts.known_accounts()
    if active and active.email not in known:
        known = sorted({*known, active.email})
    if not known:
        typer.echo("no accounts known — run: appfit accounts use <email>")
        return

    paired = accounts.pairings()
    for email in known:
        marker = "→" if email.lower() == active_email else " "
        bound = [u for u, e in paired.items() if e == email]
        suffix = f"  ({len(bound)} device(s) paired)" if bound else ""
        typer.echo(f" {marker} {email}{suffix}")
    typer.echo("\n  → = currently signed in")


@accounts_app.command("forget")
def accounts_forget(email: str) -> None:
    """Forget an Apple ID and its pairings (does not sign out of ipatool)."""
    _ok(f"forgot {email}") if accounts.forget(email) else _err(f"{email} is not known")


# ---------------------------------------------------------------- devices

@app.command("devices")
def devices_cmd() -> None:
    """List iOS devices connected over USB."""
    try:
        found = devices.connected()
    except devices.DeviceError as exc:
        _err(str(exc))
    if not found:
        typer.echo("no devices connected over USB")
        return
    paired = accounts.pairings()
    for d in found:
        typer.echo(
            f"  {d}\n    udid    {d.udid}\n"
            f"    account {paired.get(d.udid, '(unpaired)')}"
        )


@app.command("pair")
def pair_cmd(udid: str, email: str = typer.Option(..., "--account", "-a")) -> None:
    """Bind a device to the Apple ID signed in ON THAT DEVICE.

    Not your Apple ID unless it is your device: a licence claimed on the wrong
    account ties that app to the wrong purchase history for every future update.
    """
    accounts.pair(udid, email)
    _ok(f"{udid} → {email}")


# ------------------------------------------------------------------ lookup

@app.command("search")
def search_cmd(term: str, limit: int = 10) -> None:
    """Search the App Store."""
    for found in search_apps(term, limit=limit):
        typer.echo(
            f"  {found.name}\n    {found.bundle_id}  id {found.app_id}  "
            f"v{found.current_version}  needs iOS {found.minimum_os}"
        )


def _target(
    device: str | None,
    ios: str | None,
    platform: str = devices.DEFAULT_PLATFORM,
) -> tuple[devices.Target, str | None]:
    """Return the build target and the device's paired account, if any."""
    if device:
        try:
            found = devices.get(device)
        except devices.DeviceError as exc:
            _err(str(exc))
        if found is None:
            _err(f"device {device} is not connected")
        _ok(f"device  {found}")
        return found.target(), accounts.account_for_device(device)
    if ios:
        if platform not in {"ipad", "iphone"}:
            _err("--platform must be ipad or iphone")
        return devices.Target.from_ios(ios, platform), None
    _err("give either --device <udid> or --ios <version>")


def _lookup(query: str) -> App:
    try:
        return resolve_app(query)
    except AppNotFound as exc:
        _err(str(exc))


def _client_for(email: str | None) -> tuple[StoreClient, str]:
    """A client guaranteed to be operating as the intended account."""
    try:
        client = StoreClient()
        active = client.active_account()
    except IpatoolMissing as exc:
        _err(str(exc))

    if email is None:
        if active is None:
            _err("not signed in — run: appfit accounts use <email>")
        email = active.email
    try:
        client.require_account(email)
    except StoreError as exc:
        _err(str(exc))
    return client, email


def _confirm_claim(store_app: App, query: str, yes: bool) -> None:
    """Require confirmation before a fuzzy match changes purchase history."""
    if store_app.matched_exactly or yes:
        return
    typer.echo(f"  matched by search from {query!r}, by {store_app.seller}")
    if not typer.confirm("  Claim a licence for this app?", default=False):
        raise typer.Exit(0)


def _download_progress():
    """A low-noise byte callback for ipatool's otherwise silent downloads."""
    last_bytes = 0
    last_bucket = -1

    def report(current: int) -> None:
        nonlocal last_bytes, last_bucket
        if current < last_bytes:
            last_bucket = -1  # A new candidate download started.
        last_bytes = current
        bucket = current // (10 * 1024 * 1024)
        if current and bucket > last_bucket:
            typer.echo(f"    downloaded {current / 1024 / 1024:.0f} MB…")
            last_bucket = bucket

    return report


def _version_ids(client: StoreClient, store_app: App) -> list[str]:
    """History for `store_app`, recovered from a known build if need be.

    Mirrors BuildWorkflow._version_ids: the store hides an app's history behind
    the build it will serve, so a refused current build hides the older builds
    too unless appfit re-reads the list off one it already knows.
    """
    bundle_id = store_app.bundle_id
    try:
        return client.version_ids(bundle_id)
    except BuildNotServed:
        for seed in cache.known_version_ids(bundle_id):
            try:
                recovered = client.version_ids_from(bundle_id, seed)
            except (BuildNotServed, StoreError):
                continue
            if recovered:
                _warn(
                    "the store is not serving this app's current build; "
                    "read its history from a build appfit already knows"
                )
                return recovered
        _err(refusal_message(store_app))


def _do_resolve(
    client: StoreClient,
    store_app: App,
    target: devices.Target,
    yes: bool,
) -> Resolution:
    cached = cache.get(store_app.bundle_id, target.ios_version, target.platform)
    if cached is not None:
        result = Resolution(
            external_version_id=cached.external_version_id,
            display_version=cached.display_version,
            minimum_os=cached.minimum_os,
            probes=0,
            from_cache=True,
            source="cache",
        )
        _ok(
            f"newest compatible build → {result.display_version} "
            f"(min iOS {result.minimum_os}, ext id "
            f"{result.external_version_id}) [cached]"
        )
        return result

    try:
        version_ids = _version_ids(client, store_app)
    except StoreError as exc:
        _err(str(exc))

    worst = estimate_probes(len(version_ids))
    _warn(
        f"cold lookup: {len(version_ids)} builds exist. appfit will first "
        f"use release dates to narrow the search, then verify candidate IPAs "
        f"(up to ~{worst} downloads when deployment-target changes do not "
        f"track release dates)."
    )
    if not yes and not typer.confirm("  Continue?", default=False):
        raise typer.Exit(0)

    try:
        cutoffs = successors(target.ios_version, count=1)
        hint = None
        if cutoffs:
            hint = date_hint(
                client,
                store_app.bundle_id,
                cutoffs[0],
                on_step=lambda n, msg: typer.echo(f"    date {n}: {msg}"),
            )
        full_probe = download_probe(
            client,
            store_app.bundle_id,
            ipa_dir(),
            target.platform,
            on_progress=_download_progress(),
        )
        result = newest_compatible(
            store_app.bundle_id,
            target.ios_version,
            version_ids,
            probe=metadata_probe(client, store_app.bundle_id, full_probe),
            on_probe=lambda n, msg: typer.echo(f"    probe {n}: {msg}"),
            hint=hint,
            target=target,
            latest_info=(
                BuildInfo(
                    minimum_os=store_app.minimum_os,
                    display_version=store_app.current_version,
                    device_families=[],
                    source="store",
                )
                if version_tuple(store_app.minimum_os)
                > version_tuple(target.ios_version)
                else None
            ),
        )
    except (NoCompatibleBuild, ProbeFailed) as exc:
        _err(str(exc))
    except StoreError as exc:
        _err(str(exc))

    if result.from_cache:
        origin = "cached"
    elif result.source == "metadata":
        origin = f"{result.probes} range probes"
    else:
        origin = f"{result.probes} IPA probes"
    _ok(
        f"newest compatible build → {result.display_version} "
        f"(min iOS {result.minimum_os}, ext id {result.external_version_id}) [{origin}]"
    )
    return result


def _prepare_ipa(
    query: str,
    target: devices.Target,
    account: str | None,
    yes: bool,
) -> tuple[App, Path, str, Resolution]:
    """Claim, select, fetch, and locally verify one target-compatible IPA."""
    store_app = _lookup(query)
    _ok(f"app     {store_app.name} ({store_app.bundle_id})")
    _confirm_claim(store_app, query, yes)

    client, email = _client_for(account)
    _ok(f"account {email}")
    try:
        claimed = client.purchase(store_app.bundle_id)
        _ok("licence claimed" if claimed else "licence already held by this account")

        result = _do_resolve(client, store_app, target, yes)
        destination = ipa_dir() / (
            f"{store_app.bundle_id}-{result.external_version_id}.ipa"
        )
        if destination.exists():
            _ok(f"IPA     reused {destination.name}")
        else:
            client.download(
                store_app.bundle_id,
                destination,
                platform=target.platform,
                version_id=result.external_version_id,
                on_progress=_download_progress(),
            )
            _ok(f"IPA     downloaded {destination.name}")

        info = from_ipa_file(destination)
    except (StoreError, ProbeFailed) as exc:
        _err(str(exc))

    if not info.fits(target):
        _err(
            f"downloaded build does not fit {target.platform} on iOS "
            f"{target.ios_version} (build needs iOS {info.minimum_os}, "
            f"families {info.device_families or 'unknown'})"
        )
    _ok(
        f"verified v{info.display_version} for {target.platform} on iOS "
        f"{target.ios_version}"
    )
    return store_app, destination, email, result


@app.command("resolve")
def resolve_cmd(
    query: str,
    ios: str = typer.Option(None, "--ios", help="Target iOS version, e.g. 16.7.16"),
    device: str = typer.Option(None, "--device", "-d", help="UDID of a connected device"),
    platform: str = typer.Option("ipad", "--platform", help="ipad or iphone with --ios"),
    account: str = typer.Option(None, "--account", "-a"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cost warning"),
) -> None:
    """Report the newest build of an app that a given iOS version can run."""
    target, paired = _target(device, ios, platform)
    store_app = _lookup(query)
    typer.echo(
        f"  {store_app.name} — current v{store_app.current_version} "
        f"needs iOS {store_app.minimum_os}"
    )

    if version_tuple(store_app.minimum_os) <= version_tuple(target.ios_version):
        _ok(
            f"current build already runs on iOS {target.ios_version} "
            "— nothing to resolve"
        )
        return

    client, _ = _client_for(account or paired)
    _do_resolve(client, store_app, target, yes)


@app.command("get")
def get_cmd(
    query: str,
    ios: str = typer.Option(None, "--ios"),
    device: str = typer.Option(None, "--device", "-d"),
    platform: str = typer.Option("ipad", "--platform", help="ipad or iphone with --ios"),
    account: str = typer.Option(None, "--account", "-a"),
    version: bool = typer.Option(
        False, "--version-too",
        help="Also identify the exact build (may download candidate IPAs)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Claim the licence so the device can install an older compatible build.

    This is the headline command, and on its own it costs nothing but a couple
    of API calls: claiming the licence is what makes Apple offer the device a
    compatible build. Identifying which build that will be is optional.
    """
    target, paired = _target(device, ios, platform)
    store_app = _lookup(query)
    _ok(f"app     {store_app.name} ({store_app.bundle_id})")

    _confirm_claim(store_app, query, yes)

    client, email = _client_for(account or paired)
    _ok(f"account {email}")

    try:
        claimed = client.purchase(store_app.bundle_id)
    except StoreError as exc:
        _err(f"could not claim licence: {exc}")
    _ok("licence claimed" if claimed else "licence already held by this account")

    if version_tuple(store_app.minimum_os) <= version_tuple(target.ios_version):
        _ok(
            f"current build v{store_app.current_version} runs on iOS "
            f"{target.ios_version}"
        )
        typer.echo("\n→ On the device: App Store ▸ search the app ▸ install as normal.")
        return

    if version:
        _do_resolve(client, store_app, target, yes)

    typer.echo(
        f"\n→ On the device, signed in as {email}:\n"
        "  App Store ▸ your avatar ▸ Purchased ▸ Not on this Device\n"
        f"  ▸ {store_app.name} ▸ ☁️\n"
        '  Accept "Download an older version compatible with this device?"'
    )


# --------------------------------------------------------- download/install

@app.command("download")
def download_cmd(
    query: str,
    ios: str = typer.Option(None, "--ios", help="Target iOS version"),
    device: str = typer.Option(None, "--device", "-d"),
    platform: str = typer.Option("ipad", "--platform", help="ipad or iphone with --ios"),
    account: str = typer.Option(None, "--account", "-a"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Download and verify the newest build that fits a target."""
    target, paired = _target(device, ios, platform)
    _, destination, _, _ = _prepare_ipa(
        query,
        target,
        account or paired,
        yes,
    )
    typer.echo(f"\n→ {destination}")


@app.command("install")
def install_cmd(
    query: str,
    device: str = typer.Option(..., "--device", "-d", help="UDID of a connected device"),
    account: str = typer.Option(None, "--account", "-a"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Claim, download, verify, and install an app over USB."""
    target, paired = _target(device, None)
    if paired is None:
        _err(
            f"device {device} is not paired to its Apple ID. Run:\n"
            f"  appfit pair {device} --account <email>"
        )
    if account is not None and account.lower() != paired.lower():
        _err(
            f"--account {account} does not match this device's paired account "
            f"{paired}"
        )

    store_app, destination, _, _ = _prepare_ipa(query, target, paired, yes)
    last_bucket = -1

    def progress(percent: int) -> None:
        nonlocal last_bucket
        bucket = int(percent) // 10
        if bucket > last_bucket:
            typer.echo(f"    install {int(percent)}%…")
            last_bucket = bucket

    try:
        install_ipa(device, destination, on_progress=progress)
    except (devices.DeviceSupportUnavailable, InstallError) as exc:
        _err(str(exc))
    _ok(f"installed {store_app.name}")


# ------------------------------------------------------------------ cache

@cache_app.command("list")
def cache_list() -> None:
    """Show cached resolutions."""
    rows = cache.entries()
    if not rows:
        typer.echo("cache is empty")
        return
    for row in rows:
        typer.echo(
            f"  {row.bundle_id} @ {row.platform} iOS {row.ios_version} "
            f"→ v{row.display_version} "
            f"(min {row.minimum_os}, ext {row.external_version_id})"
        )


@cache_app.command("export")
def cache_export() -> None:
    """Write the shareable cache as JSON to stdout."""
    typer.echo(json.dumps(cache.export_entries(), indent=2, sort_keys=True))


@cache_app.command("import")
def cache_import(source: Path = typer.Argument(..., help="JSON file, or - for stdin")) -> None:
    """Merge resolutions and immutable build dates from another cache."""
    try:
        raw = sys.stdin.read() if str(source) == "-" else source.read_text()
        incoming = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        _err(f"could not read cache: {exc}")
    entries_added, versions_added = cache.import_entries(incoming)
    _ok(
        f"imported {entries_added} resolution(s) and "
        f"{versions_added} build date(s)"
    )


@cache_app.command("clear")
def cache_clear() -> None:
    """Empty resolution metadata. Downloaded IPAs are left untouched."""
    cache.clear()
    _ok("cache cleared")


@cache_app.command("prune")
def cache_prune(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Permanently delete the displayed files instead of a dry-run",
    ),
    min_age: int = typer.Option(
        5,
        "--min-age",
        min=0,
        help="Ignore files modified within this many minutes",
    ),
) -> None:
    """Find unreferenced appfit-downloaded IPAs; dry-run unless --yes is given."""
    directory = ipa_dir()
    try:
        candidates = cache.prune_candidates(
            directory,
            minimum_age_seconds=min_age * 60,
        )
    except cache.CacheSafetyError as exc:
        _err(str(exc))
    if not candidates:
        _ok("no unreferenced IPA files to prune")
        return

    total = sum(candidate.size for candidate in candidates)
    typer.echo(
        f"  {len(candidates)} unreferenced IPA file(s), {_format_bytes(total)}"
    )
    for candidate in candidates[:20]:
        typer.echo(f"    {_format_bytes(candidate.size):>10}  {candidate.path.name}")
    if len(candidates) > 20:
        typer.echo(f"    …and {len(candidates) - 20} more")

    if not yes:
        _warn("dry run — nothing was deleted")
        typer.echo("  Review the list, then rerun with --yes to delete permanently.")
        return

    try:
        removed_files, removed_bytes = cache.prune_ipas(directory, candidates)
    except cache.CacheSafetyError as exc:
        _err(str(exc))
    _ok(f"pruned {removed_files} IPA file(s), {_format_bytes(removed_bytes)}")
    if removed_files != len(candidates):
        _warn(
            f"skipped {len(candidates) - removed_files} file(s) that changed or "
            "became referenced"
        )


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
