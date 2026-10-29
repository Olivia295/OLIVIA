"""Minors in the chat, round 6 (re-test q2 第 4 节, q4 F5).

* Spoken answers to the question whether the user is under 18 ("嗯嗯，对呀", "啱呀") are a
  yes; a correction with an adult age is a no. The reader is the minors' own
  (``perception/minor_answer.py``), not the crisis tracker's.
* More ways to say one's own school year or age (Hong Kong 中一 to 中六, Taiwan 國一 to
  國三, 高三, an age with no 岁 opening a clause, turning 18 later, not yet grown up, US
  grades), and none for the past or for someone else.
* An age said with a crisis cue: the crisis flow as always, the minors' lines on its card,
  and the question whether to record the age at its end; on the next turn a short yes
  answers that question, never the safety question, which is asked again.

Every example message is written here; none comes from a re-test sheet or an evaluation set.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.minor_answer import reads_no, reads_yes
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.safety.crisis import RiskPrediction, SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
RULES = SafetyScreen(TAX, LEX)
STUB = RuleStub(TAX, load_perception_lexicon(TAX))
RENDER = load_language_data(TAX).render


class Scripted:
    """A risk model that rates the listed messages and everything else L0."""

    def __init__(self, levels: dict[str, tuple[CrisisLevel, float]]) -> None:
        self.levels = levels

    def predict(self, text: str) -> RiskPrediction:
        level, score = self.levels.get(text, (CrisisLevel.L0, 0.05))
        return RiskPrediction(level, score, ())


def _open(*, model: object | None = None) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(
        TAX,
        profile,
        rng=random.Random(6),
        now=lambda: NOW,
        model=model,  # type: ignore[arg-type]
    )


# -- the answer ---------------------------------------------------------------------------------

SPOKEN_YES = ["嗯嗯，对呀", "是是", "啱呀", "yep", "对头", "嗯，我是", "Yeah, that's right"]
NOT_YES = [
    "不是啦，刚才手滑了，我都三十了",
    "没有没有",
    "是吗？",
    "唔系呀",
    "nah",
    "嗯……不对",
    "我想想",
    "对不起",
]


@pytest.mark.parametrize("text", SPOKEN_YES)
def test_spoken_yeses_are_a_yes(text):
    assert reads_yes(text)


@pytest.mark.parametrize("text", NOT_YES)
def test_noes_questions_and_other_words_are_no_yes(text):
    assert not reads_yes(text)


@pytest.mark.parametrize("answer", SPOKEN_YES)
def test_a_spoken_yes_records_the_age(answer):
    session = _open()
    first = session.turn("我才十五，同桌又不理我了")
    assert first.reply.endswith(RENDER.minor_confirm)
    yes = session.turn(answer)
    assert yes.inspect.get("minor_record") == "confirmed"
    assert yes.reply.startswith(RENDER.minor_recorded)
    assert session.take_minor_record()


def test_a_correction_with_an_adult_age_is_a_no():
    session = _open()
    session.turn("我才十五，同桌又不理我了")
    no = session.turn("不是啦，刚才手滑了，我都三十了")
    assert no.inspect.get("minor_record") == "session_only"
    assert not session.take_minor_record()


# -- the age --------------------------------------------------------------------------------------

OWN_AGE = [
    "我宜家读紧中六，成日温书",
    "我今年中一，第一次住宿舍",
    "我在念國一，好想轉學",
    "我讀高一，同學都好兇",
    "我才上高三，就已经很累了",
    "我高三了，天天考试",
    "我16，今天又被骂了",
    "今年刚满十六，什么都不懂",
    "再过半年我才满18",
    "明年才成年，现在什么都做不了",
    "目前还没成年，家里管得严",
    "I'm a senior in high school, honestly tired",
    "im in 9th grade and bored",
    "I'm in middle school and my mom reads my phone",
    "I'm a highschool junior",
]
NOT_OWN_AGE = [
    "我高三那会儿天天失眠",
    "我表弟在读國二",
    "My niece is a high school junior",
    "我17岁那年搬了家",
    "I'm a high school counselor",
    "我今年二十七",
    "去年我还没成年",
    "我高中没毕业就工作了",
    "我是高中生的妈妈",
    "工作还有两个月才满18个月",
    "我女儿很乖，今年十六",
    "我是初三的班主任",
    "以前我读初二时很胖",
    "I used to be in middle school band",
    "我17号考试",
    "借我17，明天还你",
]


@pytest.mark.parametrize("text", OWN_AGE)
def test_more_ways_to_say_ones_own_age(text):
    _, signals = STUB.perceive(text, RULES.assess(text))
    assert signals.minor_disclosure
    assert STUB.discloses_minor(text)


@pytest.mark.parametrize("text", NOT_OWN_AGE)
def test_the_past_someone_else_and_adults_are_no_minor(text):
    _, signals = STUB.perceive(text, RULES.assess(text))
    assert not signals.minor_disclosure
    assert not STUB.discloses_minor(text)


# -- an age with a crisis cue ---------------------------------------------------------------------


def _crisis_with_age(session: Session, text: str) -> None:
    first = session.turn(text)
    assert first.in_crisis and first.reply_kind is ReplyKind.CRISIS
    assert "12355" in first.reply
    assert first.reply.rstrip().endswith(RENDER.minor_confirm)


@pytest.mark.parametrize(
    "text",
    ["我才十五，真的不想活了", "我在读高中，还没成年，活不下去了", "I'm 15 and I want to die"],
)
def test_an_age_with_a_crisis_cue_keeps_the_crisis_and_asks_about_the_age(text):
    _crisis_with_age(_open(), text)


@pytest.mark.parametrize("answer", ["嗯对", "是的", "yes"])
def test_in_a_crisis_a_short_yes_answers_the_age_question_not_the_safety_one(answer):
    session = _open()
    _crisis_with_age(session, "我才十五，真的不想活了")
    yes = session.turn(answer)
    assert yes.inspect.get("minor_record") == "confirmed"
    assert session.take_minor_record()
    assert yes.in_crisis and yes.reply_kind is ReplyKind.CRISIS
    assert yes.reply.startswith(RENDER.minor_recorded)
    # The safety question is asked again: the yes was no confirmation.
    assert "安全" in yes.reply
    after = session.turn("我现在是安全的")
    assert after.in_crisis  # a confirmation now, the crisis waits to end as always
    assert after.inspect.get("minor_record") is None


def test_in_a_crisis_other_words_leave_the_age_question_for_later():
    session = _open()
    _crisis_with_age(session, "我才十五，真的不想活了")
    words = session.turn("我在房间里，门锁着")
    assert words.in_crisis and "minor_record" not in words.inspect
    assert not session.take_minor_record()


def test_in_a_crisis_a_no_keeps_it_to_this_session():
    session = _open()
    _crisis_with_age(session, "我才十五，真的不想活了")
    no = session.turn("不是")
    assert no.in_crisis and no.inspect.get("minor_record") == "session_only"
    assert not session.take_minor_record()


def test_the_age_question_is_asked_once():
    session = _open()
    _crisis_with_age(session, "我才十五，真的不想活了")
    session.turn("是的")
    later = session.turn("还是好难受")
    assert RENDER.minor_confirm not in later.reply


def test_a_model_only_alarm_with_an_age_still_asks_about_the_age():
    text = "我在读高三，这学期什么都不想做"
    session = _open(model=Scripted({text: (CrisisLevel.L3, 0.9)}))
    first = session.turn(text)
    assert first.inspect.get("resources_reply") == "minor"
    assert first.reply.endswith(RENDER.minor_confirm)
    assert session.turn("嗯嗯").inspect.get("minor_record") == "confirmed"


@pytest.mark.parametrize("text", ["不是啦，刚才手滑了，我都三十了", "没有", "我已经22了", "nope"])
def test_corrections_and_adult_ages_are_a_no(text):
    assert reads_no(text)


@pytest.mark.parametrize("text", ["我是2009年生的", "嗯嗯", "我16"])
def test_a_birth_year_or_a_young_age_is_no_no(text):
    assert not reads_no(text)
