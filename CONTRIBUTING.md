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

## Releases

1. Update `pyproject.toml` and add a dated version heading to `CHANGELOG.md`.
2. Run `python scripts/release_check.py v<version>`, the full local test suite,
   and `python -m build`.
3. Push the release commit to `main` and wait for CI to pass.
4. Create and push an annotated `v<version>` tag.

The tag-triggered Release workflow repeats the offline tests, builds wheel and
source archives, and publishes both to a GitHub Release. It does not publish to
PyPI.
