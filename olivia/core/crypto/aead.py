"""AES-256-GCM sealing with associated data that binds each blob to its store.

Blob layout (format version 1)::

    b"OLVD" | version (1 byte) | nonce (12 bytes) | ciphertext || tag (16 bytes)

The associated data is ``magic | version | 0x00 | store | 0x00 | label``, so a blob
only opens under the same key, for the same store name, with the same label (for
example ``profile``/``fields`` versus ``profile``/``whole``) and the same format version.
Nonces are random; each data key seals few messages, far below the 2**32 GCM bound.

``cryptography`` is imported on the first key, seal or open, not with this module (G-3:
importing the CLI stays light).
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Final

from olivia.core.crypto.errors import DecryptionError

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES: Final = 32
NONCE_BYTES: Final = 12
TAG_BYTES: Final = 16
FORMAT_VERSION: Final = 1
DATA_MAGIC: Final = b"OLVD"

_IDENTIFIER: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")
_HEADER: Final = DATA_MAGIC + bytes([FORMAT_VERSION])


def check_identifier(name: str, what: str = "store") -> str:
    """``name`` if it is a fixed lowercase identifier, else ``ValueError``.

    Store names and labels are code constants; this keeps user text out of them.
    """
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"invalid {what} name")
    return name


def new_key() -> bytes:
    """A fresh random 256-bit key."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM.generate_key(bit_length=KEY_BYTES * 8)


def _aad(store: str, label: str) -> bytes:
    check_identifier(store)
    if label:
        check_identifier(label, "label")
    return _HEADER + b"\x00" + store.encode("ascii") + b"\x00" + label.encode("ascii")


def _cipher(key: bytes) -> AESGCM:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(key) != KEY_BYTES:
        raise ValueError("key must be 256 bits")
    return AESGCM(key)


def seal_bytes(key: bytes, plaintext: bytes, *, store: str, label: str = "") -> bytes:
    """Encrypt and authenticate ``plaintext`` for ``store`` (and ``label``)."""
    aad = _aad(store, label)
    nonce = os.urandom(NONCE_BYTES)
    return _HEADER + nonce + _cipher(key).encrypt(nonce, plaintext, aad)


def open_bytes(key: bytes, blob: bytes, *, store: str, label: str = "") -> bytes:
    """Decrypt a :func:`seal_bytes` blob; any mismatch raises :class:`DecryptionError`."""
    aad = _aad(store, label)
    cipher = _cipher(key)
    from cryptography.exceptions import InvalidTag

    if len(blob) < len(_HEADER) + NONCE_BYTES + TAG_BYTES or blob[: len(DATA_MAGIC)] != DATA_MAGIC:
        raise DecryptionError("not an encrypted blob")
    if blob[len(DATA_MAGIC)] != FORMAT_VERSION:
        raise DecryptionError("unsupported encryption format version")
    nonce = blob[len(_HEADER) : len(_HEADER) + NONCE_BYTES]
    try:
        return cipher.decrypt(nonce, blob[len(_HEADER) + NONCE_BYTES :], aad)
    except InvalidTag as exc:
        raise DecryptionError("ciphertext failed authentication") from exc
