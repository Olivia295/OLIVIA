"""Dossier situations in the session (plan D-2, PRD §8.2).

A situation read from the conversation holds for the session, is listed in
``inspect["situations"]``, prefers its dossier's imagery for the ``{metaphor}`` slot and
its dossier's Grade B methods for the one S_clarify lens. It never changes crisis
replies, red-flag referrals or the m0 rule.
"""

from __future__ import annotations

import copy
import random
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from olivia.core.language.data import load_language_data
from olivia.core.methods.contraindications import SessionContraindications, source_links
from olivia.core.methods.solver import M0_ACTION_ID
from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, UserRegion
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.safety.tracker import CrisisStatus
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import Taxonomy, load_taxonomy

TAX = load_taxonomy()
LANG = load_language_data(TAX)
TAX_FILE = Path(__file__).resolve().parents[2] / "olivia/data/taxonomy.yaml"
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
SEEDS = range(12)
LAYOFF = "我被裁员了，交接完走出公司，心里空落落的"
NOT_MINE = "我同事被裁员了，交接完走出公司，心里空落落的"
ADJUSTMENT = "SIT-06-03"


def _open(seed: int = 7) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(
        TAX, replace(profile), rng=random.Random(seed), now=lambda: NOW, student=False
    )


def _all_images() -> set[str]:
    grid = LANG.metaphors.by_spectrum_yearning
    images = {p for cell in grid.values() for ps in cell.values() for p in ps}
    images |= set(LANG.metaphors.fallback)
    for ps in LANG.metaphors.by_situation.values():
        images |= set(ps)
    return images


def _images_in(result: TurnResult) -> set[str]:
    return {image for image in _all_images() if image in result.reply}


# -- situations ---------------------------------------------------------------------------


def test_a_dossier_situation_holds_for_the_session() -> None:
    session = _open()
    assert session.turn(LAYOFF).inspect["situations"] == [ADJUSTMENT]
    later = session.turn("今天天气还行")
    assert later.inspect["situations"] == [ADJUSTMENT]
    assert session.turn("我好孤独，一个朋友都没有").inspect["situations"] == [
        ADJUSTMENT,
        "SIT-07-05",
    ]


def test_someone_elses_story_sets_no_situation() -> None:
    assert _open().turn(NOT_MINE).inspect["situations"] == []


# -- metaphor ------------------------------------------------------------------------------


def test_the_metaphor_slot_prefers_the_dossier_imagery() -> None:
    own = set(LANG.metaphors.by_situation[ADJUSTMENT])
    shown_with: set[str] = set()
    shown_without: set[str] = set()
    for seed in range(30):
        shown_with |= _images_in(_open(seed).turn(LAYOFF))
        shown_without |= _images_in(_open(seed).turn(NOT_MINE))
    assert shown_with  # some templates carry the {metaphor} slot
    assert shown_with <= own
    assert shown_without and not shown_without & own


# -- lens ----------------------------------------------------------------------------------

# Three turns that reach S_clarify through the attachment spectrum ("07"); the first one
# also names the codependency dossier (SIT-07-03), which names Adler (38) and TA (54).
TO_CLARIFY = (
    "最近和男朋友总吵架，很难过，我总在替他收拾烂摊子",
    "他总说我太黏人",
    "我也不知道该怎么办，每次吵完都很失落",
)


def _lens(session: Session, turns: tuple[str, ...]) -> TurnResult:
    results = [session.turn(text) for text in turns]
    lens = results[-1]
    assert lens.stage is HelpStage.S_CLARIFY
    assert lens.reply_kind is ReplyKind.INFO
    return lens


def test_the_lens_prefers_the_grade_b_methods_the_dossier_names() -> None:
    dossier = set(LANG.situation_lenses["SIT-07-03"])
    seen = set()
    for seed in SEEDS:
        lens = _lens(_open(seed), TO_CLARIFY)
        assert lens.inspect["situations"] == ["SIT-07-03"]
        seen.add(lens.inspect["info"])
    assert seen <= dossier
    assert seen - set(LANG.info_lenses["07"])  # Adler (38) is not a spectrum-07 lens


