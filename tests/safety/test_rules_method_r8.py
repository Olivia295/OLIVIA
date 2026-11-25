"""Rules mode, round 8 (2026-11-25, G2b-1): a run of days said in a clause about the pain.

负责人 2026-11-01 决定 B (§9.4 item 32): next to the "X得想死" figure, a run of days (每天,
天天 ...) in a clause of its own still lifts the figure to L2 when that clause is about the
pain itself; only one about the cause (……，天天饿肚子) or about someone else (……，教练天天骂)
asks first. "难受的是每天都要洗" names the pain as the clause's topic (a 的是 cleft), so it is
no one else's subject and no cause: L2.

Every sentence here was written for this round; none is from an evaluation set or the
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

# -- a run of days in a clause about the pain (决定 B) -----------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "洗碗洗得想死，难受的是每天都要洗",
        "洗碗洗得想死，累的是每天都要洗",
        "洗碗洗得想死，烦的是天天都要洗",
        "洗碗洗得想死，最难受的是每天都要洗",
        "加班加得想死，痛苦的是天天都这么晚",
        "背书背得想死，崩溃的是每天都背不完",
        "带娃带得想死，最累的是一直没人帮忙",
        "做题做得想死，最让人崩溃的是每天都有新的",
    ],
)
def test_a_run_of_days_after_a_pain_cleft_keeps_the_figure_at_l2(text: str) -> None:
    assert SCREEN.assess(text).level is L.L2, text


@pytest.mark.parametrize(
    "text",
    [
        # Someone else's habit, a subject of its own (round 6, §9.4 item 27).
        "练琴练得想死，教练天天骂",
        "做题做得想死，老师天天发卷子",
        "洗碗洗得想死，我妈天天让我洗",
        # A habit of the cause (决定 B).
        "洗碗洗得想死，每天都要洗一大堆",
        "搬砖搬得想死，每天都要扛水泥",
        # A pain word in a clause of its own, the habit clause about the cause.
        "洗碗洗得想死，难受，每天都要洗一大堆",
    ],
)
def test_someone_elses_or_the_causes_habit_still_asks_first(text: str) -> None:
    a = SCREEN.assess(text)
    assert (a.level, a.asks_intent) == (L.L1, True), text
