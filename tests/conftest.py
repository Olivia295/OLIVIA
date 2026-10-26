"""Suite-wide fixtures.

No test may ever reach the real OS keychain: every test gets a fresh in-memory
:class:`FakeKeychain` as the default key backend, and ``keyring.get_keyring`` is
replaced so that an accidental call fails loudly instead of touching the user's keychain.
Underneath both, for the whole process (subprocesses included), ``keyring`` itself only
knows its failing backend, which OLIVIA treats as no keychain at all: a test that undoes
the fixture's patches (``monkeypatch.undo()``) still cannot reach the real keychain.

Likewise no test may install a scheduled job or show a notification (B9): every test gets
a :class:`FakeMachine` as ``olivia.notify.system.current_host``, and the real runner fails
loudly if anything reaches it.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import keyring
import keyring.backends.fail
import pytest

from olivia.core.chang import onboarding as onboarding_module
from olivia.core.crypto import keychain as keychain_module
from olivia.core.crypto.errors import KeychainUnavailableError
from olivia.notify import system as notify_system

os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
keyring.set_keyring(keyring.backends.fail.Keyring())


class FakeKeychain:
    """An in-memory :class:`olivia.core.crypto.keychain.KeyBackend`.

    Set ``broken`` to an exception (for example :class:`NoKeychainError`) to make every
    call fail the way an unavailable keychain does. ``reads`` and ``writes`` record the item
    names asked for and stored; ``probes`` counts :meth:`ready` calls, which touch no item.
    """

    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.broken: KeychainUnavailableError | None = None
        self.reads: list[str] = []
        self.writes: list[str] = []
        self.probes = 0

    def _check(self) -> None:
        if self.broken is not None:
            raise self.broken

    def ready(self) -> None:
        self.probes += 1
        self._check()

    def get(self, name: str) -> str | None:
        self.reads.append(name)
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


class FakeMachine:
    """The machine the B9 reminders see in tests (``olivia.notify.system.current_host``).

    Nothing is ever installed or shown: every program "run" is recorded in ``calls`` as
    ``(argv, stdin)`` and answered from ``results`` (the first argv prefix that matches),
    else with success. ``found`` is what ``which`` finds on PATH.
    """

    def __init__(self, home: Path) -> None:
        self.system = notify_system.System.MACOS
        self.home = home
        self.config_home = home / ".config"
        self.uid = 501
        self.user = "tester"
        self.command: tuple[str, ...] = ("/opt/olivia/bin/olivia",)
        self.found: set[str] = set()
        self.results: dict[tuple[str, ...], notify_system.RunResult] = {}
        self.calls: list[tuple[tuple[str, ...], str | None]] = []

    @property
    def argvs(self) -> list[tuple[str, ...]]:
        return [argv for argv, _ in self.calls]

    def run(self, argv: Sequence[str], stdin: str | None) -> notify_system.RunResult:
        self.calls.append((tuple(argv), stdin))
        for prefix, result in self.results.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return result
        return notify_system.RunResult(0)

    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if name in self.found else None

    def host(self) -> notify_system.Host:
        return notify_system.Host(
            system=self.system,
            home=self.home,
            config_home=self.config_home,
            uid=self.uid,
            user=self.user,
            command=self.command,
            run=self.run,
            which=self.which,
        )


@pytest.fixture(autouse=True)
def machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> FakeMachine:
    """No test may install a scheduled job or show a notification on this machine."""
    fake = FakeMachine(tmp_path_factory.mktemp("user-home"))
    monkeypatch.setattr(notify_system, "current_host", fake.host)

    def forbidden(*_args: object, **_kwargs: object) -> notify_system.RunResult:
        raise AssertionError("tests must never run scheduler or notification programs")

    monkeypatch.setattr(notify_system, "system_runner", forbidden)
    return fake


@pytest.fixture(autouse=True)
def system_zone(monkeypatch: pytest.MonkeyPatch) -> str:
    """This computer's timezone as the product sees it: fixed to ``UTC`` in every test.

    ``olivia region ZZ`` and onboarding's "other region" default read it; a test that
    needs another zone patches ``olivia.core.chang.onboarding.system_timezone`` again.
    """
    monkeypatch.setattr(onboarding_module, "system_timezone", lambda: "UTC")
    return "UTC"
