"""Compositional crisis cues (fix F1): gap-tolerant pairs with negation, person, context and
exception checks (``safety/compose.py``, ``risk.yaml`` section ``compositions``).

The cases live in composition_cases.yaml; each asserts the exact level and Stage, the D3
flag and, for self-injury, the SIT-09-01 red flag. Only the user's side is written, and
every means word stays generic.
"""

from __future__ import annotations

import random
import shutil
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.models import CrisisLevel as L
from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.safety.compose import Composer, _Spans
from olivia.core.safety.crisis import RiskPrediction, RuleRiskModel, SafetyScreen
from olivia.core.safety.lexicon import (
    Composition,
    CompositionRules,
    LexiconError,
    load_safety_lexicons,
)
from olivia.core.safety.matcher import Match
from olivia.core.safety.normalize import normalize
from olivia.core.safety.red_flags import RedFlagDetector
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

HERE = Path(__file__).parent
DATA = yaml.safe_load((HERE / "composition_cases.yaml").read_text(encoding="utf-8"))
POSITIVES: list[dict[str, Any]] = DATA["positives"]
NEGATIVES: list[dict[str, Any]] = DATA["negatives"]
TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)
DETECTOR = RedFlagDetector(TAX, LEX)
SELF_INJURY = "SIT-09-01"

POSITIVE_KINDS = {
    "intent_act",
    "intent_time",
    "prep_note",
    "prep_means",
    "means_hoarded",
    "farewell_ctx",
    "farewell_ask",
    "place",
    "no_wake",
    "burden_ask",
    "weary",
    "self_injury",
    "resolve_ask",
}
NEGATIVE_KINDS = {
    "hyperbole",
    "benign_object",
    "third_person",
    "negation",
    "past",
    "fiction",
    "prep_benign",
    "farewell_benign",
    "place_benign",
    "sleep_benign",
    "burden_benign",
    "weary_benign",
    "injury_benign",
    "resolve_benign",
}


def test_case_set_sizes_and_shape():
    assert len(POSITIVES) >= 120 and len(NEGATIVES) >= 120
    cases = [*POSITIVES, *NEGATIVES]
    assert len({c["id"] for c in cases}) == len(cases)
    assert len({c["text"] for c in cases}) == len(cases)
    assert {c["kind"] for c in POSITIVES} == POSITIVE_KINDS
    assert {c["kind"] for c in NEGATIVES} == NEGATIVE_KINDS
    for case in cases:
        assert case["stage"] == ("STAGE1" if case["level"] == "L3" else "STAGE2"), case["id"]
    # Every positive kind has a handful of cases, every negative kind at least five.
    assert min(Counter(c["kind"] for c in POSITIVES).values()) >= 8
    assert min(Counter(c["kind"] for c in NEGATIVES).values()) >= 5


def _check(case: dict[str, Any]) -> None:
    a = SCREEN.assess(case["text"])
    assert a.level is L[case["level"]], (case["id"], a)
    assert a.stage == case["stage"], (case["id"], a)
    assert a.has_plan_evidence is (case["level"] == "L3"), (case["id"], a)
    assert a.asks_intent is case["ask"], (case["id"], a)
    if "flag" in case:
        assert (SELF_INJURY in DETECTOR.detect(case["text"])) is case["flag"], case["id"]


@pytest.mark.parametrize("case", POSITIVES, ids=[c["id"] for c in POSITIVES])
def test_positive(case):
    _check(case)


@pytest.mark.parametrize("case", NEGATIVES, ids=[c["id"] for c in NEGATIVES])
def test_negative(case):
    _check(case)


# The sentences the fix was reported for, all L0 before it, with their level now.
REPORTED = [
    ("我要自杀", L.L2, False),
    ("我打算明天自杀", L.L3, False),
    ("我准备今晚自杀", L.L3, False),
    ("遗书已经写好了", L.L3, False),
    ("我不想死，可是绳子都准备好了", L.L3, False),
    ("我已经站在楼顶了", L.L2, False),
    ("真希望睡着就不要醒来了", L.L2, False),
    ("活着真的没意思", L.L1, False),
    ("怎么才能去找去世的奶奶", L.L1, True),
    ("我又开始割自己了", L.L1, True),
    ("我划了自己几下", L.L1, True),
    ("昨晚又自残了", L.L1, True),
    ("连续三天绝食", L.L1, True),
    ("我今晚就打算结束这一切", L.L3, False),
    ("我已经跟大家道别了", L.L1, True),
    ("我把银行卡密码都告诉妹妹了，以后用不上了", L.L1, True),
    ("有时候我觉得大家没有我会过得更好", L.L1, True),
    ("如果明天不用醒来就好了", L.L2, False),
    ("我觉得自己是个累赘", L.L1, True),
    # L2 before the fix as well; unchanged.
    ("我想自杀", L.L2, False),
    ("我不想活了", L.L2, False),
]


