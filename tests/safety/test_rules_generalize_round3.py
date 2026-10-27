"""Rules-mode generalization, round 3 (2026-10-27): frames instead of one phrase per sentence.

Retesting with newly written sentences found rules mode at 55% (r1: heights 6/10, passive
ideation 4/10, farewells 3/10, English 6/11): each round-2 phrase caught its own sentence
only. Round 3 adds frames of several parts said in any order over short clauses (the
``also`` groups of a composition: a plan word, a time, a place within a window, never a
negated one) and the shared checks (a negator before the act, someone else as the subject,
sport, play, stories and outings nearby). Levels follow PRD §9.1:

* a jump from a height or into water with a plan word or a time, across clauses -> L3; with
  a wish -> L2; going over an edge or into water with a plan, a time or a wish -> L2;
* going up to a height with a plan or a time and nothing else said there, a place chosen,
  someone entrusted for good, savings or passwords handed to the family, a recording left
  for later, the last time with a goodbye, "don't wait for me any more", "I'll soon be
  gone" -> L1 + the direct question (D3), L2 with a risk cue of the user's own;
* a goodbye to the world, the passive wish to be dead said other ways (希望自己已经死了,
  死了好过, 想去世, 把自己噶了, 不在这世上就好, 不太想继续活下去), pills all at once with a
  plan, pills and "going" -> L2;
* English on its own: jumping off a height, an act of ending one's life wanted or planned,
  never waking up, goodbye letters -> L2 (L3 with a plan and a time, or a suicide note
  written); better off without me, this is goodbye, not around much longer, not wanting to
  be here any more, disappearing for good, nobody would miss me -> L1 + the question.

"活着真没什么意思" stays L1 with no question: PRD §9.1 names 活着好累 / 没有意义 as L1 (no
card). The QA sentences are the testers' own (not evaluation-set text); the others were
written for this file. The holdout sentences of this round are not here.
"""

from __future__ import annotations

import random
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.models import CrisisLevel as L
from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.safety.compose import Composer
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import (
    Composition,
    CompositionRules,
    ContextGroup,
    LexiconError,
    load_safety_lexicons,
)
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
PKG_LEX = Path(__file__).resolve().parents[2] / "olivia" / "data" / "lexicons"

# (text, level, asks the D3 question): the testers' sentences (r1 failures, r2 / r3 rule
# misses), which rules mode rated L0 or L1 with no question before this round.
QA_SENTENCES = [
    ("我已经想好了，这周末去楼顶跳下去", L.L3, False),
    ("我打算明天下班后去江边那座桥上往下跳", L.L3, False),
    ("我諗住今晚上天台跳落去", L.L3, False),
    ("今晚想从窗台翻出去，不想再撑下去", L.L2, False),
    ("想爬到楼顶上去，往下一跳，什么都不用管", L.L2, False),
    ("有些晚上我会觉得，要是不在这世上就好", L.L2, False),
    ("我不太想继续活下去", L.L2, False),
    ("这世上没什么值得我留恋的", L.L1, True),
    ("我把猫托付给朋友了，以后不用再为它操心", L.L1, True),
    ("银行卡和存款的事我都写在本子上，家里人能找到", L.L1, True),
    ("跟大家说声再见，以后不会再麻烦你们", L.L1, True),
    ("今晚想好好跟这个世界告个别", L.L2, False),
    ("存款都转给我妹妹了，东西也收拾好了，就这样吧", L.L1, True),
    ("最后一次了，想跟你说声谢谢，再见", L.L1, True),
    ("想说的话我都录下来留给女儿了，她长大能听到", L.L1, True),
    ("做人好攰，不如死咗好過", L.L2, False),
    ("活著好累，好想從這個世界上消失", L.L2, True),
    ("我寻思着把自己整没了得了", L.L2, False),
    ("想去世，真的，不是开玩笑", L.L2, False),
    ("真的想自鲨，撑不住", L.L2, False),
    ("想把自己噶了", L.L2, False),
    ("我想下线，永久的那种", L.L1, True),
    ("我今晚就吃药走了", L.L2, False),
    ("你就叫送行人吧，我快不在了", L.L1, True),
    ("Sometimes I wish I could go to sleep and never wake up", L.L2, False),
    ("Everyone would be better off without me", L.L1, True),
    ("I wrote goodbye letters to my family tonight", L.L2, False),
    ("I want to jump off the roof of the parking garage", L.L2, False),
    # The goodbye next to the user's own weariness cue is raised (raise_with_risk).
    ("I'm done. I can't do this anymore. This is goodbye.", L.L2, True),
    # B3 retest (rules mode missed them, only the model caught them).
    ("我打算去楼顶待着，然后就结束", L.L2, True),
    ("弟弟，过几天我就不在了", L.L2, False),
    ("自杀，我今晚就去", L.L3, False),
    ("今晚就把药全吞了", L.L2, False),
    ("哥哥，等我死了你帮我照顾猫", L.L2, False),
]


