"""At-rest encryption: AES-256-GCM, envelope keys, crypto-shredding (B1, Q6, Q7).

See :mod:`olivia.core.crypto.vault` for the key hierarchy and SDD §6.6 for the threat model.
"""

from olivia.core.crypto.errors import (
    CryptoError,
    DecryptionError,
    KeychainUnavailableError,
    KeyMissingError,
    NoKeychainError,
)
from olivia.core.crypto.keychain import KeyBackend, KeyringBackend
from olivia.core.crypto.vault import Vault

__all__ = [
    "CryptoError",
    "DecryptionError",
    "KeyBackend",
    "KeyMissingError",
    "KeychainUnavailableError",
    "KeyringBackend",
    "NoKeychainError",
    "Vault",
]