@pytest.mark.parametrize(("text", "level", "ask"), REPORTED)
def test_reported_sentences(text, level, ask):
    a = SCREEN.assess(text)
    assert a.level is level and a.asks_intent is ask, a


def test_current_self_injury_flags_and_asks_but_past_does_not():
    for text in ("我又开始割自己了", "昨晚又自残了", "连续三天绝食"):
        a = SCREEN.assess(text)
        assert a.level is L.L1 and a.asks_intent and SELF_INJURY in DETECTOR.detect(text)
    past = "以前自残过，现在好了"
    a = SCREEN.assess(past)
    assert a.level is L.L0 and not a.asks_intent and SELF_INJURY not in DETECTOR.detect(past)


def test_traditional_script_is_composed():
    assert SCREEN.assess("我打算明天自殺").level is L.L3
    assert SCREEN.assess("遺書已經寫好了").level is L.L3
    assert SCREEN.assess("我又開始割自己了").asks_intent


def test_insertions_are_tolerated_up_to_the_gap_only():
    assert SCREEN.assess("我要自杀").level is L.L2
    assert SCREEN.assess("我真的也要自杀").level is L.L2
    assert SCREEN.assess("我要好好地结束这一切").level is L.L2
    # Clause punctuation ends a gap.
    assert SCREEN.assess("我要，自杀").level is L.L0


def test_a_negator_before_or_inside_voids_but_a_question_does_not():
    assert SCREEN.assess("我不打算自杀").level is L.L0
    assert SCREEN.assess("我打算不自杀了").level is L.L0
    assert SCREEN.assess("要不要自杀呢").level is L.L2
    assert SCREEN.assess("我忍不住要去死").level is L.L2


def test_a_third_person_subject_voids_but_a_recipient_does_not():
    assert SCREEN.assess("她打算自杀").level is L.L0
    assert SCREEN.assess("我跟她说我打算自杀").level is L.L2
    assert SCREEN.assess("她跟我说打算自杀").level is L.L0


def test_a_third_person_beyond_the_carry_window_is_not_the_subject():
    # 她 lies more than two subject windows before the clause: it is not carried over, and
    # the first-person plan in the last clause stays L3.
    text = "她昨天下午在公司加班到很晚回家路上又堵车堵了好久真烦人，打算明天去死"
    a = SCREEN.assess(text)
    assert a.level is L.L3 and a.cue_ids == ("S1_PLAN_ACT_TIME",)


@pytest.mark.parametrize(
    "text",
    [
        "我打算去死，这件事想了很久很久，下周再说",
        "我准备结束生命，这个念头已经很久了，明天还要上班",
    ],
)
def test_a_time_word_outside_the_context_window_is_no_plan_context(text):
    # A time word beyond the context window does not turn an L2 intent into an L3 plan.
    a = SCREEN.assess(text)
    assert (a.level, a.stage) == (L.L2, "STAGE2")


def test_spans_cover_with_the_furthest_end_not_the_sum():
    # Coverage looks at the furthest end of the earlier spans, so two short spans never
    # reach a later one between them.
    spans = _Spans([Match("a", 0, 2), Match("b", 5, 7)])
    assert not spans.covers(Match("c", 7, 9))
    assert not spans.overlaps(8, 9)


def test_compositions_add_only_what_the_phrases_miss():
    # A phrase cue already at L2: the composition adds no id.
    assert SCREEN.assess("我想自杀").cue_ids == ("L2_WANT_DIE",)
    # A Stage 1 phrase already gives the plan evidence: no composition id either.
    assert SCREEN.assess("遗书写好了").cue_ids == ("S1_NOTE_WRITTEN",)
    # Below the phrases' level, the composition is reported.
    assert SCREEN.assess("我打算自杀").cue_ids == ("L2_INTENT_ACT",)
    # An ask composition is reported whatever the phrase level: it sets the D3 flag.
    a = SCREEN.assess("活着好累，我又割自己了")
    assert a.level is L.L1 and a.asks_intent
    assert set(a.cue_ids) == {"L1_WEARY", "ASK_INTENT_SELF_INJURY_ACT"}


