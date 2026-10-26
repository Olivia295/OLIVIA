"""GEO-08: signed hotline data, override policy and built-in integrity."""

from __future__ import annotations

import base64
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
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


def _emergency(number: str) -> dict[str, object]:
    return {
        "number": number,
        "purpose": "police_fire_ambulance",
        "source_url": "https://example.org/",
        "verified_on": "2026-10-01",
        "notes": "",
    }


def _line(line_id: str, number: str, kind: str = "crisis_hotline") -> dict[str, object]:
    return {
        "id": line_id,
        "name_zh": "测试热线",
        "number": number,
        "kind": kind,
        "levels": ["L2", "L3"],
        "hours": "24/7",
        "scope": "national",
        "adcode": None,
        "minors_only": False,
        "source_url": "https://example.org/",
        "verified_on": "2026-10-01",
        "notes": "",
    }


def _doc(compiled_on: str) -> dict[str, Any]:
    """Valid hotline data: GB (two emergency numbers) and the ZZ fallback."""
    return {
        "version": 1,
        "compiled_on": compiled_on,
        "regions": {
            "GB": {
                "emergency": [_emergency("999"), _emergency("112")],
                "lines": [_line("gb_test", "116 000")],
            },
            "ZZ": {"emergency": [_emergency("112")], "lines": [_line("zz_test", "https://x.org/")]},
        },
    }


def _dump(doc: dict[str, Any]) -> bytes:
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False).encode("utf-8")


BUILTIN = _dump(_doc("2026-10-01"))


def _public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode("ascii")


def _sign(key: Ed25519PrivateKey, data: bytes) -> bytes:
    return base64.b64encode(key.sign(data)) + b"\n"


def _yaml(compiled_on: str) -> bytes:
    return _dump(_doc(compiled_on))


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
    tampered = BUILTIN.replace(b"116 000", b"116 001")
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
    tampered = signed.replace(b"116 000", b"116 001")
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


def test_unquoted_yaml_date_is_not_valid_hotline_data(key: Ed25519PrivateKey, tmp_path: Path):
    # compiled_on_of reads it, but the store only takes quoted dates: the whole pack is
    # refused rather than accepted and then failing when a card is built.
    data = _yaml("2026-10-15").replace(b"compiled_on: '2026-10-15'", b"compiled_on: 2026-10-15")
    assert b"compiled_on: 2026-10-15\n" in data
    loaded = load_hotlines_bytes(_write_override(tmp_path, data, _sign(key, data)), today=TODAY)
    assert (loaded.source, loaded.reason) == ("builtin", bundle.REASON_INVALID)


# --- S2: a validly signed pack must be complete, well-formed hotline data ---------------


def _signed(key: Ed25519PrivateKey, tmp_path: Path, doc: dict[str, Any]) -> LoadedBundle:
    data = _dump(doc)
    return load_hotlines_bytes(_write_override(tmp_path, data, _sign(key, data)), today=TODAY)


def _without_gb_emergency_list(doc: dict[str, Any]) -> None:
    del doc["regions"]["GB"]["emergency"]


def _unknown_kind(doc: dict[str, Any]) -> None:
    doc["regions"]["GB"]["lines"][0]["kind"] = "nonsense"


def _missing_line_field(doc: dict[str, Any]) -> None:
    del doc["regions"]["GB"]["lines"][0]["number"]


def _empty_emergency(doc: dict[str, Any]) -> None:
    doc["regions"]["GB"]["emergency"] = []


@pytest.mark.parametrize(
    "damage", [_without_gb_emergency_list, _unknown_kind, _missing_line_field, _empty_emergency]
)
def test_signed_pack_with_bad_structure_falls_back(key, tmp_path, damage):
    doc = _doc("2026-10-15")
    damage(doc)
    loaded = _signed(key, tmp_path, doc)
    assert loaded == LoadedBundle(BUILTIN, "builtin", bundle.REASON_INVALID)


def _without_gb(doc: dict[str, Any]) -> None:
    del doc["regions"]["GB"]


def _drops_an_emergency_number(doc: dict[str, Any]) -> None:
    doc["regions"]["GB"]["emergency"] = [_emergency("999")]


def _changes_an_emergency_number(doc: dict[str, Any]) -> None:
    doc["regions"]["GB"]["emergency"][0]["number"] = "998"


@pytest.mark.parametrize(
    "damage", [_without_gb, _drops_an_emergency_number, _changes_an_emergency_number]
)
def test_signed_pack_that_drops_builtin_coverage_falls_back(key, tmp_path, damage):
    doc = _doc("2026-10-15")
    damage(doc)
    loaded = _signed(key, tmp_path, doc)
    assert loaded == LoadedBundle(BUILTIN, "builtin", bundle.REASON_INCOMPLETE)


def test_signed_pack_may_add_regions_numbers_and_lines(key, tmp_path):
    doc = _doc("2026-10-15")
    doc["regions"]["GB"]["emergency"].append(_emergency("911"))
    doc["regions"]["GB"]["lines"][0]["number"] = "116 123"  # a line number may change
    doc["regions"]["US"] = {"emergency": [_emergency("911")], "lines": [_line("us_test", "988")]}
    loaded = _signed(key, tmp_path, doc)
    assert (loaded.source, loaded.reason) == ("override", None)


def test_emergency_numbers_compare_without_spaces(key, tmp_path):
    doc = _doc("2026-10-15")
    doc["regions"]["GB"]["emergency"][0]["number"] = "9 9 9"
    assert _signed(key, tmp_path, doc).source == "override"


def test_an_invalid_builtin_is_a_damaged_package(monkeypatch: pytest.MonkeyPatch, tmp_path):
    private = Ed25519PrivateKey.generate()
    monkeypatch.setattr(keys, "HOTLINE_PUBLIC_KEY_B64", _public_b64(private))
    broken = _dump({"version": 1, "compiled_on": "2026-10-01", "regions": {}})
    monkeypatch.setattr(bundle, "_read_builtin", lambda: (broken, _sign(private, broken)))
    data = _yaml("2026-10-15")
    with pytest.raises(BundleIntegrityError):
        load_hotlines_bytes(_write_override(tmp_path, data, _sign(private, data)), today=TODAY)


def test_an_unreadable_builtin_is_a_damaged_package(monkeypatch: pytest.MonkeyPatch):
    def missing() -> tuple[bytes, bytes]:
        raise FileNotFoundError("hotlines.yaml.sig")

    monkeypatch.setattr(bundle, "_read_builtin", missing)
    with pytest.raises(BundleIntegrityError):
        load_hotlines_bytes(None, today=TODAY)
