"""Contraindications and situations derived from each enum's source (A1, decision D2)."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from olivia.core.methods.contraindications import (
    SHAME_CONTRAINDICATION,
    SessionContraindications,
    source_links,
)
from olivia.core.methods.solver import (
    M0_ACTION_ID,
    OVERLOAD_CONTRAINDICATION,
    SolverInput,
    active_contraindications,
    allowed_actions,
    build_plan,
    info_cards,
)
from olivia.core.models import (
    PROFILE_CONTRAINDICATIONS,
    CrisisLevel,
    HelpStage,
    PerceptionContext,
)
from olivia.core.perception.introspector import SHAME_SCHEMA
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.perception.signals import TurnSignals
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.safety.tracker import CrisisStatus
from olivia.core.taxonomy import Taxonomy, TaxonomyError, load_taxonomy

TAX = load_taxonomy()
TAX_FILE = Path(__file__).resolve().parents[2] / "olivia/data/taxonomy.yaml"
ENUMS = TAX.values("contraindication_enums")
STUB = RuleStub(TAX, load_perception_lexicon(TAX))
NO_FLAGS: frozenset[str] = frozenset()
PSYCHOSIS = "RED_FLAG_PSYCHOSIS"
# The taxonomy's methods that list it under contraindications; no registry action does.
PSYCHOSIS_BLOCKS = {"01", "02", "10", "11", "14", "16", "44", "66"}

# The taxonomy names these red-flag codes in the sources (RED_FLAG_DETECTOR (SIT-..)).
RED_FLAG_LINKS = {
    "SIT-02-04": "RED_FLAG_MANIA",
    "SIT-06-01": "RED_FLAG_PTSD_FLASHBACK",
    "SIT-06-05": "RED_FLAG_DISSOCIATION",
    "SIT-08-04": "RED_FLAG_ANOREXIA",
    "SIT-09-01": "RED_FLAG_BPD_NSSI",
    "SIT-10-04": "RED_FLAG_SUBSTANCE_WITHDRAWAL",
}


def _status(level: CrisisLevel = CrisisLevel.L0, *, in_crisis: bool = False) -> CrisisStatus:
    return CrisisStatus(
        level=level,
        in_crisis=in_crisis,
        entry_level=level if in_crisis else None,
        escalated=False,
        awaiting_confirmation=False,
        safe_turns_remaining=0,
        just_entered=False,
        just_exited=False,
    )


def _perceive(text: str) -> tuple[PerceptionContext, TurnSignals]:
    return STUB.perceive(text, CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE1", False, ()))


def _observe(
    tracker: SessionContraindications,
    text: str = "今天有点累",
    *,
    status: CrisisStatus | None = None,
    flags: frozenset[str] = NO_FLAGS,
    perception: PerceptionContext | None = None,
) -> tuple[frozenset[str], frozenset[str]]:
    context, signals = _perceive(text)
    active = tracker.observe(signals, perception or context, status or _status(), flags)
    return active.contraindications, active.situations


def _fresh(profile: tuple[str, ...] = ()) -> SessionContraindications:
    return SessionContraindications(TAX, profile)


# -- taxonomy links ------------------------------------------------------------------


def test_source_links_follow_the_codes_each_source_names():
    links = source_links(TAX)
    assert {code: set(ids) for code, ids in links.red_flags.items()} == {
        code: {enum} for code, enum in RED_FLAG_LINKS.items()
    }
    # The perinatal red flag names no contraindication; its own masks still apply.
    assert "SIT-02-06" not in links.red_flags
    assert dict(links.situations) == {"SIT-06-04": frozenset({"ACUTE_BEREAVEMENT_SHOCK"})}


def test_an_unknown_code_in_a_source_is_rejected():
    data = yaml.safe_load(TAX_FILE.read_text(encoding="utf-8"))
    broken = copy.deepcopy(data)
    broken["contraindication_enums"][0]["detection_source"] = "CRISIS_DETECTOR (SIT-99-99)"
    with pytest.raises(TaxonomyError, match="SIT-99-99"):
        source_links(Taxonomy(broken))


def test_profile_contraindications_are_the_disclosure_enums():
    sources = TAX.contraindication_sources()
    assert set(sources) == set(ENUMS) and len(ENUMS) == 13
    for enum_id in PROFILE_CONTRAINDICATIONS:
        assert "USER_PROFILE_DISCLOSURE" in sources[enum_id]


# -- one source each -------------------------------------------------------------------


def test_nothing_is_active_on_an_ordinary_turn():
    assert _observe(_fresh()) == (frozenset(), frozenset())


@pytest.mark.parametrize(
    ("level", "in_crisis", "expected"),
    [
        (CrisisLevel.L0, False, False),
        (CrisisLevel.L1, False, False),
        (CrisisLevel.L2, False, True),
        (CrisisLevel.L3, True, True),
        (CrisisLevel.L0, True, True),  # still in crisis while the exit streak runs
    ],
)
def test_crisis_active_risk_follows_the_crisis_status(level, in_crisis, expected):
    active, _ = _observe(_fresh(), status=_status(level, in_crisis=in_crisis))
    assert ("CRISIS_ACTIVE_RISK" in active) is expected


@pytest.mark.parametrize(("code", "enum_id"), sorted(RED_FLAG_LINKS.items()))
def test_each_red_flag_sets_its_contraindication(code, enum_id):
    active, _ = _observe(_fresh(), flags=frozenset({code}))
    assert active == {enum_id}


def test_the_perinatal_red_flag_sets_no_contraindication():
    assert _observe(_fresh(), flags=frozenset({"SIT-02-06"})) == (frozenset(), frozenset())


@pytest.mark.parametrize(
    ("text", "situation"),
    [
        ("我奶奶上周刚去世，我整个人都是懵的", "SIT-06-04"),
        ("葬礼刚办完，家里空荡荡的", "SIT-06-04"),
        ("最近觉得一切都没有意义", "SIT-11-01"),
        ("什么都无所谓，做什么都没意义", "SIT-11-01"),
    ],
)
def test_situation_cues_set_the_situation(text, situation):
    active, situations = _observe(_fresh(), text)
    assert situations == {situation}
    expected = {"ACUTE_BEREAVEMENT_SHOCK"} if situation == "SIT-06-04" else set()
    assert active == expected


# -- F13 (draft G-0): acute and prolonged grief are told apart --------------------------------


def test_prolonged_grief_keeps_the_situation_but_not_the_acute_enum():
    active, situations = _observe(_fresh(), "妈妈去世一年多了，我还是走不出来")
    assert situations == {"SIT-06-04"}
    assert active == frozenset()


def test_an_acute_cue_sets_the_acute_enum_even_with_the_prolonged_rule():
    # Both on one turn, or the acute cue later in the session: acute wins and holds.
    text = "爸爸去世一年多了，我还是走不出来，昨天外婆也刚去世"
    assert _observe(_fresh(), text)[0] == {"ACUTE_BEREAVEMENT_SHOCK"}
    tracker = _fresh()
    _observe(tracker, "妈妈去世一年多了，我还是走不出来")
    _observe(tracker, "我奶奶刚去世")
    assert _observe(tracker)[0] == {"ACUTE_BEREAVEMENT_SHOCK"}


def test_the_prolonged_grief_signal_is_set_only_by_the_three_lists():
    assert _perceive("妈妈去世一年多了，我还是走不出来")[1].prolonged_grief
    assert not _perceive("我奶奶刚去世")[1].prolonged_grief
    assert not _perceive("外婆去世好几年了，现在想起来更多是温暖")[1].prolonged_grief
    assert not _perceive("爸爸去世一年多了，我还是走不出来，昨天外婆也刚去世")[1].prolonged_grief


@pytest.mark.parametrize("text", ["不是一切都没有意义", "奶奶去世好几年了", "人生没有意义"])
def test_negated_or_other_wording_sets_no_situation(text):
    # "人生没有意义" is risk.yaml's L1 wording: crisis cues stay with the safety screen.
    assert _observe(_fresh(), text)[1] == frozenset()


@pytest.mark.parametrize(
    ("text", "enum_id"),
    [
        ("我就是个废物，什么都做不好", SHAME_CONTRAINDICATION),
        ("我恨我自己", SHAME_CONTRAINDICATION),
        ("我有心脏病，医生让我注意", "CARDIORESPIRATORY_INSTABILITY"),
        ("哮喘又犯了，晚上睡不好", "CARDIORESPIRATORY_INSTABILITY"),
        ("他又动手打我了", "INTERPERSONAL_SAFETY_HAZARD"),
        ("家暴好几年了", "INTERPERSONAL_SAFETY_HAZARD"),
    ],
)
def test_contraindication_cues_set_their_enum(text, enum_id):
    assert _observe(_fresh(), text)[0] == {enum_id}


@pytest.mark.parametrize("text", ["我没有心脏病", "他没有动手打我", "我不是废物"])
def test_negated_cues_set_nothing(text):
    assert _observe(_fresh(), text)[0] == frozenset()


def test_the_schema_hook_sets_toxic_shame_with_a_shame_emotion():
    context, _ = _perceive("我好丢人")
    assert context.fine_grained_emotion == "shame"
    with_schema = replace(context, detected_schemas=(SHAME_SCHEMA,))
    assert SHAME_CONTRAINDICATION in _observe(_fresh(), perception=with_schema)[0]
    assert SHAME_CONTRAINDICATION not in _observe(_fresh(), "我好丢人")[0]
    calm = replace(_perceive("今天还行")[0], detected_schemas=(SHAME_SCHEMA,))
    assert SHAME_CONTRAINDICATION not in _observe(_fresh(), perception=calm)[0]


@pytest.mark.parametrize("enum_id", PROFILE_CONTRAINDICATIONS)
def test_profile_disclosures_are_active_from_the_first_turn(enum_id):
    assert _observe(_fresh((enum_id,)))[0] == {enum_id}


def test_conversation_cues_hold_for_the_rest_of_the_session():
    tracker = _fresh()
    _observe(tracker, "我有心脏病")
    _observe(tracker, "我奶奶刚去世")
    active, situations = _observe(tracker, "今天天气还行")
    assert active == {"CARDIORESPIRATORY_INSTABILITY", "ACUTE_BEREAVEMENT_SHOCK"}
    assert situations == {"SIT-06-04"}


def test_unsaved_disclosures_are_reported_once():
    tracker = _fresh(("CARDIORESPIRATORY_INSTABILITY",))
    _observe(tracker, "我有心脏病，我恨我自己")
    # Already in the profile, and self-attack is not a profile disclosure.
    assert tracker.unsaved_disclosures() == frozenset()
    _observe(tracker, "他又动手打我了")
    assert tracker.unsaved_disclosures() == {"INTERPERSONAL_SAFETY_HAZARD"}
    tracker.mark_hinted(frozenset({"INTERPERSONAL_SAFETY_HAZARD"}))
    _observe(tracker, "他又动手打我了")
    assert tracker.unsaved_disclosures() == frozenset()


def test_every_enum_has_a_source_that_sets_it():
    """All 13 enums are reachable; RED_FLAG_PSYCHOSIS only through the profile."""
    reached: set[str] = set()
    tracker = _fresh(PROFILE_CONTRAINDICATIONS)
    for text in ("我奶奶刚去世", "我就是个废物"):
        reached |= _observe(tracker, text)[0]
    reached |= _observe(tracker, status=_status(CrisisLevel.L2), flags=frozenset(RED_FLAG_LINKS))[0]
    inp = SolverInput(
        stage=HelpStage.S_EXPLORE,
        arousal=0.9,
        active_red_flags=NO_FLAGS,
        active_contraindications=frozenset(),
        situation_codes=frozenset(),
        shelved_actions=frozenset(),
        battery=0.8,
    )
    reached |= active_contraindications(TAX, inp)
    assert reached == set(ENUMS)
    assert OVERLOAD_CONTRAINDICATION in reached


# -- RED_FLAG_PSYCHOSIS: a profile disclosure only ---------------------------------------


def test_psychosis_is_a_profile_disclosure_with_no_conversation_source():
    assert PSYCHOSIS in PROFILE_CONTRAINDICATIONS
    links = source_links(TAX)
    linked = (*links.red_flags.values(), *links.situations.values())
    assert not [ids for ids in linked if PSYCHOSIS in ids]
    assert PSYCHOSIS not in load_perception_lexicon(TAX).contraindication_cues


@pytest.mark.parametrize(
    "text",
    [
        "我总听到有人在跟我说话",
        "我觉得有人一直在监视我",
        "我有幻觉",
        "医生说我有妄想",
        "脑子里有声音",
    ],
)
def test_no_conversation_text_sets_psychosis(text):
    tracker = _fresh()
    assert PSYCHOSIS not in _observe(tracker, text)[0]
    assert PSYCHOSIS not in tracker.unsaved_disclosures()


# -- the solver never offers a contraindicated action ----------------------------------


def _own(aid: str) -> tuple[str, ...]:
    methods = TAX.methods()
    return (
        methods[aid].contraindications
        if aid in methods
        else TAX.action_registry()[aid].contraindications
    )


def _input(
    stage: HelpStage, arousal: float, contra: frozenset[str], sits=frozenset()
) -> SolverInput:
    return SolverInput(
        stage=stage,
        arousal=arousal,
        active_red_flags=NO_FLAGS,
        active_contraindications=contra,
        situation_codes=sits,
        shelved_actions=frozenset(),
        battery=0.8,
    )


@pytest.mark.parametrize("enum_id", [e for e in ENUMS if e != "RED_FLAG_SUBSTANCE_WITHDRAWAL"])
@pytest.mark.parametrize(
    ("stage", "arousal"), [(HelpStage.S_EMPOWER, 0.3), (HelpStage.S_EXPLORE, 0.8)]
)
def test_a_contraindicated_action_is_never_a_candidate(enum_id, stage, arousal):
    blocked = {aid for aid in (*TAX.methods(), *TAX.action_registry()) if enum_id in _own(aid)}
    assert blocked, enum_id  # every enum but substance withdrawal blocks some action
    without = set(allowed_actions(TAX, _input(stage, arousal, frozenset())).candidates)
    with_enum = set(allowed_actions(TAX, _input(stage, arousal, frozenset({enum_id}))).candidates)
    assert not with_enum & blocked
    assert with_enum == without - blocked


@pytest.mark.parametrize(
    ("stage", "arousal"), [(HelpStage.S_EMPOWER, 0.3), (HelpStage.S_EXPLORE, 0.8)]
)
def test_the_psychosis_disclosure_masks_exactly_its_taxonomy_methods(stage, arousal):
    blocked = {aid for aid in (*TAX.methods(), *TAX.action_registry()) if PSYCHOSIS in _own(aid)}
    assert blocked == PSYCHOSIS_BLOCKS
    active, _ = _observe(_fresh((PSYCHOSIS,)))
    assert active == {PSYCHOSIS}
    without = set(allowed_actions(TAX, _input(stage, arousal, frozenset())).candidates)
    with_disclosure = set(allowed_actions(TAX, _input(stage, arousal, active)).candidates)
    assert with_disclosure == without - PSYCHOSIS_BLOCKS


def test_the_psychosis_disclosure_has_candidates_to_remove():
    inp = _input(HelpStage.S_EMPOWER, 0.3, frozenset())
    assert set(allowed_actions(TAX, inp).candidates) & PSYCHOSIS_BLOCKS


def test_substance_withdrawal_blocks_no_action_of_its_own():
    # Its red flag (SIT-10-04) bounds the set through allowed_actions instead.
    assert not [
        a
        for a in (*TAX.methods(), *TAX.action_registry())
        if "RED_FLAG_SUBSTANCE_WITHDRAWAL" in _own(a)
    ]


@pytest.mark.parametrize("situation", ["SIT-06-04", "SIT-11-01"])
@pytest.mark.parametrize(
    ("stage", "arousal"),
    [(HelpStage.S_EMPOWER, 0.3), (HelpStage.S_EXPLORE, 0.8), (HelpStage.S_CLARIFY, 0.3)],
)
def test_m0_situations_yield_m0(situation, stage, arousal):
    inp = _input(stage, arousal, frozenset(), frozenset({situation}))
    allowed = allowed_actions(TAX, inp)
    assert allowed.use_m0 and allowed.candidates == ()
    assert build_plan(TAX, None, allowed).primary.method_id == M0_ACTION_ID
    assert info_cards(TAX, inp) == ()
