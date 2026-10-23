"""Grade B/C information cards through the solver's masks (roadmap next-phase A4).

PRD §8.1: Grade B is explained only in S_clarify, Grade C only when the user asks about
it. Both pass the same four masks as an exercise (SDD §4.3.7, §8.4 closure axiom) and the
arousal gate that keeps S_clarify to stabilization at or above the somatic line (R-P3a).
"""

from __future__ import annotations

import pytest

from olivia.core.methods.solver import SolverInput, info_cards
from olivia.core.models import HelpStage, SafetyGrade
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
GRADE_B = tuple(mid for mid, m in TAX.methods().items() if m.grade is SafetyGrade.GRADE_B)
GRADE_C = tuple(mid for mid, m in TAX.methods().items() if m.grade is SafetyGrade.GRADE_C)
SOMATIC = TAX.threshold("arousal.thresholds.somatic_priority")
ASK_STAGES = (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER, HelpStage.S_CLOSING)


def _inp(
    stage: HelpStage = HelpStage.S_CLARIFY,
    arousal: float = 0.4,
    flags: frozenset[str] = frozenset(),
    situations: frozenset[str] = frozenset(),
) -> SolverInput:
    return SolverInput(
        stage=stage,
        arousal=arousal,
        active_red_flags=flags,
        active_contraindications=frozenset(),
        situation_codes=situations,
        shelved_actions=frozenset(),
    )


def test_s_clarify_offers_every_grade_b_explainer_and_no_grade_c() -> None:
    assert len(GRADE_B) == 26 and len(GRADE_C) == 17
    assert info_cards(TAX, _inp()) == GRADE_B


@pytest.mark.parametrize(
    "stage",
    [
        HelpStage.S_READY,
        HelpStage.S_EXPLORE,
        HelpStage.S_EMPOWER,
        HelpStage.S_CLOSING,
        HelpStage.S_HAVEN,
        HelpStage.S_CRISIS,
    ],
)
def test_no_unasked_explainer_outside_s_clarify(stage: HelpStage) -> None:
    assert info_cards(TAX, _inp(stage)) == ()


@pytest.mark.parametrize("arousal", [SOMATIC, 0.85, 1.0])
def test_arousal_gate_blocks_every_info_card(arousal: float) -> None:
    assert info_cards(TAX, _inp(arousal=arousal)) == ()
    assert info_cards(TAX, _inp(arousal=arousal), asked="21") == ()
    assert info_cards(TAX, _inp(arousal=arousal), asked="19") == ()


@pytest.mark.parametrize("stage", ASK_STAGES)
@pytest.mark.parametrize("method_id", GRADE_C)
def test_asked_grade_c_is_explained_in_any_ordinary_stage(stage: HelpStage, method_id: str) -> None:
    assert info_cards(TAX, _inp(stage), asked=method_id) == (method_id,)


@pytest.mark.parametrize("stage", [HelpStage.S_HAVEN, HelpStage.S_CRISIS, HelpStage.S_READY])
def test_asked_grade_c_waits_outside_ordinary_stages(stage: HelpStage) -> None:
    assert info_cards(TAX, _inp(stage), asked="21") == ()


def test_asked_grade_b_only_in_s_clarify() -> None:
    assert info_cards(TAX, _inp(), asked="19") == ("19",)
    for stage in (HelpStage.S_EXPLORE, HelpStage.S_EMPOWER, HelpStage.S_CLOSING):
        assert info_cards(TAX, _inp(stage), asked="19") == ()


@pytest.mark.parametrize("flag", sorted(TAX.red_flags()))
def test_red_flag_closure_blocks_every_info_card(flag: str) -> None:
    # No red flag's allowed_actions names a Grade B/C method, so the closed upper bound
    # leaves no information card; the referral card speaks instead (SDD §8.4).
    flags = frozenset({flag})
    assert info_cards(TAX, _inp(flags=flags)) == ()
    for method_id in ("21", "26", "59", "19"):
        assert info_cards(TAX, _inp(flags=flags), asked=method_id) == ()


@pytest.mark.parametrize("situation", ["SIT-06-04", "SIT-11-01"])
def test_m0_situations_get_no_info_card(situation: str) -> None:
    situations = frozenset({situation})
    assert info_cards(TAX, _inp(situations=situations)) == ()
    assert info_cards(TAX, _inp(situations=situations), asked="21") == ()


@pytest.mark.parametrize("method_id", ["01", "28", "30:grounding", "99"])
def test_asked_id_must_be_a_grade_b_or_c_method(method_id: str) -> None:
    with pytest.raises(ValueError, match="Grade B or C"):
        info_cards(TAX, _inp(), asked=method_id)


def test_unknown_flag_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown red flag"):
        info_cards(TAX, _inp(flags=frozenset({"SIT-99-99"})))
