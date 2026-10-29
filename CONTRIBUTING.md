# Contributing

Contributions are welcome when they preserve appfit's safety boundary: only
account-owned, encrypted App Store packages, with no DRM bypass, decrypted IPA
distribution, or credential handling inside appfit.

## Development setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,device]"
.venv/bin/pytest -m "not network"
```

For GUI development and offscreen widget tests:

```bash
.venv/bin/pip install -e ".[dev,gui]"
QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_gui.py tests/test_workflows.py
.venv/bin/appfit-gui
```

The public iTunes lookup tests are opt-in because they depend on an external
service:

```bash
.venv/bin/pytest -m network
```

Tests that use an Apple ID or physical device must never run in CI. Redact Apple
IDs, device UDIDs, App Store session data, and IPA contents from issues and test
logs.

## Dependency inventory

`uv.lock` is a reproducible resolver inventory snapshot of the package's direct
and transitive dependencies, including all `device`, `gui`, `package`, and `dev`
extras and Python/platform resolution branches. It is input for security
scanning, not an installed-artifact SBOM: the pip-based test, build, release, and
user installation paths can resolve different versions. Build isolation tools,
the frozen Python runtime, and the bundled Go helper need separate evidence.

Use uv 0.10.2 to update it after changing dependency declarations:

```bash
uv lock --no-build --no-python-downloads
uv lock --check --no-build --no-python-downloads
```

To deliberately refresh all resolved versions, add `--upgrade` to the first
command and review the lockfile diff. These commands resolve published metadata;
they do not sync an environment or install dependencies. appfit's metadata is
static in `pyproject.toml`; keep it static so locking does not invoke a project
build backend. CI checks lock freshness independently of the application tests.

## Pull requests

- Add regression coverage for behavior changes.
- Keep `appfit cache prune` dry-run-first and preserve its cache/file rechecks.
- Run the full local suite and `git diff --check`.
- Update `README.md` and `CHANGELOG.md` for user-visible changes.
- If the pinned ipatool revision changes, verify the bundled patch against that
  exact official commit and test real compatibility metadata before updating the
  manifest constants.

## CI/CD

Pushes to `main` and pull requests run the offline test suite on macOS with
Python 3.10 and 3.14, build a wheel, and run the GUI/widget suite offscreen on
Python 3.12. CI must not use Apple credentials or a physical device.

The manually triggered `macOS App` workflow builds unsigned test bundles for
Apple silicon and Intel. Public GUI release artifacts must additionally be
Developer ID signed, hardened-runtime enabled, notarized, and stapled; do not
publish the unsigned test artifacts as a release.

Tags matching `v*` start the release workflow. It verifies the tag against the
package version and changelog, repeats the offline tests, builds wheel and source
archives, builds the Apple silicon and Intel disk images, and publishes them all
to a GitHub Release. It does not publish to PyPI.

## Releases

1. Update `pyproject.toml` and add a dated version heading to `CHANGELOG.md`.
2. Run `python scripts/release_check.py v<version>`, the full local test suite,
   and `python -m build`.
3. Push the release commit to `main` and wait for CI to pass.
4. Create and push an annotated `v<version>` tag.

The release notes are composed by `scripts/release_notes.py`: the changelog
entry for that version with its bullets unwrapped, closed by a `Full Changelog`
link, matching the releases before it.

Confirm the resulting GitHub Release contains both archives and both disk
images, and that the public installation instructions match the released wheel
filename.

## Build the Mac application locally

Use a Python 3.12 environment so the frozen runtime has a stable deployment
baseline:

```bash
python3.12 -m venv .venv-build
.venv-build/bin/pip install -e ".[gui,package]"
.venv-build/bin/python scripts/build_macos_app.py
```

The build compiles the pinned patched ipatool, places it inside the bundle,
generates the icon family from `assets/appfit-icon-1024.png`, produces
`deployment/appfit-<architecture>.app`, sets a macOS 13 minimum, and applies an
ad-hoc signature for local testing. It then wraps the bundle in
`deployment/appfit-<version>-<architecture>.dmg` alongside an Applications
symlink; pass `--skip-dmg` to build the app alone. Release signing and
notarization are intentionally separate credentialed steps.

## Refresh the README screenshots

```bash
.venv/bin/python scripts/capture_screenshots.py
```

The window is driven with stand-in account, device, and build data, so the
images in `assets/screenshots/` never contain an Apple ID, a device name, or a
UDID. Re-run it after changing the desktop layout.
