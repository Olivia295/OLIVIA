"""GEO-08: signed hotline data, override policy and built-in integrity."""

from __future__ import annotations

import base64
from datetime import date
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from olivia.core.resources import bundle, keys
from olivia.core.resources.bundle import (
    BundleIntegrityError,
    LoadedBundle,
    load_hotlines_bytes,
    verify_signature,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "olivia" / "data" / "resources"
TODAY = date(2026, 10, 22)
BUILTIN = b'version: 1\ncompiled_on: "2026-10-01"\nregions: {}\n'


def _public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode("ascii")


def _sign(key: Ed25519PrivateKey, data: bytes) -> bytes:
    return base64.b64encode(key.sign(data)) + b"\n"


def _yaml(compiled_on: str) -> bytes:
    return f'version: 1\ncompiled_on: "{compiled_on}"\nregions: {{}}\n'.encode()


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> Ed25519PrivateKey:
    """A throwaway signing key; the built-in data is replaced by a fixture signed with it."""
    private = Ed25519PrivateKey.generate()
    monkeypatch.setattr(keys, "HOTLINE_PUBLIC_KEY_B64", _public_b64(private))
    signature = _sign(private, BUILTIN)
    monkeypatch.setattr(bundle, "_read_builtin", lambda: (BUILTIN, signature))
    return private


def _write_override(folder: Path, data: bytes, signature: bytes | None) -> Path:
    (folder / "hotlines.yaml").write_bytes(data)
    if signature is not None:
        (folder / "hotlines.yaml.sig").write_bytes(signature)
    return folder


# --- the real packaged data ------------------------------------------------------------


def test_committed_signature_matches_committed_data():
    # Fails if hotlines.yaml was edited without `python scripts/sign_hotlines.py`.
    data = (DATA_DIR / "hotlines.yaml").read_bytes()
    signature = (DATA_DIR / "hotlines.yaml.sig").read_bytes()
    assert verify_signature(data, signature, keys.HOTLINE_PUBLIC_KEY_B64)


def test_packaged_builtin_loads_and_verifies():
    loaded = load_hotlines_bytes(None, today=TODAY)
    assert loaded == LoadedBundle(
        data=(DATA_DIR / "hotlines.yaml").read_bytes(), source="builtin", reason="no override"
    )


def test_public_key_is_a_raw_32_byte_key():
    assert len(base64.b64decode(keys.HOTLINE_PUBLIC_KEY_B64, validate=True)) == 32


# --- built-in integrity ----------------------------------------------------------------


def test_tampered_builtin_raises(key: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch):
    tampered = BUILTIN.replace(b"regions: {}", b"regions: {CN: {}}")
    monkeypatch.setattr(bundle, "_read_builtin", lambda: (tampered, _sign(key, BUILTIN)))
    with pytest.raises(BundleIntegrityError):
        load_hotlines_bytes(None, today=TODAY)


def test_builtin_signed_by_another_key_raises(monkeypatch: pytest.MonkeyPatch):
    signer, trusted = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    monkeypatch.setattr(keys, "HOTLINE_PUBLIC_KEY_B64", _public_b64(trusted))
    monkeypatch.setattr(bundle, "_read_builtin", lambda: (BUILTIN, _sign(signer, BUILTIN)))
    with pytest.raises(BundleIntegrityError):
        load_hotlines_bytes(None, today=TODAY)


def test_builtin_with_garbage_signature_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bundle, "_read_builtin", lambda: (BUILTIN, b"not base64 !!\n"))
    with pytest.raises(BundleIntegrityError):
        load_hotlines_bytes(None, today=TODAY)


# --- override policy -------------------------------------------------------------------


def test_newer_valid_override_wins(key: Ed25519PrivateKey, tmp_path: Path):
    data = _yaml("2026-10-15")
    loaded = load_hotlines_bytes(_write_override(tmp_path, data, _sign(key, data)), today=TODAY)
    assert loaded == LoadedBundle(data=data, source="override", reason=None)


def test_no_override_dir(key: Ed25519PrivateKey):
    assert load_hotlines_bytes(None, today=TODAY) == LoadedBundle(BUILTIN, "builtin", "no override")


def test_empty_override_dir(key: Ed25519PrivateKey, tmp_path: Path):
    loaded = load_hotlines_bytes(tmp_path, today=TODAY)
    assert (loaded.source, loaded.reason) == ("builtin", "no override")


def test_override_missing_signature(key: Ed25519PrivateKey, tmp_path: Path):
    loaded = load_hotlines_bytes(_write_override(tmp_path, _yaml("2026-10-15"), None), today=TODAY)
    assert loaded == LoadedBundle(BUILTIN, "builtin", "override signature missing")


def test_override_tampered_after_signing(key: Ed25519PrivateKey, tmp_path: Path):
    signed = _yaml("2026-10-15")
    tampered = signed.replace(b"regions: {}", b"regions: {CN: {}}")
    loaded = load_hotlines_bytes(
        _write_override(tmp_path, tampered, _sign(key, signed)), today=TODAY
    )
    assert loaded == LoadedBundle(BUILTIN, "builtin", "override signature invalid")


def test_override_signed_by_untrusted_key(key: Ed25519PrivateKey, tmp_path: Path):
    data = _yaml("2026-10-15")
    stranger = Ed25519PrivateKey.generate()
    loaded = load_hotlines_bytes(
        _write_override(tmp_path, data, _sign(stranger, data)), today=TODAY
    )
    assert (loaded.source, loaded.reason) == ("builtin", "override signature invalid")


def test_override_garbage_signature(key: Ed25519PrivateKey, tmp_path: Path):
    loaded = load_hotlines_bytes(
        _write_override(tmp_path, _yaml("2026-10-15"), b"%%%\n"), today=TODAY
    )
    assert (loaded.source, loaded.reason) == ("builtin", "override signature invalid")


@pytest.mark.parametrize("compiled_on", ["2026-09-30", "2026-10-01"])
def test_override_not_newer_than_builtin(key: Ed25519PrivateKey, tmp_path: Path, compiled_on: str):
    data = _yaml(compiled_on)
    loaded = load_hotlines_bytes(_write_override(tmp_path, data, _sign(key, data)), today=TODAY)
    assert loaded == LoadedBundle(BUILTIN, "builtin", "override older than built-in")


def test_override_dated_in_the_future(key: Ed25519PrivateKey, tmp_path: Path):
    data = _yaml("2026-10-23")
    loaded = load_hotlines_bytes(_write_override(tmp_path, data, _sign(key, data)), today=TODAY)
    assert (loaded.source, loaded.reason) == ("builtin", "override compiled in the future")


@pytest.mark.parametrize(
    "data", [b"version: 1\nregions: {}\n", b"compiled_on: not-a-date\n", b"[: bad", b"- a\n"]
)
def test_signed_but_unreadable_override(key: Ed25519PrivateKey, tmp_path: Path, data: bytes):
    loaded = load_hotlines_bytes(_write_override(tmp_path, data, _sign(key, data)), today=TODAY)
    assert (loaded.source, loaded.reason) == ("builtin", "override unreadable")


def test_unquoted_yaml_date_is_accepted(key: Ed25519PrivateKey, tmp_path: Path):
    data = b"version: 1\ncompiled_on: 2026-10-15\nregions: {}\n"
    loaded = load_hotlines_bytes(_write_override(tmp_path, data, _sign(key, data)), today=TODAY)
    assert loaded.source == "override"
