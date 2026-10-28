"""Envelope encryption with one data key per store, and crypto-shredding (B1).

Key hierarchy (SDD §6.6)::

    OS keychain, item "master-key"     master key (KEK), 256-bit random
        └─ <data dir>/keys/<store>.key that store's data key (DEK), wrapped by the master
              └─ the store's files       AES-256-GCM blobs sealed with the DEK

A wrapped key file is ``b"OLVK" | version | master key id (8 bytes) | sealed DEK``; the
DEK is sealed with :func:`aead.seal_bytes` for the store's name and a label carrying the
master key id, so a key file only opens for its own store under its own master.

Crypto-shredding:

* :meth:`Vault.shred` deletes a store's wrapped key, then rotates the master key
  (re-wrapping the surviving keys), so even a copy of the deleted key file that lingers
  on disk becomes useless once the old master leaves the keychain. Shredding the last
  store deletes the master key outright.
* :meth:`Vault.shred_all` deletes every wrapped key and the master key ("forget
  everything").

Rotation is crash-safe: the new master is stored as ``master-key-next`` before any key
file is re-wrapped, both masters open key files meanwhile, and the next process to use
the vault finishes an interrupted rotation. A master key is created only on the first
seal, and never while wrapped keys exist without one, so a keychain that is reset or
briefly answers "no such item" can never cause a silent overwrite of a lost master.

Another process may change the keys under a vault that holds them in memory (a
``forget`` in a second terminal rotates the master key and re-keys a store). Only one
OLIVIA process writes a data directory at a time (:mod:`olivia.core.datalock`); as a
second line of defence a vault re-reads a store's key file whenever it changed on disk
since it was read, and re-reads the master key from the keychain before it wraps a new
data key, so it never seals under a key that is no longer the one on disk.

Nothing here logs, and keychain item names are fixed constants: user text never reaches
the keychain or an error message.
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from olivia.core.crypto import aead, keychain
from olivia.core.crypto.errors import (
    DecryptionError,
    KeychainUnavailableError,
    KeyFileUnreadableError,
    KeyMissingError,
)
from olivia.core.storage import atomic_write_bytes, remove_file

MASTER_ITEM: Final = "master-key"
NEXT_MASTER_ITEM: Final = "master-key-next"
KEYS_DIRNAME: Final = "keys"

_KEY_SUFFIX: Final = ".key"
_KEY_MAGIC: Final = b"OLVK"
_KEY_ID_BYTES: Final = 8
_KEY_HEADER: Final = len(_KEY_MAGIC) + 1 + _KEY_ID_BYTES
_MASTER_PREFIX: Final = "olivia-mk1"


@dataclass(frozen=True)
class _Master:
    key_id: bytes
    key: bytes


def encode_master(key_id: bytes, key: bytes) -> str:
    """The keychain value for a master key: ``olivia-mk1:<id hex>:<key base64>``."""
    return f"{_MASTER_PREFIX}:{key_id.hex()}:{base64.b64encode(key).decode('ascii')}"


def _decode_master(value: str) -> _Master:
    parts = value.split(":")
    try:
        if len(parts) != 3 or parts[0] != _MASTER_PREFIX:
            raise ValueError("unknown master key format")
        key_id = bytes.fromhex(parts[1])
        key = base64.b64decode(parts[2], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise KeyMissingError("the master key in the keychain is malformed") from exc
    if len(key_id) != _KEY_ID_BYTES or len(key) != aead.KEY_BYTES:
        raise KeyMissingError("the master key in the keychain is malformed")
    return _Master(key_id, key)


def _new_master() -> _Master:
    return _Master(os.urandom(_KEY_ID_BYTES), aead.new_key())


def _wrap_label(key_id: bytes) -> str:
    return f"dek_{key_id.hex()}"


def key_file_intact(base_dir: Path, store: str) -> bool:
    """Whether ``store``'s wrapped data key under ``base_dir`` is there and well formed.

    Only the file is read (header and length): nothing is unwrapped and the keychain is
    never asked, so whether its master key still exists is not known here.
    """
    path = base_dir / KEYS_DIRNAME / f"{aead.check_identifier(store)}{_KEY_SUFFIX}"
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    return (
        raw[: len(_KEY_MAGIC)] == _KEY_MAGIC
        and raw[len(_KEY_MAGIC) : len(_KEY_MAGIC) + 1] == bytes([aead.FORMAT_VERSION])
        and aead.looks_sealed(raw[_KEY_HEADER:], size=aead.KEY_BYTES)
    )


_Signature = tuple[int, int, int]


def _signature(path: Path) -> _Signature | None:
    """What changes when another process rewrites or removes ``path``."""
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_ino, st.st_size, st.st_mtime_ns


class Vault:
    """Seal and open data for named stores under ``base_dir``.

    ``backend`` is the master-key store; ``None`` means the OS keychain. Every method
    may raise :class:`KeychainUnavailableError` (or its :class:`NoKeychainError`).
    """

    def __init__(self, base_dir: Path, backend: keychain.KeyBackend | None = None) -> None:
        self.keys_dir: Path = base_dir / KEYS_DIRNAME
        self._backend = keychain.default_backend() if backend is None else backend
        self._loaded = False
        self._masters: dict[bytes, bytes] = {}
        self._current: _Master | None = None
        self._deks: dict[str, bytes] = {}
        self._signatures: dict[str, _Signature | None] = {}
        """Each cached data key's key file as it was when read or written."""

    def available(self) -> bool:
        """Whether the keychain answers now (a cheap read; nothing is created)."""
        try:
            self.check()
        except KeychainUnavailableError:
            return False
        return True

    def check(self) -> None:
        """Raise :class:`KeychainUnavailableError` (:class:`NoKeychainError` when this
        device has none) unless the keychain answers now; nothing is created."""
        self._backend.get(MASTER_ITEM)

    def seal(self, store: str, plaintext: bytes, *, label: str = "") -> bytes:
        """Encrypt for ``store``, creating its data key (and the master key) on first use."""
        aead.check_identifier(store)
        dek = self._data_key(store, create=True)
        return aead.seal_bytes(dek, plaintext, store=store, label=label)

    def open(self, store: str, blob: bytes, *, label: str = "") -> bytes:
        """Decrypt; :class:`KeyMissingError` if the store's keys are gone (shredded),
        :class:`DecryptionError` if the blob or the key file was tampered with."""
        aead.check_identifier(store)
        dek = self._data_key(store, create=False)
        return aead.open_bytes(dek, blob, store=store, label=label)

    def has_data_key(self, store: str) -> bool:
        return self._key_path(store).is_file()

    def has_data_keys(self) -> bool:
        """Whether any store has a wrapped key here (so a master key exists somewhere)."""
        return bool(self._key_files())

    def master_lost(self) -> bool:
        """Whether a wrapped data key here names a master key the keychain no longer holds
        (the item was removed, or the keychain reset): what it sealed cannot be opened.

        False when there is no wrapped key or the keychain does not answer now (a locked
        keychain is not a lost key). Reads the two master items; creates nothing.
        """
        files = self._key_files()
        if not files:
            return False
        try:
            held = {
                _decode_master(raw).key_id
                for raw in (self._backend.get(MASTER_ITEM), self._backend.get(NEXT_MASTER_ITEM))
                if raw is not None
            }
        except KeyMissingError:  # a malformed item opens nothing
            held = set()
        except KeychainUnavailableError:
            return False
        for _, path in files:
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            well_formed = len(raw) > _KEY_HEADER and raw[: len(_KEY_MAGIC)] == _KEY_MAGIC
            if well_formed and raw[len(_KEY_MAGIC) + 1 : _KEY_HEADER] not in held:
                return True
        return False

    def check_data_key(self, store: str) -> None:
        """Raise unless ``store``'s data key opens now: :class:`KeyMissingError` (none, or
        its master is gone), :class:`DecryptionError` (the key file is damaged) or
        :class:`KeychainUnavailableError`. Nothing is created."""
        aead.check_identifier(store)
        self._data_key(store, create=False)

    def shred(self, store: str) -> None:
        """Make everything sealed for ``store`` permanently unreadable."""
        path = self._key_path(store)
        self._deks.pop(store, None)
        self._signatures.pop(store, None)
        remove_file(path)
        if self._key_files():
            self.rotate_master_key()
        else:
            self._delete_masters()

    def shred_all(self) -> None:
        """Make everything this vault ever sealed permanently unreadable.

        Wrapped keys are deleted first (always possible locally); the keychain error, if
        any, is raised afterwards.
        """
        self._deks.clear()
        self._signatures.clear()
        try:
            for _, path in self._key_files():
                remove_file(path)
        finally:
            self._delete_masters()

    def rotate_master_key(self) -> None:
        """Re-wrap every data key under a fresh master key and delete the old one."""
        self._load()
        if self._current is None:
            return
        new = _new_master()
        self._backend.set(NEXT_MASTER_ITEM, encode_master(new.key_id, new.key))
        self._masters[new.key_id] = new.key
        self._finish_rotation(new)

    # -- internals ---------------------------------------------------------------------

    def _key_path(self, store: str) -> Path:
        return self.keys_dir / f"{aead.check_identifier(store)}{_KEY_SUFFIX}"

    def _key_files(self) -> list[tuple[str, Path]]:
        if not self.keys_dir.is_dir():
            return []
        found = []
        for path in self.keys_dir.iterdir():
            store = path.name.removesuffix(_KEY_SUFFIX)
            if path.is_file() and path.name.endswith(_KEY_SUFFIX):
                try:
                    found.append((aead.check_identifier(store), path))
                except ValueError:
                    continue
        return sorted(found)

    def _load(self) -> None:
        if self._loaded:
            return
        current_raw = self._backend.get(MASTER_ITEM)
        next_raw = self._backend.get(NEXT_MASTER_ITEM)
        self._current = _decode_master(current_raw) if current_raw is not None else None
        self._masters = {} if self._current is None else {self._current.key_id: self._current.key}
        if next_raw is not None:  # an earlier rotation was interrupted: finish it
            new = _decode_master(next_raw)
            self._masters[new.key_id] = new.key
            self._finish_rotation(new)
        self._loaded = True

    def _finish_rotation(self, new: _Master) -> None:
        for store, path in self._key_files():
            try:
                key_id, dek = self._unwrap(path, store)
            except (KeyMissingError, DecryptionError):
                continue  # unreadable under every master: nothing to carry forward
            if key_id != new.key_id:
                self._write_wrapped(path, store, dek, new)
        self._backend.set(MASTER_ITEM, encode_master(new.key_id, new.key))
        self._backend.delete(NEXT_MASTER_ITEM)
        self._masters = {new.key_id: new.key}
        self._current = new

    def _delete_masters(self) -> None:
        self._loaded = False
        self._masters, self._current = {}, None
        self._backend.delete(NEXT_MASTER_ITEM)
        self._backend.delete(MASTER_ITEM)
        self._loaded = True

    def _current_or_new_master(self) -> _Master:
        if self._current is not None:
            return self._current
        if self._key_files():
            raise KeyMissingError("data keys exist but their master key is gone")
        master = _new_master()
        self._backend.set(MASTER_ITEM, encode_master(master.key_id, master.key))
        self._masters[master.key_id] = master.key
        self._current = master
        return master

    def _forget_cached_keys(self) -> None:
        """Drop every key held in memory; the next use reads the keychain and disk again."""
        self._loaded = False
        self._masters, self._current = {}, None
        self._deks.clear()
        self._signatures.clear()

    def _data_key(self, store: str, *, create: bool) -> bytes:
        path = self._key_path(store)
        cached = self._deks.get(store)
        if cached is not None:
            if self._signatures.get(store) == _signature(path):
                return cached
            self._forget_cached_keys()  # another process changed the keys meanwhile
        self._load()
        if path.is_file():
            _, dek = self._unwrap(path, store)
        elif not create:
            raise KeyMissingError("this store has no data key")
        else:
            self._reload_if_master_changed()
            master = self._current_or_new_master()
            dek = aead.new_key()
            self._write_wrapped(path, store, dek, master)
        self._deks[store] = dek
        self._signatures[store] = _signature(path)
        return dek

    def _reload_if_master_changed(self) -> None:
        """Before wrapping a new data key: is the master in memory still the keychain's?"""
        current_raw = self._backend.get(MASTER_ITEM)
        on_keychain = _decode_master(current_raw).key_id if current_raw is not None else None
        held = self._current.key_id if self._current is not None else None
        if on_keychain != held or self._backend.get(NEXT_MASTER_ITEM) is not None:
            self._forget_cached_keys()
            self._load()

    def _unwrap(self, path: Path, store: str) -> tuple[bytes, bytes]:
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise KeyMissingError("this store has no data key") from exc
        except OSError as exc:
            raise KeyFileUnreadableError("a wrapped data key cannot be read") from exc
        if (
            len(raw) <= _KEY_HEADER
            or raw[: len(_KEY_MAGIC)] != _KEY_MAGIC
            or raw[len(_KEY_MAGIC)] != aead.FORMAT_VERSION
        ):
            raise DecryptionError("not a wrapped data key")
        key_id = raw[len(_KEY_MAGIC) + 1 : _KEY_HEADER]
        master = self._masters.get(key_id)
        if master is None:
            raise KeyMissingError("the master key for this data key is gone")
        dek = aead.open_bytes(master, raw[_KEY_HEADER:], store=store, label=_wrap_label(key_id))
        if len(dek) != aead.KEY_BYTES:
            raise DecryptionError("wrapped data key has the wrong length")
        return key_id, dek

    def _write_wrapped(self, path: Path, store: str, dek: bytes, master: _Master) -> None:
        if not self.keys_dir.is_dir():
            self.keys_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                self.keys_dir.chmod(0o700)
        body = aead.seal_bytes(master.key, dek, store=store, label=_wrap_label(master.key_id))
        header = _KEY_MAGIC + bytes([aead.FORMAT_VERSION]) + master.key_id
        atomic_write_bytes(path, header + body, snapshot=False)
        if store in self._deks:
            self._signatures[store] = _signature(path)


class ReadOnlyVault(Vault):
    """A vault that only opens (``olivia doctor``): it reads the master key items, never
    finishes an interrupted rotation, and never creates, writes or deletes a key."""

    def _load(self) -> None:
        if self._loaded:
            return
        masters: dict[bytes, bytes] = {}
        for item in (MASTER_ITEM, NEXT_MASTER_ITEM):
            raw = self._backend.get(item)
            if raw is not None:
                found = _decode_master(raw)
                masters[found.key_id] = found.key
        self._masters, self._current, self._loaded = masters, None, True

    def _finish_rotation(self, new: _Master) -> None:
        raise RuntimeError("a read-only vault changes no key")

    def _delete_masters(self) -> None:
        raise RuntimeError("a read-only vault changes no key")

    def _current_or_new_master(self) -> _Master:
        raise RuntimeError("a read-only vault changes no key")

    def _write_wrapped(self, path: Path, store: str, dek: bytes, master: _Master) -> None:
        raise RuntimeError("a read-only vault changes no key")
