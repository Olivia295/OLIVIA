"""G-3 memory: heavy libraries load only on the paths that use them (SDD §0, < 50 MB).

NumPy and the student load only in ``--model`` mode; ``keyring`` only when the OS keychain
is first asked for a key; ``cryptography`` only when something is sealed, opened or
verified. Each check runs in a fresh interpreter, so modules other tests imported do not
count.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEAVY = ("numpy", "keyring", "cryptography")


def _loaded_after(code: str) -> set[str]:
    probe = (
        f"{code}\nimport json, sys\n"
        f"print(json.dumps(sorted(m for m in {HEAVY!r} if m in sys.modules)))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=ROOT
    )
    return set(json.loads(done.stdout.splitlines()[-1]))


def test_importing_the_cli_loads_none_of_them() -> None:
    assert _loaded_after("import olivia.cli") == set()


def test_a_rules_mode_choice_leaves_numpy_unloaded() -> None:
    code = (
        "from olivia.core.perception.student import choose_risk_model\n"
        "assert choose_risk_model(student=False).model is None"
    )
    assert "numpy" not in _loaded_after(code)


def test_model_mode_loads_numpy_and_the_student() -> None:
    code = (
        "from olivia.core.perception.student import choose_risk_model\n"
        "assert choose_risk_model(student=True).student is not None"
    )
    assert "numpy" in _loaded_after(code)


def test_sealing_loads_cryptography_and_an_injected_key_store_needs_no_keyring() -> None:
    code = (
        "from olivia.core.crypto import aead\n"
        "key = aead.new_key()\n"
        "blob = aead.seal_bytes(key, b'x', store='ledger')\n"
        "assert aead.open_bytes(key, blob, store='ledger') == b'x'"
    )
    assert _loaded_after(code) == {"cryptography"}
