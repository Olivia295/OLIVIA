"""Where the master key lives: the OS keychain, through ``keyring`` (decision Q7).

macOS Keychain, Windows Credential Manager, or the Secret Service / KWallet on Linux.
Items live under the service ``olivia`` and have fixed names (``master-key``,
``master-key-next``); user text never becomes an item name. A backend ``keyring``
itself does not recommend (priority below 1: the failing and null backends, plaintext
file backends from ``keyrings.alt``) counts as no keychain at all, and every write is
read back, so a backend that silently drops writes can never lose a master key.

Tests never reach the real keychain: they replace :func:`default_backend`.

``keyring`` is imported on the first keychain read, write or delete, not with this module:
it pulls in ``urllib.request`` and, on macOS, the system frameworks behind it (about 20 MB
of the SDD §0 50 MB envelope), and commands that never touch the vault do not need it.
Resolving the backend still happens in the same place and the same order as before.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Protocol

from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError

if TYPE_CHECKING:
    from keyring.backend import KeyringBackend as _KeyringBase

SERVICE: Final = "olivia"
_RECOMMENDED_PRIORITY: Final = 1
_ITEM_NAME: Final = re.compile(r"[a-z][a-z0-9-]{0,63}")


class KeyBackend(Protocol):
    """A small secret store. Every method may raise :class:`KeychainUnavailableError`."""

    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None:
        """Remove ``name``; removing an absent item is not an error."""


class KeyringBackend:
    """:class:`KeyBackend` over ``keyring``; ``backend`` overrides the OS default."""

    def __init__(self, backend: _KeyringBase | None = None, service: str = SERVICE) -> None:
        self._injected = backend
        self._service = service

    def _keyring(self) -> _KeyringBase:
        import keyring
        from keyring.errors import KeyringError

        try:
            backend = self._injected if self._injected is not None else keyring.get_keyring()
        except KeyringError as exc:
            raise NoKeychainError("no keychain backend could be loaded") from exc
        if backend.priority < _RECOMMENDED_PRIORITY:
            raise NoKeychainError("no recommended keychain backend on this device")
        return backend

    @staticmethod
    def _name(name: str) -> str:
        if not _ITEM_NAME.fullmatch(name):
            raise ValueError("invalid keychain item name")
        return name

    def get(self, name: str) -> str | None:
        item = self._name(name)
        backend = self._keyring()
        from keyring.errors import NoKeyringError

        try:
            return backend.get_password(self._service, item)
        except NoKeyringError as exc:
            raise NoKeychainError("no keychain backend on this device") from exc
        except Exception as exc:  # OS keychain errors are not all KeyringError subclasses
            raise KeychainUnavailableError("the keychain could not be read") from exc

    def set(self, name: str, value: str) -> None:
        item = self._name(name)
        backend = self._keyring()
        from keyring.errors import NoKeyringError

        try:
            backend.set_password(self._service, item, value)
        except NoKeyringError as exc:
            raise NoKeychainError("no keychain backend on this device") from exc
        except Exception as exc:
            raise KeychainUnavailableError("the keychain could not be written") from exc
        if self.get(item) != value:
            raise KeychainUnavailableError("the keychain did not keep the item")

    def delete(self, name: str) -> None:
        item = self._name(name)
        backend = self._keyring()
        from keyring.errors import NoKeyringError

        try:
            backend.delete_password(self._service, item)
        except NoKeyringError as exc:
            raise NoKeychainError("no keychain backend on this device") from exc
        except Exception as exc:
            # Most backends raise PasswordDeleteError for an absent item: that is fine.
            if self.get(item) is not None:
                raise KeychainUnavailableError("the keychain item could not be deleted") from exc


def default_backend() -> KeyBackend:
    """The OS keychain. Resolving the actual ``keyring`` backend waits until first use."""
    return KeyringBackend()