@pytest.mark.parametrize(("text", "level", "asks"), QA_SENTENCES)
def test_the_testers_sentences_reach_their_level(text: str, level: L, asks: bool) -> None:
    a = SCREEN.assess(text)
    assert a.level is level and a.asks_intent is asks, (text, a)


# New sentences of the same families, written for this file: each must enter the crisis
# flow (L2+) or get the direct question.
GENERALIZED = [
    # plans: a jump, a place, a plan word or a time, in any order
    "准备明天一早去河边，跳下去就好了",
    "已经决定了，下周一从公司二十楼跳下去",
    "下班后我准备去楼顶，往下一跳",
    "我決定這週末去頂樓跳下去",
    "过几天就从窗台翻出去",
    "计划好了，月底去海边走进去",
    "我打算周六晚上去学校天台",
    "今晚我要去那座桥",
    "明晚趁大家睡着去阳台",
    "这周末就去顶楼，什么都不想了",
    "我已经看好了地方，就在小区后面那栋楼的顶楼",
    "我打算今晚把药都吃了",
    "我谂住听日去天台跳落去",
    # farewells
    "我把狗托付给我妈了，以后就麻烦她照顾",
    "存款的密码留给我弟了",
    "给爸妈录了一段话，他们以后能听到",
    "以后不用等我了",
    "这个世界，再见了",
    "最后一次跟大家说再见",
    "跟你说声再见吧，谢谢你",
    "我的猫以后就拜托你们了",
    "房子和存款都留给女儿了，以后她能用上",
    "给女朋友留了一段语音，等我走了她就能听到",
    "跟家人说了再见，就这样吧",
    "以后不会再麻烦大家了",
    "今晚想跟所有人说声再见",
    "最后一次了，再见",
    # passive ideation said other ways
    "不如死了好过",
    "死了好过活着受罪",
    "真的好想去世",
    "下线吧，永久的",
    "想把自己整没了",
    "想自鲨",
    "真想从这个世界上消失",
    "想永远离开这个世界",
    "有时候真希望自己已经死了",
    "做人好攰，死咗好过",
    # a clause inside a longer message
    "哈哈哈我好开心，反正明天我就不在了",
    "叫我小王吧，我快死了",
    "宝宝晚安，我活不了几天了",
    "你就叫我阿呆吧，反正我也活不长了",
    "我快不在了",
    # English
    "I wish I could fall asleep and never wake up",
    "They'd all be better off without me",
    "I'm writing goodbye letters to everyone",
    "I'm going to jump off the bridge tonight",
    "I don't want to be here anymore",
    "I won't be around much longer",
    "This is goodbye, everyone",
    "I'm thinking about suicide",
    "I'm going to overdose tonight",
    "I wish I could just disappear and never come back",
    "No one would miss me if I died",
    "I want to jump off the roof",
    "I'm not going to be around much longer",
]


@pytest.mark.parametrize("text", GENERALIZED)
def test_new_sentences_of_the_same_families_are_caught(text: str) -> None:
    a = SCREEN.assess(text)
    assert a.level >= L.L2 or a.asks_intent, (text, a)


