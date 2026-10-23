"""Narrative externalization (PRD 特性四, step C3): copy, loader, answers and pacing."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate
from olivia.core.models import HelpStage, PersonaSpectrum
from olivia.core.perception.externalize import (
    CRITIC_DISTORTIONS,
    CRITIC_SCHEMAS,
    LINE_MAX,
    NAMING_GAP,
    Externalizer,
    ExternalizeStatus,
    ExternalizeTextError,
    load_externalize_text,
    read_naming_answer,
)
from olivia.core.perception.introspector import load_introspection_lexicon
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
TEXT = load_externalize_text(TAX)
ANSWERS = load_introspection_lexicon(TAX).answers
DATA = Path(__file__).resolve().parents[2] / "olivia" / "data"
OFFER = TEXT.offers[0]
FIRST, SECOND, THIRD = OFFER.names
# Personas that can be offered the name; SILENT_ANCHOR never is.
PERSONAS = (
    PersonaSpectrum.GENTLE_HOLDING,
    PersonaSpectrum.ZEN_PHILOSOPHER,
    PersonaSpectrum.RATIONAL_PEER,
)


def _all_lines() -> list[tuple[str, str]]:
    lines = [("offer", o.line) for o in TEXT.offers]
    for nid in TEXT.names:
        lines += [("accepted", TEXT.fill(line, nid)) for line in TEXT.accepted]
        lines += [("callbacks", TEXT.fill(line, nid)) for line in TEXT.callbacks]
    lines += [("declined", line) for line in TEXT.declined]
    return lines


def _ids(value: object) -> str:
    return str(value) if value in ("offer", "accepted", "declined", "callbacks") else ""


# -- triggers ---------------------------------------------------------------------------------


def test_trigger_ids_are_taxonomy_ids():
    assert {"DEFECTIVENESS", "PUNITIVENESS", "UNRELENTING_STANDARDS", "FAILURE"} == CRITIC_SCHEMAS
    assert set(TAX.values("schemas")) >= CRITIC_SCHEMAS
    assert {"SHOULD_STATEMENTS", "ALL_OR_NOTHING"} == CRITIC_DISTORTIONS
    assert set(TAX.values("cognitive_distortions")) >= CRITIC_DISTORTIONS


# -- copy (draft pending G-0) -----------------------------------------------------------------


def test_copy_carries_the_draft_header():
    first = (DATA / "language" / "externalize.yaml").read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# 草稿：待 G-0 两名注册心理师审核")


def test_offers_propose_two_or_three_template_names_and_allow_a_no():
    assert len(TEXT.offers) >= 2
    for offer in TEXT.offers:
        assert 2 <= len(offer.names) <= 3
        for number, nid in enumerate(offer.names, start=1):
            assert f"{number}「{TEXT.names[nid]}」" in offer.line
        assert offer.line.count("？") == 1
        assert "没关系" in offer.line or "不起也" in offer.line
    # The PRD's own example name is among them.
    assert "那个追求完美的严苛督察员" in TEXT.names.values()


@pytest.mark.parametrize("persona", PERSONAS, ids=lambda p: p.value)
@pytest.mark.parametrize("kind,line", _all_lines(), ids=_ids)
def test_every_line_passes_willow_unchanged_and_the_gate(persona, kind, line):
    lang = load_language_data(TAX).for_persona(persona)
    assert len(line) <= min(LINE_MAX, lang.templates.paragraph_max)
    assert "\n" not in line and "{" not in line
    assert apply_willow(line, ContentKind.NORMAL, lang.willow) == line
    gate = OutputGate(TAX, lang)
    for stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY):
        assert gate.reasons(line, kind=ContentKind.NORMAL, stage=stage) == (), kind


@pytest.mark.parametrize("kind,line", _all_lines(), ids=_ids)
def test_no_diagnosis_or_clinical_words(kind, line):
    names = {
        str(entry["name"])
        for entry in yaml.safe_load((DATA / "taxonomy.yaml").read_text("utf-8"))["schemas"]
    }
    assert not any(name in line for name in names)
    for word in (
        "图式",
        "核心信念",
        "认知扭曲",
        "缺陷",
        "障碍",
        "症",
        "病",
        "诊断",
        "应该",
        "必须",
    ):
        assert word not in line, (kind, word)


# -- reading the answer -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,name",
    [
        ("1", FIRST),
        ("２", SECOND),
        ("3", THIRD),
        ("第二个", SECOND),
        ("第三个吧", THIRD),
        ("选1", FIRST),
        ("就叫第二个吧", SECOND),
        ("嗯，2", SECOND),
        (TEXT.names[THIRD], THIRD),
        (f"{TEXT.names[THIRD]}吧", THIRD),
        (f"嗯……我想想，就叫{TEXT.names[FIRST]}好了", FIRST),
        (f"不错，就叫{TEXT.names[SECOND]}", SECOND),
    ],
)
def test_a_number_or_a_name_accepts(message, name):
    found = read_naming_answer(ANSWERS, TEXT, OFFER.names, message)
    assert found is not None
    assert (found.status, found.name) == (ExternalizeStatus.ACCEPTED, name)


@pytest.mark.parametrize(
    "message",
    ["不用了", "不要", "不是", "没有", "不想起", "先不起吧", "算了吧", "不用起名字了，谢谢"],
)
def test_a_clear_no_declines(message):
    found = read_naming_answer(ANSWERS, TEXT, OFFER.names, message)
    assert found is not None
    assert (found.status, found.name) == (ExternalizeStatus.DECLINED, None)


def test_the_rule_stubs_no_declines():
    found = read_naming_answer(ANSWERS, TEXT, OFFER.names, "嗯不了", stub_declined=True)
    assert found is not None and found.status is ExternalizeStatus.DECLINED


@pytest.mark.parametrize(
    "message",
    [
        "好",  # a yes without a pick: no name to keep
        "嗯",
        "今天外面下雨了",
        "我1点要开会",  # a digit that is not the whole clause
        "4",  # out of range
        "第五个",
        f"不要，{TEXT.names[FIRST]}太凶了",  # a no and a pick
        f"我不喜欢{TEXT.names[FIRST]}",  # a negated name
        f"{TEXT.names[FIRST]}还是{TEXT.names[THIRD]}呢",  # two picks
        "",
    ],
)
def test_anything_else_is_no_answer(message):
    assert read_naming_answer(ANSWERS, TEXT, OFFER.names, message) is None


def test_only_offered_names_count():
    two = TEXT.offers[0].names[:2]
    assert read_naming_answer(ANSWERS, TEXT, two, "3") is None
    missing = next(n for n in TEXT.names if n not in two)
    assert read_naming_answer(ANSWERS, TEXT, two, TEXT.names[missing]) is None


# -- the session state ------------------------------------------------------------------------


def _ext(enabled: bool = True) -> Externalizer:
    return Externalizer(TEXT, ANSWERS, enabled=enabled)


def test_due_after_one_critic_schema_on_a_calm_turn():
    ext = _ext()
    ext.observe(["APPROVAL_SEEKING"], [], counts=True)
    assert not ext.due()
    ext.observe(["FAILURE"], [], counts=False)
    assert not ext.due()
    ext.observe(["FAILURE"], [], counts=True)
    assert ext.due()


def test_a_critic_distortion_needs_two_calm_turns():
    ext = _ext()
    ext.observe([], ["SHOULD_STATEMENTS"], counts=True)
    ext.observe([], ["ALL_OR_NOTHING"], counts=True)
    ext.observe([], ["SHOULD_STATEMENTS"], counts=False)
    assert not ext.due()
    ext.observe([], ["SHOULD_STATEMENTS"], counts=True)
    assert ext.due()


def test_off_in_rules_mode():
    ext = _ext(enabled=False)
    ext.observe(["FAILURE"], [], counts=True)
    assert not ext.due()


def test_offered_once_and_read_on_the_next_turn_only():
    ext = _ext()
    ext.observe(["FAILURE"], [], counts=True)
    ext.mark_offered(OFFER)
    assert ext.status is ExternalizeStatus.OFFERED and not ext.due()
    found = ext.answer("2", readable=True)
    assert found is not None and found.name == SECOND
    assert (ext.status, ext.name) == (ExternalizeStatus.ACCEPTED, SECOND)
    assert ext.answer("3", readable=True) is None
    assert ext.name == SECOND and not ext.due()


def test_an_unreadable_or_unclear_answer_lets_the_offer_lapse():
    for first in ("2", "今天外面下雨了"):
        ext = _ext()
        ext.observe(["FAILURE"], [], counts=True)
        ext.mark_offered(OFFER)
        assert ext.answer(first, readable=first != "2") is None
        assert ext.answer("2", readable=True) is None
        assert ext.status is ExternalizeStatus.OFFERED and ext.name is None and not ext.due()


def test_no_answer_without_an_offer():
    assert _ext().answer("2", readable=True) is None


def test_callbacks_need_the_pattern_and_the_gap():
    ext = _ext()
    ext.observe(["FAILURE"], [], counts=True)
    ext.mark_offered(OFFER)
    ext.answer("1", readable=True)
    ext.observe([], [], counts=True)
    ext.mark_named()  # the acknowledgement
    named = []
    for turn in range(1, 8):
        ext.observe(["DEFECTIVENESS"], [], counts=True)
        if ext.callback_due(["DEFECTIVENESS"], []):
            ext.mark_named()
            named.append(turn)
    assert named == [NAMING_GAP, 2 * NAMING_GAP]
    for _ in range(NAMING_GAP):
        ext.observe([], [], counts=True)
    assert not ext.callback_due(["APPROVAL_SEEKING"], ["CATASTROPHIZING"])
    assert ext.callback_due([], ["ALL_OR_NOTHING"])


def test_no_callback_without_an_accepted_name():
    ext = _ext()
    ext.observe(["FAILURE"], [], counts=True)
    ext.mark_offered(OFFER)
    ext.answer("不用了", readable=True)
    assert ext.status is ExternalizeStatus.DECLINED and ext.name is None
    assert not ext.callback_due(["FAILURE"], [])


# -- loader validation ------------------------------------------------------------------------


def _doc() -> dict[str, Any]:
    loaded = yaml.safe_load((DATA / "language" / "externalize.yaml").read_text("utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _offer(doc: dict[str, Any]) -> dict[str, Any]:
    entry = doc["offers"][0]
    assert isinstance(entry, dict)
    return entry


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda d: d.update({"extra": 1}), "unknown keys"),
        (lambda d: d["names"].update({"bad id": {"text": "x", "match": ["x", "y"]}}), "upper"),
        (lambda d: d["names"]["NITPICKER"].update({"match": ["挑刺先生"]}), "2 phrases"),
        (lambda d: d["names"]["NITPICKER"].update({"match": ["挑刺", "挑毛病"]}), "include"),
        (lambda d: d["names"]["LITTLE_HORN"]["match"].append("挑刺先"), "lies inside"),
        (lambda d: _offer(d).update({"names": ["NITPICKER"]}), "2 or 3"),
        (lambda d: _offer(d).update({"names": ["NITPICKER", "NOPE"]}), "unknown names"),
        (lambda d: _offer(d).update({"line": "{user_name}，起个名字吗？"}), "no slots"),
        (lambda d: _offer(d).update({"line": _offer(d)["line"].replace("？", "。")}), "question"),
        (
            lambda d: _offer(d).update({"names": list(reversed(_offer(d)["names"]))}),
            "after the names",
        ),
        (lambda d: _offer(d).update({"line": _offer(d)["line"] + "第4个？"}), "digits"),
        (lambda d: _offer(d).update({"line": _offer(d)["line"] * 2}), "at most"),
        (lambda d: d["accepted"].append("就叫它吧。"), "once"),
        (lambda d: d["declined"].append("好的，{name}。"), "no slots"),
        (lambda d: d["callbacks"].append("「{name}」" + "又" * 80), "at most"),
        (lambda d: d["declines"].append("不"), "two characters"),
        (lambda d: d.pop("callbacks"), "non-empty list"),
    ],
)
def test_loader_rejects_bad_copy(tmp_path, mutate: Callable[[dict[str, Any]], None], match):
    doc = _doc()
    mutate(doc)
    (tmp_path / "externalize.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(ExternalizeTextError, match=match):
        load_externalize_text(TAX, tmp_path)


def test_loader_reports_a_missing_file(tmp_path):
    with pytest.raises(ExternalizeTextError, match="cannot read"):
        load_externalize_text(TAX, tmp_path)
