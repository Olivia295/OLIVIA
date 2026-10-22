"""Public keys that verify OLIVIA's signed resource data (GEO-08).

The matching private key never enters the repository: it lives at
``~/.config/olivia/signing/hotlines.ed25519.signing.key`` on the release machine and is
used only by ``scripts/sign_hotlines.py``. Rotating it (``--rotate``) prints a new public
key, which must replace the value below in the same change that re-signs the data.
"""

from typing import Final

# Raw 32-byte Ed25519 public key, base64. Verifies olivia/data/resources/hotlines.yaml.sig.
HOTLINE_PUBLIC_KEY_B64: Final = "Xsknzney9U1xJNdefEq1e6MvA0ePpXKhgHkFg3BMFi0="
