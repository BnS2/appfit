# appfit

Find and install the newest App Store version that still works on an older
iPhone or iPad.

When an app's current release requires a newer iOS version, a compatible build
may still exist in its App Store history. appfit finds that build, verifies that
it fits the target device, and can download or install it using the Apple ID
that owns the app.

## What appfit can do

- Search the App Store by name, bundle ID, numeric ID, or App Store URL.
- Detect a connected device and its iOS version, or use a manual iOS target.
- Recommend the newest compatible historical build.
- Browse older verified builds in small pages.
- Claim a free app licence and show Apple's on-device installation steps.
- Download and locally verify an exact encrypted store IPA.
- Install the selected build over USB on a trusted device.
- Reuse verified downloads and manage cached build data.
- Run through a Mac GUI or command-line interface.

## Choose the use case that fits

| Use case | USB | Choose it when… |
|---|---:|---|
| **Mac GUI** | Optional | You want a guided way to search, compare compatible versions, download, or install from one window. |
| **Licence mode** | No | You want to add a free app to Purchased history and let the device request Apple's compatible version. |
| **Direct Install mode** | Yes | You want appfit to find, download, verify, and install the exact compatible build. |

## Requirements

- macOS
- Python 3.10 or newer
- Go, used to build appfit's compatible ipatool helper
- The Apple ID used for App Store purchases on the target device
- For USB installation: an unlocked, connected, and trusted iPhone or iPad

Install Go with Homebrew if needed:

```bash
brew install go
```

## Install appfit

Download `appfit-0.3.0-py3-none-any.whl` from
[GitHub Releases](https://github.com/BnS2/appfit/releases), then create a Python
environment:

```bash
mkdir -p "$HOME/appfit"
cd "$HOME/appfit"
python3 -m venv .venv
source .venv/bin/activate
```

For the Mac GUI:

```bash
pip install "$HOME/Downloads/appfit-0.3.0-py3-none-any.whl[gui]"
appfit ipatool install
appfit-gui
```

The GUI currently launches from Terminal. A signed and notarized `.app` bundle
is not yet distributed.

For the command line with USB device support:

```bash
pip install "$HOME/Downloads/appfit-0.3.0-py3-none-any.whl[device]"
appfit ipatool install
```

For Licence mode only, install the wheel without an extra:

```bash
pip install "$HOME/Downloads/appfit-0.3.0-py3-none-any.whl"
appfit ipatool install
```

If the wheel is somewhere else, replace the path in the install command. When
returning later, reactivate the environment with:

```bash
cd "$HOME/appfit"
source .venv/bin/activate
```

## Use the Mac GUI

1. Launch `appfit-gui`.
2. Select a connected device, or enter a manual iOS version and device family.
3. Search for an app and select the correct result.
4. Choose **Find newest compatible version** and confirm the Apple ID action.
5. Install over USB, download the IPA, or show the licence-only instructions.

The GUI can load older compatible versions after the recommendation. Password
and two-factor prompts stay in ipatool's Terminal session; appfit does not
receive or store those secrets.

## Use Licence mode

Choose this use case when you want Apple to perform the download on the device.
USB is not required.

Sign in, then claim the free app licence for the target iOS version:

```bash
appfit accounts use you@example.com
appfit get <bundle-id> --ios 16.7.16 --platform ipad
```

appfit prints the Purchased-tab steps. Apple decides whether an older version
is offered on the device.

## Use Direct Install mode

Choose this use case when you want appfit to select and install the exact build.

Sign in, connect and trust the device, then list it:

```bash
appfit accounts use you@example.com
appfit devices
```

Pair its UDID with the Apple ID currently used for App Store purchases on that
device:

```bash
appfit pair <udid> --account you@example.com
```

Install the newest compatible build:

```bash
appfit install <bundle-id> --device <udid>
```

To stop before installation:

```bash
appfit resolve <bundle-id> --device <udid>
appfit download <bundle-id> --device <udid>
```

Search first if you do not know the bundle ID:

```bash
appfit search "app name"
```

## Useful commands

| Command | Purpose |
|---|---|
| `appfit search <query>` | Find an App Store app. |
| `appfit accounts use <email>` | Sign in through ipatool. |
| `appfit devices` | List connected devices and iOS versions. |
| `appfit get <app> --ios <version>` | Claim a free licence and show on-device steps. |
| `appfit resolve <app> --device <udid>` | Find the newest compatible build. |
| `appfit download <app> --device <udid>` | Download and verify the selected IPA. |
| `appfit install <app> --device <udid>` | Install the selected IPA over USB. |
| `appfit cache list` | Show cached resolutions and downloads. |
| `appfit cache prune` | Preview cleanup of unreferenced IPA files. |
| `appfit ipatool status` | Show the selected ipatool helper. |

`<app>` can be a bundle ID, numeric App Store ID, App Store URL, or search term.
Use an exact identifier before any licence-changing action.

## Safety and limits

- appfit uses intact, encrypted App Store IPAs. It does not decrypt apps or
  bypass FairPlay.
- Device installation stops if the active Apple ID does not match the account
  paired to that device.
- Apple controls app availability, licence eligibility, regions, retained
  historical builds, and its on-device compatible-version offer.
- Compatibility checks cover declared iOS and device-family requirements, not
  every hardware, server-side, or account restriction.
- appfit cannot make third-party IPA downloads safe or account-compatible.

appfit uses Apple's public search API, ipatool, and pymobiledevice3. It is
independent and is not affiliated with or endorsed by Apple Inc.

## Cache and privacy

Build metadata and downloaded IPAs are stored under `~/.config/appfit/` and are
reused when possible. Cleanup is dry-run-first:

```bash
appfit cache prune
appfit cache prune --yes
```

Exported cache metadata contains no password or App Store session, but it can
include app bundle IDs and target iOS versions. Review it before sharing.

## Project information

- [Release history](CHANGELOG.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [MIT License](LICENSE)

appfit is not currently published on PyPI.
