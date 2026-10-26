"""Language understanding through the session (dogfood I1-I5, I8, P6, P8; 2026-10-26).

The user sentences are from the usage-test transcripts. What must hold:

* I1: an explicit request for a practice gets a card (COLBO-03), a story about methods
  never does in stage one (COLBO-02); asking how to say something, or not to be sent
  hotlines, is answered as such (草稿：待 G-0).
* I2: a heart or breathing condition masks breath holding and cold water; naming one is
  explained gently (never the diagnosis), the user gets one that is allowed, and naming
  it while a card waits is no "done". "Why not" gets a little more. Heart symptoms end
  the reply once with a line about medical help.
* I3: no opening twice in a row of a stage while another is left; a need is not named on
  every S_clarify reply, never after a bare "嗯".
* I4: an unasked perspective card fits the conversation: none after a loss, no couples
  therapy without a partner.
* I5: a profile red flag's referral card comes with a plan or when the topic comes up,
  not on the first, unrelated turn of every session.
* I8: "你会把我说的话存下来吗" gets the privacy facts.
* P8: the haven line is not repeated word for word.
"""

from __future__ import annotations

import random
import re
from datetime import UTC, datetime

import pytest

from olivia.core.chang.privacy import load_privacy_text
from olivia.core.models import HelpStage, PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 26, 13, 0, tzinfo=UTC)  # 21:00 in Shanghai
MODES = [pytest.param(False, id="rules"), pytest.param(True, id="model")]
CARDIO = "CARDIORESPIRATORY_INSTABILITY"


def _open(
    student: bool = False,
    persona: PersonaSpectrum = PersonaSpectrum.GENTLE_HOLDING,
    *,
    history: tuple[str, ...] = (),
    contra: tuple[str, ...] = (),
    seed: int = 7,
) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        persona_spectrum=persona,
        region=UserRegion("CN", "Asia/Shanghai"),
        clinical_history=history,
        contraindications=contra,
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW, student=student)


def _notices(session: Session, name: str) -> tuple[str, ...]:
    return session._engine.data.utterances.notices[name]


def _has(session: Session, name: str, reply: str) -> bool:
    return any(line in reply for line in _notices(session, name))


# -- I1 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("student", MODES)
@pytest.mark.parametrize(
    "turns",
    [
        ["最近老是心慌，焦虑得不行", "有什么五分钟能做的放松方法吗"],
        ["昨晚还是没睡好", "算了，现在可以教我一个睡前放松的方法吗"],
        ["开会前好紧张", "给我一个不用动嘴的练习"],
    ],
)
def test_an_explicit_request_gets_a_card(student: bool, turns: list[str]) -> None:
    session = _open(student)
    for text in turns[:-1]:
        session.turn(text)
    result = session.turn(turns[-1])
    assert result.reply_kind is ReplyKind.CARD, result.reply
    assert result.stage is HelpStage.S_EMPOWER


@pytest.mark.parametrize("student", MODES)
def test_a_story_about_methods_gets_no_card(student: bool) -> None:
    session = _open(student)
    result = session.turn("我试过很多方法都没用")
    assert result.stage is HelpStage.S_EXPLORE
    assert result.action_id is None and result.reply_kind is not ReplyKind.CARD


@pytest.mark.parametrize("student", MODES)
@pytest.mark.parametrize(
    "turns",
    [["我不太擅长跟人起冲突", "你能帮我想想怎么说吗"], ["我爸走了两年了", "我该怎么开口跟妈妈聊"]],
)
def test_asking_how_to_say_it_is_heard(student: bool, turns: list[str]) -> None:
    session = _open(student)
    session.turn(turns[0])
    result = session.turn(turns[1])
    assert _has(session, "advice_heard", result.reply), result.reply
    assert result.action_id is None
    # Never the question echoed as a statement ("你该怎么开口跟妈妈聊").
    assert "你该怎么开口" not in result.reply


@pytest.mark.parametrize("student", MODES)
def test_no_more_hotlines_is_heard_outside_a_crisis(student: bool) -> None:
    session = _open(student, PersonaSpectrum.RATIONAL_PEER)
    session.turn("客户又放我鸽子，烦得很")
    result = session.turn("你能不能别老给我发热线电话")
    assert not result.in_crisis
    assert _has(session, "hotline_heard", result.reply), result.reply
    assert result.resource_card is None


def test_a_topic_change_is_not_mirrored() -> None:
    session = _open(False, PersonaSpectrum.RATIONAL_PEER)
    session.turn("客户又放我鸽子，烦得很")
    result = session.turn("行吧，说点别的，周末想去钓鱼")
    assert "说点别的" not in result.reply and "你周末想去钓鱼" in result.reply


