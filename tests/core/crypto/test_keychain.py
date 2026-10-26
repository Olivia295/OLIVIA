"""The OS-keychain adapter, driven through injected ``keyring`` backends only (B1).

The real keychain is never touched: ``tests/conftest.py`` makes ``keyring.get_keyring``
fail, and every adapter here is given an in-memory or deliberately failing backend.
"""

from __future__ import annotations

import keyring.backends.fail
import keyring.backends.null
import pytest
from keyring.backend import KeyringBackend as KeyringBase
from keyring.errors import KeyringLocked, PasswordDeleteError

from olivia.core.crypto import keychain
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError

REAL_DEFAULT = keychain.default_backend  # captured before the autouse fixture patches it


class MemoryKeyring(KeyringBase):
    priority = 5  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.data.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.data[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.data:
            raise PasswordDeleteError("not found")
        del self.data[(service, username)]


class LockedKeyring(MemoryKeyring):
    def get_password(self, service: str, username: str) -> str | None:
        raise KeyringLocked("locked")

    set_password = delete_password = get_password  # type: ignore[assignment]


class ForgetfulKeyring(MemoryKeyring):
    """Accepts writes and silently drops them."""

    def set_password(self, service: str, username: str, password: str) -> None:
        return None


class LowPriorityKeyring(MemoryKeyring):
    priority = 0.5  # type: ignore[assignment]  # e.g. keyrings.alt's plaintext file


def test_round_trip_under_the_olivia_service():
    backend = MemoryKeyring()
    store = keychain.KeyringBackend(backend)
    assert store.get("master-key") is None
    store.set("master-key", "value")
    assert store.get("master-key") == "value"
    assert backend.data == {(keychain.SERVICE, "master-key"): "value"}
    store.delete("master-key")
    store.delete("master-key")  # deleting an absent item is not an error
    assert store.get("master-key") is None


@pytest.mark.parametrize(
    "backend",
    [keyring.backends.fail.Keyring(), keyring.backends.null.Keyring(), LowPriorityKeyring()],
    ids=["fail", "null", "low-priority"],
)
def test_no_usable_backend_is_reported_as_no_keychain(backend):
    store = keychain.KeyringBackend(backend)
    for call in (lambda: store.get("master-key"), lambda: store.set("master-key", "v")):
        with pytest.raises(NoKeychainError):
            call()


def test_locked_keychain_is_unavailable_but_not_absent():
    store = keychain.KeyringBackend(LockedKeyring())
    with pytest.raises(KeychainUnavailableError) as info:
        store.get("master-key")
    assert not isinstance(info.value, NoKeychainError)
    with pytest.raises(KeychainUnavailableError):
        store.set("master-key", "v")
    with pytest.raises(KeychainUnavailableError):
        store.delete("master-key")


def test_a_write_the_keychain_does_not_keep_is_an_error():
    store = keychain.KeyringBackend(ForgetfulKeyring())
    with pytest.raises(KeychainUnavailableError):
        store.set("master-key", "v")


@pytest.mark.parametrize("name", ["", "Master", "小林的钥匙", "a b", "x" * 65])
def test_item_names_are_fixed_identifiers(name):
    store = keychain.KeyringBackend(MemoryKeyring())
    with pytest.raises(ValueError):
        store.get(name)


def test_default_backend_is_the_os_keychain_and_resolves_lazily():
    backend = REAL_DEFAULT()
    assert isinstance(backend, keychain.KeyringBackend)
    # Resolving the OS keyring happens on first use; here that hits the test guard.
    with pytest.raises(AssertionError):
        backend.get("master-key")


# -- probing without touching an item (olivia doctor) ------------------------------------------


class CountingKeyring(MemoryKeyring):
    """Fails the test on any item access."""

    def get_password(self, service: str, username: str) -> str | None:
        raise AssertionError("ready() must not read an item")

    set_password = delete_password = get_password  # type: ignore[assignment]


def test_ready_resolves_the_backend_without_touching_an_item():
    keychain.KeyringBackend(CountingKeyring()).ready()


@pytest.mark.parametrize(
    "backend",
    [keyring.backends.fail.Keyring(), keyring.backends.null.Keyring(), LowPriorityKeyring()],
    ids=["fail", "null", "low-priority"],
)
def test_ready_reports_no_usable_backend_as_no_keychain(backend):
    with pytest.raises(NoKeychainError):
        keychain.KeyringBackend(backend).ready()


def test_probe_names_each_outcome(request):
    fake = request.getfixturevalue("keychain")  # the suite's in-memory keychain
    assert keychain.probe(fake) is keychain.Probe.READY
    fake.broken = NoKeychainError("none")
    assert keychain.probe(fake) is keychain.Probe.NONE
    fake.broken = KeychainUnavailableError("locked")
    assert keychain.probe(fake) is keychain.Probe.UNAVAILABLE
    assert fake.reads == [] and fake.writes == []


def test_probe_without_a_ready_method_is_unchecked():
    class Bare:
        def get(self, name: str) -> str | None:
            raise AssertionError("never read")

        def set(self, name: str, value: str) -> None:
            raise AssertionError("never written")

        def delete(self, name: str) -> None:
            raise AssertionError("never deleted")

    assert keychain.probe(Bare()) is keychain.Probe.UNCHECKED


def test_probe_uses_the_default_backend(request):
    fake = request.getfixturevalue("keychain")
    assert keychain.probe() is keychain.Probe.READY
    assert fake.probes == 1 and fake.reads == []
