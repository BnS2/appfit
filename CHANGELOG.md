# Changelog

All notable changes to appfit are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.3.0 - 2026-09-01

### Added

- A PySide6 Mac compatible-build finder with connected-device iOS detection,
  editable manual iOS targets, App Store search, newest-compatible
  recommendation, and lazy pages of verified older versions.
- GUI actions for account-safe licence claims, exact-version downloads, local
  IPA verification, device pairing, and USB installation.
- Structured GUI-safe workflow results and progress events, a bundled patched
  ipatool lookup path, offscreen widget tests, and reproducible arm64/x86_64 Mac
  bundle tooling.
- A focused macOS workspace with compact readiness states, contextual primary
  actions, App Store artwork, keyboard shortcuts, accessible labels, and a
  purpose-built appfit application icon.

### Changed

- Public documentation now describes Licence and Direct Install as modes,
  reserving version numbers for appfit releases and internal data formats.
- The source package version is now 0.3.0 for the GUI release.
- The provisional stacked-form GUI was replaced before release with a compact,
  light/dark-aware Mac utility layout while preserving its safety confirmations
  and backend workflows.

## 0.2.0 - 2026-08-31

### Added

- Direct USB installation of intact, Apple-signed store IPAs through iOS
  Installation Proxy.
- Device-aware compatibility checks for iOS version, platform, and
  `UIDeviceFamily`.
- Release-date-seeded historical build resolution and shareable cache metadata.
- Cache export/import and dry-run-first `appfit cache prune` maintenance.
- An appfit-managed, compatibility-aware ipatool build pinned to official
  v2.4.0 source, with `appfit ipatool install` and `status` diagnostics.
- Download and installation progress reporting.
- MIT licensing, reader-first documentation, macOS CI, and tag-driven GitHub
  Release delivery for wheel/source artifacts.

### Changed

- Cache schema v2 keys resolutions by bundle ID, iOS version, and platform while
  preserving v1 iPad entries during migration.
- Install and download commands enforce the device-to-Apple-ID pairing before
  any licence or package operation.

### Verified

- Installed and launched FAST and the last compatible Termius v6.3.0 build on
  a stock-booted iPad 5 running iOS 16.7.16.

## 0.1.0 - 2026-08-30

### Added

- App Store lookup, Apple-ID account safety, device pairing, licence claiming,
  historical build resolution, and local compatibility probing.