def test_masks_void_l1_and_l2_compositions_but_never_ask_or_stage1():
    # NEG_NOT_SUICIDE (不想自杀) contains 想自杀; 不 is also a negator, so both void it.
    assert SCREEN.assess("我真的不想自杀").level is L.L0
    # A hyperbole mask never hides the self-injury question or Stage 1.
    assert SCREEN.assess("累死了，又自残了").asks_intent
    assert SCREEN.assess("累死了，遗书已经写好了").level is L.L3


def test_rule_model_alone_sees_stage2_compositions_only():
    model = RuleRiskModel(TAX, LEX)
    assert model.predict("我打算自杀") == RiskPrediction(L.L2, 0.7, ("L2_INTENT_ACT",))
    # Stage 1 compositions are the screen's, not the rule model's.
    assert model.predict("遗书已经写好了").level is L.L0


def test_an_injected_model_never_lowers_a_composition():
    class Calm:
        def predict(self, text: str) -> RiskPrediction:
            return RiskPrediction(L.L0, 0.0, ())

    screen = SafetyScreen(TAX, LEX, Calm())
    assert screen.assess("我打算自杀").level is L.L2
    assert screen.assess("我打算明天自杀").level is L.L3
    a = screen.assess("我又开始割自己了")
    assert a.level is L.L1 and a.asks_intent


# -- the engine on neutral placeholder words ------------------------------------------------


def _rules(**entry: Any) -> CompositionRules:
    base: dict[str, Any] = {
        "id": "L2_TEST",
        "level": L.L2,
        "score": 0.7,
        "ask": False,
        "heads": ("甲",),
        "tails": ("乙",),
        "max_gap": 2,
    }
    return CompositionRules(
        stops=frozenset(",。"),
        lookback=2,
        subject_window=6,
        negators=("不",),
        non_negators=("忍不住",),
        selves=("我",),
        others=("他", "你"),
        recipients=("跟",),
        listeners=("你",),
        entries=(Composition(**{**base, **entry}),),
    )


def _fires(rules: CompositionRules, text: str) -> bool:
    return bool(Composer(rules).find(text))


def test_engine_gap_order_and_clause():
    rules = _rules()
    assert _fires(rules, "甲乙") and _fires(rules, "甲一二乙")
    assert not _fires(rules, "甲一二三乙")
    assert not _fires(rules, "甲,乙")
    assert not _fires(rules, "乙甲")
    assert _fires(_rules(either_order=True), "乙一甲")
    assert _fires(_rules(tails=()), "甲")


def test_engine_negators():
    rules = _rules()
    assert not _fires(rules, "不甲乙") and not _fires(rules, "甲不乙")
    # Outside the lookback, in another clause, inside a non-negator or an A-not-A question.
    assert _fires(rules, "不一二甲乙") and _fires(rules, "不,甲乙")
    assert _fires(rules, "忍不住甲乙") and _fires(rules, "甲不甲乙")


def test_engine_persons():
    rules = _rules()
    assert not _fires(rules, "他甲乙") and _fires(rules, "他说我甲乙")
    assert _fires(rules, "我跟他甲乙")
    assert _fires(rules, "他,我甲乙") and _fires(_rules(persons=False), "他甲乙")
    # A clause naming nobody keeps the subject of the clause before; a listener does not
    # carry over, and a subject far back in the same clause is not looked past.
    assert not _fires(rules, "他一二,甲乙") and _fires(rules, "我一二,甲乙")
    assert _fires(rules, "你,甲乙") and not _fires(rules, "你甲乙")
    assert _fires(rules, "他一二三四五六七八甲乙")


def test_engine_context_unless_exceptions_blockers():
    near = _rules(context=("丙",), context_window=1)
    assert _fires(near, "丙甲乙") and not _fires(near, "丙一甲乙")
    assert _fires(_rules(context=("丙",)), "丙一二三四,甲乙")
    unless = _rules(unless=("丁",), unless_window=3)
    assert not _fires(unless, "丁甲乙") and _fires(unless, "丁,甲乙")
    assert _fires(unless, "丁一二三甲乙")
    excepted = _rules(exceptions=("甲乙戊",))
    assert not _fires(excepted, "甲乙戊") and _fires(excepted, "甲乙")
    assert not _fires(_rules(blockers=("己",)), "甲己乙")


def test_engine_trailing_requires_the_match_to_end_its_clause():
    final = _rules(tails=(), trailing=("了", "吧"))
    assert _fires(final, "甲") and _fires(final, "甲了吧") and _fires(final, "甲吧,一二")
    assert not _fires(final, "甲一") and not _fires(final, "甲了一")
    # Without trailing, anything may follow.
    assert _fires(_rules(tails=()), "甲一")