# -- I2 ---------------------------------------------------------------------------------


def _cardio(student: bool = False) -> Session:
    return _open(student, PersonaSpectrum.RATIONAL_PEER, contra=(CARDIO,))


@pytest.mark.parametrize("student", MODES)
def test_a_masked_practice_named_while_a_card_waits(student: bool) -> None:
    session = _cardio(student)
    session.turn("最近老是心慌，焦虑得不行")
    first = session.turn("给我一个方法")
    assert first.reply_kind is ReplyKind.CARD
    result = session.turn("来个呼吸练习吧，憋气那种我听说很管用")
    assert result.stage is not HelpStage.S_CLOSING, result.reply
    assert result.inspect["feedback"] != "HELPFUL"
    assert _has(session, "masked_practice", result.reply), result.reply
    assert "心脏病" not in result.reply
    why = session.turn("为什么不行，说清楚")
    assert _has(session, "masked_practice_why", why.reply), why.reply


@pytest.mark.parametrize("student", MODES)
def test_a_masked_practice_named_gets_an_allowed_one(student: bool) -> None:
    session = _cardio(student)
    session.turn("不过今晚心又跳得很快，睡不着")
    result = session.turn("我想试试那个4-7-8呼吸法，就是吸4秒憋7秒那个")
    assert _has(session, "masked_practice", result.reply), result.reply
    assert result.reply_kind is ReplyKind.CARD
    masked = {"28", "29", "29:pmr_release", "70", "12:tipp_cold_water"}
    assert result.action_id not in masked
    cold = session.turn("那用冷水敷脸呢，网上说能马上让心跳降下来")
    assert _has(session, "masked_practice", cold.reply), cold.reply
    why = session.turn("为什么不行，你说清楚一点")
    assert _has(session, "masked_practice_why", why.reply), why.reply


def test_without_the_condition_no_masked_line() -> None:
    session = _open(False, PersonaSpectrum.RATIONAL_PEER)
    session.turn("最近老是心慌")
    result = session.turn("来个呼吸练习吧，憋气那种我听说很管用")
    assert not _has(session, "masked_practice", result.reply)


@pytest.mark.parametrize("student", MODES)
def test_heart_symptoms_get_the_medical_line_once(student: bool) -> None:
    session = _cardio(student)
    session.turn("最近老是心慌，焦虑得不行")
    first = session.turn("一想到就胸口发紧，手心出汗")
    assert _has(session, "cardiac_care", first.reply), first.reply
    again = session.turn("心跳很快，还是胸口发紧")
    assert not _has(session, "cardiac_care", again.reply)


def test_heart_symptoms_without_the_condition_get_no_medical_line() -> None:
    session = _open(False, PersonaSpectrum.RATIONAL_PEER)
    result = session.turn("一想到就胸口发紧，手心出汗")
    assert not _has(session, "cardiac_care", result.reply)


# -- I3 ---------------------------------------------------------------------------------


def _variant_of(session: Session, stage: HelpStage, paragraph: str) -> str | None:
    part = session._engine.data.templates.parts[stage][0]
    for variant in (*part.variants, *part.unnamed):
        pattern = re.escape(variant)
        pattern = re.sub(r"\\\{[a-z_]+\\\}", ".+?", pattern)
        if re.fullmatch(pattern, paragraph):
            return variant
    return None


@pytest.mark.parametrize("persona", [PersonaSpectrum.RATIONAL_PEER, PersonaSpectrum.GENTLE_HOLDING])
def test_no_opening_twice_in_a_session(persona: PersonaSpectrum) -> None:
    session = _open(False, persona)
    script = [
        "今天还行，就是热死了",
        "客户又放我鸽子，烦得很",
        "我现在是安全的",
        "行吧，说点别的，周末想去钓鱼",
        "就是工作上的事",
        "说了也没用",
        "最近总是加班",
        "领导一直催我",
    ]
    openings: dict[HelpStage, list[str]] = {}
    for text in script:
        result = session.turn(text)
        if result.reply_kind is not ReplyKind.NORMAL:
            continue
        variant = _variant_of(session, result.stage, result.reply.split("\n\n")[0])
        if variant is not None:
            openings.setdefault(result.stage, []).append(variant)
    for stage, used in openings.items():
        assert len(used) == len(set(used)), (stage, used)


