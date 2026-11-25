#!/usr/bin/env python3
"""Generate the ICU block of olivia/core/safety/_trad2simp.py.

    python scripts/gen_trad2simp.py [--check]

**macOS only.** The mapping comes from the ICU that ships with macOS, reached through
``osascript -l JavaScript`` (``NSString stringByApplyingTransform:reverse:`` with the ICU
transform ``Traditional-Simplified``). Nothing is downloaded and nothing else is read. On
any other platform the script exits with status 2. Tests never run it: every platform reads
only the committed table, so the fold does not depend on the ICU version of the machine.

Rules (each pair is one Traditional character and one Simplified character):

1. Candidates are the CJK Unified Ideographs U+4E00-U+9FFF that cannot be encoded in
   GB2312, i.e. that are not themselves valid Simplified characters. So 乾 (乾坤), 著
   (著名), 後, 於, 覆, 藉 and 沈 never fold here: they can all be encoded in GB2312.
2. ICU maps each candidate on its own (one per line, so no neighbour changes it).
3. A pair is kept when the result is one character, differs from the source and can be
   encoded in GB2312 (a common Simplified character).
4. Left out: sources of the hand-built pairs (``_PAIRS``: the hand table wins, and its
   disagreements with ICU are printed), the context-dependent characters of ``AMBIGUOUS``
   (each with its reason there), and any result that is itself a hand-built source (the
   fold must stay idempotent).

The kept pairs replace the block between the two ``generated`` markers of _trad2simp.py.
``--check`` rewrites nothing and exits 1 when the committed block differs from a fresh run.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from olivia.core.safety._trad2simp import (  # noqa: E402
    AMBIGUOUS,
    GENERATED_BEGIN,
    GENERATED_END,
    HAND_PAIRS,
    is_simplified,
)

TABLE = ROOT / "olivia" / "core" / "safety" / "_trad2simp.py"
FIRST, LAST = 0x4E00, 0x9FFF
PER_LINE = 18
TRANSFORM = "Traditional-Simplified"
_JXA = """
ObjC.import('Foundation');
function run(argv) {
  var text = $.NSString.alloc.initWithUTF8String(argv[0]);
  return ObjC.unwrap(text.stringByApplyingTransformReverse(argv[1], false));
}
"""


def icu(chars: list[str], transform: str = TRANSFORM) -> list[str]:
    """Each character through the macOS ICU transform, one per line."""
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", _JXA, "\n".join(chars), transform],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.rstrip("\n").split("\n")
    if len(lines) != len(chars):
        raise RuntimeError(f"ICU returned {len(lines)} lines for {len(chars)} characters")
    return lines


def candidates() -> list[str]:
    return [chr(cp) for cp in range(FIRST, LAST + 1) if not is_simplified(chr(cp))]


def generated_pairs() -> tuple[dict[str, str], list[str]]:
    """The pairs to commit, and notes on what was left out and why."""
    chars = candidates()
    pairs: dict[str, str] = {}
    notes: list[str] = []
    for trad, simp in zip(chars, icu(chars), strict=True):
        if simp == trad or len(simp) != 1 or not is_simplified(simp):
            continue
        if trad in HAND_PAIRS:
            if HAND_PAIRS[trad] != simp:
                notes.append(
                    f"手写表与 ICU 不同（保留手写）：{trad} → {HAND_PAIRS[trad]}（ICU {simp}）"
                )
            continue
        if trad in AMBIGUOUS:
            notes.append(f"有歧义，不收：{trad} → {simp}（{AMBIGUOUS[trad]}）")
            continue
        if simp in HAND_PAIRS:
            notes.append(f"目标字本身是手写表的源字，不收：{trad} → {simp}")
            continue
        pairs[trad] = simp
    return pairs, notes


def render(pairs: dict[str, str]) -> str:
    """The generated block, markers included, in code point order."""
    items = [f"{trad}{pairs[trad]}" for trad in sorted(pairs)]
    rows = [" ".join(items[i : i + PER_LINE]) + " " for i in range(0, len(items), PER_LINE)]
    body = "\n".join(f'    "{row}"' for row in rows)
    return f"{GENERATED_BEGIN}\n_GENERATED: Final = (\n{body}\n)\n{GENERATED_END}"


def splice(source: str, block: str) -> str:
    """``source`` with the block between the marker lines replaced (the markers are matched
    as whole lines, not where the module spells them as constants)."""
    start = source.index(f"\n{GENERATED_BEGIN}\n") + 1
    end = source.index(f"\n{GENERATED_END}\n", start) + 1 + len(GENERATED_END)
    return source[:start] + block + source[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用 macOS 自带的 ICU 生成繁简折叠表的生成部分。")
    parser.add_argument("--check", action="store_true", help="只比较，不改写；不一致时退出码 1")
    args = parser.parse_args(argv)
    if sys.platform != "darwin" or shutil.which("osascript") is None:
        print(
            "gen_trad2simp: 只能在 macOS 上运行（需要 osascript 与系统自带的 ICU）", file=sys.stderr
        )
        return 2
    pairs, notes = generated_pairs()
    for note in notes:
        print(note)
    source = TABLE.read_text(encoding="utf-8")
    updated = splice(source, render(pairs))
    print(f"生成 {len(pairs)} 对（候选 {len(candidates())} 字，手写 {len(HAND_PAIRS)} 对）")
    if args.check:
        if updated != source:
            print("gen_trad2simp: _trad2simp.py 的生成部分与重新生成的结果不同", file=sys.stderr)
            return 1
        return 0
    TABLE.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
