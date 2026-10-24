"""Load the signed hotline data, preferring a newer signed override (GEO-08, SDD §8.3).

The data ships as ``olivia/data/resources/hotlines.yaml`` plus a detached signature
``hotlines.yaml.sig`` (base64 Ed25519 over the file's exact bytes), verified against
``keys.HOTLINE_PUBLIC_KEY_B64``. An override pair in a user data directory replaces the
built-in data only when its signature verifies and it was compiled after the built-in
data; otherwise the built-in data is used and ``reason`` says why, for ``--inspect``.
A built-in file that fails verification raises: unverified numbers are never shown.
``cryptography`` is imported when a signature is first verified, not with this module.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Literal

import yaml

from olivia.core.resources import keys
from olivia.core.yaml_load import safe_load

DATA_NAME = "hotlines.yaml"
SIG_NAME = DATA_NAME + ".sig"

REASON_NO_OVERRIDE = "no override"
REASON_SIG_MISSING = "override signature missing"
REASON_SIG_INVALID = "override signature invalid"
REASON_UNREADABLE = "override unreadable"
REASON_FUTURE = "override compiled in the future"
REASON_NOT_NEWER = "override older than built-in"


class BundleIntegrityError(RuntimeError):
    """The packaged hotline data does not match its signature."""


@dataclass(frozen=True)
class LoadedBundle:
    data: bytes
    source: Literal["override", "builtin"]
    reason: str | None


def verify_signature(data: bytes, signature_b64: bytes, public_key_b64: str) -> bool:
    """True if ``signature_b64`` (base64 text, surrounding whitespace allowed) signs ``data``."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        signature = base64.b64decode(signature_b64.strip(), validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        public_key.verify(signature, data)
    except (InvalidSignature, binascii.Error, ValueError):
        return False
    return True


def _read_builtin() -> tuple[bytes, bytes]:
    folder = resources.files("olivia").joinpath("data/resources")
    return folder.joinpath(DATA_NAME).read_bytes(), folder.joinpath(SIG_NAME).read_bytes()


def _compiled_on(data: bytes) -> date:
    """The ``compiled_on`` date of a hotline file; raises ValueError if absent or malformed."""
    try:
        doc = safe_load(data)
    except yaml.YAMLError as exc:
        raise ValueError("not valid YAML") from exc
    value = doc.get("compiled_on") if isinstance(doc, dict) else None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError("missing compiled_on")


def load_hotlines_bytes(override_dir: Path | None, *, today: date) -> LoadedBundle:
    """Return the hotline YAML bytes to use, with where they came from and why.

    ``today`` rejects an override dated after the current day, which a genuine release
    cannot be.
    """
    builtin, builtin_sig = _read_builtin()
    if not verify_signature(builtin, builtin_sig, keys.HOTLINE_PUBLIC_KEY_B64):
        raise BundleIntegrityError(
            "built-in hotlines.yaml does not match hotlines.yaml.sig; the package is damaged"
        )

    def fallback(reason: str) -> LoadedBundle:
        return LoadedBundle(data=builtin, source="builtin", reason=reason)

    if override_dir is None or not (override_dir / DATA_NAME).is_file():
        return fallback(REASON_NO_OVERRIDE)
    sig_path = override_dir / SIG_NAME
    if not sig_path.is_file():
        return fallback(REASON_SIG_MISSING)
    try:
        data = (override_dir / DATA_NAME).read_bytes()
        signature = sig_path.read_bytes()
    except OSError:
        return fallback(REASON_UNREADABLE)
    if not verify_signature(data, signature, keys.HOTLINE_PUBLIC_KEY_B64):
        return fallback(REASON_SIG_INVALID)

    try:
        override_date = _compiled_on(data)
    except ValueError:
        return fallback(REASON_UNREADABLE)
    if override_date > today:
        return fallback(REASON_FUTURE)
    if override_date <= _compiled_on(builtin):
        return fallback(REASON_NOT_NEWER)
    return LoadedBundle(data=data, source="override", reason=None)
