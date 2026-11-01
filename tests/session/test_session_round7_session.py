"""The session, round 7 (re-test 2026-10-31, q3 第四节 and q4 P6, P8, P12; drafts, G-0).

* Once the user asked not to be asked about feelings, no sentence of an ordinary reply
  talks about feelings, not only its closing question.
* "Don't reason with me", "no practice", "just listen" in words the lexicon's lock phrases
  miss turn the listening lock on: no card is offered unasked.
* While a card waits, a question about what to do or think is a new request, and any
  message with words of its own after the /done prompt was said once leaves the wait.
* A bare number given as the card's distress rating is not "another language".
* A long run of Chinese said back is cut where a word ends.
* Asked whether the lines speak Mandarin, a user in mainland China gets a plain yes.

Every example message is written here; none comes from an evaluation set or the re-test.
"""

from __future__ import annotations

import random
import re
from datetime import UTC, datetime

import pytest

from olivia.core.language.engine import without_feeling_talk
from olivia.core.language.mirror import mirror
from olivia.core.models import HelpStage, PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 31, 15, 0, tzinfo=UTC)
FEELING_TALK = re.compile(r"感受|感觉|滋味|心情|情绪|心里|心事")


def _open(*, seed: int = 5, region: str = "CN", persona: PersonaSpectrum | None = None) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="阿青",
        region=UserRegion(region, "Asia/Shanghai"),
        **({"persona_spectrum": persona} if persona is not None else {}),
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW)


# -- no feeling talk ----------------------------------------------------------------------


def test_without_feeling_talk_drops_only_those_sentences() -> None:
    variant = "嗯，我在这里。{mirror}。不管心里是轻是重，你都不用一个人对着它。"
    assert without_feeling_talk(variant) == "嗯，我在这里。{mirror}。"
    assert without_feeling_talk("这些感受可以先放着。") == "这些感受可以先放着。"


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
@pytest.mark.parametrize("seed", [1, 4])
def test_no_sentence_about_feelings_once_asked(persona: PersonaSpectrum, seed: int) -> None:
    session = _open(seed=seed, persona=persona)
    session.turn("你能不能别一直问我心情啊，随便聊聊就行")
    for text in (
        "早上骑车去上班，路上风挺大的",
        "中午食堂新出了一道土豆烧排骨",
        "下午开了两个会，讲的都是预算的事",
        "晚上准备煮点挂面随便吃一口",
        "这周末想把阳台那几个旧纸箱清掉",
        "我表妹下个月要来我这边住几天",
    ):
        result = session.turn(text)
        if result.reply_kind is not ReplyKind.NORMAL:
            continue
        assert result.stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_HAVEN)
        if result.stage is HelpStage.S_HAVEN:
            continue
        assert FEELING_TALK.search(result.reply) is None, (text, result.reply)


# -- just listen --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "你可不可以别跟我讲大道理",
        "我不想做那些放松练习，就随便说说",
        "现在就想有个人听我讲讲",
        "不用给我安排什么呼吸练习",
    ],
)
def test_asking_to_be_heard_turns_the_listening_lock_on(text: str) -> None:
    result = _open().turn(text)
    assert result.inspect["lock"] is True


@pytest.mark.parametrize(
    "text",
    ["我今天把讲道理的那本书看完了", "明天要早起去做核酸练习册", "练习册落在公司了"],
)
def test_everyday_words_leave_the_lock_off(text: str) -> None:
    assert _open().turn(text).inspect["lock"] is False


def test_no_card_offered_after_asking_for_none() -> None:
    session = _open(seed=2)
    session.turn("最近项目压得我喘不过气，你别给我讲道理，听着就行")
    for text in (
        "每天加班到十点，回家倒头就睡",
        "领导又临时加了一个需求",
        "我真的有点烦，周末也在回消息",
        "感觉一直在被推着走",
        "算了，说出来稍微好一点",
    ):
        result = session.turn(text)
        assert result.reply_kind is not ReplyKind.CARD, (text, result.reply)


# -- a card waiting -----------------------------------------------------------------------


def _with_card(seed: int = 7) -> Session:
    session = _open(seed=seed)
    shown = session.turn("这两天睡得不好，给我一个方法")
    assert shown.reply_kind is ReplyKind.CARD
    return session


def test_a_question_about_what_to_do_leaves_the_wait() -> None:
    session = _with_card()
    result = session.turn("我同学下个月结婚，份子钱给多少合适，你有什么主意")
    assert "/done" not in result.reply
    assert result.stage is HelpStage.S_EXPLORE
    assert session.snapshot()["pending_action"] is None


def test_the_second_message_after_the_prompt_leaves_the_wait() -> None:
    session = _with_card()
    first = session.turn("好的，我晚上睡前再看看")
    assert "/done" in first.reply
    second = session.turn("说起来我妈下周要来我这儿住几天")
    assert "/done" not in second.reply
    assert second.stage is HelpStage.S_EXPLORE
    assert second.inspect["feedback"] is None
    assert session.snapshot()["pending_action"] is None


def test_words_about_the_card_still_keep_it_waiting_after_the_prompt() -> None:
    session = _with_card()
    assert "/done" in session.turn("好的，我晚上睡前再看看").reply
    assert "/done" in session.turn("这个练习第二步要做多久").reply


def test_a_rating_is_heard_as_a_rating() -> None:
    session = _with_card()
    result = session.turn("6")
    assert "换了一种语言" not in result.reply


# -- the mirror and the lines' language ----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("上周买的那双运动鞋终于到了上周买的那双运动鞋终于到了", "你上周买的那双运动鞋终于到了"),
        ("昨天晚上加班到很晚然后地铁停运了只好打车回家", "你昨天晚上加班到很晚然后地铁停运了"),
    ],
)
def test_a_long_run_is_cut_where_a_word_ends(text: str, said: str) -> None:
    assert mirror(text) == said


def test_mandarin_is_a_plain_yes_in_mainland_china() -> None:
    session = _open()
    session.turn("把求助热线的电话给我看看")
    result = session.turn("打过去能讲普通话吗")
    assert "普通话接听" in result.reply


def test_elsewhere_the_language_answer_stays_general() -> None:
    session = _open(region="HK")
    session.turn("把求助热线的电话给我看看")
    result = session.turn("打过去能讲普通话吗")
    assert "普通话接听" not in result.reply
