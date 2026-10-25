"""Passive ideation with 再 in the middle: 不想再醒来, 再也不醒来 (C-SSRS item 1, L2).

The lexicon already had 不想醒来 and 再也不要醒; inserting 再 or dropping 要 broke the
substring match. Bare 再也不醒来 also describes someone else's death (外婆睡着后就再也不
醒来了), so it counts only next to a wish of one's own (想, 希望, 就好, 消失, 睡过去).

The sentences are written from the category, not copied from the red-team suite.
"""

import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
SCREEN = SafetyScreen(TAX, load_safety_lexicons(TAX))

POSITIVES = [
    "我不想再醒来了",
    "真的不想再醒来",
    "今晚睡着了就不想再醒过来",
    "我不想再醒了，太累了",
    "不要再醒来了，就这样吧",
    "别让我再醒来",
    "希望再也不醒来",
    "好想再也不醒来",
    "要是能再也不醒来就好了",
    "睡过去再也不醒来多好",
    "再也不醒来算了",
    "我想消失，再也不醒来",
    "想消失再也不醒来",
    "就这样睡过去，再也不醒来",
    "閉上眼睛就不想再醒來了",
    # F16a: 永远 + fall asleep for good.
    "我想永远睡过去",
    "好想就这样永远地睡过去",
    "让我永远睡下去吧",
]

NEGATIVES = [
    "外婆那天睡着后就再也不醒来了，我好想她",
    "爷爷是在睡梦中走的，再也没有醒来",
    "闹钟响了三次我都没醒，又迟到了",
    "我再也不熬夜了",
    "睡得太香了，今天醒来神清气爽",
    "我想再睡五分钟就起",
    "小说里公主睡着了，再也不醒来，直到王子出现",
    "宝宝夜里醒了好几次，我也跟着醒",
    "周末好想一直睡下去，不想上班",
    "昨晚一躺下就睡过去了",
]


@pytest.mark.parametrize("text", POSITIVES)
def test_passive_ideation_with_inserted_words_is_l2(text: str) -> None:
    assert SCREEN.assess(text).level >= L.L2, text


@pytest.mark.parametrize("text", NEGATIVES)
def test_sleep_and_waking_talk_stays_below_l2(text: str) -> None:
    assert SCREEN.assess(text).level < L.L2, text


def test_passive_ideation_never_reaches_l3() -> None:
    # A wish without plan, means, time or act stays L2 (Stage 1 needs plan evidence).
    assert all(SCREEN.assess(text).level is L.L2 for text in POSITIVES)
