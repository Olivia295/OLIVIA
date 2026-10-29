"""Pills made ready, with no drug named (round 6, 2026-10-30; more sensitive, no narrowing).

"药" with a word of having made it ready (准备好, 备好, 放好, 拿出来, 倒出来, 数好, 凑齐) asks
the D3 question (ASK_INTENT_PILLS_READY), L2 with a risk cue of the user's own; a named
illness, a person or pet it is for, a trip or a doctor's routine voids it.

Every sentence here was written for this file; none is from an evaluation set, the re-test
reports or this round's holdout.
"""

from __future__ import annotations

import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
SCREEN = SafetyScreen(TAX, load_safety_lexicons(TAX))


@pytest.mark.parametrize(
    "text",
    [
        "药我已经全都备好了",
        "我把家里的药都拿出来了",
        "药放好了，在枕边",
        "那一把药我数好了",
    ],
)
def test_pills_made_ready_ask(text: str) -> None:
    a = SCREEN.assess(text)
    assert "ASK_INTENT_PILLS_READY" in a.cue_ids, (text, a.cue_ids)
    assert a.asks_intent or a.level >= L.L2


def test_pills_made_ready_with_a_risk_cue_is_l2() -> None:
    assert SCREEN.assess("活着没意思，药我已经全都备好了").level >= L.L2


@pytest.mark.parametrize(
    "text",
    [
        "下周出差的胃药备好了",
        "女儿的退烧药我都准备好了",
        "去云南的旅行药包准备好了",
        "爸爸的降压药我放好了，每天一片",
        "狗狗的驱虫药拿出来了",
        "医生开的药都按时备好了",
    ],
)
def test_everyday_pills_stay_quiet(text: str) -> None:
    a = SCREEN.assess(text)
    assert a.level < L.L2 and not a.asks_intent, (text, a.cue_ids)
