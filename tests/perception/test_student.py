"""The packaged perception student (P6-6a): parity, loader failures, RiskModel contract."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from olivia.core.models import CrisisLevel
from olivia.core.perception import student as student_module
from olivia.core.perception.student import (
    CONFIG,
    MANIFEST,
    VOCAB,
    WEIGHTS,
    StudentLoad,
    StudentModel,
    StudentRiskModel,
    StudentUnavailableError,
    choose_risk_model,
    default_student,
    load_student,
    preprocess,
    try_load_student,
)
from olivia.core.safety.crisis import MODEL_FAILURE, RiskPrediction, SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

HERE = Path(__file__).parent
GOLDEN = json.loads((HERE / "student_golden.json").read_text(encoding="utf-8"))
SAFETY_CASES = yaml.safe_load((HERE.parent / "safety" / "cases.yaml").read_text(encoding="utf-8"))
PACKAGED = Path(str(resources.files("olivia").joinpath("data/models/perception")))
TOLERANCE = 1e-5
TAX = load_taxonomy()


@pytest.fixture(scope="module")
def student() -> StudentModel:
    loaded = default_student()
    assert loaded.reason is None and loaded.model is not None
    return loaded.model


# -- parity with the training notebook's reference forward -----------------------------------


def test_golden_fixture_matches_the_packaged_student(student: StudentModel) -> None:
    assert GOLDEN["student_fingerprint"] == student.fingerprint
    assert len(GOLDEN["cases"]) >= 40


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda c: f"{len(c['text'])}ch")
def test_forward_matches_the_reference(student: StudentModel, case: dict[str, Any]) -> None:
    raw = student.raw_outputs(case["text"])
    assert raw.shape == (len(case["raw"]),)
    assert np.allclose(raw, case["raw"], rtol=0, atol=TOLERANCE)
    heads = student.predict_heads(case["text"])
    probs = heads["risk"]
    assert isinstance(probs, dict)
    assert np.allclose(list(probs.values()), case["risk_probs"], rtol=0, atol=TOLERANCE)
    assert heads["crisis_confidence"] == pytest.approx(case["crisis_confidence"], abs=TOLERANCE)
    level, score = student.risk(case["text"])
    assert level == CrisisLevel(case["risk_level"])
    assert score == pytest.approx(case["crisis_confidence"], abs=TOLERANCE)


def test_golden_covers_the_edge_cases() -> None:
    texts = [c["text"] for c in GOLDEN["cases"]]
    assert "" in texts and any(len(t) == 1 for t in texts)
    assert any(len(t) > 500 for t in texts)
    assert any("&amp;" in t for t in texts) and any(" " in t for t in texts)
    assert any(ord(ch) > 0xFFFF for t in texts for ch in t)  # emoji


def test_preprocess_and_encode(student: StudentModel) -> None:
    assert preprocess("  鱼&amp;熊掌   好\t\n") == "鱼&熊掌 好"
    assert student.encode("") == [0] * 5  # padded to min_len with PAD
    long_ids = student.encode("一" * 100 + "二" * 120)
    assert len(long_ids) == 160
    assert long_ids[:48] == student.encode("一" * 48)[:48]
    assert long_ids[-112:] == student.encode("二" * 112)
    assert student.encode("😋")[0] == 1  # unknown code point -> UNK


def test_predict_heads_returns_every_head(student: StudentModel) -> None:
    heads = student.predict_heads("周末想去公园散散步")
    assert set(heads) == set(student.heads)
    for name, head in student.heads.items():
        value = heads[name]
        if head.kind == "class":
            assert isinstance(value, dict) and list(value) == list(head.labels or ())
            assert sum(value.values()) == pytest.approx(1.0)
        elif head.kind == "tanh":
            assert isinstance(value, float) and -1.0 <= value <= 1.0
        else:
            assert isinstance(value, float) and 0.0 <= value <= 1.0


# -- loader failures ---------------------------------------------------------------------------


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "model"
    shutil.copytree(PACKAGED, target)
    return target


def _remanifest(folder: Path) -> None:
    files = {}
    for name in (WEIGHTS, VOCAB, CONFIG):
        data = (folder / name).read_bytes()
        files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    doc = {"format_version": 1, "files": files}
    (folder / MANIFEST).write_text(json.dumps(doc), encoding="utf-8")


def _arrays(folder: Path) -> dict[str, np.ndarray]:
    with np.load(folder / WEIGHTS, allow_pickle=False) as npz:
        return {name: npz[name] for name in npz.files}


def _save_npz(folder: Path, arrays: dict[str, Any], *, allow_pickle: bool = False) -> None:
    buffer = io.BytesIO()
    np.savez(buffer, allow_pickle=allow_pickle, **arrays)
    (folder / WEIGHTS).write_bytes(buffer.getvalue())
    _remanifest(folder)


def _edit_config(folder: Path, change: Any) -> None:
    config = json.loads((folder / CONFIG).read_text(encoding="utf-8"))
    change(config)
    (folder / CONFIG).write_text(json.dumps(config), encoding="utf-8")
    _remanifest(folder)


def _reason(folder: Path) -> str | None:
    loaded = try_load_student(folder)
    assert (loaded.model is None) == (loaded.reason is not None)
    return loaded.reason


def test_packaged_copy_loads(tmp_path: Path) -> None:
    assert _reason(_copy(tmp_path)) is None


@pytest.mark.parametrize("name", [WEIGHTS, VOCAB, CONFIG, MANIFEST])
def test_missing_file(tmp_path: Path, name: str) -> None:
    folder = _copy(tmp_path)
    (folder / name).unlink()
    assert _reason(folder) == f"missing_file:{name}"


def test_bad_hash(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    data = bytearray((folder / WEIGHTS).read_bytes())
    data[-10] ^= 0xFF  # same size, different bytes
    (folder / WEIGHTS).write_bytes(bytes(data))
    assert _reason(folder) == f"hash_mismatch:{WEIGHTS}"


def test_size_mismatch(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / VOCAB).write_bytes((folder / VOCAB).read_bytes() + b" ")
    assert _reason(folder) == f"size_mismatch:{VOCAB}"


def test_broken_manifest(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / MANIFEST).write_text("[]", encoding="utf-8")
    assert _reason(folder) == "manifest_invalid"


def test_wrong_shape(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    arrays = _arrays(folder)
    arrays["dense_bias"] = arrays["dense_bias"][:-1]
    _save_npz(folder, arrays)
    assert _reason(folder) == "array_shape:dense_bias"


def test_wrong_dtype(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    arrays = _arrays(folder)
    arrays["heads_bias"] = arrays["heads_bias"].astype(np.int32)
    _save_npz(folder, arrays)
    assert _reason(folder) == "array_dtype:heads_bias"


def test_non_finite_weights(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    arrays = _arrays(folder)
    arrays["heads_bias"] = arrays["heads_bias"].copy()
    arrays["heads_bias"][0] = np.nan
    _save_npz(folder, arrays)
    assert _reason(folder) == "array_nonfinite:heads_bias"


def test_missing_and_extra_arrays(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    arrays = _arrays(folder)
    del arrays["conv5_bias"]
    _save_npz(folder, arrays)
    assert _reason(folder) == "array_names"
    arrays = _arrays(_copy(tmp_path / "again"))
    arrays["extra"] = np.zeros(3, dtype=np.float16)
    _save_npz(folder, arrays)
    assert _reason(folder) == "array_names"


def test_pickled_npz_is_refused(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    arrays: dict[str, Any] = _arrays(folder)
    arrays["embedding"] = np.array([{"x": 1}], dtype=object)
    _save_npz(folder, arrays, allow_pickle=True)
    assert _reason(folder) == "npz_unreadable"


def test_garbage_npz(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / WEIGHTS).write_bytes(b"not a zip file")
    _remanifest(folder)
    assert _reason(folder) == "npz_unreadable"


def test_format_version(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit_config(folder, lambda c: c.update(format_version=2))
    assert _reason(folder) == "format_version"


def test_head_layout_must_cover_the_output_width(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit_config(folder, lambda c: c["heads"].pop())  # 12 outputs left unclaimed
    assert _reason(folder) == "head_layout"


def test_head_layout_needs_the_risk_heads(tmp_path: Path) -> None:
    folder = _copy(tmp_path)

    def rename(config: dict[str, Any]) -> None:
        for head in config["heads"]:
            if head["name"] == "crisis_confidence":
                head["name"] = "something_else"

    _edit_config(folder, rename)
    assert _reason(folder) == "head_layout"


def test_risk_thresholds_are_required(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit_config(folder, lambda c: c["risk"].pop("threshold_ge2"))
    assert _reason(folder) == "risk_thresholds"


def test_vocab_must_match_the_embedding(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    vocab = json.loads((folder / VOCAB).read_text(encoding="utf-8"))
    vocab["chars"].pop()
    (folder / VOCAB).write_text(json.dumps(vocab), encoding="utf-8")
    _remanifest(folder)
    assert _reason(folder) == "vocab_invalid"


def test_load_student_raises_only_its_own_error(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / CONFIG).write_text("{not json", encoding="utf-8")
    _remanifest(folder)
    with pytest.raises(StudentUnavailableError) as caught:
        load_student(folder)
    assert caught.value.reason == "config_invalid"


# -- RiskModel contract and the screen -------------------------------------------------------


def test_risk_model_contract(student: StudentModel) -> None:
    model = StudentRiskModel(student)
    assert model.name == f"student:{student.fingerprint}"
    for case in GOLDEN["cases"]:
        prediction = model.predict(case["text"])
        assert isinstance(prediction, RiskPrediction)
        assert isinstance(prediction.level, CrisisLevel)
        assert type(prediction.score) is float and 0.0 <= prediction.score <= 1.0
        assert prediction.cue_ids == ()


def test_screen_with_the_student_never_lowers_and_stays_capped(student: StudentModel) -> None:
    lexicons = load_safety_lexicons(TAX)
    rules = SafetyScreen(TAX, lexicons)
    model = StudentRiskModel(student)
    screen = SafetyScreen(TAX, lexicons, model, model_plan_evidence=False)
    texts = [c["text"] for c in SAFETY_CASES] + [c["text"] for c in GOLDEN["cases"]]
    student_l3 = 0
    for text in texts:
        floor = rules.assess(text)
        assessed = screen.assess(text)
        assert assessed.level >= floor.level, text
        assert MODEL_FAILURE not in assessed.cue_ids
        if assessed.stage == "STAGE2":
            assert assessed.level <= CrisisLevel.L2 and not assessed.has_plan_evidence
            student_l3 += model.predict(text).level is CrisisLevel.L3
        else:
            assert assessed == floor  # Stage 1 never consults the model
    assert student_l3 > 0  # the cap was exercised by real L3 predictions


def test_choose_risk_model(monkeypatch: pytest.MonkeyPatch, student: StudentModel) -> None:
    chosen = choose_risk_model()
    assert chosen.label == f"student:{student.fingerprint}" and chosen.reason is None
    assert choose_risk_model(rules_only=True).label == "rules-only"
    with pytest.raises(ValueError):
        choose_risk_model(StudentRiskModel(student), rules_only=True)
    monkeypatch.setattr(
        student_module, "default_student", lambda: StudentLoad(None, "hash_mismatch:x")
    )
    fallback = choose_risk_model()
    assert (fallback.label, fallback.reason, fallback.model) == (
        "rules-only",
        "hash_mismatch:x",
        None,
    )
    assert fallback.take_turn() == (None, None)
