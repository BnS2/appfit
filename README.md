# appfit

Install an account-owned historical App Store build that still fits an older
iPhone or iPad. appfit uses Apple's store package and stock iOS installation;
it does not require a decrypted IPA, AppSync, or an active jailbreak.

> **Current status:** appfit's command-line modes are available in v0.2 and
> tested on macOS with an iPad 5 (`iPad6,11`) running iOS 16.7.16. The v0.3
> source now includes a Mac compatible-build finder GUI; a signed downloadable
> GUI release has not been published yet.

## What problem does it solve?

An app's current release may require a newer iOS version even though older,
compatible builds still exist in its App Store history. Getting one onto an
older device involves several separate jobs:

1. use the Apple ID that belongs to the target device;
2. claim the free app licence if the account does not own it;
3. find the newest historical build whose declared requirements fit;
4. download that account's intact, encrypted store IPA; and
5. optionally install it over USB.

appfit coordinates those jobs and refuses a device operation when the active
Apple ID does not match the account paired to that device.

Apple still controls app availability, licence eligibility, historical-build
retention, and its on-device last-compatible-version offer. appfit cannot create
a missing build or force Apple to offer one.

## Choose a mode

appfit offers two command-line modes and a Mac GUI over the same compatibility,
account-safety, download, and installation backend.

| Mode or interface | Status | USB | What it does |
|---|---|---:|---|
| **Licence mode** | Available | Not required | Claims a free licence and prints Apple's Purchased-tab steps. Apple may offer its last compatible build on the device. |
| **Direct Install mode** | Available | Required | Resolves, downloads, verifies, and installs the fitting store IPA directly. |
| **Mac GUI** | Available in v0.3 source | Optional by task | Searches by name or identifier, detects or accepts a target iOS version, recommends the newest compatible build, lazily offers older builds, and exposes the existing actions. |

For the most predictable working path today, use Direct Install mode with a Mac
and USB cable.

## Install on a Mac

### Requirements

- macOS with Terminal
- Python 3.10 or newer
- Go (`brew install go` if needed)
- for Direct Install mode: the iPhone or iPad unlocked, connected by USB, and
  trusted by the Mac
- the Apple ID currently used for App Store purchases on that device

### Recommended: install the v0.2 release

