"""Two narrowings the owner approved (负责人 2026-10-30 决定), each with its real-crisis side.

* 血止不住 with an everyday injury in the same clause (切菜, 摔, 刮 ...) is no act in
  progress: not L3 (S1_BLEEDING_UNSTOPPED, a Stage 1 composition that replaced the bare
  Stage 1 phrase). Said alone or after an act on oneself it stays L3.
* 结束这一切的 + a noun (结束这一切的拖延) names a thing to end, not one's life: not L2 from
  L2_THEN_DEATH, as the other entries already read it (act_exceptions). 结束这一切 said
  on its own stays at its level.

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
        "切菜的时候切到手血止不住",
        "下楼摔了一跤膝盖血止不住",
        "刮胡子刮破了血止不住",
        "拔完牙一直血止不住",
    ],
)
def test_everyday_bleeding_in_its_clause_is_not_l3(text: str) -> None:
    # 负责人 2026-10-30 决定
    assert SCREEN.assess(text).level < L.L3, text


@pytest.mark.parametrize(
    "text",
    [
        "我割了手腕血止不住",
        "血止不住，我也不想去包",
        "刚才动手了，现在血止不住",
    ],
)
def test_bleeding_alone_or_after_an_act_stays_l3(text: str) -> None:
    assert SCREEN.assess(text).level is L.L3, text


@pytest.mark.parametrize(
    "text",
    ["明天就结束这一切的混乱，好好收拾房间", "这周就结束这一切的争吵吧"],
)
def test_ending_a_named_thing_is_not_l2(text: str) -> None:
    # 负责人 2026-10-30 决定
    assert SCREEN.assess(text).level < L.L2, text


@pytest.mark.parametrize(
    "text",
    ["要是这次还不行，我就结束这一切", "我想结束这一切", "再这样下去我就结束这一切了"],
)
def test_ending_it_all_alone_keeps_its_level(text: str) -> None:
    assert SCREEN.assess(text).level >= L.L2, text
