"""Build profiles that ship with the package, so an installed grz-build can plan without a clone."""

from __future__ import annotations

import json
from pathlib import Path

from grz_core.contracts import BuildProfile, ContractError

_HERE = Path(__file__).parent
BUNDLED_PROFILES = sorted(p.stem for p in _HERE.glob("*.json"))


def profile_path(value: str | Path) -> Path:
    """A file that exists wins; otherwise the value names a bundled profile (older docs pass examples\\<name>.json)."""
    given = Path(value)
    if given.is_file():
        return given
    bundled = _HERE / f"{given.stem}.json"
    if bundled.is_file():
        return bundled
    raise ContractError("PROFILE_NOT_FOUND", f"No profile file {value} and no bundled profile named {given.stem}; "
                                             f"bundled: {', '.join(BUNDLED_PROFILES)}")


def load_profile(value: str | Path) -> BuildProfile:
    return BuildProfile(**json.loads(profile_path(value).read_text(encoding="utf-8")))
