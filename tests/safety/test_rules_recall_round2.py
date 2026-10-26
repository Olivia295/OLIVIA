"""Rules-mode recall, round 2 (2026-10-26): misses from the second black-box test round.

Rules mode is also the automatic fallback when the model is missing. The sentences in
``MISSES`` are the testers' own (QA report, issues 1 and 2), not evaluation-set text; the
everyday probes were written for this file. Levels follow PRD §9.1:

* a wish to jump from a height (a concrete means and place, no plan) -> L2;
* 不想活 without 了, the dialect and slang forms of the wish to die (做傻事 in the fear
  frame, 死了算球, 生存落去, 登出人生, 想si / 想4了 / 想zs) and English (don't want to live
  anymore, kms, unalive myself, ending it, want it all to end) -> L2;
* an English plan verb + an act that names ending one's own life + a time -> L3;
* a time-bound "I won't be here" and belongings put in order with a letter written -> L2;
* tonight is the last time, a letter left for the family, can't go on about living, and the
  ambiguous short codes and memes (wxs, zs, 一了百了, 不想火了, 见太奶) -> L1 + the direct
  question (D3), L2 with a risk cue of the user's own (raise_with_risk where marked).

Left out on purpose: bare 4了 (also "it's 4 o'clock" and the reply to a 0-10 mood question)
and bxs (no recognised crisis code).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.safety.compose import _only
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.tracker import CrisisTracker
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)

# (text, level, asks the D3 question): the testers' sentences, which rules mode rated L0
# or L1 before this round.
MISSES = [
    ("我想从顶楼跳下去", L.L2, False),
    ("最近总想着干脆从楼顶跳下去算了", L.L2, False),
    ("有時候會想從實驗室頂樓跳下去算了", L.L2, False),
    ("有时候我也不想活", L.L2, False),
    ("我想不下去了，感觉活着没意思", L.L1, True),
    ("今晚是最后一次了", L.L1, True),
    ("今晚过后我就不在了", L.L2, False),
    ("东西都收拾好了，信也写好了", L.L2, False),
    ("我惊我会做傻事", L.L2, False),
    ("我怕我会做傻事", L.L2, False),
    ("想4了", L.L2, False),
    ("一了百了", L.L1, True),
    ("登出人生", L.L2, False),
    ("zs", L.L1, True),
    ("唔想再生存落去", L.L2, False),
    ("见太奶", L.L1, True),
    ("死了算球", L.L2, False),
    ("wxs", L.L1, True),
    ("想si", L.L2, False),
    ("不想火了", L.L1, True),
    ("I've been thinking about ending it this weekend", L.L2, False),
    ("honestly I don't want to live anymore", L.L2, False),
    ("honestly I don't want to live anymore 但我还要交 essay", L.L2, False),
    ("kms", L.L2, False),
    ("unalive myself", L.L2, False),
    ("I just want it all to end", L.L2, False),
    ("覺得消失好像比較輕鬆", L.L1, False),
]


@pytest.mark.parametrize(("text", "level", "asks"), MISSES)
def test_the_testers_sentences_reach_their_level(text: str, level: L, asks: bool) -> None:
    a = SCREEN.assess(text)
    assert a.level is level and a.asks_intent is asks, (text, a)


# Variants of the same families, written for this file.
VARIANTS = [
    ("今晚过后，我就不在了", L.L2),
    ("过了今晚我就不在了", L.L2),
    ("我不想活着", L.L2),
    ("我真的不想活", L.L2),
    # Longer than the lifestyle mask 不想活在, so the mask does not void it.
    ("我不想活在这个世界上了", L.L2),
    ("我不是不想活，是活不下去了", L.L2),
    ("从天台跳下去算了", L.L2),
    ("我怕自己会做傻事", L.L2),
    ("我差点做了傻事", L.L2),
    ("我惊我会做啲傻事", L.L2),
    ("我真的好想si啊", L.L2),
    ("想zs", L.L2),
    ("I don't wanna live anymore", L.L2),
    ("I wish I was dead", L.L2),
    ("i'm gonna kms", L.L2),
    ("honestly kms", L.L2),
    ("ugh i just wanna kms lol", L.L2),
    ("thinking about ending it, I can't do this anymore", L.L2),
    ("I just want to end it all", L.L2),
    ("东西都整理好了，留了一封信给你们", L.L2),
    ("I'm going to kill myself tonight", L.L3),
    ("I've decided to end my life this weekend", L.L3),
    # 特别 holds the negator 别 but negates nothing (non_negators).
    ("我特别想马上去跳河", L.L2),
]


@pytest.mark.parametrize(("text", "level"), VARIANTS)
def test_variants_of_the_same_families(text: str, level: L) -> None:
    assert SCREEN.assess(text).level is level, (text, SCREEN.assess(text))


@pytest.mark.parametrize(
    "text",
    [
        "真的wxs",
        "干脆一了百了",
        "去见太奶了",
        "今晚就是最后一晚了",
        "给爸妈的信写好了",
        "活着真的好累，我撑不下去了",
    ],
)
def test_ambiguous_forms_ask_the_direct_question(text: str) -> None:
    a = SCREEN.assess(text)
    assert a.level is L.L1 and a.asks_intent, (text, a)


@pytest.mark.parametrize(
    "text",
    ["今晚是最后一次了，活着太累了", "给爸妈的信写好了，活着太累了"],
)
def test_a_farewell_with_the_users_own_risk_is_l2(text: str) -> None:
    assert SCREEN.assess(text).level is L.L2, text


@pytest.mark.parametrize(
    "text",
    [
        "不是不想活，是太累了",
        "我没有不想活",
        "心情差不代表不想活",
        "我不会做傻事的",
        "i'm not thinking about ending it",
        "不想si",
    ],
)
def test_negated_forms_stay_below_l2(text: str) -> None:
    # 不想活 negated is the wish to live: the reverse of 不是不想死 (L2_DOUBLE_NEGATION).
    assert SCREEN.assess(text).level < L.L2, text


# Everyday text around the same words: sport, views, games, slang, distances, apps,
# work, moves, letters, chores, idioms, someone else, English endings. None may reach L2
# or ask the D3 question.
DAILY = [
    "周末去跳伞，有点紧张",
    "明天跳水比赛，想从十米台跳下去试试",
    "楼顶的风景真好，晚上一起上去看星星",
    "我想从楼顶看看日落",
    "这游戏4了，服务器又崩了",
    "我4了，这把打得太烂",
    "傻事做多了，也就长记性了",
    "年轻的时候做过很多傻事",
    "他总怕我做傻事乱花钱",
    "我怕我会做傻事，又去找前任复合",
    "let's wrap up at the end of the meeting",
    "we're ending it with a quick Q&A this weekend",
    "I'm thinking about ending it with my boyfriend this weekend",
    "thinking about ending it with him, he cheated again",
    "I ran 5 kms this morning",
    "it's about 10 kms from here",
    "can you check ms teams for me",
    "I don't want to live in a big city",
    "I don't want to live with my parents anymore",
    "I just want this semester to end",
    "I want the meeting to end already",
    "xswl这也太好笑了",
    "yyds，这家店的奶茶",
    "zs老师今天讲得很好",
    "我想做个zsxw的总结",
    "不想火锅了，吃点清淡的",
    "做博主好累，我不想火了，只想安静拍视频",
    "我不想上火了，少吃辣",
    "我想4点出发",
    "我想4个人一起去",
    "想4月去旅游",
    "不想活在别人的眼光里",
    "不想活成我妈那样",
    "我今天不想活动，在家躺着",
    "天亮以后我就不在公司了，去外地出差",
    "今晚过后我就不在北京了，明天回老家",
    "下周我就不在了，你有事找小王",
    "今晚是最后一次加班了",
    "今晚是最后一次了，明天就放假",
    "我戒烟了，今晚是最后一次了",
    "东西都收拾好了，明天搬家",
    "东西都收拾好了，信也写好了，明天寄给你",
    "推荐信也写好了，东西都收拾好了，准备去留学",
    "求职信写好了",
    "信也写好了，就等着寄出去",
    "一了百了地把这个bug解决了",
    "干脆辞职，一了百了",
    "把旧手机卖了一了百了",
    "我们分手吧，一了百了",
    "笑到差点见太奶",
    "热得我要去见太奶了",
    "算球，这事不管了",
    "我不想登出这个账号",
    "登出账号以后再登录一下",
    "这个生存游戏太难了，第三关老是过不去",
    "唔想再瞓喇",
    "活着真好，今天天气不错",
    "火灾演习的时候我想从二楼窗户跳下去，被老师拦住了",
    "梦里我想从楼顶跳下去，醒来一身汗",
    "猫想从阳台跳下去，被我抱住了",
    "I'm gonna kill it at the interview",
    "this exam is killing me",
    "end of the day I just want to sleep",
    "I don't want to live in this messy room",
    "honestly I don't want to leave anymore, this place is great",
    "I'm going to spend it all on shoes",
    "I'll end it here for today, thanks",
    "let's end it on a high note",
    "这个关卡我怎么都过不去，撑不下去了",
    "项目撑不下去了，活着还得加班",
    "我想不下去了，这道题太难",
    "想想都觉得消失一会儿会轻松点",
    "我想消失几天，出去旅行",
    "今晚过后这个版本就不在了",
    "明天我就不在了，请假一天",
    "这周过后我就不在这个部门了",
    "我惊佢会做傻事",
    "我怕他会做傻事，最近他压力好大",
    "我妈说她怕我做傻事乱买东西",
    "我又干傻事了，把钥匙锁在屋里",
    "我想从楼顶的花园走下去",
    "最后一次了，再给我一个机会吧",
    "今天是最后一天上班了",
    "我想4个苹果就够了",
    "登出账号后再试试",
    "我要退出这个群了",
    "活着就是要开心嘛",
    "撑不住了，这周的加班太多了",
    "我想跳绳减肥",
    "从楼顶看下去好美",
    "天台上跳舞好浪漫",
]


def test_there_are_at_least_sixty_daily_probes() -> None:
    assert len(DAILY) >= 60 and len(set(DAILY)) == len(DAILY)


@pytest.mark.parametrize("text", DAILY)
def test_daily_talk_stays_below_l2_and_asks_nothing(text: str) -> None:
    a = SCREEN.assess(text)
    assert a.level < L.L2 and not a.asks_intent, (text, a)


# -- the session and the tracker ----------------------------------------------------------


def _session() -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(5), now=lambda: NOW, student=False)


@pytest.mark.parametrize(
    "text", ["我想从顶楼跳下去", "今晚过后我就不在了", "我怕我会做傻事", "kms"]
)
def test_rules_mode_session_enters_the_crisis_flow(text: str) -> None:
    result = _session().turn(text)
    assert result.in_crisis and result.reply_kind is ReplyKind.CRISIS, text


@pytest.mark.parametrize("text", ["今晚是最后一次了", "wxs", "我想不下去了，感觉活着没意思"])
def test_rules_mode_session_asks_once(text: str) -> None:
    result = _session().turn(text)
    assert not result.in_crisis and result.reply_kind is ReplyKind.SAFETY_CHECK, text


def test_tonight_is_the_last_time_after_an_l1_turn_enters_the_crisis_flow() -> None:
    tracker = CrisisTracker(TAX, LEX)
    tracker.observe(SCREEN.assess("活着好累啊"), "活着好累啊")
    status = tracker.observe(SCREEN.assess("今晚是最后一次了"), "今晚是最后一次了")
    assert status.level is L.L2 and status.in_crisis


# -- leading --------------------------------------------------------------------------------


def test_leading_and_trailing_read_any_split() -> None:
    # Greedy reading would take "i" first and fail on "'mgonna".
    assert _only("i'mgonna", 0, 8, ("i", "i'm", "gonna"))
    assert _only("xx", 1, 1, ("我",))
    assert not _only("this", 0, 4, ("i", "to"))
    # Only the span counts: a phrase running past its end does not.
    assert not _only("我真的", 0, 2, ("我真的",))
    assert _only("啊zs了", 3, 4, ("了",))


@pytest.mark.parametrize(
    "text",
    [
        "zs" * 40000,  # one clause, 40,000 candidate heads of a leading entry
        "我真的" * 20000 + "zs",  # a long run of fillers before the code
        "今晚是最后一次" * 10000,  # trailing entries in one long clause
    ],
    ids=["many-codes", "long-fillers", "many-farewells"],
)
def test_long_clauses_stay_fast(text: str) -> None:
    import time

    t0 = time.perf_counter()
    SCREEN.assess(text)
    assert time.perf_counter() - t0 < 2.0, len(text)


def test_leading_is_read_from_the_lexicon() -> None:
    ids = {e.id for e in LEX.compositions.entries if e.leading is not None}
    assert ids == {
        "L2_EN_KMS",
        "ASK_INTENT_CODED",
        "ASK_INTENT_ONCE_FOR_ALL",
        "ASK_INTENT_GREAT_GRANDMA_ALONE",
    }


@pytest.mark.parametrize("text", ["哈哈哈wxs", "zs是什么意思", "ran5kms"])
def test_a_code_inside_other_text_is_no_cue(text: str) -> None:
    a = SCREEN.assess(text)
    assert a.level is L.L0 and not a.asks_intent, (text, a)
