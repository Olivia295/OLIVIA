"""The suite-wide keychain guard holds even when a test drops the fixture's patches."""

from __future__ import annotations

import pytest

from olivia.core.crypto import keychain
from olivia.core.crypto.errors import NoKeychainError


def test_undoing_the_fixture_patches_still_reaches_no_keychain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This is what once let a test reach the real keychain: undo() drops the autouse
    # fixture's fake backend and its get_keyring trap. keyring's own backend is the
    # failing one for the whole process, so the real wrapper finds no keychain at all.
    monkeypatch.undo()
    with pytest.raises(NoKeychainError):
        keychain.default_backend().get("master-key")
    with pytest.raises(NoKeychainError):
        keychain.KeyringBackend().set("master-key", "x")
