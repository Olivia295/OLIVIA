#!/usr/bin/env python3
"""Relabel round-3 and round-4 synthetic data for annotation guide v0.2 (step C5).

Guide v0.2 (2026-10-23, roadmap C4; ``docs/eval/perception-annotation-guide.md`` §4.4)
puts requests that only a doctor can answer -- asking the companion to prescribe, to
confirm one's own dose change, stop or switch, to diagnose oneself, or where to go and
which department -- under ``intent = REFERRAL`` (§4.2 step 3), while pure knowledge
questions (what a drug usually does, its common side effects, "does this count as
depression") stay ``INFORMATION``. Rounds 3 and 4 were labelled before that rule.

The only machine-readable trace of what a message asks for is its quota slot (top-level
``slot``, or ``meta.slot`` in raw batch files; the round comes from ``source`` =
``synthetic:r4b02`` or ``meta.batch``). A slot can be relabelled wholesale only if it
holds decision requests alone. None of the round-3/4 medication or diagnosis slots does:

- round 3 ``L0_medical_request`` -- 能开药吗 (decision) but also 我是不是抑郁症 and
  某药副作用 (knowledge under §4.4 / §8);
- round 4 ``L0_med_self_adjust`` -- 加量、减量、停药、换药、漏服、买药 (decisions) but also
  问副作用 (knowledge);
- round 4 ``L0_diagnosis_question`` -- 要不要去看、你觉得我是什么问题 (REFERRAL) but also
  是不是某种病、怎么判断 (knowledge).

So ``DECISION_SLOTS`` is empty and these three are ``MIXED_SLOTS``: by default the script
changes nothing and only reports how many records each mixed slot would move. A mixed
slot is relabelled only when named with ``--include-mixed ROUND:SLOT`` (an owner's
decision). Not candidates at all: ``L0_technique_request`` / ``L0_redflag_topic_request``
(their REFERRAL rule is v0.1's red-flag clause, unchanged by v0.2), ``L2_med_ideation`` /
``L3_med_plan`` (REFERRAL already, constraint C1), and round 6 (written under v0.2).

Within a relabelled slot a record changes only when it is L0/L1, its arousal is below
0.80 and its intent is neither ``REFERRAL`` nor ``STABILIZATION`` (§4.2 step 2, high
arousal, comes first; schema constraint C2). Every other line is copied byte for byte.

    python training/data_gen/relabel_v02.py combined.jsonl --out relabelled.jsonl \
        [--include-mixed 4:L0_med_self_adjust ...]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

# (round, slot) pairs that hold only decision requests: relabelled by default. None so far.
DECISION_SLOTS: frozenset[tuple[int, str]] = frozenset()
# (round, slot) pairs that mix decision requests with knowledge questions: reported, and
# relabelled only with --include-mixed.
MIXED_SLOTS: dict[tuple[int, str], str] = {
    (3, "L0_medical_request"): "能开药吗（决定）+ 我是不是抑郁症、某药副作用（知识）",
    (4, "L0_med_self_adjust"): "加量减量停药换药漏服买药（决定）+ 问副作用（知识）",
    (4, "L0_diagnosis_question"): "要不要去看、你觉得我是什么问题（转介）+ 是不是某种病、怎么判断（知识）",
}
NEW_INTENT = "REFERRAL"
KEEP_INTENTS = frozenset({"REFERRAL", "STABILIZATION"})
STABILIZATION_AROUSAL = 0.80


def batch_round(batch: str) -> int | None:
    """``r4b01`` -> 4; round-1 batches (``b01``) and unknown ids -> None."""
    if len(batch) < 2 or batch[0] != "r" or not batch[1].isdigit():
        return None
    digits = ""
    for ch in batch[1:]:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits)


def record_round(record: dict) -> int | None:
    meta = record.get("meta") or {}
    batch = meta.get("batch") or str(record.get("source", "")).removeprefix("synthetic:")
    return batch_round(str(batch))


def record_slot(record: dict) -> str | None:
    slot = record.get("slot") or (record.get("meta") or {}).get("slot")
    return str(slot) if slot else None


def parse_slot(value: str) -> tuple[int, str]:
    """``4:L0_med_self_adjust`` -> (4, "L0_med_self_adjust"); must be a mixed slot."""
    round_text, _, slot = value.partition(":")
    key = (int(round_text), slot) if round_text.isdigit() else (-1, slot)
    if key not in MIXED_SLOTS:
        known = ", ".join(f"{r}:{s}" for r, s in sorted(MIXED_SLOTS))
        raise argparse.ArgumentTypeError(f"{value!r} is not a mixed slot ({known})")
    return key


def relabel_line(line: str, include: frozenset[tuple[int, str]], counts: Counter[str]) -> str:
    """The output line for one input line, counting what happened in ``counts``."""
    if not line.strip():
        return line
    record = json.loads(line)
    counts["records"] += 1
    key = (record_round(record), record_slot(record))
    if key[1] is None and key[0] in (3, 4):
        counts["no_slot_round3_4"] += 1
    if key not in DECISION_SLOTS and key not in MIXED_SLOTS:
        return line
    name = f"r{key[0]}:{key[1]}"
    intent = record.get("intent")
    if record.get("risk") not in ("L0", "L1"):
        counts[f"kept:{name}:risk_{record.get('risk')}"] += 1
        return line
    if intent in KEEP_INTENTS:
        counts[f"kept:{name}:{intent}"] += 1
        return line
    if float(record.get("arousal", 0.0)) >= STABILIZATION_AROUSAL:
        counts[f"kept:{name}:arousal_ge_0.80"] += 1
        return line
    if key in MIXED_SLOTS and key not in include:
        counts[f"mixed_not_relabelled:{name}:{intent}"] += 1
        counts["mixed_not_relabelled"] += 1
        return line
    counts[f"relabelled:{name}:{intent}->{NEW_INTENT}"] += 1
    counts["relabelled"] += 1
    record["intent"] = NEW_INTENT
    return json.dumps(record, ensure_ascii=False)


def relabel_file(src: Path, out: Path, include: frozenset[tuple[int, str]] = frozenset()) -> Counter[str]:
    counts: Counter[str] = Counter()
    lines = src.read_text(encoding="utf-8").splitlines()
    result = [relabel_line(line, include, counts) for line in lines]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(result) + "\n", encoding="utf-8")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("src", type=Path, help="merged or raw batch JSONL")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--include-mixed", type=parse_slot, action="append", default=[],
                        metavar="ROUND:SLOT", help="also relabel this mixed slot (owner's decision)")
    args = parser.parse_args()
    if args.out.resolve() == args.src.resolve():
        raise SystemExit("--out must differ from the input file")
    counts = relabel_file(args.src, args.out, frozenset(args.include_mixed))
    print(f"wrote {args.out}")
    for key in ("records", "relabelled", "mixed_not_relabelled", "no_slot_round3_4"):
        print(f"  {key}: {counts.get(key, 0)}")
    for key in sorted(k for k in counts if k.startswith(("relabelled:", "mixed_not_relabelled:", "kept:"))):
        print(f"  {key}: {counts[key]}")
    if counts.get("no_slot_round3_4"):
        print("note: round-3/4 records without a slot are never relabelled")


if __name__ == "__main__":
    main()
