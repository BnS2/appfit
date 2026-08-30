"""appfit command line."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from . import accounts, cache, devices
from .apps import App, AppNotFound, resolve as resolve_app, search as search_apps
from .probe import version_tuple
from .resolve import (
    NoCompatibleBuild,
    download_probe,
    estimate_probes,
    newest_compatible,
)
from .store import IpatoolMissing, StoreClient, StoreError, login_interactively

app = typer.Typer(
    help="Get modern apps onto aged-out iOS devices.",
    no_args_is_help=True,
    add_completion=False,
)
accounts_app = typer.Typer(help="Apple ID logins.", no_args_is_help=True)
cache_app = typer.Typer(help="Resolved-build cache.", no_args_is_help=True)
app.add_typer(accounts_app, name="accounts")
app.add_typer(cache_app, name="cache")


def _err(message: str) -> None:
    typer.secho(f"✗ {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _ok(message: str) -> None:
    typer.secho(f"✓ {message}", fg=typer.colors.GREEN)


def _warn(message: str) -> None:
    typer.secho(f"! {message}", fg=typer.colors.YELLOW)


def ipa_dir() -> Path:
    d = accounts.config_dir() / "ipa"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
    except devices.DeviceSupportUnavailable as exc:
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


def _target(device: str | None, ios: str | None) -> tuple[str, str | None]:
    """Returns (ios_version, paired_account_email)."""
    if device:
        try:
            found = devices.get(device)
        except devices.DeviceSupportUnavailable as exc:
            _err(str(exc))
        if found is None:
            _err(f"device {device} is not connected")
        _ok(f"device  {found}")
        return found.ios_version, accounts.account_for_device(device)
    if ios:
        return ios, None
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


def _do_resolve(
    client: StoreClient, target: App, ios_version: str, yes: bool
) -> None:
    version_ids = client.version_ids(target.bundle_id)

    if not cache.get(target.bundle_id, ios_version):
        worst = estimate_probes(len(version_ids))
        _warn(
            f"cold lookup: identifying the right build means downloading up to "
            f"~{worst} candidate IPAs ({len(version_ids)} builds exist).\n"
            f"  Apple's own Purchased-tab prompt picks the build for free — this "
            f"is only worth it if you need the version number."
        )
        if not yes and not typer.confirm("  Continue?", default=False):
            raise typer.Exit(0)

    try:
        result = newest_compatible(
            target.bundle_id,
            ios_version,
            version_ids,
            probe=download_probe(client, target.bundle_id, ipa_dir()),
            on_probe=lambda n, msg: typer.echo(f"    probe {n}: {msg}"),
        )
    except NoCompatibleBuild as exc:
        _err(str(exc))
    except StoreError as exc:
        _err(str(exc))

    origin = "cached" if result.from_cache else f"{result.probes} downloads"
    _ok(
        f"newest compatible build → {result.display_version} "
        f"(min iOS {result.minimum_os}, ext id {result.external_version_id}) [{origin}]"
    )


@app.command("resolve")
def resolve_cmd(
    query: str,
    ios: str = typer.Option(None, "--ios", help="Target iOS version, e.g. 16.7.16"),
    device: str = typer.Option(None, "--device", "-d", help="UDID of a connected device"),
    account: str = typer.Option(None, "--account", "-a"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cost warning"),
) -> None:
    """Report the newest build of an app that a given iOS version can run."""
    ios_version, paired = _target(device, ios)
    target = _lookup(query)
    typer.echo(
        f"  {target.name} — current v{target.current_version} needs iOS {target.minimum_os}"
    )

    if version_tuple(target.minimum_os) <= version_tuple(ios_version):
        _ok(f"current build already runs on iOS {ios_version} — nothing to resolve")
        return

    client, _ = _client_for(account or paired)
    _do_resolve(client, target, ios_version, yes)


@app.command("get")
def get_cmd(
    query: str,
    ios: str = typer.Option(None, "--ios"),
    device: str = typer.Option(None, "--device", "-d"),
    account: str = typer.Option(None, "--account", "-a"),
    version: bool = typer.Option(
        False, "--version-too",
        help="Also identify the exact build (downloads candidate IPAs)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Claim the licence so the device can install an older compatible build.

    This is the headline command, and on its own it costs nothing but a couple
    of API calls: claiming the licence is what makes Apple offer the device a
    compatible build. Identifying which build that will be is optional.
    """
    ios_version, paired = _target(device, ios)
    target = _lookup(query)
    _ok(f"app     {target.name} ({target.bundle_id})")

    # The store returns a match for almost any text, so a typo can otherwise
    # claim a licence for an unrelated app -- which stays in the purchase
    # history permanently. Identifiers (bundle ID, numeric ID, store URL) are
    # unambiguous and skip this.
    if not target.matched_exactly and not yes:
        typer.echo(f"  matched by search from {query!r}, by {target.seller}")
        if not typer.confirm("  Claim a licence for this app?", default=False):
            raise typer.Exit(0)

    client, email = _client_for(account or paired)
    _ok(f"account {email}")

    try:
        claimed = client.purchase(target.bundle_id)
    except StoreError as exc:
        _err(f"could not claim licence: {exc}")
    _ok("licence claimed" if claimed else "licence already held by this account")

    if version_tuple(target.minimum_os) <= version_tuple(ios_version):
        _ok(f"current build v{target.current_version} runs on iOS {ios_version}")
        typer.echo("\n→ On the device: App Store ▸ search the app ▸ install as normal.")
        return

    if version:
        _do_resolve(client, target, ios_version, yes)

    typer.echo(
        f"\n→ On the device, signed in as {email}:\n"
        "  App Store ▸ your avatar ▸ Purchased ▸ Not on this Device\n"
        f"  ▸ {target.name} ▸ ☁️\n"
        '  Accept "Download an older version compatible with this device?"'
    )


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
            f"  {row.bundle_id} @ iOS {row.ios_version} → v{row.display_version} "
            f"(min {row.minimum_os}, ext {row.external_version_id})"
        )


@cache_app.command("clear")
def cache_clear() -> None:
    """Empty the cache."""
    cache.clear()
    _ok("cache cleared")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
