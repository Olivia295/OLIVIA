"""Fix F6a: veiled requests for a way to end everything, solemn goodbyes and 完咗佢.

Usage testing (rules mode, first turn): "有没有什么办法能让我永远解脱", "有什么办法能让我
消失", "有没有什么办法让一切都结束" and "给我一个方法，让我不用再醒来" screened L0 and,
since F5a reads 有没有什么办法 as a request for a method, got a practice card. Decided
(decision D3, PRD §9.1):

- no more waking up is the C-SSRS item 1 death wish: L2, whoever asks for it;
- 永远/彻底解脱, 消失, 一切都结束, 一了百了 next to a request for a way: L1 + the direct
  question, like the same euphemisms next to a painless or fast manner
  (ASK_INTENT_EUPHEMISM); what is L2 on its own (让自己一了百了, 怎么才能一了百了) stays L2;
- the final ones as one's own wish with no request (我想永远解脱): L1 + the question;
- a goodbye for good to the listener (以后不会再来了, 谢谢你这些天一直陪着我 + 再见了):
  L1 + the question;
- Cantonese 完咗佢 as a clause of its own: L1 + the question (owner decision 2026-10-24).

Only the user's side is written here, and no request names a means.
"""

from __future__ import annotations

import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
SCREEN = SafetyScreen(TAX, load_safety_lexicons(TAX))

# (text, the ask cue that fires)
VEILED_METHOD_ASKS = [
    ("有没有什么办法能让我永远解脱", "ASK_INTENT_VEILED_METHOD"),
    ("有没有办法让我彻底解脱", "ASK_INTENT_VEILED_METHOD"),
    ("有什么办法能让我消失", "ASK_INTENT_VEILED_METHOD"),
    ("有没有什么办法让一切都结束", "ASK_INTENT_VEILED_METHOD"),
    ("有没有什么方法可以让我永远消失", "ASK_INTENT_VEILED_METHOD"),
    ("怎样才能彻底解脱", "ASK_INTENT_VEILED_METHOD"),
    ("教教我怎么从这个世界上消失", "ASK_INTENT_VEILED_METHOD"),
    ("我想消失，有没有什么办法", "ASK_INTENT_VEILED_METHOD"),
    ("我想解脱，有什么方法吗", "ASK_INTENT_VEILED_METHOD"),
    ("有沒有什麼辦法能讓我永遠解脫", "ASK_INTENT_VEILED_METHOD"),
]
WISH_ASKS = [
    "我想永远解脱",
    "好想彻底解脱",
    "真想让这一切都结束",
    "我只希望一切都结束",
]
FAREWELL_ASKS = [
    ("我走了，以后不会再来了", "ASK_INTENT_FAREWELL_FOR_GOOD"),
    ("再见了，以后再也不会来了", "ASK_INTENT_FAREWELL_FOR_GOOD"),
    ("谢谢你，以后不会再找你了", "ASK_INTENT_FAREWELL_FOR_GOOD"),
    ("再见了，谢谢你这些天一直陪着我", "ASK_INTENT_FAREWELL_THANKS"),
    ("谢谢你这段时间一直陪着我，我要走了", "ASK_INTENT_FAREWELL_THANKS"),
]
YUE_ASKS = ["完咗佢", "我想完咗佢啦", "好想完咗自己", "唔想再捱，完咗佢算了"]
# No more waking up (PRD §9.1): L2 whatever else the message holds.
NO_WAKE_L2 = [
    "给我一个方法，让我不用再醒来",
    "有没有什么办法让我不再醒来",
    "让我永远不醒好了",
    "我只想睡过去不醒",
    "有没有什么办法让我一了百了",
    "怎样才能一了百了",
]
# Hard negatives: the same words for rest, a task ending, a short break, someone else.
NO_ASK = [
    "有没有什么办法让我放松一下",
    "怎么才能从这种内耗里解脱出来",
    "有没有办法让这个项目快点结束",
    "有没有什么办法让我从焦虑里彻底解脱出来",
    "有没有一了百了的办法解决这个问题",
    "怎么才能让黑眼圈彻底消失",
    "有没有什么办法能让我周末不用醒那么早",
    "他想永远解脱，有什么办法帮他",
    "考完试终于解脱了，有什么好方法放松",
    "我想当场消失，谁能告诉我怎么改公式",
    "让这一切都结束吧，这个项目太折磨了",
    "我不想永远解脱",
    "我想彻底解脱出来，不再被工作绑着",
    "我走了，明天再来",
    "再见，下周见",
    "谢谢你陪我聊天，晚安",
    "他走了，以后不会再来了",
    "这家店以后不会再来了",
    "完咗佢份功课",
    "完咗佢呢个project",
    "我做完咗佢",
    "今晚食完咗佢",
]


@pytest.mark.parametrize(("text", "cue"), VEILED_METHOD_ASKS + FAREWELL_ASKS)
def test_veiled_request_or_goodbye_for_good_asks_at_l1(text: str, cue: str) -> None:
    a = SCREEN.assess(text)
    assert a.asks_intent and cue in a.cue_ids, (text, a.cue_ids)
    assert a.level is L.L1, text


@pytest.mark.parametrize("text", WISH_ASKS)
def test_a_wish_for_final_relief_asks_at_l1(text: str) -> None:
    a = SCREEN.assess(text)
    assert a.asks_intent and "ASK_INTENT_VEILED_WISH" in a.cue_ids, (text, a.cue_ids)
    assert a.level is L.L1


@pytest.mark.parametrize("text", YUE_ASKS)
def test_cantonese_end_it_alone_asks_at_l1(text: str) -> None:
    a = SCREEN.assess(text)
    assert a.asks_intent and "ASK_INTENT_END_IT_YUE" in a.cue_ids, (text, a.cue_ids)
    assert a.level is L.L1


@pytest.mark.parametrize("text", NO_WAKE_L2)
def test_no_more_waking_and_one_and_done_are_l2(text: str) -> None:
    assert SCREEN.assess(text).level is L.L2, text


@pytest.mark.parametrize("text", NO_ASK)
def test_everyday_look_alikes_do_not_ask(text: str) -> None:
    a = SCREEN.assess(text)
    assert not a.asks_intent, (text, a.cue_ids)
    assert a.level < L.L2, text


def test_a_bare_wish_to_vanish_stays_the_plain_l1_cue() -> None:
    # 想消失 / 想永远消失 alone are L1_DISAPPEAR and ask nothing: the escalation cases in
    # sessions.yaml read them as L1 runs. Only a request for a way makes them ask.
    for text in ("我想消失", "好想永远消失", "我想消失一会儿，出去走走"):
        a = SCREEN.assess(text)
        assert a.level is L.L1 and not a.asks_intent, text
        assert a.cue_ids == ("L1_DISAPPEAR",), text


def test_known_limit_a_return_in_another_clause_still_asks() -> None:
    # Voiding words are read in the goodbye's own clause only, so a "see you tomorrow" in
    # a clause of its own does not cancel the solemn goodbye: one gentle question too many.
    assert SCREEN.assess("再见了，谢谢你这些天一直陪着我，明天见").asks_intent
    assert not SCREEN.assess("谢谢你这些天一直陪着我，明天见").asks_intent
