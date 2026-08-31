# Changelog

All notable changes to appfit are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

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