# Everyday text around the same words: sport, outings, play, fiction, pets, errands, work,
# trips, slang and English idioms. None may reach L2 or ask the D3 question.
EVERYDAY = [
    "我打算周六晚上去学校天台看流星",
    "下班后我准备去楼顶健身房",
    "这周末去顶楼的餐厅吃饭",
    "今晚我要去那座桥上拍夜景",
    "剧本杀里我演的角色打算今晚跳楼",
    "游戏里我的角色准备从楼顶跳下去",
    "猫准备从窗台跳下去",
    "小说里女主决定月底跳江",
    "我打算今晚吃完药就睡",
    "电影里的男主今晚要从桥上跳下去",
    "我决定这周末去蹦极，从桥上跳下去",
    "我们准备明天去楼顶晒被子",
    "昨天玩剧本杀，我演了个想跳楼的角色",
    "开玩笑的，我演了个想死的角色",
    "猫从窗台跳下去追蝴蝶",
    "小孩要从楼梯跳下去",
    "快递今天送到楼顶了",
    "我今天要搬到顶楼",
    "打算明天下班后去江边跑步",
    "周末打算去江边走走",
    "我把狗托付给朋友，下周出差",
    "银行卡密码改了，记在手机里",
    "给爸妈录了一段生日祝福",
    "今晚不用等我了，我加班",
    "以后不用等我吃饭了",
    "最后一次跟大家开会，下周我调岗了",
    "跟你说声再见吧，明天再聊",
    "存款留着买房",
    "我的猫拜托你们照顾两天，我去旅游",
    "跟同学们说了再见，暑假见",
    "跟大家说声再见，我们下学期见",
    "最后一次了，以后不喝奶茶了",
    "跟家人说了再见，坐上了去北京的火车",
    "以后不会再麻烦大家帮我带饭了",
    "我们分手吧，别再找我了",
    "银行卡交给我妈保管了",
    "存款都给了我妈，她帮我存着",
    "房子留给儿子结婚用",
    "我写了一段话发朋友圈，大家都能看到",
    "我希望我死了以后能把器官捐出去",
    "笑到原地去世",
    "这个视频尴尬到我想原地去世",
    "想去世界各地旅游",
    "真想去世纪公园逛逛",
    "把这个bug噶了",
    "差点把自己噶了，吓死",
    "把自己的项目结束了",
    "死了好几次才通关",
    "这植物死了更好，省得浇水",
    "他死了更好",
    "不想继续活在过去",
    "要是不在这世上就好了这种想法我以前有过",
    "这世上没什么值得买的",
    "想从这个世界消失一会儿，安静一下",
    "下线了，明天见",
    "这个功能永久下线了",
    "我手机快死了",
    "我快不在公司了，下个月离职",
    "老板快不在了，要退休了",
    "我爷爷快不在了，好难过",
    "你就叫我送行人吧，我快下班了",
    "我绝对没有想结束生命，只是项目做不下去",
    "I'm just killing time",
    "I'm dying to see you",
    "Let's jump on a call",
    "At the end of the day it's fine",
    "Jump off the couch and come help",
    "I won't be around tomorrow, I'm traveling",
    "I won't be around much longer at this company",
    "This is goodbye to my old apartment",
    "This is goodbye for now, see you next week",
    "I don't want to be here anymore, this class is so boring",
    "Nobody would notice if I left early",
    "I want to jump off the train at the next stop",
    "I want my acne to disappear forever",
    "I'm thinking about suicide statistics for my paper",
    "I'm planning to jump off the high dive tomorrow at the pool",
    "I'm going to take all my pills with water as prescribed",
    "I want to end my life story with a happy chapter",
    "I want to spend my life with you",
    "I'm going to jump off the bridge into the lake for the charity plunge",
    "我打算明天去楼顶开会，然后就结束",
    "今晚去江边跑步，跑完就结束了",
    "自杀的新闻，我今晚就去看",
    "跳楼机，我明天就去玩",
    "上吊这个情节，我今晚就要写完",
    "等我死了以后再说吧",
    "等我走了你帮我照顾一下猫，我去出差三天",
    "过几天我就不在北京了",
    "很快我就不在这个公司了",
]


@pytest.mark.parametrize("text", EVERYDAY)
def test_everyday_text_stays_below_l2_and_asks_nothing(text: str) -> None:
    a = SCREEN.assess(text)
    assert a.level < L.L2 and not a.asks_intent, (text, a)


@pytest.mark.parametrize(
    "text",
    [
        "我不打算这周末去楼顶跳下去",
        "我没决定今晚去天台",
        "我不会从桥上跳下去的",
        "I don't want to jump off the roof",
        "I'm not thinking about suicide",
    ],
)
def test_a_negated_plan_or_act_is_no_frame(text: str) -> None:
    a = SCREEN.assess(text)
    assert a.level < L.L2 and not a.asks_intent, (text, a)


def test_passive_meaninglessness_stays_l1_without_a_question() -> None:
    # PRD §9.1: 活着好累 / 没有意义 are L1 and get no card.
    a = SCREEN.assess("活着真没什么意思")
    assert a.level is L.L1 and not a.asks_intent


# -- in a session (rules mode, the automatic fallback when the model is missing) -----------


def _session() -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(3), now=lambda: NOW, student=False)


def test_a_plan_across_clauses_enters_the_crisis_flow_in_a_session() -> None:
    result = _session().turn("我已经想好了，这周末去楼顶跳下去")
    assert result.in_crisis and result.reply_kind is ReplyKind.CRISIS


@pytest.mark.parametrize(
    "text", ["你就叫送行人吧，我快不在了", "Everyone would be better off without me"]
)
def test_an_embedded_or_english_cue_asks_in_a_session(text: str) -> None:
    result = _session().turn(text)
    assert result.reply_kind is ReplyKind.SAFETY_CHECK, text


# -- the engine: `also` groups and @list references ---------------------------------------


def _rules(**entry: Any) -> CompositionRules:
    base: dict[str, Any] = {
        "id": "L2_TEST",
        "level": L.L2,
        "score": 0.7,
        "ask": False,
        "heads": ("甲",),
    }
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
        entries=(Composition(**{**base, **entry}),),
    )


