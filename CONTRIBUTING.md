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
archives, and publishes both to a GitHub Release. It does not publish to PyPI.

## Releases

1. Update `pyproject.toml` and add a dated version heading to `CHANGELOG.md`.
2. Run `python scripts/release_check.py v<version>`, the full local test suite,
   and `python -m build`.
3. Push the release commit to `main` and wait for CI to pass.
4. Create and push an annotated `v<version>` tag.

Confirm the resulting GitHub Release contains both archives and that its public
installation instructions match the released wheel filename.

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
ad-hoc signature for local testing. Release signing and notarization are
intentionally separate credentialed steps.
