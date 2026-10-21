"""Persistence for the user's PersonaProfile.

A damaged profile is never silently replaced by an empty one: ``load`` either
returns a valid profile (from the main file or a snapshot), ``None`` when the
profile was never saved, or raises ``ProfileCorruptError``.
"""

import json
from pathlib import Path
from typing import Final

from olivia.core.models import PersonaProfile
from olivia.core.storage import (
    StorageCorruptError,
    app_data_dir,
    atomic_write_text,
    read_text_with_recovery,
)

PROFILE_FILENAME: Final = "profile.json"


class ProfileCorruptError(Exception):
    """The profile file and all of its snapshots are unreadable or invalid."""


def _parse(text: str) -> PersonaProfile:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("profile JSON top level must be an object")
    return PersonaProfile.from_dict(data)


def _is_valid(text: str) -> bool:
    try:
        _parse(text)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return False
    return True


class ProfileStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        directory = app_data_dir() if base_dir is None else base_dir
        self.path: Path = directory / PROFILE_FILENAME

    def load(self) -> PersonaProfile | None:
        try:
            text = read_text_with_recovery(self.path, _is_valid)
        except FileNotFoundError:
            return None
        except StorageCorruptError as exc:
            raise ProfileCorruptError(
                f"profile at {self.path} and its snapshots are unreadable or invalid"
            ) from exc
        return _parse(text)

    def save(self, profile: PersonaProfile) -> None:
        text = json.dumps(profile.to_dict(), ensure_ascii=False, indent=2)
        atomic_write_text(self.path, text)
