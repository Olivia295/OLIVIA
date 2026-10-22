"""Red-flag table and property checks against expectations computed from taxonomy data.

The helpers below re-derive each mask straight from the taxonomy accessors, so these
tests do not trust the solver's own set arithmetic.
"""

from collections.abc import Iterable

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from olivia.core.methods.solver import M0_ACTION_ID, M0_SITUATIONS, SolverInput, allowed_actions
from olivia.core.models import HelpStage
from olivia.core.taxonomy import Taxonomy, load_taxonomy

TAX = load_taxonomy()
RED_FLAGS = tuple(TAX.red_flags())
ENUMS = TAX.values("contraindication_enums")
ALL_IDS = tuple(TAX.methods()) + tuple(TAX.action_registry())


def _canon(entries: Iterable[str]) -> set[str]:
    return {TAX.canonical_action_id(e) for e in entries}


def _subs_of(method_id: str) -> set[str]:
    return {a.id for a in TAX.action_registry().values() if a.parent_method_id == method_id}


def _with_subs(ids: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for aid in _canon(ids):
        out |= {aid} | _subs_of(aid)
    return out


def _stage_eligible(tax: Taxonomy, stage: HelpStage, arousal: float) -> set[str]:
    high = arousal >= tax.threshold("arousal.thresholds.somatic_priority")
    if high and stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER):
        return _with_subs(tax.stabilization_whitelist())
    if stage is HelpStage.S_EMPOWER:
        return _with_subs(tax.grade_a_ids())
    return set()


def _banned(flags: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for code in flags:
        flag = TAX.red_flags()[code]
        for entry in flag.banned_methods:
            ids = TAX.banned_tag_methods(entry) if TAX.is_banned_tag(entry) else (entry,)
            for aid in _canon(ids):
                out.add(aid)
                out |= _subs_of(aid) - _canon(flag.allowed_actions)
    return out


def _own_contra(aid: str) -> tuple[str, ...]:
    if aid in TAX.methods():
        return TAX.methods()[aid].contraindications
    return TAX.action_registry()[aid].contraindications


def _active(arousal: float, contra: Iterable[str]) -> set[str]:
    overload = arousal >= TAX.threshold("arousal.thresholds.cognitive_block")
    return set(contra) | ({"ACUTE_AROUSAL_OVERLOAD"} if overload else set())


# -- the seven red flags at arousal 0.85 in S_explore -------------------------------------------


def _expected_explore_high(code: str) -> set[str]:
    pool = _stage_eligible(TAX, HelpStage.S_EXPLORE, 0.85)
    pool &= _canon(TAX.red_flags()[code].allowed_actions)
    pool -= _banned([code])
    active = _active(0.85, ())
    return {aid for aid in pool if not active & set(_own_contra(aid))}


@pytest.mark.parametrize("code", RED_FLAGS)
def test_red_flag_at_overload_in_explore_matches_taxonomy(code: str) -> None:
    result = allowed_actions(
        TAX,
        SolverInput(
            HelpStage.S_EXPLORE, 0.85, frozenset({code}), frozenset(), frozenset(), frozenset()
        ),
    )
    expected = _expected_explore_high(code)
    assert set(result.candidates) == expected
    assert result.use_m0 == (not expected)
    assert result.referral_flags == (code,)
    assert "12:tipp_cold_water" not in result.candidates
    assert "28" not in result.candidates


def test_seven_red_flags_by_hand() -> None:
    assert len(RED_FLAGS) == 7
    assert _expected_explore_high("SIT-09-01") == {"12:tipp_breathing", "29:pmr_release"}
    assert _expected_explore_high("SIT-06-01") == {"30:grounding"}
    assert _expected_explore_high("SIT-06-05") == {"30:grounding"}
    for code in ("SIT-02-04", "SIT-02-06", "SIT-08-04", "SIT-10-04"):
        assert _expected_explore_high(code) == set()


# -- property: no candidate ever escapes a mask ----------------------------------------------------

_arousal = st.one_of(
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    st.sampled_from([0.0, 0.79, 0.8, 0.84, 0.85, 1.0]),
)


@settings(max_examples=300, deadline=None)
@given(
    stage=st.sampled_from(list(HelpStage)),
    arousal=_arousal,
    flags=st.frozensets(st.sampled_from(RED_FLAGS), max_size=3),
    contra=st.frozensets(st.sampled_from(ENUMS), max_size=4),
    situations=st.frozensets(st.sampled_from([*sorted(M0_SITUATIONS), "SIT-01-01"]), max_size=2),
    shelved=st.frozensets(st.sampled_from(ALL_IDS), max_size=4),
)
def test_candidates_never_escape_a_mask(
    stage: HelpStage,
    arousal: float,
    flags: frozenset[str],
    contra: frozenset[str],
    situations: frozenset[str],
    shelved: frozenset[str],
) -> None:
    result = allowed_actions(TAX, SolverInput(stage, arousal, flags, contra, situations, shelved))
    eligible = _stage_eligible(TAX, stage, arousal)
    banned = _banned(flags)
    active = _active(arousal, contra)
    for aid in result.candidates:
        assert aid in eligible
        assert aid not in banned
        assert active.isdisjoint(_own_contra(aid))
        assert aid not in _canon(shelved)
        for code in flags:
            assert aid in _canon(TAX.red_flags()[code].allowed_actions)
    assert M0_ACTION_ID not in result.candidates
    assert len(set(result.candidates)) == len(result.candidates)
    assert result.use_m0 == (not result.candidates)
    assert set(result.referral_flags) == flags
    if stage is HelpStage.S_HAVEN or situations & M0_SITUATIONS:
        assert result.use_m0
