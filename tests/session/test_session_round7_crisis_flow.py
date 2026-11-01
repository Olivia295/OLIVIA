"""Crisis flow, someone else's risk and minors, round 7 (re-test 2026-10-31).

* A message that reports someone and also says something of the user's own ("他要是……，我
  就……") is no "someone else's words alone": a model-only alarm on it follows the 0.6 rule
  (owner decision 2026-10-26), a sure one enters the crisis flow.
* The answer to the direct question: a first clause that is a question is no yes; an
  English no with "I'm fine" is a no.
* Someone else's risk: a subject-less intent clause goes on with the same person, a fall
  from a height, a means saved up (Cantonese too), a painless way looked up, leaving life
  said gently, not coming back from a place; a passive agent owned by the user ("被我爸
  ……得想死") is no speaker. Follow-ups about the police and warning signs get their own
  answers, in the crisis flow too; the user joining in ("我自己都……", "跟他一起算了")
  enters the crisis flow.
* Safety confirmations next to "别担心我", going to bed, Cantonese particles, English.
* Minors: an age with "才" opening a clause, a school move still ahead.

Every example message is written here; none comes from an evaluation set or the re-test.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.safety.crisis import RiskPrediction, SafetyScreen
from olivia.core.safety.intent_check import IntentAnswer, read_answer
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.normalize import normalize
from olivia.core.safety.reported import names_plan
from olivia.core.safety.tracker import CrisisTracker
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
RULES = SafetyScreen(TAX, LEX)
CRISIS_OPENER = "我已经撑不住了，真的不想活了"


class Scripted:
    """A risk model that rates the listed messages and everything else L0."""

    def __init__(self, levels: dict[str, tuple[CrisisLevel, float]]) -> None:
        self.levels = levels

    def predict(self, text: str) -> RiskPrediction:
        level, score = self.levels.get(text, (CrisisLevel.L0, 0.05))
        return RiskPrediction(level, score, ())


def _open(*, model: object | None = None, region: str = "CN") -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小周",
        region=UserRegion(region, "Asia/Shanghai"),
    )
    return Session.open(
        TAX,
        profile,
        rng=random.Random(7),
        now=lambda: NOW,
        model=model,  # type: ignore[arg-type]
    )


def _numbers(result: object) -> list[str]:
    card = result.resource_card  # type: ignore[attr-defined]
    assert card is not None
    return [em.number for em in card.emergency]


# -- the user's own words next to someone else's ------------------------------------------

THREATS = ["他要是明天还不回家，我就做给他看", "她要是再不接我电话，我就让她后悔一辈子"]


@pytest.mark.parametrize("text", THREATS)
def test_the_users_own_clause_is_heard_next_to_a_report(text: str) -> None:
    assert RULES.assess(text).rule_clear
    found = RULES.reported_risk(text)
    assert found is None or found.user_speaks


@pytest.mark.parametrize("text", THREATS)
def test_a_sure_model_alarm_next_to_the_users_own_clause_enters_the_crisis(text: str) -> None:
    session = _open(model=Scripted({text: (CrisisLevel.L2, 0.71)}))
    result = session.turn(text)
    assert result.in_crisis
    assert result.reply_kind is ReplyKind.CRISIS


@pytest.mark.parametrize("text", THREATS)
def test_an_unsure_model_alarm_there_still_asks_first(text: str) -> None:
    session = _open(model=Scripted({text: (CrisisLevel.L2, 0.45)}))
    result = session.turn(text)
    assert not result.in_crisis
    assert result.reply_kind is ReplyKind.SAFETY_CHECK


def test_a_worried_clause_of_the_user_is_no_words_of_their_own() -> None:
    text = "我同事说她明天就不想再来了，我好担心"
    found = RULES.reported_risk(text)
    assert found is not None
    assert not found.user_speaks


# -- answers to the direct question --------------------------------------------------------


def _answer(text: str) -> IntentAnswer:
    return read_answer(LEX.intent_answers, text, RULES.assess(text), RULES.assess).answer


@pytest.mark.parametrize(
    "text",
    [
        "有时候在想我是不是选错了专业",
        "有没有什么办法能睡得好一点",
        "是吗，你怎么会这么问",
        "有什么好说的呢",
    ],
)
def test_a_question_is_no_yes(text: str) -> None:
    assert _answer(text) is IntentAnswer.UNCLEAR


@pytest.mark.parametrize("text", ["是的", "有一点", "嗯，有过", "对，最近经常想"])
def test_a_yes_is_still_a_yes(text: str) -> None:
    assert _answer(text) is IntentAnswer.AFFIRMED


@pytest.mark.parametrize("text", ["nope I'm okay, just tired", "no, I'm good honestly"])
def test_an_english_no_with_im_fine_is_a_no(text: str) -> None:
    assert _answer(text) is IntentAnswer.DENIED


@pytest.mark.parametrize("text", ["nah I'm fine but sometimes I think about it", "no I'm ok maybe"])
def test_an_english_no_with_a_hedge_stays_unclear(text: str) -> None:
    assert _answer(text) is not IntentAnswer.DENIED


# -- someone else's risk -------------------------------------------------------------------

REPORTS = [
    "我表哥前天打电话说他真的活不下去了，想去江边结束掉",
    "我室友刚在群里说今晚要从宿舍楼顶上下去",
    "我老妈总念叨说她死了算了，最近还偷偷攒了一盒安眠药",
    "我细佬话佢唔想活，仲储咗好多药",
    "我爷爷说过两天他进山就不回来了",
    "我姐说等我毕业她就能安心走了",
    "我师兄在朋友圈发了张天台的照片，配文说今晚终于可以解脱了",
    "有个群友私聊跟我道别，说谢谢大家照顾，明晚过后就再也不上线了",
]


@pytest.mark.parametrize("text", REPORTS)
def test_someone_elses_risk_gets_the_card_to_pass_on(text: str) -> None:
    for model in (None, Scripted({})):
        result = _open(model=model).turn(text)
        assert result.inspect.get("resources_reply") == "third_party", text
        assert not result.in_crisis
        assert result.crisis_level <= CrisisLevel.L1


@pytest.mark.parametrize("text", [REPORTS[0], REPORTS[1], REPORTS[2], REPORTS[3], REPORTS[5]])
def test_a_plan_in_the_report_puts_the_emergency_numbers_first(text: str) -> None:
    result = _open().turn(text)
    assert "110" in _numbers(result)


@pytest.mark.parametrize(
    "text",
    ["我奶奶说等我结婚她就放心了", "我爸说他周末进山拍照", "同事说他下午要从楼上搬东西下来"],
)
def test_everyday_reports_get_no_card(text: str) -> None:
    result = _open().turn(text)
    assert result.inspect.get("resources_reply") != "third_party"
    assert not result.in_crisis


def test_parts_of_a_plan_read_by_grammar() -> None:
    assert names_plan(normalize("他在查怎么死才不痛苦"))
    assert names_plan(normalize("她说再也不回来了，把狗托付给我"))
    assert not names_plan(normalize("她说再也不回来这家店了"))


@pytest.mark.parametrize("text", ["被我爸唠叨得想死", "被我室友吵得想死"])
def test_a_passive_agent_owned_by_the_user_is_no_speaker(text: str) -> None:
    result = _open().turn(text)
    assert result.inspect.get("resources_reply") != "third_party"
    assert result.reply_kind in (ReplyKind.SAFETY_CHECK, ReplyKind.CRISIS)


def test_a_risky_answer_after_the_figure_enters_the_crisis() -> None:
    session = _open()
    assert session.turn("被我爸唠叨得想死").reply_kind is ReplyKind.SAFETY_CHECK
    assert session.turn("没有啦……不过有时候真会想，但不会去做").in_crisis


@pytest.mark.parametrize("student", [False, True], ids=["rules", "model"])
def test_asking_about_the_police_gets_an_answer_and_the_emergency_numbers(student: bool) -> None:
    follow = "我该不该报警啊"
    model = Scripted({follow: (CrisisLevel.L3, 0.8)}) if student else None
    session = _open(model=model)
    session.turn(REPORTS[0])
    result = session.turn(follow)
    assert not result.in_crisis
    assert result.reply.startswith(tuple(p[:12] for p in _render().third_party_police))
    assert "110" in _numbers(result)


def test_asking_whether_it_is_a_warning_sign_gets_an_answer() -> None:
    session = _open()
    session.turn(REPORTS[4])
    result = session.turn("这算是危险的信号吗")
    assert result.reply.startswith(tuple(p[:12] for p in _render().third_party_signs))


@pytest.mark.parametrize("join", ["说真的我自己都不想再撑了", "有时候我也想跟他一起算了"])
def test_the_user_joining_in_enters_the_crisis(join: str) -> None:
    session = _open()
    session.turn(REPORTS[0])
    assert session.turn(join).in_crisis


def test_a_question_about_the_other_person_is_answered_first_in_the_crisis() -> None:
    session = _open()
    session.turn(REPORTS[0])
    assert session.turn("说真的我自己都不想再撑了").in_crisis
    result = session.turn("那我要不要先报警")
    assert result.in_crisis
    assert result.reply.startswith(tuple(p[:12] for p in _render().third_party_police))


def _render():  # type: ignore[no-untyped-def]
    return _open()._engine.data.render


# -- confirmations ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "嗯，我现在安全，别担心我",
        "我安全的，准备去睡觉了",
        "我冇事，安全嘅",
        "I'm safe now, don't worry about me.",
    ],
)
def test_more_confirmations_count_and_the_crisis_ends(text: str) -> None:
    session = _open()
    assert session.turn(CRISIS_OPENER).in_crisis
    session.turn(text)
    exits = [session.turn(t).in_crisis for t in ("今天下雨了", "晚上吃了饺子", "明天要早起")]
    assert exits[-1] is False


@pytest.mark.parametrize(
    "text",
    ["我安全，别担心我，已经决定了", "我安全的，准备睡了，最好别再醒", "安全嘅，不过听日就唔知"],
)
def test_a_confirmation_with_danger_next_to_it_does_not_count(text: str) -> None:
    tracker = CrisisTracker(TAX, LEX)
    assert not tracker.confirms_safety(text, RULES.assess(text))


# -- minors ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["才十五岁，就觉得活着没意思", "明年我就要中考了，压力好大", "我马上要小升初了"]
)
def test_more_minor_disclosures(text: str) -> None:
    session = _open()
    assert session._shared.stub.discloses_minor(text)


@pytest.mark.parametrize(
    "text", ["我儿子明年就要小升初了", "我中考那年特别累", "才十六岁的孩子懂什么", "她才十五岁"]
)
def test_not_a_minor_disclosure(text: str) -> None:
    session = _open()
    assert not session._shared.stub.discloses_minor(text)


def test_a_minor_in_the_crisis_gets_the_youth_line_and_the_age_question() -> None:
    session = _open()
    result = session.turn("才十五岁，就真的不想活了")
    assert result.in_crisis
    assert result.resource_card is not None
    assert "12355" in [ln.number for ln in result.resource_card.lines]
    after = session.turn("是的")
    assert after.inspect.get("minor_record") == "confirmed"
    assert session.take_minor_record()
