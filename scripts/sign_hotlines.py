"""Sign the hotline data with the OLIVIA Ed25519 release key (GEO-08).

Usage:
    python scripts/sign_hotlines.py                 # sign hotlines.yaml -> hotlines.yaml.sig
    python scripts/sign_hotlines.py --generate-key  # first run on a new machine: create key, sign
    python scripts/sign_hotlines.py --rotate        # replace the key, sign (update keys.py!)

The private key lives OUTSIDE the repository at
~/.config/olivia/signing/hotlines.ed25519.signing.key (PEM, mode 0600, directory 0700).
This script never prints or copies it; it prints only the public key (base64 of the raw
32 bytes), which belongs in olivia/core/resources/keys.py as HOTLINE_PUBLIC_KEY_B64.
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATA = REPO / "olivia" / "data" / "resources" / "hotlines.yaml"
DEFAULT_KEY = Path.home() / ".config" / "olivia" / "signing" / "hotlines.ed25519.signing.key"


def _fail(message: str) -> int:
    print(f"sign_hotlines: {message}", file=sys.stderr)
    return 1


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO)
    except ValueError:
        return False
    return True


def _write_new_key(key_path: Path) -> None:
    key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(key_path.parent, 0o700)
    pem = Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    # Write to a fresh 0600 file, then move it into place, so the key is never readable
    # by others and a crash cannot leave a half-written key behind.
    tmp = key_path.with_name(key_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    os.replace(tmp, key_path)
    os.chmod(key_path, 0o600)


def _load_key(key_path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError(f"{key_path} is not an Ed25519 private key")
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--generate-key", action="store_true", help="create the signing key if absent"
    )
    parser.add_argument(
        "--rotate", action="store_true", help="replace an existing signing key with a new one"
    )
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY, help=argparse.SUPPRESS)
    parser.add_argument("--file", type=Path, default=DEFAULT_DATA, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    key_path: Path = args.key.expanduser()
    data_path: Path = args.file
    if _inside_repo(key_path):
        return _fail(f"refusing to use a signing key inside the repository: {key_path}")

    if args.generate_key or args.rotate:
        if key_path.exists() and not args.rotate:
            return _fail(f"{key_path} already exists; pass --rotate to replace it")
        _write_new_key(key_path)
        print(f"wrote new signing key to {key_path} (mode 0600)", file=sys.stderr)
    elif not key_path.exists():
        return _fail(f"no signing key at {key_path}; run with --generate-key first")

    key = _load_key(key_path)
    data = data_path.read_bytes()
    signature = key.sign(data)
    public = key.public_key()
    try:
        public.verify(signature, data)
    except InvalidSignature:
        return _fail("self-check failed: the new signature does not verify")

    sig_path = data_path.with_name(data_path.name + ".sig")
    sig_path.write_bytes(base64.b64encode(signature) + b"\n")
    raw_public = public.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    print(f"signed {data_path} -> {sig_path}", file=sys.stderr)
    print(base64.b64encode(raw_public).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
