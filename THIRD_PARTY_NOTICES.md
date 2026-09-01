# Third-party notices

The appfit macOS application bundles these independently maintained components:

- **Qt for Python / PySide6 and Qt 6**, available under LGPLv3/GPLv3 or
  commercial Qt terms. Source and licence information:
  <https://doc.qt.io/qtforpython-6/licenses.html>
- **ipatool**, copyright Majd Alfhaily and contributors, MIT licensed. appfit
  builds the pinned revision documented in `src/appfit/toolchain.py` and applies
  `src/appfit/data/ipatool-compatibility-metadata.patch`.
- Python packages listed by the `gui` optional dependency and their transitive
  dependencies retain their respective licences.

appfit itself is distributed under the MIT License in `LICENSE`.
