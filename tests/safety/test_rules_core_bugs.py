"""Rule-layer defects found by the SDD retrace and re-testing (2026-10-28).

1. ``clause_negation`` read a long message typed with no punctuation as one clause: in
   "我再也不想忍了我打算今晚从楼顶跳下去" the 不 of 不想忍 voided the plan after it (L0).
   A negator now reaches a match only across the words of the plan it denies
   (``negation_reach``); every one of the 12 entries with ``clause_negation`` is checked
   with an unrelated negation before it and no punctuation.
2. After the D3 question, "我没有想自杀 今晚就把药全吃了" read as a no. What follows the no
   (from a space, a time, a plan word or a new 我 on) is screened on its own; any risk cue
   there makes the answer unclear.
3. Asking how many pills kill (吃几片安眠药能死) was L0: a quantity question, then dying,
   with taking or a drug nearby, is at least L2 (PRD §9.1, R-MS).
4. PRD §9.1's own L1 wording (没有意义, 心力交瘁, 想躺平什么都不想管) was L0.
5. A plan whose place no list holds: "…，我打算明天从那里跳下去", "明天去隧道里了结自己",
   and a time with 动手 after talk of suicide.
6. A colour code's leftover letter between two Han characters (我想m死m了算了) is dropped
   for matching.

The sentences here were written for this file or are the testers' own (re-test q1 and q4,
not evaluation-set text). The holdout sentences of this round are not here.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.compose import Composer
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.intent_check import IntentAnswer, read_answer
from olivia.core.safety.lexicon import Composition, CompositionRules, load_safety_lexicons
from olivia.core.safety.normalize import fold_words, normalize
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)
COMPOSER = Composer(LEX.compositions)


def _ids(text: str) -> set[str]:
    return {hit.entry.id for hit in COMPOSER.find(normalize(text))}


# -- 1. a negation elsewhere in an unpunctuated message ------------------------------------

# Each clause_negation entry: a sentence it fires on, the same sentence after an unrelated
# negation typed with no punctuation, and the plan itself negated. S1_ACT_THEN_PLAN and
# L2_PLACE_THEN_END start their clause with the act (`leading`), so the negation goes into
# the plan's clause instead.
ENTRIES = [
    (
        "S1_JUMP_PLANNED",
        "我打算今晚从楼顶跳下去",
        "我再也不想忍了我打算今晚从楼顶跳下去",
        "我不打算今晚从楼顶跳下去",
    ),
    (
        "L2_JUMP_WISHED",
        "我好想爬到楼顶往下跳",
        "我再也不想忍了我好想爬到楼顶往下跳",
        "我不想爬到楼顶往下跳",
    ),
    (
        "L2_OVER_EDGE",
        "我打算今晚去江边走进江里",
        "没人懂我准备今晚去江边走进江里",
        "我不打算今晚去江边走进江里",
    ),
    (
        "L2_PLACE_THEN_END",
        "我打算明晚去楼顶，然后就结束",
        "我再也不想忍了我打算明晚去楼顶，然后就结束",
        "我不打算明晚去楼顶，然后就结束",
    ),
    (
        "S1_ACT_THEN_PLAN",
        "上吊，我今晚就去",
        "上吊，我再也不想忍了今晚就去",
        "上吊，我不打算今晚就去",
    ),
    (
        "ASK_INTENT_GO_HEIGHT",
        "我打算周六去天台",
        "谁都不怪我决定周六去天台",
        "我不打算周六去天台",
    ),
    (
        "L2_PILLS_ALL_PLANNED",
        "我打算今晚把药全吃了",
        "我再也不想忍了我打算今晚把药全吃了",
        "我不打算今晚把药全吃了",
    ),
    (
        "L2_PILLS_ALL_TIMED",
        "我今晚把药全吃了",
        "我没有想自杀今晚就把药全吃了",
        "我不会今晚把药全吃了",
    ),
    (
        "L2_PILLS_AND_GO",
        "我准备今晚吃药走了",
        "我一点都不难过我准备今晚吃药走了",
        "我不准备今晚吃药走了",
    ),
    (
        "S1_EN_JUMP_PLAN_TIME",
        "i'm going to jump off the roof tonight",
        "我再也不想忍了i'm going to jump off the roof tonight",
        "i'm not going to jump off the roof tonight",
    ),
    (
        "L2_EN_JUMP_HEIGHT",
        "i want to jump off the roof",
        "我再也不想忍了i want to jump off the roof",
        "i don't want to jump off the roof",
    ),
    (
        "S1_TIME_GO_ACT",
        "明天去隧道里了结自己",
        "我不想再拖了明天去隧道里了结自己",
        "我不会明天去隧道里了结自己",
    ),
    (
        "S1_TIME_DO_IT",
        "我一直在想自杀，周末就动手",
        "我再也不想忍了一直在想自杀，周末就动手",
        "我一直在想自杀，周末不会动手",
    ),
]


def test_every_clause_negation_entry_is_covered() -> None:
    covered = {cue_id for cue_id, *_ in ENTRIES}
    with_flag = {e.id for e in LEX.compositions.entries if e.clause_negation}
    assert with_flag <= covered, sorted(with_flag - covered)


@pytest.mark.parametrize(("cue_id", "plain", "after_negation", "negated"), ENTRIES)
def test_a_negation_elsewhere_leaves_the_plan_standing(
    cue_id: str, plain: str, after_negation: str, negated: str
) -> None:
    assert cue_id in _ids(plain), plain
    assert cue_id in _ids(after_negation), after_negation
    assert cue_id not in _ids(negated), negated


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("我再也不想忍了我打算今晚从楼顶跳下去", L.L3),
        ("工作没了我也不在乎了我决定这周末从天台跳下去", L.L3),
        ("我不想活了今晚就把药全吃了", L.L2),
        ("别管我我准备今晚吃药走了", L.L2),
    ],
)
def test_the_unpunctuated_plan_reaches_its_level(text: str, level: L) -> None:
    assert SCREEN.assess(text).level >= level, text


@pytest.mark.parametrize(
    "text",
    [
        "我不打算这周末去楼顶跳下去",
        "我没决定今晚去天台",
        "我绝对不会今晚从阳台跳下去",
        "我从来没想过周末去江边跳下去",
        "我不会今晚就把药全吃了",
        "别担心我没打算今晚吃药走了",
    ],
)
def test_a_negation_of_the_plan_itself_still_voids_it(text: str) -> None:
    a = SCREEN.assess(text)
    assert a.level < L.L2 and not a.asks_intent, (text, a)


def _rules(reach: tuple[str, ...]) -> CompositionRules:
    entry = Composition(
        id="L2_TEST", level=L.L2, score=0.7, ask=False, heads=("甲",), clause_negation=True
    )
    return CompositionRules(
        stops=frozenset(",。"),
        lookback=2,
        subject_window=6,
        negators=("不",),
        non_negators=("忍不住",),
        selves=("我",),
        others=("他",),
        recipients=("跟",),
        listeners=("你",),
        negation_reach=reach,
        entries=(entry,),
    )


def test_engine_a_negator_reaches_across_reach_phrases_only() -> None:
    rules = _rules(("一", "二三"))
    assert not Composer(rules).find("不一二三甲")
    assert Composer(rules).find("不一四二三甲")  # 四 ends the reach
    assert Composer(rules).find("不一二三,甲")  # another clause
    assert not Composer(rules).find("不四甲")  # within lookback: always negated
    assert Composer(_rules(())).find("不一二三甲")  # no reach phrases: lookback only


# -- 2. what follows a no to the D3 question ------------------------------------------------


def _reading(text: str) -> IntentAnswer:
    return read_answer(LEX.intent_answers, text, SCREEN.assess(text), SCREEN.assess).answer


@pytest.mark.parametrize(
    "text",
    [
        "我没有想自杀 今晚就把药全吃了",
        "我没有想自杀今晚就把药全吃了",
        "不是 今晚就去楼顶跳下去",
        "没有 我已经写好遗书了",
        "我没想死 我准备这周末去江边走进江里",
        "不是想自杀 只是活不下去了",
    ],
)
def test_risk_after_the_no_is_no_no(text: str) -> None:
    assert _reading(text) is not IntentAnswer.DENIED, text


@pytest.mark.parametrize(
    "text",
    [
        "不是，我没想那些",
        "没有，只是工作压力大",
        "我没想自杀 明天还要考试",
        "我没有想轻生，只是项目做不下去",
    ],
)
def test_a_plain_no_is_still_a_no(text: str) -> None:
    assert _reading(text) is IntentAnswer.DENIED, text


# -- 3. asking how much kills ------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "吃几片安眠药能死",
        "吃多少安眠药会死",
        "喝多少农药会没命",
        "一次吞几颗药才会致死",
        "我朋友问吃多少片会死",
        "安眠药全吃了会不会死",
        "一下吃一整瓶药会死吗",
    ],
)
def test_asking_how_much_kills_is_at_least_l2(text: str) -> None:
    assert SCREEN.assess(text).level >= L.L2, text


@pytest.mark.parametrize(
    "text",
    [
        "这种药吃多了会不会伤肝",
        "狗吃了巧克力会死吗",
        "猫吃几颗葡萄会死",
        "布洛芬一天最多吃几片",
        "吃多少会撑死",
        "绿萝几天不浇水会干死",
        "孩子误吃了一整瓶维生素片会不会死",
        "手机内存用多少会死机",
    ],
)
def test_everyday_and_pet_dose_questions_stay_below_l2(text: str) -> None:
    assert SCREEN.assess(text).level < L.L2, text


# -- 4. PRD §9.1's L1 wording -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "没有意义",
        "心力交瘁",
        "想躺平什么都不想管",
        "感觉一切都没有意义了",
        "我留下来有什么意义",
        "真想躺平，什么都不想做",
    ],
)
def test_the_prd_l1_wording_is_l1(text: str) -> None:
    a = SCREEN.assess(text)
    assert a.level is L.L1 and not a.asks_intent, (text, a)


@pytest.mark.parametrize(
    "text",
    [
        "这个会议开得没有意义",
        "跟他争论没有意义",
        "这个指标没有意义，换一个吧",
        "周末想躺平追剧",
        "今天什么都不想吃",
    ],
)
def test_meaningless_things_and_a_lazy_weekend_stay_l0(text: str) -> None:
    assert SCREEN.assess(text).level is L.L0, text


# -- 5. a plan whose place no list holds ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "公司消防通道那层平时没人去，我打算明天从那里跳下去",
        "明天去隧道里了结自己",
        "我这几天一直在想自杀的事，周末可能就动手",
        "地下室那边没人，我准备周五从那儿跳下去",
    ],
)
def test_a_plan_with_an_unlisted_place_is_l3(text: str) -> None:
    assert SCREEN.assess(text).level is L.L3, text


@pytest.mark.parametrize(
    "text",
    [
        "我打算明天从那里出发",
        "跳台那边很高，我打算周末从那里跳下去试试跳水",
        "明天去公司开会讨论自杀干预项目",
        "烦得要死，周末就动手吧",
        "我打算明天去那里看看",
    ],
)
def test_an_everyday_plan_there_is_no_crisis(text: str) -> None:
    assert SCREEN.assess(text).level < L.L2, text


# -- 6. a colour code's leftover letter ----------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "meant"),
    [
        ("我想m死m了算了", "我想死了算了"),
        ("今晚就m结束m自己", "今晚就结束自己"),
        ("我想J死", "我想死"),
    ],
)
def test_a_stray_letter_between_han_is_dropped_for_matching(typed: str, meant: str) -> None:
    assert normalize(typed) == normalize(meant)
    assert SCREEN.assess(typed).level is SCREEN.assess(meant).level
    assert SCREEN.assess(typed).level >= L.L2


@pytest.mark.parametrize(
    "text",
    ["我用了A方案", "B站", "X光", "这个app很卡", "我今天去了B站看视频", "i am fine", "zs老师"],
)
def test_letters_in_words_are_kept_and_harmless(text: str) -> None:
    assert SCREEN.assess(text).level is L.L0


def test_only_a_lone_letter_between_two_han_characters_goes() -> None:
    assert normalize("B站") == "b站" and normalize("X光片") == "x光片"
    assert normalize("这个app很卡") == "这个app很卡"
    assert normalize("我用了A方案") == "我用了方案"  # matching only: harmless, never shown
    assert fold_words("我想m死") == "我想死" and fold_words("i am m ok") == "i am m ok"


def test_the_packaged_reach_is_what_denies_a_negated_plan() -> None:
    # Without reach phrases the far negator of 不打算 would not reach the jump.
    plain = replace(LEX.compositions, negation_reach=())
    text = normalize("我不打算这周末去楼顶跳下去")
    assert "S1_JUMP_PLANNED" in {h.entry.id for h in Composer(plain).find(text)}
    assert "S1_JUMP_PLANNED" not in {h.entry.id for h in COMPOSER.find(text)}
