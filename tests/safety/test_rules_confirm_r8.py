"""Rules round 8, task G2b-2 (2026-11-25): the screen side.

1. 负责人 2026-11-25 决定: a means "put away" (收好) next to a death word that is itself a
   denial ("我不想死，刀我已经收好了") is still Stage 1 for the screen, but it is a plan
   candidate (``CrisisAssessment.plan_candidate``) when nothing else in the message is a risk
   cue: no plan, time, farewell, hedge or contrast, no other Stage 1 phrase or composition, no
   Stage 2 phrase of the user's own. The session then asks once first. Anything else keeps
   the plain L3.

Every sentence here was written for this round; none comes from an evaluation set or the
red-team suite.
"""

from __future__ import annotations

import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)

# -- 1. a means put away ---------------------------------------------------------------------

PUT_AWAY_ALONE = [
    "我不想死，刀我已经收好了",
    "我不会伤害自己的，刀我已经收好了",
    "放心，我不会做傻事，药都收好了",
    "我没想自杀，刀片我都收好了",
    "我不会想不开的，安眠药我已经收好了",
]

PUT_AWAY_WITH_MORE = [
    "我想死，刀我已经收好了",  # a death wish of the user's own
    "我不想活了 刀已经收好了",
    "我不想死，刀我已经收好了，今晚再说",  # a time
    "我不想死，但刀已经收好了",  # a contrast
    "我不想死，刀收好了，遗书也写好了",  # a farewell
    "我不想死，药我已经收好了，准备好了",  # a plan word
    "我不想死，刀我先收好了，万一用得上",  # a hedge
    "我不想死，刀我收好了，藏在枕头底下",  # hidden at hand
    "我不想死，可是绳子都准备好了，刀也收好了",  # another means made ready
]


@pytest.mark.parametrize("text", PUT_AWAY_ALONE)
def test_a_means_put_away_alone_is_a_plan_candidate(text: str) -> None:
    result = SCREEN.assess(text)
    assert result.level is L.L3
    assert result.has_plan_evidence
    assert result.plan_candidate
    assert "S1_MEANS_PUT_AWAY" in result.cue_ids


@pytest.mark.parametrize("text", PUT_AWAY_WITH_MORE)
def test_a_means_put_away_with_more_stays_plain_l3(text: str) -> None:
    result = SCREEN.assess(text)
    assert result.level is L.L3
    assert not result.plan_candidate


@pytest.mark.parametrize(
    "text",
    [
        "我不想死，刀我已经藏好了",  # a strong ready mark, as before
        "我不想死，可是绳子都准备好了",
    ],
)
def test_other_ready_marks_are_no_candidate(text: str) -> None:
    result = SCREEN.assess(text)
    assert result.level is L.L3
    assert not result.plan_candidate


@pytest.mark.parametrize(
    "text",
    [
        "刀我已经收好了",  # no death word: no cue at all, as before
        "厨房的刀我都收好了，孩子够不着",
        "切完西瓜，刀我已经收好了",
    ],
)
def test_a_means_put_away_with_no_death_word_is_no_cue(text: str) -> None:
    result = SCREEN.assess(text)
    assert result.level is L.L0
    assert not result.plan_candidate


def test_the_put_away_rules_name_l3_compositions() -> None:
    rules = LEX.put_away_ask
    assert rules.ids == frozenset({"S1_MEANS_PUT_AWAY"})
    entries = {e.id: e for e in LEX.compositions.entries}
    assert all(entries[i].level is L.L3 for i in rules.ids)
    assert "收好" in entries["S1_MEANS_PUT_AWAY"].tails
    assert "收好" not in entries["S1_MEANS_PREPARED"].tails
