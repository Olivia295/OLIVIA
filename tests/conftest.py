"""Suite-wide fixtures.

No test may ever reach the real OS keychain: every test gets a fresh in-memory
:class:`FakeKeychain` as the default key backend, and ``keyring.get_keyring`` is
replaced so that an accidental call fails loudly instead of touching the user's keychain.
"""

from __future__ import annotations

import keyring
import pytest

from olivia.core.crypto import keychain as keychain_module
from olivia.core.crypto.errors import KeychainUnavailableError


class FakeKeychain:
    """An in-memory :class:`olivia.core.crypto.keychain.KeyBackend`.

    Set ``broken`` to an exception (for example :class:`NoKeychainError`) to make every
    call fail the way an unavailable keychain does.
    """

    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.broken: KeychainUnavailableError | None = None
        self.writes: list[str] = []

    def _check(self) -> None:
        if self.broken is not None:
            raise self.broken

    def get(self, name: str) -> str | None:
        self._check()
        return self.items.get(name)

    def set(self, name: str, value: str) -> None:
        self._check()
        self.writes.append(name)
        self.items[name] = value

    def delete(self, name: str) -> None:
        self._check()
        self.items.pop(name, None)


@pytest.fixture(autouse=True)
def keychain(monkeypatch: pytest.MonkeyPatch) -> FakeKeychain:
    fake = FakeKeychain()
    monkeypatch.setattr(keychain_module, "default_backend", lambda: fake)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("tests must never touch the real OS keychain")

    monkeypatch.setattr(keyring, "get_keyring", forbidden)
    return fake


@pytest.fixture
def new_keychain() -> type[FakeKeychain]:
    """A factory for extra, independent keychains (another device, another user)."""
    return FakeKeychain
