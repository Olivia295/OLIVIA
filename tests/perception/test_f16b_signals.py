"""F16b: ``another_method``, a direct request for another or a different method.

While a card waits for feedback the session reads it as not_now for that card and offers
another one, so a plain request ("给我一个方法", the red-team probe "能给我一个练习试试吗")
must never set it, and neither may talk that only contains the words."""

from __future__ import annotations

import pytest

from olivia.core.models import CrisisLevel
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.perception.signals import TurnSignals
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
STUB = RuleStub(TAX, load_perception_lexicon(TAX))


def _signals(text: str) -> TurnSignals:
    return STUB.perceive(text, CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE2", False, ()))[1]


@pytest.mark.parametrize(
    "text",
    [
        "再给我一个别的方法",
        "再给我一个别的方法吧",
        "再给我一个练习",
        "换个方法吧",
        "换一个练习试试",
        "还有别的办法吗？",
        "有没有其他方法",
        "给我一个别的",
        # whole messages
        "再给我一个",
        "再来一个",
        "换一个",
        "换个吧",
        "还有别的吗",
    ],
)
def test_requests_for_another_method(text: str) -> None:
    signals = _signals(text)
    assert signals.direct_request and signals.another_method, text


@pytest.mark.parametrize(
    "text",
    [
        "给我一个方法",
        "能给我一个练习试试吗",
        "有没有什么办法能让我先缓一缓",
        "能带我做一下正念吗",
        "换个话题吧",
        "老板说再给我一个机会",
        "我试过别的方法都没用",
        "不用换一个方法",
    ],
)
def test_not_a_request_for_another_method(text: str) -> None:
    assert not _signals(text).another_method, text