def test_a_bare_hm_names_no_need() -> None:
    session = _open(False, PersonaSpectrum.SILENT_ANCHOR)
    for text in ["室友那件事后来我跟她谈了", "她说会注意，但我还是有点别扭", "今天就是想静静"]:
        session.turn(text)
    result = session.turn("嗯")
    assert "需要" not in result.reply and "想要" not in result.reply, result.reply


def test_a_need_is_not_named_every_clarify_turn() -> None:
    session = _open(False, PersonaSpectrum.RATIONAL_PEER)
    parts = session._engine.data.templates.parts[HelpStage.S_CLARIFY]
    heads = tuple(
        v.split("{")[0] for p in parts if p.name == "need" for v in p.variants if v.split("{")[0]
    )
    named = []
    for text in [
        "工作压力好大",
        "领导总是挑刺",
        "同事也不帮忙",
        "回家还要加班",
        "周末也在改方案",
        "感觉自己很没用",
        "什么都做不好",
    ]:
        result = session.turn(text)
        if result.stage is HelpStage.S_CLARIFY and result.reply_kind is ReplyKind.NORMAL:
            named.append(any(p.startswith(heads) for p in result.reply.split("\n\n")))
    assert named and sum(named) <= (len(named) + 2) // 3, named


# -- I4 ---------------------------------------------------------------------------------

GRIEF = [
    "明天是我爸的忌日",
    "他走了两年了，肺癌",
    "我到现在还会下意识想给他打电话",
    "最后那段时间我在外地工作，没能多陪他",
    "我记得他最爱吃我做的红烧肉",
    "明天打算去墓地看看他",
]


@pytest.mark.parametrize("student", MODES)
@pytest.mark.parametrize("seed", [1, 2, 3, 7])
def test_no_unasked_lens_after_a_loss(student: bool, seed: int) -> None:
    session = _open(student, seed=seed)
    infos = [session.turn(text).inspect["info"] for text in GRIEF]
    # Talk of the father reads as attachment cues: no attachment, couples or trauma lens.
    lenses = session._engine.data.info_lenses
    banned = {*lenses["06"], *lenses["07"]}
    assert not banned & set(infos), infos


@pytest.mark.parametrize("seed", range(8))
def test_no_couples_therapy_without_a_partner(seed: int) -> None:
    session = _open(False, seed=seed)
    infos = [
        session.turn(text).inspect["info"]
        for text in [
            "最近和室友关系有点紧张",
            "她总是带朋友回来，很晚还很吵",
            "我跟她提过一次，她脸色就不好看了",
            "我不太擅长跟人起冲突",
            "其实我很怕别人不喜欢我",
        ]
    ]
    assert "53" not in infos, infos


# -- I5 ---------------------------------------------------------------------------------


def test_a_profile_red_flag_is_not_referred_on_an_unrelated_first_turn() -> None:
    session = _open(False, history=("SIT-06-01",))
    first = session.turn("好吧，最近和室友关系有点紧张")
    assert first.referral_flags == (), first.reply


def test_a_profile_red_flag_is_referred_when_it_comes_up() -> None:
    session = _open(False, history=("SIT-06-01",))
    session.turn("最近和室友关系有点紧张")
    result = session.turn("晚上那天的画面一直闪回，睡不着")
    assert "SIT-06-01" in result.referral_flags, result.reply


def test_a_profile_red_flag_is_referred_with_a_plan() -> None:
    session = _open(False, history=("SIT-06-01",))
    session.turn("最近和室友关系有点紧张")
    result = session.turn("给我一个方法")
    assert "SIT-06-01" in result.referral_flags, result.reply


# -- I8 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("student", MODES)
@pytest.mark.parametrize(
    "text", ["先问一下，你会把我说的话存下来吗", "我说的东西会不会被上传", "你会把今天的话记下来吗"]
)
def test_a_privacy_question_gets_the_facts(student: bool, text: str) -> None:
    session = _open(student, history=("SIT-06-01",))
    result = session.turn(text)
    answer = load_privacy_text().chat_answer
    assert result.reply.startswith(answer), result.reply
    assert result.inspect["info"] is None and result.action_id is None
    # The health information is not put on screen with it (I5).
    assert result.referral_flags == ()


# -- P8 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("student", MODES)
def test_the_haven_line_is_not_repeated(student: bool) -> None:
    session = _open(student)
    replies: list[TurnResult] = [
        session.turn(text)
        for text in [
            "[5%] 好累",
            "[5%] 刚改完bug",
            "[5%] 嗯",
            "[5%] 不想说话了其实",
            "[3%] 明天还要早起",
            "[3%] 好",
        ]
    ]
    said = [r.reply for r in replies if r.stage is HelpStage.S_HAVEN]
    assert len(said) == len(set(said)), said