def test_trailing_is_read_from_the_lexicon():
    entry = next(e for e in LEX.compositions.entries if e.id == "ASK_INTENT_RESOLVED_TONIGHT")
    assert entry.trailing is not None and "了" in entry.trailing
    # F6a: the Cantonese 完咗佢 cue must end its clause too.
    yue = next(e for e in LEX.compositions.entries if e.id == "ASK_INTENT_END_IT_YUE")
    assert yue.trailing is not None and "啦" in yue.trailing
    # 2026-10-26: the same resolve with a day ("我已经想好了，就这周五") ends its clause too.
    day = next(e for e in LEX.compositions.entries if e.id == "ASK_INTENT_RESOLVED_DAY")
    assert day.trailing == entry.trailing
    ends = (entry, yue, day)
    assert all(e.trailing is None for e in LEX.compositions.entries if e not in ends)


def test_f5a_usage_sentences_ask_and_a_death_word_goes_to_stage1():
    # Usage test 92 (rules mode): both were L0 with an ordinary reply.
    for text in ("我已经把想说的话都写下来留给家人了", "我已经决定好了，就在今晚"):
        a = SCREEN.assess(text)
        assert a.level is L.L1 and a.asks_intent and not a.has_plan_evidence, (text, a)
    # With a death word in the same sentence the existing Stage 1 cues answer L3.
    for text in ("我已经决定好了，就在今晚结束自己", "遗书写好了，留给家人"):
        a = SCREEN.assess(text)
        assert a.level is L.L3 and a.stage == "STAGE1", (text, a)


def test_f5a_usage_sentences_get_the_direct_question_in_a_session():
    for text in ("我已经把想说的话都写下来留给家人了", "我已经决定好了，就在今晚"):
        result = _session().turn(text)
        assert result.reply_kind is ReplyKind.SAFETY_CHECK, text
        assert result.inspect["safety_check"] == "asked" and not result.in_crisis


def test_composer_without_entries_finds_nothing():
    assert Composer(CompositionRules()).find(normalize("我要自杀")) == []
    assert Composer(LEX.compositions).find("") == []


def test_long_input_stays_linear():
    # Thousands of heads, tails and negators: the search per entry stays bounded.
    text = normalize("我不要，自杀，" * 5000 + "我要自杀")
    hits = Composer(LEX.compositions).find(text)
    assert [h.entry.id for h in hits] == ["L2_INTENT_ACT"]


# -- the D3 path in a session -------------------------------------------------------------

NOW = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)


def _session(seed: int = 3) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW, student=False)


def test_self_injury_asks_the_direct_question_and_a_yes_enters_crisis():
    session = _session()
    asked = session.turn("我又开始割自己了")
    assert asked.reply_kind is ReplyKind.SAFETY_CHECK
    assert asked.inspect["safety_check"] == "asked"
    assert asked.crisis_level is L.L1 and not asked.in_crisis
    assert SELF_INJURY in asked.inspect["red_flags"]
    answered = session.turn("是的")
    assert answered.reply_kind is ReplyKind.CRISIS and answered.in_crisis
    assert answered.crisis_level >= L.L2
    assert answered.inspect["safety_check"] == "affirmed"


def test_self_injury_denied_returns_with_the_referral():
    session = _session()
    session.turn("昨晚又自残了")
    denied = session.turn("不是")
    assert denied.inspect["safety_check"] == "denied" and not denied.in_crisis
    assert SELF_INJURY in denied.referral_flags
    assert SELF_INJURY in session.snapshot()["referred_flags"]


def test_past_self_injury_neither_asks_nor_refers():
    result = _session().turn("以前自残过，现在好了")
    assert result.reply_kind is not ReplyKind.SAFETY_CHECK
    assert result.inspect["safety_check"] is None
    assert SELF_INJURY not in result.inspect["red_flags"]


# -- loader validation --------------------------------------------------------------------

PKG_LEX = Path(__file__).resolve().parents[2] / "olivia/data/lexicons"


