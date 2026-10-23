"""AES-256-GCM sealing with store-bound associated data (B1)."""

from __future__ import annotations

import pytest

from olivia.core.crypto import aead
from olivia.core.crypto.errors import DecryptionError

KEY = bytes(range(32))
OTHER_KEY = bytes(range(1, 33))


def test_round_trip_and_fresh_nonce():
    first = aead.seal_bytes(KEY, "心里有点乱".encode(), store="profile", label="fields")
    second = aead.seal_bytes(KEY, "心里有点乱".encode(), store="profile", label="fields")
    assert first != second  # a random nonce per message
    assert aead.open_bytes(KEY, first, store="profile", label="fields").decode() == "心里有点乱"
    assert "心里".encode() not in first


def test_empty_plaintext_round_trips():
    blob = aead.seal_bytes(KEY, b"", store="ledger")
    assert aead.open_bytes(KEY, blob, store="ledger") == b""


def test_wrong_key_is_rejected():
    blob = aead.seal_bytes(KEY, b"secret", store="profile")
    with pytest.raises(DecryptionError):
        aead.open_bytes(OTHER_KEY, blob, store="profile")


@pytest.mark.parametrize(("store", "label"), [("ledger", ""), ("profile", "whole")])
def test_store_and_label_are_bound(store, label):
    blob = aead.seal_bytes(KEY, b"secret", store="profile")
    with pytest.raises(DecryptionError):
        aead.open_bytes(KEY, blob, store=store, label=label)


def test_every_flipped_byte_is_detected():
    blob = aead.seal_bytes(KEY, b"twelve bytes", store="kit")
    for index in range(len(blob)):
        tampered = bytearray(blob)
        tampered[index] ^= 0x01
        with pytest.raises(DecryptionError):
            aead.open_bytes(KEY, bytes(tampered), store="kit")


@pytest.mark.parametrize("cut", [0, 4, 5, 17, -1])
def test_truncated_blob_is_rejected(cut):
    blob = aead.seal_bytes(KEY, b"secret", store="kit")
    with pytest.raises(DecryptionError):
        aead.open_bytes(KEY, blob[:cut], store="kit")


def test_unknown_format_version_is_rejected():
    blob = bytearray(aead.seal_bytes(KEY, b"secret", store="kit"))
    blob[len(aead.DATA_MAGIC)] = aead.FORMAT_VERSION + 1
    with pytest.raises(DecryptionError, match="version"):
        aead.open_bytes(KEY, bytes(blob), store="kit")


@pytest.mark.parametrize("store", ["", "Profile", "../x", "profile.json", "a" * 33, "小林"])
def test_store_names_are_fixed_identifiers(store):
    with pytest.raises(ValueError):
        aead.seal_bytes(KEY, b"x", store=store)


def test_key_must_be_256_bits():
    with pytest.raises(ValueError):
        aead.seal_bytes(KEY[:16], b"x", store="kit")
    assert len(aead.new_key()) == aead.KEY_BYTES == 32
    assert aead.new_key() != aead.new_key()
