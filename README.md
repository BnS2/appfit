# appfit

[![CI](https://github.com/BnS2/appfit/actions/workflows/ci.yml/badge.svg)](https://github.com/BnS2/appfit/actions/workflows/ci.yml)

**Find a historical App Store build that fits an older iPhone or iPad, download
the account-owned package, and optionally install it over USB.** No jailbreak or
third-party IPA archive is required.

appfit has two related flows:

- `appfit get` claims a free app licence on the selected Apple ID and prints the
  standard Purchased-tab steps. Apple may then offer its own last-compatible
  version. appfit cannot guarantee that offer: the app must still be available,
  the account must be eligible, and Apple must retain a compatible build.
- `appfit install` resolves a historical build, downloads the intact encrypted
  store IPA for that Apple ID, verifies its declared iOS/device-family support,
  and hands it unchanged to iOS Installation Proxy over USB.

### What v0.2 actually verified

On 2026-08-31, an iPad 5 (`iPad6,11`) running iOS 16.7.16 was rebooted out of
Dopamine jailbreak mode. The current Termius release required iOS 17. appfit:

1. read the 277-build history through the account's App Store session;
2. selected Termius v6.3.0, whose plist declares minimum iOS 16.0 and iPhone/iPad
   device families;
3. downloaded only that winning FairPlay-bound IPA;
4. installed it through stock iOS Installation Proxy; and
5. launched it successfully, as confirmed on the device.

FAST Speed Test was also installed and launched through the same stock-device
path. These tests prove the flow on that device and those apps; they do not
promise that every App Store title retains a compatible historical build.

## Install

appfit currently installs from source and requires Python 3.10 or newer:

```bash
git clone https://github.com/BnS2/appfit.git
cd appfit
python3 -m venv .venv
source .venv/bin/activate
pip install -e .              # licence, lookup, resolve, and download
pip install -e '.[device]'    # optional: USB detection and direct install

brew install go               # one-time build dependency for optimized ipatool
appfit ipatool install        # pinned official source + appfit metadata patch
appfit ipatool status
```

`appfit ipatool install` builds official ipatool v2.4.0 at its immutable source
commit and stores the result under `~/.config/appfit/tools/`. It verifies the
commit before applying appfit's bundled patch, and Go verifies dependencies
against upstream's `go.sum`; appfit does not download an opaque helper binary.
The source revision is pinned, but builds are not promised to be byte-for-byte
identical across different Go toolchains or operating systems.

If Go is unavailable, `brew install ipatool` remains a supported fallback. It
can claim and download apps normally, but cold compatibility searches may need
full candidate IPA downloads. `APPFIT_IPATOOL=/path/to/ipatool` explicitly
overrides both the managed helper and PATH lookup.

Direct installation additionally needs the target device connected over USB,
unlocked, and trusted by the computer. The cable-free `get --ios` flow does not
need the `[device]` extra or a connected device.

## Use

```bash
appfit accounts use <apple-id>      # sign in (password + 2FA go to ipatool)
appfit get <app> --ios 16.7.16      # claim the licence
appfit get <app> --device <udid>    # or read the iOS version off the device
appfit download <app> --device <udid> # fetch and verify the fitting IPA
appfit install <app> --device <udid>  # fetch and install it over USB

appfit devices                      # USB devices: model, iOS, UDID
appfit pair <udid> --account <email>
appfit search "termius"
appfit resolve <app> --ios 16.7.16  # which build exactly?
appfit cache export > seed.json     # share account-free resolution data
appfit cache import seed.json
appfit cache prune                  # dry-run: show unreferenced IPA downloads
appfit cache prune --yes            # permanently delete the reviewed files
appfit ipatool status               # helper path and fast-probe capability
```

`<app>` accepts a bundle ID, numeric App Store ID, store URL, or a search term.

## Whose Apple ID?

**The one signed into the target device.** Not yours, unless it is your device.

Apple gates the older-version offer on that account's purchase history, and
FairPlay binds the binary to that account. Claiming a licence on your own Apple
ID for a friend's iPad means their app depends on your account for every future
update, and account sharing breaks Apple's terms.

`ipatool` holds one session at a time. For `--device` operations, appfit records
which Apple ID that device belongs to and **refuses to act when a different
account is signed in** rather than quietly claiming a licence on it:

```
✗ signed in as me@example.com, but this device is paired to them@example.com.
  Switch with:  appfit accounts use them@example.com
```

For the same reason, an app matched by fuzzy text search must be confirmed before
a licence is claimed — the store returns a plausible result for almost any
string, and a claim is permanent.

With `--ios` and no connected device, appfit cannot discover the device's Apple
ID. It uses the explicit `--account` value or, if omitted, the account currently
signed into ipatool. The user is responsible for choosing the account that is
actually used on the target device.

Direct USB install does not bypass FairPlay. ipatool downloads the account's
encrypted store package, including `iTunesMetadata.plist` and the app's
`SC_Info/*.sinf`; appfit verifies its OS/device-family requirements and hands it
unchanged to iOS Installation Proxy. A stock iPad accepts that package without
AppSync because it remains Apple-signed and licensed to the device's account.

## Why it drives ipatool instead of speaking the protocol

Apple's App Store requests require authenticated signing that appfit does not
implement. appfit delegates account login, licence claims, build history, and
downloads to ipatool. appfit owns identifier resolution, device detection,
account/device safeguards, compatibility search, local verification, and cache
management.

**The upstream cost of that choice:** released ipatool does not expose the
signed download URL or the historical build's minimum OS, so compatibility
would normally need candidate IPA downloads. appfit's managed helper adds the
two metadata fields to ipatool's existing partial-ZIP response; the ordinary
release remains supported as a slower fallback.

## Historical build resolution

`get` is cheap because it only claims the free licence; it does not prove that a
compatible historical build exists. `resolve` answers the separate question
"*which* build fits?". v2 searches release dates first, then verifies the result:

- The verified Termius history contained 277 builds. With appfit's managed
  helper, the logarithmic search uses small partial-ZIP metadata requests and
  normally downloads only the selected IPA. An ordinary upstream ipatool binary
  remains supported, but may require roughly a dozen full candidate downloads.
- Results are cached in `~/.config/appfit/cache.json`, keyed by
  (bundle ID, iOS version, platform), alongside immutable build metadata. The
  file contains no credentials, Apple ID, or session data, but it does reveal
  app bundle IDs and target versions; review it before sharing.
- Downloaded IPAs are kept in `~/.config/appfit/ipa/` so a later install
  reuses them.
- The command warns and asks before a cold lookup.

### Cache maintenance

`appfit cache prune` lists appfit-downloaded IPAs that no cached resolution
references. It is always a dry-run unless `--yes` is supplied. Referenced
winning builds, files modified within the last five minutes, symlinks, and files
that do not follow appfit's naming scheme are protected. Before deletion, appfit
rechecks the cache and file identity so a build that became referenced or was
replaced after the dry-run is skipped. If `cache.json` is corrupt or uses an
unknown schema, prune fails closed and deletes nothing.

```bash
appfit cache prune                 # inspect candidates; deletes nothing
appfit cache prune --min-age 30    # ignore files newer than 30 minutes
appfit cache prune --yes           # permanent deletion after review
```

`appfit cache clear` removes resolution metadata only; it intentionally leaves
IPAs untouched. A later prune will treat those now-unreferenced appfit IPAs as
candidates, so export useful metadata before clearing it.

`probe.py` still contains a working, tested HTTP-Range reader that pulls
`Info.plist` out of a remote IPA without downloading it (a few hundred KB instead
of hundreds of MB). It is unused against Apple only because there is no URL to
point it at. If the signing is ever implemented, the cheap path is already built.

Current ipatool already range-reads each historical IPA's `Info.plist` for
display version and release date, but does not expose the `MinimumOSVersion` or
`UIDeviceFamily` values it read. appfit bundles a minimal source patch and a
pinned source-build installer:

```bash
appfit ipatool install
appfit ipatool status
appfit install <app> --device <udid>
```

The managed binary is preferred automatically. This is the path used to resolve
Termius from 277 historical builds: eight partial `Info.plist` probes, one full
download for the winning v6.3.0 IPA, then stock-device installation. The
regular Homebrew binary remains supported and falls back to full IPA probes.

## Limitations

- Apple controls licence eligibility, historical-build retention, and the
  Purchased-tab last-compatible-version offer. appfit cannot create a build or
  force an offer when Apple does not provide one.
- Removed, paid, region-restricted, account-ineligible, or never-compatible apps
  may fail before resolution or installation.
- `MinimumOSVersion` and `UIDeviceFamily` catch most incompatibility, but RAM,
  GPU and Metal requirements are not declared in `Info.plist` — a build can
  resolve as compatible and still run badly on an A9. Treat the answer as the
  best candidate, not a guarantee.
- The build search assumes minimum OS is non-decreasing over a title's history.
  It usually is; appfit checks the next three builds for a nearby reversal, but
  it cannot prove compatibility across an arbitrarily non-monotonic history.
- Some apps have never shipped a build for your device's iOS. appfit says so
  plainly instead of leaving you hunting mirrors.
- Direct USB install is deliberately gated on a device↔Apple-ID pairing. Store
  IPAs remain FairPlay-bound to the licensing account; pairing the wrong account
  can produce an app that installs but cannot launch.

## Roadmap

- **v1** — accounts, pairing, device detection, licence claim, build
  resolution. Stock-safe, no USB required.
- **v2 (now)** — release-date-seeded resolution, platform/family checks, cache
  sharing, and `download`/`install` over USB via pymobiledevice3. Verified through
  stock iOS Installation Proxy with an intact FairPlay-signed store IPA; no
  AppSync or jailbreak service is required.
- **v3** — a Mac GUI over this core.

Only user-licensed store IPAs, using the account that legitimately owns them. No
decrypted IPAs, no DRM circumvention.

appfit is an independent project and is not affiliated with or endorsed by
Apple Inc.

## License

[MIT](LICENSE)

## Tests

```bash
pytest              # 80 tests
pytest -m "not network"
```

The ZIP range reader is tested against a synthetic IPA served by a local
range-capable HTTP server, and the build search against fake histories — so both
run without credentials or network.