def _copy(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> Path:
    d = tmp_path / "lex"
    shutil.copytree(PKG_LEX, d)
    data = yaml.safe_load((d / "risk.yaml").read_text(encoding="utf-8"))
    mutate(data)
    (d / "risk.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return d


def _entry(d: dict[str, Any], cue_id: str = "L2_INTENT_ACT") -> dict[str, Any]:
    entry: dict[str, Any] = next(e for e in d["compositions"]["entries"] if e["id"] == cue_id)
    return entry


def test_section_is_optional(tmp_path):
    lex = load_safety_lexicons(TAX, _copy(tmp_path, lambda d: d.pop("compositions")))
    assert lex.compositions.entries == ()
    assert SafetyScreen(TAX, lex).assess("我打算自杀").level is L.L0


def test_loaded_entries_have_levels_scores_and_ids():
    entries = LEX.compositions.entries
    assert entries
    for entry in entries:
        if entry.ask:
            assert entry.id.startswith("ASK_INTENT") and entry.level is L.L1
        elif entry.level is L.L3:
            assert entry.id.startswith("S1_")
        assert entry.score == pytest.approx(
            TAX.threshold(f"risk.lexicon_scores.{entry.level.name}")
        )
    stops = LEX.compositions.stops
    assert "," in stops and "。" in stops


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.update(compositions=[]), "must be a mapping"),
        (lambda d: d["compositions"].update(extra=1), "unknown keys"),
        (lambda d: d["compositions"].update(stops=""), "stops"),
        (lambda d: d["compositions"].update(lookback=99), "lookback"),
        (lambda d: d["compositions"].update(subject_window=True), "subject_window"),
        (lambda d: d["compositions"].update(negators=[]), "negators"),
        (lambda d: d["compositions"].update(lists=[]), "lists"),
        (lambda d: d["compositions"].update(entries={}), "entries"),
        (lambda d: _entry(d).update(level="L4"), "level"),
        (lambda d: _entry(d).update(level="L3"), "S1_"),
        (lambda d: _entry(d).update(level="ASK"), "ASK_INTENT"),
        (lambda d: _entry(d, "S1_PLAN_ACT_TIME").update(level="L2"), "S1_"),
        (lambda d: _entry(d).update(heads="no_such_list"), "unknown list"),
        (lambda d: _entry(d).update(heads=[]), "heads"),
        (lambda d: _entry(d).update(trailing=[]), "trailing"),
        (lambda d: _entry(d).update(trailing="no_such_list"), "unknown list"),
        (lambda d: _entry(d).update(max_gap=40), "max_gap"),
        (lambda d: _entry(d).update(order="tail_first"), "order"),
        (lambda d: _entry(d).update(context_window=3), "context_window"),
        (lambda d: _entry(d).update(unless_window=3), "unless_window"),
        (lambda d: _entry(d, "ASK_INTENT_JOIN_THE_DEAD").pop("unless_window"), "unless_window"),
        (lambda d: _entry(d).update(exceptions=["预防"]), "contains no head or tail"),
        (lambda d: _entry(d).update(persons="yes"), "persons"),
        (lambda d: _entry(d).update(colour="red"), "unknown keys"),
        (lambda d: _entry(d, "ASK_INTENT_SELF_INJURY_WORD").update(max_gap=2), "need 'tails'"),
        (lambda d: _entry(d).update(id="L2_WANT_DIE"), "duplicate id"),
    ],
)
def test_rejects_malformed_composition_data(tmp_path, mutate, match):
    with pytest.raises(LexiconError, match=match):
        load_safety_lexicons(TAX, _copy(tmp_path, mutate))


# (section or entry id, key, lowest allowed, highest allowed)
WINDOW_BOUNDS = [
    ("compositions", "lookback", 0, 8),
    ("compositions", "subject_window", 0, 16),
    ("compositions", "unless_negation_gap", 0, 8),
    ("L2_INTENT_ACT", "max_gap", 0, 12),
    ("S1_PLAN_ACT_TIME", "context_window", 0, 24),
    ("S1_NOTE_PREPARED", "unless_window", 1, 24),
    ("reported_speech", "speaker_gap", 0, 24),
]


def _set(owner: str, key: str, value: int) -> Callable[[dict[str, Any]], None]:
    def mutate(d: dict[str, Any]) -> None:
        node = d[owner] if owner in ("compositions", "reported_speech") else _entry(d, owner)
        node[key] = value

    return mutate


@pytest.mark.parametrize(("owner", "key", "low", "high"), WINDOW_BOUNDS)
def test_window_and_gap_bounds_are_inclusive(tmp_path, owner, key, low, high):
    # Both ends of each range load; one step outside either end is rejected.
    for value in (low, high):
        load_safety_lexicons(TAX, _copy(tmp_path / f"ok{value}", _set(owner, key, value)))
    for value in (low - 1, high + 1):
        with pytest.raises(LexiconError, match=key):
            load_safety_lexicons(TAX, _copy(tmp_path / f"bad{value}", _set(owner, key, value)))