def test_without_the_situation_the_spectrum_lens_is_used() -> None:
    plain = ("最近和男朋友总吵架，很难过", *TO_CLARIFY[1:])
    for seed in SEEDS:
        lens = _lens(_open(seed), plain)
        assert lens.inspect["situations"] == []
        assert lens.inspect["info"] in LANG.info_lenses["07"]


# -- contraindications ---------------------------------------------------------------------


def test_a_contraindication_a_dossier_source_names_passes_through() -> None:
    """A1's path: any SIT code named in a ``detection_source`` reaches the solver.

    Only SIT-06-04 is named today (bereavement); none of the other dossiers lists an
    action to avoid that maps to a taxonomy enum (see the coverage report). If one is
    added to a source, a D-2 cue for that dossier sets it, as this shows.
    """
    data = yaml.safe_load(TAX_FILE.read_text(encoding="utf-8"))
    linked = copy.deepcopy(data)
    for entry in linked["contraindication_enums"]:
        if entry["id"] == "INTERPERSONAL_SAFETY_HAZARD":
            entry["detection_source"] += " / DISTRESS_TRACKER (SIT-07-06)"
    tax = Taxonomy(linked)
    assert source_links(tax).situations["SIT-07-06"] == {"INTERPERSONAL_SAFETY_HAZARD"}
    stub = RuleStub(tax, load_perception_lexicon(tax))
    context, signals = stub.perceive(
        "他总说我太敏感，我现在都不敢相信自己的记忆",
        CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE1", False, ()),
    )
    status = CrisisStatus(
        level=CrisisLevel.L0,
        in_crisis=False,
        entry_level=None,
        escalated=False,
        awaiting_confirmation=False,
        safe_turns_remaining=0,
        just_entered=False,
        just_exited=False,
    )
    tracker = SessionContraindications(tax, ())
    active = tracker.observe(signals, context, status, frozenset())
    assert active.situations == {"SIT-07-06"}
    assert "INTERPERSONAL_SAFETY_HAZARD" in active.contraindications
    # Linked through the taxonomy, it is not a profile disclosure: no olivia health hint.
    assert tracker.unsaved_disclosures() == frozenset()


def test_the_packaged_taxonomy_links_only_bereavement() -> None:
    assert dict(source_links(TAX).situations) == {
        "SIT-06-04": frozenset({"ACUTE_BEREAVEMENT_SHOCK"})
    }


# -- safety paths unchanged ----------------------------------------------------------------


def test_a_situation_never_softens_a_crisis() -> None:
    for seed in SEEDS:
        session = _open(seed)
        session.turn(LAYOFF)
        result = session.turn("我不想活了")
        assert result.reply_kind is ReplyKind.CRISIS
        assert result.in_crisis
        assert result.resource_card is not None
        assert result.inspect["situations"] == [ADJUSTMENT]
        assert not _images_in(result)  # crisis replies weave no metaphor


def test_a_situation_never_hides_the_red_flag_referral() -> None:
    for seed in SEEDS:
        session = _open(seed)
        session.turn(LAYOFF)
        result = session.turn("我是边缘型人格，确诊两年了，给我一个练习")
        assert "SIT-09-01" in result.referral_flags
        assert result.inspect["situations"] == [ADJUSTMENT]


@pytest.mark.parametrize(
    "text", ["[80%] " + LAYOFF + "，给我一个方法", "[80%] 我职业倦怠了，给我一个方法"]
)
def test_dossier_situations_do_not_route_to_m0(text: str) -> None:
    for seed in SEEDS:
        result = _open(seed).turn(text)
        assert result.inspect["situations"]
        assert result.inspect["candidates"]
        assert result.action_id != M0_ACTION_ID