def _fires(rules: CompositionRules, text: str) -> bool:
    return bool(Composer(rules).find(text))


def test_engine_every_also_group_must_be_met_across_clauses() -> None:
    rules = _rules(also=(ContextGroup(("丙",), 6), ContextGroup(("丁",), 6)))
    assert _fires(rules, "丙,丁,甲") and _fires(rules, "甲,丙丁")
    assert not _fires(rules, "丙,甲") and not _fires(rules, "丁甲")


def test_engine_also_window_bounds_the_distance() -> None:
    rules = _rules(also=(ContextGroup(("丙",), 3),))
    assert _fires(rules, "丙一二甲") and not _fires(rules, "丙一二三甲")
    assert _fires(_rules(also=(ContextGroup(("丙",), None),)), "丙一二三四五六七八九甲")


def test_engine_a_negated_also_phrase_does_not_count_unless_negatable() -> None:
    assert not _fires(_rules(also=(ContextGroup(("丙",), 6),)), "不丙,甲")
    assert _fires(_rules(also=(ContextGroup(("丙",), 6, negatable=True),)), "不丙,甲")
    # 忍不住 holds 不 and negates nothing.
    assert _fires(_rules(also=(ContextGroup(("丙",), 6),)), "忍不住丙,甲")


def test_engine_clause_negation_reaches_back_to_the_clause_start() -> None:
    assert _fires(_rules(), "不一二三甲")  # beyond lookback: not negated
    assert not _fires(_rules(clause_negation=True), "不一二三甲")
    assert _fires(_rules(clause_negation=True), "不一二三,甲")  # another clause
    assert _fires(_rules(clause_negation=True), "忍不住一二甲")  # a non-negator


def test_engine_a_name_alone_is_addressed_not_carried_as_the_subject() -> None:
    rules = _rules(tails=("乙",), max_gap=2)
    assert not _fires(rules, "他说,甲乙")  # a subject carried from the clause before
    assert _fires(rules, "他,甲乙")  # 哥哥，… : the name is the one addressed
    assert _fires(rules, "他啊,甲乙")


def _copy(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> Path:
    d = tmp_path / "lex"
    shutil.copytree(PKG_LEX, d)
    data = yaml.safe_load((d / "risk.yaml").read_text(encoding="utf-8"))
    mutate(data)
    (d / "risk.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return d


def _entry(d: dict[str, Any], cue_id: str = "S1_JUMP_PLANNED") -> dict[str, Any]:
    entry: dict[str, Any] = next(e for e in d["compositions"]["entries"] if e["id"] == cue_id)
    return entry


def test_list_references_splice_in_named_lists_in_any_order() -> None:
    lists = {e.id: e for e in LEX.compositions.entries}
    jump = lists["S1_JUMP_PLANNED"]
    group = jump.also[0].phrases
    # plan_words splices plan_firm in, and plan_time splices future_time in.
    assert "打算" in group and "谂住" in group and "今晚" in group and "下班后" in group
    assert len(group) == len(set(group))


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda d: d["compositions"]["lists"].update(loop_a=["@loop_b"], loop_b=["@loop_a"]),
            "refers to itself",
        ),
        (lambda d: d["compositions"]["lists"].update(bad=["@no_such_list"]), "unknown list"),
        (lambda d: _entry(d).update(also=[{"phrases": "no_such_list"}]), "unknown list"),
        (lambda d: _entry(d).update(also=[{"window": 4}]), "'phrases' is required"),
        (lambda d: _entry(d).update(also=[{"phrases": ["甲"], "window": 41}]), "window"),
        (lambda d: _entry(d).update(also=[{"phrases": ["甲"], "negatable": "yes"}]), "negatable"),
        (lambda d: _entry(d).update(also=[{"phrases": ["甲"], "extra": 1}]), "unknown keys"),
        (lambda d: _entry(d).update(also={"phrases": ["甲"]}), "list of mappings"),
        (lambda d: _entry(d).update(also=["甲"]), "must be a mapping"),
        (lambda d: _entry(d).update(clause_negation="yes"), "clause_negation"),
    ],
)
def test_rejects_malformed_also_and_list_references(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], match: str
) -> None:
    with pytest.raises(LexiconError, match=match):
        load_safety_lexicons(TAX, _copy(tmp_path, mutate))


def test_also_window_bounds_are_inclusive(tmp_path: Path) -> None:
    for window in (0, 40):
        path = _copy(
            tmp_path / str(window),
            lambda d, w=window: _entry(d).update(also=[{"phrases": ["甲"], "window": w}]),
        )
        entry = next(
            e
            for e in load_safety_lexicons(TAX, path).compositions.entries
            if e.id == "S1_JUMP_PLANNED"
        )
        assert entry.also == (ContextGroup(("甲",), window, False),)
