"""``training/data_gen/relabel_v02.py``: the annotation-guide v0.2 intent relabel (step C5)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA_GEN = ROOT / "training" / "data_gen"
_spec = importlib.util.spec_from_file_location("relabel_v02", DATA_GEN / "relabel_v02.py")
assert _spec is not None and _spec.loader is not None
relabel = importlib.util.module_from_spec(_spec)
sys.modules["relabel_v02"] = relabel
_spec.loader.exec_module(relabel)

MED = (4, "L0_med_self_adjust")


def _record(text: str, batch: str, slot: str | None, **labels: object) -> dict:
    """The combined-file shape: ten labels, ``source`` and (rounds 3, 4, 6) top-level ``slot``."""
    record: dict = {
        "text": text,
        "valence": -0.3,
        "emotion": "anxiety",
        "arousal": 0.45,
        "intent": "INFORMATION",
        "risk": "L0",
        "crisis_confidence": 0.0,
        "stance": "CONGRUENT",
        "readiness": 0.6,
        "dominant_spectrum": "02",
        "source": f"synthetic:{batch}",
    }
    if slot is not None:
        record["slot"] = slot
    record.update(labels)
    return record


def _run(tmp_path: Path, records: list[dict], include: frozenset = frozenset()):
    src, out = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    counts = relabel.relabel_file(src, out, include)
    return lines, out.read_text(encoding="utf-8").splitlines(), counts


def test_candidate_slots_exist_in_their_round_quota() -> None:
    for round_no, slot in [*relabel.DECISION_SLOTS, *relabel.MIXED_SLOTS]:
        quota = yaml.safe_load((DATA_GEN / f"quota_round{round_no}.yaml").read_text("utf-8"))
        assert quota["round"] == round_no
        assert slot in quota["risk_mix"], (round_no, slot)
        assert slot.startswith("L0_")
    assert round_no in (3, 4)


def test_by_default_mixed_slots_are_only_counted(tmp_path: Path) -> None:
    records = [
        _record("甲", "r4b01", "L0_med_self_adjust"),
        _record("乙", "r3b02", "L0_medical_request", intent="EXPLORATION"),
        _record("丙", "r4b03", "L0_diagnosis_question"),
        _record("丁", "r4b01", "L0_technique_request"),
    ]
    lines, result, counts = _run(tmp_path, records)
    assert result == lines
    assert counts["relabelled"] == 0
    assert counts["mixed_not_relabelled"] == 3
    assert counts["mixed_not_relabelled:r3:L0_medical_request:EXPLORATION"] == 1


def test_included_mixed_slot_becomes_referral_and_the_rest_is_copied(tmp_path: Path) -> None:
    records = [
        _record("甲", "r4b01", "L0_med_self_adjust"),
        _record("乙", "r4b02", "L0_med_self_adjust", intent="VALIDATION"),
        _record("丙", "r4b03", "L0_diagnosis_question"),  # mixed, not included
        _record("丁", "r6b05", "L0_med_self_adjust"),  # round 6 is never relabelled
        _record("戊", "b01", "L0_med_self_adjust"),  # round 1
        _record("己", "r4b01", None),  # no slot
    ]
    lines, result, counts = _run(tmp_path, records, frozenset({MED}))
    intents = [json.loads(line)["intent"] for line in result]
    assert intents == ["REFERRAL", "REFERRAL", *["INFORMATION"] * 4]
    assert result[2:] == lines[2:]  # untouched lines are copied byte for byte
    for before, after in zip(lines[:2], result[:2], strict=True):
        old, new = json.loads(before), json.loads(after)
        assert {k: v for k, v in old.items() if k != "intent"} == {
            k: v for k, v in new.items() if k != "intent"
        }
    assert counts["relabelled"] == 2
    assert counts["no_slot_round3_4"] == 1
    assert counts["records"] == 6


def test_high_arousal_stabilization_referral_and_crisis_rows_are_kept(tmp_path: Path) -> None:
    records = [
        _record("甲", "r4b01", "L0_med_self_adjust", intent="STABILIZATION", arousal=0.85),
        _record("乙", "r4b01", "L0_med_self_adjust", arousal=0.80),
        _record("丙", "r4b01", "L0_med_self_adjust", intent="REFERRAL"),
        _record("丁", "r4b01", "L0_med_self_adjust", intent="VALIDATION", risk="L2"),
    ]
    lines, result, counts = _run(tmp_path, records, frozenset({MED}))
    assert result == lines
    assert counts["relabelled"] == 0
    for reason in ("STABILIZATION", "arousal_ge_0.80", "REFERRAL", "risk_L2"):
        assert counts[f"kept:r4:L0_med_self_adjust:{reason}"] == 1


def test_meta_slot_of_raw_batch_files_is_read(tmp_path: Path) -> None:
    raw = {k: v for k, v in _record("甲", "r4b01", None).items() if k != "source"}
    raw["meta"] = {"batch": "r4b01", "slot": "L0_med_self_adjust"}
    _, result, counts = _run(tmp_path, [raw], frozenset({MED}))
    assert json.loads(result[0])["intent"] == "REFERRAL"
    assert counts["relabelled"] == 1


def test_parse_slot_accepts_only_mixed_slots() -> None:
    assert relabel.parse_slot("4:L0_med_self_adjust") == MED
    with pytest.raises(argparse.ArgumentTypeError):
        relabel.parse_slot("6:L0_med_diag_with_venting")
    with pytest.raises(argparse.ArgumentTypeError):
        relabel.parse_slot("L0_med_self_adjust")


def test_batch_round() -> None:
    assert relabel.batch_round("r4b01") == 4
    assert relabel.batch_round("r12b3") == 12
    assert relabel.batch_round("b01") is None
    assert relabel.batch_round("") is None
