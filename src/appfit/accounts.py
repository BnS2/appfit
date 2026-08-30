"""Device→Apple ID pairings.

The licence for an app has to be claimed on the Apple ID signed into the
*target device*. Using your own Apple ID for someone else's iPad ties their app
to your purchase history for every future update, so appfit never picks an
account implicitly: a device is paired to one, or the caller names one.

Credentials themselves are ipatool's business (see store.py). Nothing secret is
written here -- only which email belongs with which device, so the tool can
refuse to act when the wrong account is signed in.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    d = Path(base) / "appfit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file() -> Path:
    return config_dir() / "devices.json"


def _read() -> dict:
    f = _file()
    if not f.exists():
        return {"pairings": {}, "known": []}
    try:
        data = json.loads(f.read_text())
    except json.JSONDecodeError:
        return {"pairings": {}, "known": []}
    data.setdefault("pairings", {})
    data.setdefault("known", [])
    return data


def _write(data: dict) -> None:
    _file().write_text(json.dumps(data, indent=2, sort_keys=True))


def remember(email: str) -> None:
    """Note an Apple ID we've been asked to use, so it can be listed later."""
    data = _read()
    if email not in data["known"]:
        data["known"].append(email)
        data["known"].sort()
        _write(data)


def known_accounts() -> list[str]:
    return _read()["known"]


def forget(email: str) -> bool:
    data = _read()
    if email not in data["known"]:
        return False
    data["known"].remove(email)
    data["pairings"] = {u: e for u, e in data["pairings"].items() if e != email}
    _write(data)
    return True


def pair(udid: str, email: str) -> None:
    """Bind a device to the Apple ID that is signed in ON THAT DEVICE."""
    data = _read()
    data["pairings"][udid] = email
    if email not in data["known"]:
        data["known"].append(email)
        data["known"].sort()
    _write(data)


def account_for_device(udid: str) -> str | None:
    return _read()["pairings"].get(udid)


def pairings() -> dict[str, str]:
    return _read()["pairings"]
