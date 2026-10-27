"""Load the signed hotline data, preferring a newer signed override (GEO-08, SDD §8.3).

The data ships as ``olivia/data/resources/hotlines.yaml`` plus a detached signature
``hotlines.yaml.sig`` (base64 Ed25519 over the file's exact bytes), verified against
``keys.HOTLINE_PUBLIC_KEY_B64``. An override pair in a user data directory replaces the
built-in data only when its signature verifies and it was compiled after the built-in
data; otherwise the built-in data is used and ``reason`` says why, for ``--inspect``.
A signed override must also be complete, well-formed hotline data (S2): it has to pass
the store's full schema check and keep every built-in region and each region's built-in
emergency numbers (it may add regions, numbers and lines, or change a line's number);
otherwise the whole override is set aside for the built-in data. A built-in file that is
missing, unreadable or fails verification raises :class:`BundleIntegrityError`:
unverified numbers are never shown (callers show ``fallback.fallback_text`` instead).

The product looks for the override pair in ``override_dir_location()``, the ``resources``
sub-directory of the data directory (F14): ``olivia chat`` passes it to the session and
``olivia resources`` says which data it shows.
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
from olivia.core.resources.store import ResourceDataError, ResourceStore, parse_store
from olivia.core.storage import data_dir_location
from olivia.core.yaml_load import safe_load

DATA_NAME = "hotlines.yaml"
SIG_NAME = DATA_NAME + ".sig"
OVERRIDE_DIR_NAME = "resources"
"""The data directory's sub-directory holding a signed update pair (F14)."""

REASON_NO_OVERRIDE = "no override"
REASON_SIG_MISSING = "override signature missing"
REASON_SIG_INVALID = "override signature invalid"
REASON_UNREADABLE = "override unreadable"
REASON_FUTURE = "override compiled in the future"
REASON_NOT_NEWER = "override older than built-in"
REASON_INVALID = "override data invalid"
REASON_INCOMPLETE = "override drops built-in regions or emergency numbers"


class BundleIntegrityError(RuntimeError):
    """The packaged hotline data is missing, unreadable or does not match its signature."""


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


def override_dir_location() -> Path:
    """Where an update pair is looked for: ``<data dir>/resources/`` (F14).

    The data directory is ``OLIVIA_HOME`` or the platform's user data directory
    (``storage.data_dir_location``). Nothing is created; a missing directory simply means
    there is no update.
    """
    return data_dir_location() / OVERRIDE_DIR_NAME


def _read_builtin() -> tuple[bytes, bytes]:
    folder = resources.files("olivia").joinpath("data/resources")
    return folder.joinpath(DATA_NAME).read_bytes(), folder.joinpath(SIG_NAME).read_bytes()


def _compact(number: str) -> str:
    return "".join(number.split())


def _covers(override: ResourceStore, builtin: ResourceStore) -> bool:
    """Whether ``override`` keeps every built-in region and its emergency numbers."""
    for code, region in builtin.regions.items():
        if not override.has_region(code):
            return False
        kept = {_compact(e.number) for e in override.region(code).emergency}
        if any(_compact(e.number) not in kept for e in region.emergency):
            return False
    return True


def _store_of(data: bytes) -> ResourceStore:
    """Parse and fully validate hotline YAML; raises :class:`ResourceDataError`."""
    try:
        doc = safe_load(data)
    except yaml.YAMLError as exc:
        raise ResourceDataError("not valid YAML") from exc
    return parse_store(doc)


def compiled_on_of(data: bytes) -> date:
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
    try:
        builtin, builtin_sig = _read_builtin()
    except OSError as exc:
        raise BundleIntegrityError(
            "built-in hotlines.yaml or hotlines.yaml.sig cannot be read; the package is damaged"
        ) from exc
    if not verify_signature(builtin, builtin_sig, keys.HOTLINE_PUBLIC_KEY_B64):
        raise BundleIntegrityError(
            "built-in hotlines.yaml does not match hotlines.yaml.sig; the package is damaged"
        )

    def fallback(reason: str) -> LoadedBundle:
        return LoadedBundle(data=builtin, source="builtin", reason=reason)

    if override_dir is None:
        return fallback(REASON_NO_OVERRIDE)
    sig_path = override_dir / SIG_NAME
    try:  # a data directory without permissions cannot even be looked into (QA r3)
        if not (override_dir / DATA_NAME).is_file():
            return fallback(REASON_NO_OVERRIDE)
        if not sig_path.is_file():
            return fallback(REASON_SIG_MISSING)
    except OSError:
        return fallback(REASON_UNREADABLE)
    try:
        data = (override_dir / DATA_NAME).read_bytes()
        signature = sig_path.read_bytes()
    except OSError:
        return fallback(REASON_UNREADABLE)
    if not verify_signature(data, signature, keys.HOTLINE_PUBLIC_KEY_B64):
        return fallback(REASON_SIG_INVALID)

    try:
        override_date = compiled_on_of(data)
    except ValueError:
        return fallback(REASON_UNREADABLE)
    if override_date > today:
        return fallback(REASON_FUTURE)
    try:
        builtin_date = compiled_on_of(builtin)
    except ValueError as exc:
        raise BundleIntegrityError("built-in hotlines.yaml has no valid compiled_on") from exc
    if override_date <= builtin_date:
        return fallback(REASON_NOT_NEWER)

    try:
        override_store = _store_of(data)
    except ResourceDataError:
        return fallback(REASON_INVALID)
    try:
        builtin_store = _store_of(builtin)
    except ResourceDataError as exc:
        raise BundleIntegrityError("built-in hotlines.yaml is not valid hotline data") from exc
    if not _covers(override_store, builtin_store):
        return fallback(REASON_INCOMPLETE)
    return LoadedBundle(data=data, source="override", reason=None)
