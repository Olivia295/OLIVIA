"""Errors of the at-rest encryption layer.

Messages name only fixed identifiers (store names, keychain item names), never user text.
"""

from __future__ import annotations


class CryptoError(Exception):
    """Base class for every encryption-layer failure."""


class KeychainUnavailableError(CryptoError):
    """The OS keychain cannot be used right now (locked, access denied, backend error).

    Nothing was written. The data is intact and may open again later.
    """


class NoKeychainError(KeychainUnavailableError):
    """This device has no usable OS keychain (for example headless Linux without a backend).

    Sensitive data cannot be protected here, so it must not be stored at all.
    """


class KeyMissingError(CryptoError):
    """A key the data needs no longer exists.

    It was shredded, or the data came from another device or user account; the
    ciphertext can never be opened again.
    """


class DecryptionError(CryptoError):
    """Ciphertext or a wrapped key is corrupt, tampered with, or belongs to another store."""
