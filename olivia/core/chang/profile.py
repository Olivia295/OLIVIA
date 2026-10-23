"""Persistence for the user's PersonaProfile, encrypted at rest (B1, ruling 28).

A damaged profile is never silently replaced by an empty one: ``load`` either
returns a valid profile (from the main file or a snapshot), ``None`` when the
profile was never saved, or raises ``ProfileCorruptError`` / ``ProfileLockedError``.

File forms of ``profile.json`` (all JSON):

* **plain** -- the profile as JSON, without any :data:`SENSITIVE_FIELDS`. Used when the
  profile holds no sensitive data and the at-rest switch (ONB-06) is off; needs no keychain.
* **fields** -- the same, plus ``sealed_fields``: the sensitive fields, sealed with the
  ``profile`` data key. Sensitive data is always sealed, whatever the switch says.
* **whole** -- only ``{"sealed_profile": ...}``: the entire profile sealed. Used whenever
  ``enable_at_rest_encryption`` is on.

Sensitive data is never written in plaintext. If the keychain cannot be used, ``save``
raises :class:`ProfileLockedError` and leaves the file untouched; callers decide what to
tell the user (onboarding then saves without the sensitive fields).

A plaintext profile written before B1 is migrated on ``load``: re-saved in its proper
form, after which every snapshot that still holds plaintext sensitive data (or, with
the switch on, any plaintext at all) is deleted. On a device with no keychain the
legacy sensitive fields are dropped instead (``dropped_sensitive_data`` is set so the
caller can say so); while the keychain is only temporarily unavailable nothing changes
and the migration is retried on the next load.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Any, Final

from olivia.core.crypto.errors import (
    CryptoError,
    DecryptionError,
    KeychainUnavailableError,
    KeyMissingError,
    NoKeychainError,
)
from olivia.core.crypto.vault import Vault
from olivia.core.models import PersonaProfile
from olivia.core.storage import (
    StorageCorruptError,
    app_data_dir,
    atomic_write_text,
    read_text_with_recovery,
    remove_file,
    snapshot_paths,
)

PROFILE_FILENAME: Final = "profile.json"
PROFILE_STORE: Final = "profile"
SENSITIVE_FIELDS: Final = ("clinical_history", "contraindications")
"""Profile keys that are sealed regardless of the at-rest switch (ruling 28, D2)."""

_FIELDS_KEY: Final = "sealed_fields"
_WHOLE_KEY: Final = "sealed_profile"
_FIELDS_LABEL: Final = "fields"
_WHOLE_LABEL: Final = "whole"
_PARSE_ERRORS: Final = (ValueError, TypeError, OverflowError, RecursionError, DecryptionError)


class ProfileCorruptError(Exception):
    """The profile file and all of its snapshots are unreadable or invalid."""


class ProfileLockedError(Exception):
    """Encrypted profile data cannot be read or written right now.

    ``lost`` is False when the keychain is unavailable (locked, denied, or absent on this
    device): nothing was changed and a later attempt may succeed. It is True when the
    keys are gone (shredded, or the data came from another device): the encrypted part
    can never be opened again.
    """

    def __init__(self, message: str, *, lost: bool) -> None:
        super().__init__(message)
        self.lost = lost


class _Form(Enum):
    PLAIN = 0
    FIELDS = 1
    WHOLE = 2


def _has_value(value: object) -> bool:
    return value not in (None, "", [], (), {})


def _sensitive_values(data: Mapping[str, object]) -> dict[str, object]:
    return {name: data[name] for name in SENSITIVE_FIELDS if name in data}


def _has_sensitive(profile: PersonaProfile) -> bool:
    return any(_has_value(v) for v in _sensitive_values(profile.to_dict()).values())


def _target_form(profile: PersonaProfile) -> _Form:
    if profile.enable_at_rest_encryption:
        return _Form.WHOLE
    return _Form.FIELDS if _has_sensitive(profile) else _Form.PLAIN


def _without_sensitive(profile: PersonaProfile) -> PersonaProfile:
    cleared: dict[str, Any] = {name: () for name in SENSITIVE_FIELDS if hasattr(profile, name)}
    return replace(profile, enable_at_rest_encryption=False, **cleared)


def _json_object(raw: bytes | str) -> dict[str, object]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("profile JSON top level must be an object")
    return data


def _b64(data: dict[str, object], key: str) -> bytes:
    value = data[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except binascii.Error as exc:
        raise ValueError(f"{key} is not valid base64") from exc


def _snapshot_compliant(raw: bytes, form: _Form) -> bool:
    """Whether a snapshot may stay on disk under the current profile's form."""
    try:
        data = _json_object(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        # Unreadable junk: keep it only if it cannot hold anything that must be protected.
        return form is not _Form.WHOLE and not any(n.encode() in raw for n in SENSITIVE_FIELDS)
    if set(data) == {_WHOLE_KEY}:
        return True
    if form is _Form.WHOLE:
        return False
    return not any(_has_value(v) for v in _sensitive_values(data).values())


class ProfileStore:
    """Load and save the profile under ``base_dir`` (default: the app data directory).

    ``vault`` holds the keys; by default it lives in the same directory and keeps its
    master key in the OS keychain.
    """

    def __init__(self, base_dir: Path | None = None, vault: Vault | None = None) -> None:
        directory = app_data_dir() if base_dir is None else base_dir
        self.path: Path = directory / PROFILE_FILENAME
        self.vault: Vault = Vault(directory) if vault is None else vault
        self.dropped_sensitive_data: bool = False
        """Set by ``load`` when legacy sensitive fields had to be deleted (no keychain)."""

    def can_protect_sensitive(self) -> bool:
        """Whether sensitive fields (and the whole profile) can be encrypted on this device."""
        return self.vault.available()

    def load(self) -> PersonaProfile | None:
        self.dropped_sensitive_data = False
        decoded: dict[str, tuple[PersonaProfile, _Form]] = {}

        def is_valid(text: str) -> bool:
            try:
                decoded[text] = self._decode(text)
            except _PARSE_ERRORS:
                return False
            return True

        try:
            text = read_text_with_recovery(self.path, is_valid)
        except FileNotFoundError:
            return None
        except StorageCorruptError as exc:
            raise ProfileCorruptError(
                f"profile at {self.path} and its snapshots are unreadable or invalid"
            ) from exc
        except CryptoError as exc:
            raise _locked(exc) from exc
        profile, form = decoded[text]
        target = _target_form(profile)
        if form.value >= target.value:
            self._purge_snapshots(target)
            return profile
        # Less protected than it must be (a pre-B1 plaintext profile): migrate.
        try:
            self._save(profile)
        except NoKeychainError:
            # Sensitive data cannot be protected on this device, so it is not kept.
            had_sensitive = _has_sensitive(profile)
            profile = _without_sensitive(profile)
            self._save(profile)
            self.dropped_sensitive_data = had_sensitive
        except CryptoError:
            pass  # keychain locked or keys damaged: change nothing, retry on the next load
        return profile

    def save(self, profile: PersonaProfile) -> None:
        try:
            self._save(profile)
        except CryptoError as exc:
            raise _locked(exc) from exc

    # -- internals ---------------------------------------------------------------------

    def _save(self, profile: PersonaProfile) -> None:
        atomic_write_text(self.path, self._encode(profile))
        self._purge_snapshots(_target_form(profile))

    def _encode(self, profile: PersonaProfile) -> str:
        data = profile.to_dict()
        if profile.enable_at_rest_encryption:
            whole = json.dumps(data, ensure_ascii=False).encode("utf-8")
            blob = self.vault.seal(PROFILE_STORE, whole, label=_WHOLE_LABEL)
            return json.dumps({_WHOLE_KEY: base64.b64encode(blob).decode("ascii")}, indent=2)
        sensitive = _sensitive_values(data)
        for name in sensitive:
            del data[name]
        if any(_has_value(v) for v in sensitive.values()):
            plain = json.dumps(sensitive, ensure_ascii=False).encode("utf-8")
            blob = self.vault.seal(PROFILE_STORE, plain, label=_FIELDS_LABEL)
            data[_FIELDS_KEY] = base64.b64encode(blob).decode("ascii")
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _decode(self, text: str) -> tuple[PersonaProfile, _Form]:
        data = _json_object(text)
        if _WHOLE_KEY in data:
            if set(data) != {_WHOLE_KEY}:
                raise ValueError("a sealed profile holds nothing else")
            inner = _json_object(
                self.vault.open(PROFILE_STORE, _b64(data, _WHOLE_KEY), label=_WHOLE_LABEL)
            )
            if _WHOLE_KEY in inner or _FIELDS_KEY in inner:
                raise ValueError("nested sealed profile")
            return PersonaProfile.from_dict(inner), _Form.WHOLE
        if _FIELDS_KEY not in data:
            return PersonaProfile.from_dict(data), _Form.PLAIN
        if _sensitive_values(data):
            raise ValueError("sensitive fields appear both sealed and in plaintext")
        sealed = _b64(data, _FIELDS_KEY)
        del data[_FIELDS_KEY]
        fields = _json_object(self.vault.open(PROFILE_STORE, sealed, label=_FIELDS_LABEL))
        if not set(fields) <= set(SENSITIVE_FIELDS):
            raise ValueError("sealed fields hold an unexpected key")
        return PersonaProfile.from_dict(data | fields), _Form.FIELDS

    def _purge_snapshots(self, form: _Form) -> None:
        """Delete snapshots that hold data the current form says must be protected."""
        for snapshot in snapshot_paths(self.path):
            try:
                raw = snapshot.read_bytes()
            except OSError:
                continue
            if not _snapshot_compliant(raw, form):
                remove_file(snapshot)


def _locked(exc: CryptoError) -> Exception:
    if isinstance(exc, KeyMissingError):
        return ProfileLockedError("the profile's encryption keys are gone", lost=True)
    if isinstance(exc, KeychainUnavailableError):
        return ProfileLockedError("the keychain is unavailable", lost=False)
    return ProfileCorruptError("the profile's encryption keys are damaged")