1. Download `appfit-0.2.0-py3-none-any.whl` from the
   [v0.2.0 GitHub Release](https://github.com/BnS2/appfit/releases/tag/v0.2.0).
2. Open Terminal and run:

```bash
mkdir -p "$HOME/appfit"
cd "$HOME/appfit"

python3 -m venv .venv
source .venv/bin/activate
pip install "$HOME/Downloads/appfit-0.2.0-py3-none-any.whl[device]"

appfit ipatool install
appfit ipatool status
```

If the browser saved the wheel somewhere else, replace the path after
`pip install` with that location.

The `[device]` extra installs USB support. For Licence mode only, omit `[device]`
when installing the wheel:

```bash
pip install "$HOME/Downloads/appfit-0.2.0-py3-none-any.whl"
```

When opening a new Terminal later, return to the appfit folder and reactivate the
environment:

```bash
cd "$HOME/appfit"
source .venv/bin/activate
```

### Run the v0.3 GUI from source

Until signed GUI artifacts are published, developers can run it from a checkout:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[gui]"
.venv/bin/appfit ipatool install
.venv/bin/appfit-gui
```

The GUI has one primary flow:

1. check the compact App Store, Apple ID, and device readiness strip;
2. select a connected device to detect iOS automatically, or choose **Manual
   iOS target** and type a version such as `16.7.16`;
3. search by app name, bundle ID, numeric App Store ID, or App Store URL, then
   select the matching artwork-backed result;
4. confirm the account-owned licence lookup and accept the recommended newest
   compatible build;
5. optionally load older verified versions in pages of ten; and
6. install over USB, download the selected encrypted IPA, or show the
   licence-only on-device instructions.

The focused workspace keeps progress concise by default, with full activity
details available on demand. Command-F focuses search and Command-R refreshes
account and device readiness.

Historical build lookup requires the active Apple ID and may add a free app to
that account's Purchased history. appfit confirms this before resolving. The
password and two-factor prompt still run directly in ipatool's Terminal session,
so the GUI does not receive or store either value.

## First-time account setup

Sign into ipatool with the same Apple ID used by the target device:

```bash
appfit accounts use you@example.com
appfit accounts whoami
```

The password and two-factor prompt belong to ipatool. appfit stores the email
used for device pairing, not the password or App Store session.

## Use Licence mode: claim, then install on-device

Use this path when you want Apple to perform the download on the device and do
not need appfit to identify or install the exact historical build.

```bash
appfit get <exact-bundle-id> --ios 16.7.16 --platform ipad
```

appfit claims the free licence and prints the Purchased-tab steps. Apple may
offer an older compatible version there. This offer is not guaranteed.

If you do not know the bundle ID:

```bash
appfit search "termius"
```

Use the exact bundle ID from the result when claiming a licence. Text-search
matches require confirmation because a licence claim changes purchase history.

## Use Direct Install mode: install over USB

### 1. Find the device

```bash
appfit devices
```

Copy the displayed UDID.

### 2. Verify and pair its Apple ID

Check the App Store account on the device itself, then record that relationship:

```bash
appfit pair <udid> --account you@example.com
appfit accounts list
```

Pairing is a safety assertion made by the user; appfit cannot read the device's
App Store email automatically.

### 3. Install an exact app

```bash
appfit install <exact-bundle-id> --device <udid>
```

appfit will:

- reject the operation if the signed-in account does not match the pairing;
- claim the free licence if needed;
- select the newest build matching iOS and device family;
- download and locally verify the winning IPA; and
- upload and install it through stock iOS Installation Proxy.

Useful variants:

```bash
appfit resolve <exact-bundle-id> --device <udid>   # identify the fitting build
appfit download <exact-bundle-id> --device <udid>  # download without installing
```

## Command guide

| Command | Purpose |
|---|---|
| `appfit search <words>` | Find an App Store title and bundle ID. |
| `appfit accounts use <email>` | Sign into ipatool interactively. |
| `appfit accounts whoami` | Show the active store account. |
| `appfit devices` | List connected USB devices, iOS versions, and UDIDs. |
| `appfit pair <udid> --account <email>` | Record the device/account safety pairing. |
| `appfit get <app> --ios <version>` | Claim a free licence and print on-device steps. |
| `appfit resolve <app> --device <udid>` | Find the newest compatible historical build. |
| `appfit download <app> --device <udid>` | Resolve, download, and verify an IPA. |
| `appfit install <app> --device <udid>` | Resolve, download, verify, and install over USB. |
| `appfit cache prune` | Dry-run a cleanup of unreferenced IPA downloads. |
| `appfit ipatool status` | Show which ipatool helper appfit selected. |

`<app>` may be a bundle ID, numeric App Store ID, App Store URL, or search term.
Use an exact identifier for licence-changing commands whenever possible.

## What does appfit wrap?

appfit is the safety and compatibility layer around three lower-level pieces:

| Component | appfit uses it for |
|---|---|
| **Apple's public iTunes Search API** | App lookup, current version, and current minimum iOS. |
| **ipatool** | Apple-ID login, signed App Store requests, free licence claims, build history, metadata, and IPA downloads. |
| **pymobiledevice3** | USB discovery, trusted-device connection, IPA upload, and iOS Installation Proxy. |

The optimized helper installed by `appfit ipatool install` builds official
ipatool v2.4.0 at a pinned commit and applies appfit's small metadata patch. The
patch exposes `MinimumOSVersion` and `UIDeviceFamily` from ipatool's existing
partial-ZIP read, so appfit normally downloads only the winning IPA.

`brew install ipatool` is supported as a fallback, but the unpatched release may
need full candidate IPA downloads during a cold resolve. Set
`APPFIT_IPATOOL=/path/to/ipatool` to choose a specific binary explicitly.

## What Direct Install mode verified

On 2026-08-31, the test iPad was rebooted out of Dopamine jailbreak mode. appfit
resolved a 277-build Termius history, selected v6.3.0 (minimum iOS 16.0, iPhone
and iPad families), downloaded only that build, installed it through stock iOS,
and the user confirmed it launched. FAST Speed Test was also installed and
launched through the same path.

That verifies the mechanism on those apps and that device. It does not guarantee
that every app has a compatible build or that declared compatibility covers RAM,
GPU, Metal, server-side, or account restrictions.

## Cache and disk space

Resolved builds are stored in `~/.config/appfit/cache.json`. Downloaded IPAs are
stored in `~/.config/appfit/ipa/` and reused by later commands.

```bash
appfit cache list
appfit cache export > seed.json
appfit cache import seed.json

appfit cache prune          # dry-run; deletes nothing
appfit cache prune --yes    # permanently delete the displayed candidates
```

Prune protects referenced winners, recent files, symlinks, unrelated filenames,
and files that changed after the dry-run. It fails closed if the cache cannot be
read safely. `cache clear` removes metadata only; it does not delete IPAs.

Exported cache metadata contains no password, Apple ID, or App Store session,
but it does reveal app bundle IDs and target versions. Review it before sharing.

## What appfit does not do

- It does not decrypt IPAs or bypass FairPlay.
- It does not make random third-party IPA downloads safe or account-compatible.
- It does not bypass paid-app, region, removal, or account eligibility rules.
- It cannot guarantee Apple's on-device older-version offer.
- It checks declared iOS/device-family compatibility, not every hardware or
  server-side runtime requirement.
- Its historical search assumes minimum iOS usually rises over time and checks
  only the next three builds for a nearby reversal.

## Downloads and project information

Download appfit from [GitHub Releases](https://github.com/BnS2/appfit/releases).
appfit is not currently published on PyPI.

See [CHANGELOG.md](CHANGELOG.md) for release history, [SECURITY.md](SECURITY.md)
for private security reporting, and [CONTRIBUTING.md](CONTRIBUTING.md) if you
want to work on appfit itself.

appfit is independent and is not affiliated with or endorsed by Apple Inc.

## License

[MIT](LICENSE)
