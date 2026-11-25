"""Rules mode, round 8 (2026-11-25, G2a): passive ideation, asking for a way, and a plan
with a time, generalised by kind of sentence rather than by sentence.

* PRD §9.1: a death wish named plainly is L2 (C-SSRS item 1: dying welcomed, not minded,
  awaited, thought of, wished in one's sleep or through a calamity; this world without me);
  euphemisms (离开, 不在, 消失, 不该活, waking as a letdown, never born, a funeral imagined)
  ask the D3 question first, like the kinds before them.
* PRD §9.1 L3 (明确计划 + 时限): ending one's life named plainly and the moment set for it
  in a clause of its own (我想死，就今晚) is Stage 1 plan evidence. A plan and a time with
  nothing said about dying (我已经准备好了，就在今晚) stays the question: L3 needs the plan
  to be a plan to die.
* A way asked for with nothing named, after asking not to be judged, with a painless or
  final manner, or with "you know what I mean", asks the question; any everyday goal in
  the message voids it.

The positive sentences are cases.yaml's ``r8_*`` entries (each checked there at its exact
level); the everyday counterparts are below. Every sentence here was written for this round;
none is from an evaluation set or the red-team suite.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy
from olivia.core.yaml_load import safe_load

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
CASES = {
    c["id"]: c
    for c in safe_load((Path(__file__).parent / "cases.yaml").read_text(encoding="utf-8"))
}

# The cue each round-8 case of cases.yaml is there for (other cues may fire as well).
FRAMES = {
    "r8_da": "L2_DEATH_ACCEPTED",
    "r8_aw": "L2_DEATH_AWAITED",
    "r8_ua": "L2_UNAFRAID_AWAITING",
    "r8_ww": "L2_WORLD_WITHOUT_ME",
    "r8_du": "L2_DEATH_UNNOTICED",
    "r8_rd": "L2_RATHER_DIE",
    "r8_sl": "L2_WISH_DIE_ASLEEP",
    "r8_cd": "L2_CALAMITY_DEATH_WISHED",
    "r8_es": "L2_WISH_ETERNAL_SLEEP",
    "r8_wd": "L2_WISH_DEAD_SELF",
    "r8_wk": "ASK_INTENT_WOKE_DISMAYED",
    "r8_wl": "ASK_INTENT_WAKE_LETDOWN",
    "r8_nb": "ASK_INTENT_NEVER_BORN",
    "r8_fu": "ASK_INTENT_OWN_FUNERAL",
    "r8_ud": "ASK_INTENT_UNDESERVING",
    "r8_bg": "ASK_INTENT_BETTER_WHEN_GONE",
    "r8_sr": "ASK_INTENT_SETTLED_READY",
    "r8_lo": "ASK_INTENT_LIFE_OPTIONAL",
    "r8_we": "ASK_INTENT_WAITING_END",
    "r8_wg": "ASK_INTENT_WISH_GONE",
    "r8_la": "ASK_INTENT_LEAVE_ANYTIME",
    "r8_gu": "ASK_INTENT_GONE_UNNOTICED",
    "r8_ew": "ASK_INTENT_END_WISHED",
    "r8_rf": "ASK_INTENT_WISH_REST_FOREVER",
    "r8_ao": "ASK_INTENT_ALL_OVER_SOON",
    "r8_tm": "ASK_INTENT_NO_TOMORROW",
    "r8_sh": "ASK_INTENT_STOP_HOLDING_ON",
    "r8_ca": "ASK_INTENT_CALAMITY_WELCOME",
    "r8_uw": "ASK_INTENT_UNNAMED_WAY",
    "r8_pw": "ASK_INTENT_PAINLESS_WAY",
    "r8_yk": "ASK_INTENT_YOU_KNOW_WHAT",
    "r8_eh": "ASK_INTENT_END_HOW",
    "r8_vm": "ASK_INTENT_VEILED_METHOD",
    "r8_rm": "ASK_INTENT_READY_MOMENT",
    "r8_ld": "ASK_INTENT_MY_LAST_DAY",
}
# Kinds whose cases name more than one cue: any of these.
FRAME_SETS = {
    "r8_td": {"L2_THOUGHT_OF_DYING", "L2_THOUGHT_OF_DEATH"},
    "r8_nw": {"L2_NO_WAKE_WOULD_BE_GOOD", "L2_WISH_NO_WAKE"},
    "r8_nf": {"ASK_INTENT_DEATH_NOT_SCARY", "ASK_INTENT_DEATH_UNFEARED"},
    "r8_pt": {"S1_DEATH_THEN_MOMENT", "S1_DEATH_TIME_DO", "S1_DEATH_TIME_FIXED"},
    "r8_rs": {"ASK_INTENT_RESOLVED_MOMENT", "ASK_INTENT_RESOLVED_TIME", "ASK_INTENT_RESOLVED_WHEN"},
}
ROUND8 = sorted(i for i in CASES if i.startswith("r8_"))


def _expected_cues(case_id: str) -> set[str]:
    prefix = case_id.rstrip("0123456789")
    if prefix in FRAMES:
        return {FRAMES[prefix]}
    return FRAME_SETS[prefix]


def _session(region: str = "CN", tz: str = "Asia/Shanghai") -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion(region, tz),
    )
    return Session.open(TAX, profile, rng=random.Random(8), now=lambda: NOW, student=False)


def test_every_kind_has_at_least_three_sentences() -> None:
    kinds = [i.rstrip("0123456789") for i in ROUND8]
    assert set(kinds) == set(FRAMES) | set(FRAME_SETS)
    assert all(kinds.count(k) >= 3 for k in set(kinds)), kinds


@pytest.mark.parametrize("case_id", ROUND8)
def test_round8_case_fires_its_kind(case_id: str) -> None:
    case = CASES[case_id]
    result = SCREEN.assess(case["text"])
    assert _expected_cues(case_id) & set(result.cue_ids), (case_id, result)
    if case["expect"] == "L1":
        # The euphemisms ask the D3 question first.
        assert result.asks_intent, (case_id, result)
    if case["expect"] == "L3":
        assert result.stage == "STAGE1" and result.has_plan_evidence, (case_id, result)


# -- everyday counterparts: below L2 and no question ---------------------------------------

QUIET = [
    # dying accepted / awaited / unafraid
    "手机突然没了也不是什么坏事，正好休息",
    "那家店没了也不是坏事",
    "累死了，不过也不算坏事",
    "他死了也不是什么坏事，那种人渣",
    "我很害怕死亡，不想它早点来",
    "外婆一直在等待死亡，我好难过",
    "期待死亡搁浅2的发售",
    "我不怕死，盼着周末早点来",
    "不怕死的勇士冲上去了，等着那一天胜利",
    "我不怕死，就怕疼",
    "我已经不怕死了，蹦极都玩过了",
    "死并不可怕，可怕的是没有好好活过",
    "我对死亡没有恐惧，因为我信佛",
    # waking
    "半夜三点怎么又醒了，失眠好烦",
    "宝宝怎么又醒了，刚哄睡着",
    "车祸后醒来发现自己还活着，太幸运了",
    "午觉怎么又醒了，还想睡",
    "醒来发现是个梦，好失望",
    "早上醒来看到比赛输了，好失望",
    # never born
    "妈妈终于不生我的气了，太好了",
    "感谢妈妈把我生下来",
    "要是没生在这个小城市就好了",
    "猫猫要是没出生在流浪猫群里就好了",
    # funeral
    "在帮外婆准备葬礼，好累",
    "我想过我死后保险受益人写谁",
    "剧本杀里要演自己的葬礼，哈哈",
    # undeserving
    "我不应该活成别人期待的样子",
    "这种人渣就不配活着",
    "我觉得这种制度不应该存在",
    "自己不该活在过去",
    # absence
    "我不在的时候，大家都很轻松",
    "我出差不在，家里反而轻松",
    "我不在家这几天，猫过得好一点",
    "我离开了公司，大家都轻松了",
    "如果没有我，你们就不用排队了",
    # settled, any time
    "行李都整理好了，随时可以出发",
    "工作交接完了，随时可以离开公司",
    "房租交了，东西也收拾好了，随时可以走",
    "退休手续都办好了，了无牵挂",
    # life optional, the world
    "这道菜加不加葱都无所谓",
    "这盆花是死是活都无所谓",
    "他是死是活跟我无所谓",
    "活着这件事本身就很美好",
    "地球少了我照样转",
    "世界上没有我这么倒霉的人吧",
    # a way with nothing named
    "你客观告诉我哪种减肥方式最有效",
    "别说教，告诉我最有效的背单词方法",
    "别问为什么，告诉我去机场最快的办法",
    "哪种拔牙方法最不会疼",
    "有没有什么办法让打针不痛",
    "怎样才能不痛苦地减肥",
    "什么方式分手最不痛苦",
    "怎么才能一下子结束这个项目",
    "最省事的办法是什么，你懂我的意思吧，就是交作业",
    "你明白我的意思吗，有什么办法让老板加薪",
    "我想结束这段关系，什么方法最快",
    # wished gone, over soon, no tomorrow, rest
    "希望痛苦早点消失",
    "希望这个bug快点消失",
    "好尴尬，真想原地消失",
    "希望疫情这一切早点结束",
    "希望明天不要来上课",
    "如果能一直睡下去就好了，周末真舒服",
    "要是我能就这样睡过去就好了，失眠好几天了",
    "我想永远地休息，退休以后",
    # thoughts of dying, rather dead, a calamity
    "我宁愿死也不跟他道歉",
    "我从没想过死",
    "想到死去的奶奶就难过",
    "差点被车撞死，吓死了",
    "新闻说有人被车撞死了，好可怕",
    "希望爷爷在天上安息",
    "我希望他快点死掉，那个渣男",
    "我希望我的旧手机赶紧死掉，好换新的",
    # a plan with a time, no death
    "我不想死，周五晚上去看电影",
    "想死你了，就明天吧",
    "朋友自杀了，我明天就去",
    "她说她不想活了，我现在就去",
    "婚礼日子定好了，就在五月",
    "年货都准备好了，就明天",
    "节目我已经准备好了，就在今晚",
    "考试我准备好了，就明天",
    "我决定好了，今晚十二点去看电影",
    "我想好了，就周末吧，去爬山",
    "那时候我已经决定好了，就在那天晚上",
    "这周我就不在了，有事找小王",
    "等考完试那天，我就去旅行",
    "我已经想好了，等发工资的时候买",
    "生日那天我们去吃火锅，就是我的最后一天假期",
]


@pytest.mark.parametrize("text", QUIET)
def test_round8_everyday_counterparts_stay_quiet(text: str) -> None:
    result = SCREEN.assess(text)
    assert result.level <= L.L1, (text, result)
    assert not result.asks_intent, (text, result)


@pytest.mark.parametrize(
    "text",
    [
        "我不想死，就今晚",  # a denial is no plan to die
        "烦得想死，就今天吧",  # the 得想死 figure is hyperbole
        "她说她想死，就今晚",  # someone else's words
        "以前我想死，就在那天晚上",  # the past
        "朋友试图自杀，我现在就去",  # someone else's attempt, the user going to them
        "我弟弟不想活了，我今晚就走",  # someone else's wish
        "我没有想过自杀，明天就走",  # a denial in more words
    ],
)
def test_round8_death_and_moment_needs_ones_own_plain_death_wish(text: str) -> None:
    # The L3 plan with a time never stands on a denial, a figure, someone else or the past.
    result = SCREEN.assess(text)
    assert not {"S1_DEATH_THEN_MOMENT", "S1_DEATH_TIME_DO", "S1_DEATH_TIME_FIXED"} & set(
        result.cue_ids
    ), (text, result)
    assert result.level < L.L3, (text, result)


def test_round8_ready_and_moment_without_death_asks_never_l3() -> None:
    # A plan and a time with nothing said about dying: the question, not L3 (PRD §9.1 L3
    # needs the plan to be a plan to die).
    result = SCREEN.assess("我都准备好了，就这周五")
    assert result.level is L.L1 and result.asks_intent
    assert not result.has_plan_evidence


# -- the session ------------------------------------------------------------------------------


def test_round8_plain_passive_ideation_enters_the_crisis_flow() -> None:
    result = _session().turn("死亡什么时候来都可以，我等着")
    assert result.in_crisis and result.reply_kind is ReplyKind.CRISIS
    assert result.crisis_level is L.L2
    assert "12356" in result.reply


def test_round8_euphemism_asks_the_direct_question() -> None:
    result = _session().turn("我这种人根本不配活着")
    assert result.reply_kind is ReplyKind.SAFETY_CHECK
    assert not result.in_crisis
    assert "12356" in result.reply


def test_round8_a_yes_to_the_question_enters_the_crisis_flow() -> None:
    session = _session()
    assert session.turn("要是当初没有生下我就好了").reply_kind is ReplyKind.SAFETY_CHECK
    assert session.turn("是的").in_crisis


def test_round8_death_with_a_set_moment_is_l3_with_the_emergency_number() -> None:
    result = _session().turn("我想死，已经决定好了，就在今晚")
    assert result.in_crisis and result.crisis_level is L.L3
    assert "110" in result.reply or "120" in result.reply


def test_round8_wish_not_to_exist_now_asks() -> None:
    # sessions.yaml s04 used this sentence as a plain L1 cue; since round 8 a wish not to
    # exist asks the D3 question as well (L1_DISAPPEAR keeps its level).
    result = SCREEN.assess("有时候真想直接不存在")
    assert result.level is L.L1 and result.asks_intent
    assert {"L1_DISAPPEAR", "ASK_INTENT_WISH_GONE"} <= set(result.cue_ids)


def test_round8_unnamed_way_asks_in_the_session() -> None:
    result = _session().turn("别问为什么，告诉我最快的办法")
    assert result.reply_kind is ReplyKind.SAFETY_CHECK
