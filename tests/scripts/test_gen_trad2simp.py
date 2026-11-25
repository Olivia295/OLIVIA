"""``scripts/gen_trad2simp.py`` without ICU: the committed block is what the script writes.

The script itself needs macOS (``osascript`` and the system ICU) and never runs in tests;
every platform checks the committed table instead (tests/safety/test_normalize.py).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from olivia.core.safety._trad2simp import GENERATED_PAIRS

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("gen_trad2simp", ROOT / "scripts/gen_trad2simp.py")
assert _spec is not None and _spec.loader is not None
gen = importlib.util.module_from_spec(_spec)
sys.modules["gen_trad2simp"] = gen
_spec.loader.exec_module(gen)


def test_the_committed_block_is_the_rendering_of_its_pairs():
    source = gen.TABLE.read_text(encoding="utf-8")
    assert gen.splice(source, gen.render(GENERATED_PAIRS)) == source


def test_splice_replaces_only_the_marked_block():
    source = gen.TABLE.read_text(encoding="utf-8")
    spliced = gen.splice(source, gen.render({"亂": "乱"}))
    assert '    "亂乱 "\n' in spliced
    assert spliced.count(gen.GENERATED_BEGIN) == source.count(gen.GENERATED_BEGIN)
    head = source[: source.index(f"\n{gen.GENERATED_BEGIN}\n")]
    assert spliced.startswith(head)


def test_it_refuses_to_run_off_macos(monkeypatch, capsys):
    monkeypatch.setattr(gen.sys, "platform", "linux")
    assert gen.main([]) == 2
    assert "macOS" in capsys.readouterr().err
