# appfit

**Find the last version of an app that still fits your device — and get it
installed.** No jailbreak, no cable, no IPA hunting.

An iPad 5 on iPadOS 16.7.16 can't install Amazon Prime Video: the current build
requires iOS 17, so the App Store shows no **Get** button at all. The usual
response is to go hunting for IPA files on mirror sites, which cannot work —
App Store IPAs are FairPlay-bound to the Apple ID that downloaded them.

The real blocker is mundane. Apple *will* serve an older, compatible build of an
app — but only to an Apple ID that already has that app in its purchase history.
No purchase history, no offer, nothing to downgrade to. Claiming the free licence
is the entire fix:

```
$ appfit get "prime video" --ios 16.7.16
✓ app     Amazon Prime Video (com.amazon.aiv.AIVApp)
✓ account someone@example.com
✓ licence claimed

→ On the device, signed in as someone@example.com:
  App Store ▸ your avatar ▸ Purchased ▸ Not on this Device
  ▸ Amazon Prime Video ▸ ☁️
  Accept "Download an older version compatible with this device?"
```

No jailbreak, no USB cable, no IPA. This works on a completely stock device.

## Install

```bash
brew install ipatool          # required: handles Apple's signed requests
pip install -e .
pip install -e '.[device]'    # optional: USB device detection
```

## Use

```bash
appfit accounts use <apple-id>      # sign in (password + 2FA go to ipatool)
appfit get <app> --ios 16.7.16      # claim the licence
appfit get <app> --device <udid>    # or read the iOS version off the device

appfit devices                      # USB devices: model, iOS, UDID
appfit pair <udid> --account <email>
appfit search "prime video"
appfit resolve <app> --ios 16.7.16  # which build exactly? (expensive, see below)
```

`<app>` accepts a bundle ID, numeric App Store ID, store URL, or a search term.

## Whose Apple ID?

**The one signed into the target device.** Not yours, unless it is your device.

Apple gates the older-version offer on that account's purchase history, and
FairPlay binds the binary to that account. Claiming a licence on your own Apple
ID for a friend's iPad means their app depends on your account for every future
update, and account sharing breaks Apple's terms.

`ipatool` holds one session at a time, so appfit records which Apple ID each
device belongs to and **refuses to act when the wrong one is signed in** rather
than quietly claiming a licence on it:

```
✗ signed in as me@example.com, but this device is paired to them@example.com.
  Switch with:  appfit accounts use them@example.com
```

For the same reason, an app matched by fuzzy text search must be confirmed before
a licence is claimed — the store returns a plausible result for almost any
string, and a claim is permanent.

## Why it drives ipatool instead of speaking the protocol

The original design spoke to Apple's endpoints directly, so it could get the
signed IPA download URL and read each build's `MinimumOSVersion` cheaply. That
does not work any more:

- The endpoints come from a bag config (`init.itunes.apple.com/bag.xml`), not
  fixed hostnames — and the bag's `authenticateAccount` is
  `buy.itunes.apple.com`, not the `p25`/`p71` prefixes older tools use.
- Unsigned POSTs to it return a bare **HTTP 403 with an empty body**. Verified
  from python-requests *and* curl, so it is not a TLS-fingerprint problem —
  Apple signs these requests (`ActionSigner`/SAP in ipatool).

ipatool implements the signing and is maintained, so appfit drives it and
keeps the parts that are its own: identifier resolution, device detection,
account safety, the build search, and caching.

**The cost of that choice:** ipatool never exposes the download URL, so
determining a build's minimum OS means downloading the IPA.

## The expensive part: `resolve`

`get` is cheap and is what actually solves the problem — Apple picks the right
build on-device for free. `resolve` answers the extra question "*which* build
will that be?", and that costs real downloads:

- ~370 builds exist for a title like Prime Video. Binary search cuts it to ~14
  worst case, not 370 — but each probe is a 100–300 MB IPA.
- Results are cached in `~/.config/appfit/cache.json`, keyed by
  (bundle ID, iOS version). Nothing in that file is account-specific, so it is
  safe to share or seed.
- Downloaded IPAs are kept in `~/.config/appfit/ipa/` so a later install
  reuses them.
- The command warns and asks before a cold lookup.

In phase 2 this cost mostly disappears: installing downloads an IPA anyway, so
the probe that identifies the build is the same fetch that installs it.

`probe.py` still contains a working, tested HTTP-Range reader that pulls
`Info.plist` out of a remote IPA without downloading it (a few hundred KB instead
of hundreds of MB). It is unused against Apple only because there is no URL to
point it at. If the signing is ever implemented, the cheap path is already built.

## Limitations

- `MinimumOSVersion` and `UIDeviceFamily` catch most incompatibility, but RAM,
  GPU and Metal requirements are not declared in `Info.plist` — a build can
  resolve as compatible and still run badly on an A9. Treat the answer as the
  best candidate, not a guarantee.
- The build search assumes minimum OS is non-decreasing over a title's history.
  It usually is; a forward scan after the search catches the exception.
- Some apps have never shipped a build for your device's iOS. appfit says so
  plainly instead of leaving you hunting mirrors.

## Roadmap

- **v1 (now)** — accounts, pairing, device detection, licence claim, build
  resolution. Stock-safe, no USB required.
- **v2** — `download` and `install` over USB via pymobiledevice3. Installing an
  off-store IPA needs a jailbroken device with AppSync Unified; on a stock device
  installd refuses it.
- **v3** — a Mac GUI over this core.

Only user-licensed store IPAs, using the account that legitimately owns them. No
decrypted IPAs, no DRM circumvention.

## Tests

```bash
pytest              # 34 tests
pytest -m "not network"
```

The ZIP range reader is tested against a synthetic IPA served by a local
range-capable HTTP server, and the build search against fake histories — so both
run without credentials or network.
