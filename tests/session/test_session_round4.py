"""Session flows, round 4 (re-test 2026-10-28, q2 report and the SDD re-trace).

* 1: in a crisis the L1 escalation does not apply; after a confirmation an L1 turn pauses
  the exit count (SDD §8.2), so a run of L1 turns no longer voids the confirmation.
* 2: someone else's risk in more forms (我哥 … 跟我说, quoted words, a colon, words posted
  in a group or on a page, a student's note with a time, someone's self-injury), follow-ups
  that ask how to start the talk or say the other person is fine, 我也 + worry is no joining
  in, and a model-only alarm on a message reporting someone's words asks instead of the
  crisis flow.
* 3: more ways to confirm safety (an English clause, a promise to be well tonight, having
  come down from a roof); the model's alarm alone on such a confirmation is no relapse.
* 4: in the crisis flow, a question about when a number answers gets the hours from the
  hotline data; an English question about the university's counselling centre is answered.
* 5: more ways to say one is under 18; a gentle question whether to record it, and the
  record only after a yes.
* 6: whether a number is real or official, Cantonese questions, and the region "other"
  with a country named: no "your region's numbers", the country's emergency numbers.
* 7: /commands lists the chat commands.
* 8: a 0-10 distress rating while a card waits sets the turn's arousal (SUDS / 10).

Every example message comes from the re-test reports or is written here; none comes from
an evaluation set.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, UserRegion
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.safety.crisis import RiskPrediction, SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.tracker import CrisisTracker
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
RULES = SafetyScreen(TAX, LEX)
STUB = RuleStub(TAX, load_perception_lexicon(TAX))
RENDER = load_language_data(TAX).render
SAFETY_QUESTIONS = ("安全吗", "是安全的吗", "身边安全吗")
MODES = [pytest.param(False, id="rules"), pytest.param(True, id="model")]
ZONES = {"CN": "Asia/Shanghai", "US": "America/New_York", "HK": "Asia/Hong_Kong", "ZZ": "UTC"}


class Scripted:
    """A risk model that rates the listed messages and everything else L0."""

    def __init__(self, levels: dict[str, tuple[CrisisLevel, float]]) -> None:
        self.levels = levels

    def predict(self, text: str) -> RiskPrediction:
        level, score = self.levels.get(text, (CrisisLevel.L0, 0.05))
        return RiskPrediction(level, score, ())


def _open(*, model: object | None = None, student: bool = False, region: str = "CN") -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion(region, ZONES.get(region, "Asia/Shanghai")),
    )
    return Session.open(
        TAX,
        profile,
        rng=random.Random(5),
        now=lambda: NOW,
        model=model,  # type: ignore[arg-type]
        student=student,
    )


def _asks_safety(reply: str) -> bool:
    return any(q in reply for q in SAFETY_QUESTIONS)


def _third_party(result: TurnResult) -> bool:
    return (
        result.reply_kind is ReplyKind.RESOURCES
        and result.inspect.get("resources_reply") == "third_party"
        and not result.in_crisis
        and result.stage is not HelpStage.S_CRISIS
        and not _asks_safety(result.reply)
    )


def _confirmed(session: Session) -> bool:
    status = session._last_status
    return status is not None and status.in_crisis and not status.awaiting_confirmation


# -- 1: no L1 escalation in a crisis --------------------------------------------------------------


def test_three_l1_turns_after_a_confirmation_only_pause_the_exit_count():
    tracker = CrisisTracker(TAX, LEX)

    def observe(text: str):
        return tracker.observe(RULES.assess(text), text)

    assert observe("我不想活了").just_entered
    assert not observe("我现在是安全的").awaiting_confirmation
    for _ in range(3):
        status = observe("活着好累")
        assert status.level is CrisisLevel.L1 and not status.escalated
        assert status.in_crisis and not status.awaiting_confirmation
        assert status.safe_turns_remaining == 2
    assert observe("今天吃了面").safe_turns_remaining == 1
    assert observe("今天吃了面").just_exited


def test_an_l2_turn_after_a_confirmation_still_voids_it():
    tracker = CrisisTracker(TAX, LEX)
    for text in ("我不想活了", "我现在是安全的", "活着好累", "活着好累"):
        tracker.observe(RULES.assess(text), text)
    status = tracker.observe(RULES.assess("我又想死了"), "我又想死了")
    assert status.level is CrisisLevel.L2 and status.awaiting_confirmation


def test_l1_escalation_still_applies_outside_a_crisis_after_one():
    tracker = CrisisTracker(TAX, LEX)
    for text in ("我不想活了", "我现在是安全的", "今天吃了面", "今天吃了面"):
        last = tracker.observe(RULES.assess(text), text)
    assert last.just_exited
    statuses = [tracker.observe(RULES.assess("活着好累"), "活着好累") for _ in range(3)]
    assert statuses[-1].escalated and statuses[-1].in_crisis


def test_model_band_l1_turns_after_a_confirmation_never_void_it():
    # Re-test reproduction: the student puts the confirmation itself in its L1 band and two
    # later turns at an unsure L2 (paused); the fourth turn used to escalate.
    model = Scripted(
        {
            "我不想活了": (CrisisLevel.L2, 0.66),
            "我现在是安全的": (CrisisLevel.L0, 0.23),
            "它一直跟着我走了一段": (CrisisLevel.L2, 0.59),
            "明天还想去看看它": (CrisisLevel.L2, 0.34),
        }
    )
    session = _open(model=model)
    session.turn("我不想活了")
    session.turn("我现在是安全的")
    assert _confirmed(session)
    for text in ("它一直跟着我走了一段", "明天还想去看看它"):
        result = session.turn(text)
        assert result.in_crisis and _confirmed(session)
        assert not _asks_safety(result.reply)
    session.turn("今天天气挺好")
    assert not session.turn("嗯").in_crisis


# -- 2: someone else's risk -----------------------------------------------------------------------

REPORTED = [
    "我哥昨晚喝多了，跟我说活着没意思，他不想活了",
    "我表妹在家族群里发了一句“我真的撑不下去了，想死”，后来又撤回了",
    "我学生在作业本最后一页留言说，下周一考完试她就去死",
    "她说她想死，我也不知道该怎么办了",
    "我弟又开始伤害自己了",
    # written here
    "我姑姑昨天给我打电话，跟我说她不想活了",
    "同学在群里发了一句“我真的不想活了”",
    "我室友在日记里写：明天考完就去死",
]
URGENT_REPORTED = [
    "我学生在作业本最后一页留言说，下周一考完试她就去死",
    "室友刚在朋友圈发了一句“大家再见了，谢谢你们”，配图是天台",
    "闺蜜跟我说她把攒的药都准备好了，打算今晚就吃",
    # written here
    "我同事在朋友圈发了一句“永别了”，配了一张江边的照片",
]
NOT_REPORTED = [
    "最后一次开周会了，以后改双周",
    "被同事吵得想死",
    "我妈在我朋友圈底下留言：累了就回家，家里永远有你一碗饭",
    "我妈说缘分到了还会再遇到的",
    # written here
    "被室友气得想死",
    "我同事在群里发了一句“大家下周见”",
    "我妈留言：周末回家吃饭",
]


@pytest.mark.parametrize("student", MODES)
@pytest.mark.parametrize("text", REPORTED)
def test_someone_elses_risk_gets_the_card_not_the_crisis_flow(student, text):
    result = _open(student=student).turn(text)
    assert _third_party(result), result.reply


@pytest.mark.parametrize("student", MODES)
@pytest.mark.parametrize("text", URGENT_REPORTED)
def test_a_reported_time_means_or_place_leads_with_the_emergency_numbers(student, text):
    result = _open(student=student).turn(text)
    assert _third_party(result), result.reply
    assert result.reply.index("110") < result.reply.index("12356")


@pytest.mark.parametrize("text", NOT_REPORTED)
def test_everyday_words_are_no_reported_risk(text):
    result = _open().turn(text)
    assert result.inspect.get("resources_reply") != "third_party"
    assert not result.in_crisis


def test_joining_in_still_keeps_the_users_own_flow():
    for text in ("她说她想死，我也是", "他说他想死，我也想死", "她说她不想活了，我也撑不住了"):
        result = _open().turn(text)
        assert result.inspect.get("resources_reply") != "third_party", text
        assert result.in_crisis or result.reply_kind is ReplyKind.SAFETY_CHECK, text


def test_a_model_alarm_on_reported_words_asks_instead_of_the_crisis_flow():
    text = "我妈在我朋友圈底下留言：累了就回家，家里永远有你一碗饭"
    session = _open(model=Scripted({text: (CrisisLevel.L3, 0.70)}))
    result = session.turn(text)
    assert not result.in_crisis
    assert result.reply_kind is ReplyKind.SAFETY_CHECK
    assert result.inspect.get("resources_reply") != "third_party"


@pytest.mark.parametrize(
    ("first", "follow", "pool"),
    [
        ("我朋友说他不想活了", "我该怎么开口问他是不是真的有这个想法", "third_party_how_to_ask"),
        ("闺蜜跟我说她不想活了", "我现在该跟她说点什么", "third_party_how_to_ask"),
        ("我朋友说他不想活了", "要是他说没事呢", "third_party_says_fine"),
        ("我表妹在群里说她想死", "她说她没事，就是随口一说", "third_party_says_fine"),
        ("我哥跟我说他不想活了", "他让我别告诉爸妈", "third_party_secret"),
        ("闺蜜跟我说她不想活了", "她求我千万别告诉任何人", "third_party_secret"),
    ],
)
def test_follow_ups_about_the_other_person_get_what_to_do(first, follow, pool):
    session = _open()
    assert _third_party(session.turn(first))
    result = session.turn(follow)
    assert _third_party(result) and result.inspect.get("third_party_followup") is True
    assert any(result.reply.startswith(line) for line in getattr(RENDER, pool)), result.reply


def test_he_says_he_is_fine_alone_is_ordinary():
    assert _open().turn("他说他没事").reply_kind is not ReplyKind.RESOURCES


# -- 3: confirming safety -------------------------------------------------------------------------

CONFIRMATIONS = [
    ("I want to kill myself", "I'm safe now, I promise. My friend is here with me.", "US"),
    ("我不想活了", "我保证今晚好好的，不会乱来", "CN"),
    ("我想从天台跳下去", "我已经从天台下来了，现在在家，安全的", "CN"),
    # written here
    ("我不想活了", "我答应你今晚不会做傻事", "CN"),
    ("I want to kill myself", "I promise I'm safe now", "US"),
    ("我想从桥上跳下去", "我从桥上下来了，在家，是安全的", "CN"),
]
NOT_CONFIRMATIONS = [
    "我从楼顶下来了，但明天还会上去",
    "我在天台上，挺安全的",
    "I'm safe for now",
    "我保证今晚好好的，可是药还在",
    "我保证不了",
]


@pytest.mark.parametrize("student", MODES)
@pytest.mark.parametrize(("opening", "text", "region"), CONFIRMATIONS)
def test_more_ways_to_confirm_safety(student, opening, text, region):
    session = _open(student=student, region=region)
    session.turn(opening)
    session.turn(text)
    assert _confirmed(session)


@pytest.mark.parametrize("text", NOT_CONFIRMATIONS)
def test_hedged_or_placed_words_are_no_confirmation(text):
    session = _open()
    session.turn("我想从楼顶跳下去")
    session.turn(text)
    assert not _confirmed(session)


def test_a_model_alarm_alone_on_a_confirmation_is_no_relapse():
    text = "我已经从天台下来了，现在在家，安全的"
    session = _open(
        model=Scripted({"我想从天台跳下去": (CrisisLevel.L2, 0.7), text: (CrisisLevel.L3, 0.95)})
    )
    session.turn("我想从天台跳下去")
    result = session.turn(text)
    assert result.in_crisis and _confirmed(session)
    # The model's L3 keeps the emergency numbers in front for the rest of the crisis.
    assert "110" in session.turn("嗯").reply


# -- 4: new words in the crisis flow --------------------------------------------------------------


def test_a_question_about_the_hours_gets_them_from_the_hotline_data():
    session = _open()
    session.turn("我不想活了")
    result = session.turn("12356 晚上几点还有人接？")
    first = result.reply.split("\n\n")[0]
    assert result.in_crisis and first.startswith(RENDER.hotline_hours_from_data)
    assert "12356" in first and "18小时" in first


def test_an_english_question_about_the_university_counselling_centre_is_answered():
    session = _open(region="US")
    session.turn("I want to kill myself")
    result = session.turn("Is there a counseling center I can go to at my university?")
    assert result.in_crisis and result.reply.split("\n\n")[0] in RENDER.help_seeking_school


# -- 5: minors ------------------------------------------------------------------------------------

MINORS = [
    "俺今年十六，还在县城念高中，天天起老早",
    "我今年先十四岁咋，阿妈成日闹我",
    "我们初二的数学老师好凶，今天又罚我站了",
    "我才十六，爸妈天天吵架",
    "我系中四学生，今年十六岁，功课好多",
    # written here
    "咱才十五，啥也不懂",
    "我仲系中三学生",
    "我们高二的班主任要求好严",
]
NOT_MINORS = [
    "我今年十六号搬家",
    "我才十点就困了",
    "我们初二那年的班主任很好",
    "我们高一的时候一起逃过课",
    "我中二病又犯了",
    "我儿子今年十六",
]


@pytest.mark.parametrize("text", MINORS)
def test_more_ways_to_say_one_is_under_18(text):
    _, signals = STUB.perceive(text, RULES.assess(text))
    assert signals.minor_disclosure


@pytest.mark.parametrize("text", NOT_MINORS)
def test_dates_counts_the_past_and_others_are_not_the_users_age(text):
    _, signals = STUB.perceive(text, RULES.assess(text))
    assert not signals.minor_disclosure


def test_the_first_minors_reply_asks_whether_to_record_it():
    session = _open()
    first = session.turn("我才十六，爸妈天天吵架")
    assert first.reply.endswith(RENDER.minor_confirm)
    assert not session.take_minor_record()
    yes = session.turn("是的")
    assert yes.inspect.get("minor_record") == "confirmed"
    assert yes.reply.startswith(RENDER.minor_recorded)
    assert session.take_minor_record()
    assert not session.take_minor_record()  # once
    later = session.turn("你好")
    assert later.inspect.get("resources_reply") == "minor" and "minor_record" not in later.inspect


def test_without_a_yes_nothing_is_recorded_and_the_session_stays_for_adults_only():
    session = _open()
    session.turn("我才十六")
    no = session.turn("不是")
    assert no.inspect.get("minor_record") == "session_only"
    assert no.reply.startswith(RENDER.minor_session_only)
    assert not session.take_minor_record()
    assert session.turn("你好").inspect.get("resources_reply") == "minor"


def test_the_minors_record_holds_no_words():
    session = _open()
    session.turn("我才十六，爸妈天天吵架")
    session.turn("是的")
    snapshot = repr(session.snapshot())
    assert "十六" not in snapshot and "吵架" not in snapshot


# -- 6: hotline follow-ups ------------------------------------------------------------------------


@pytest.mark.parametrize("question", ["这号码是真的吗，别骗我", "这个是官方的吗"])
def test_whether_a_number_is_real_or_official_is_answered(question):
    session = _open()
    session.turn("能给我一个心理援助热线的号码吗")
    result = session.turn(question)
    assert result.inspect.get("resources_reply") == "hotline"
    assert any(line in result.reply for line in RENDER.hotline_real)


def test_a_cantonese_question_about_the_language_is_answered():
    session = _open(region="HK")
    session.turn("有冇心理熱線")
    result = session.turn("可唔可以讲普通话")
    assert result.inspect.get("resources_reply") == "hotline"
    assert any(line in result.reply for line in RENDER.hotline_language)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("我在日本工作，想找个可以打的心理咨询电话", "JP"),
        ("我住在新加坡，有什么热线", "SG"),
        ("我在德国读书，能给我一个心理热线吗", "DE"),
    ],
)
def test_region_other_names_no_regions_numbers_and_the_countrys_emergency_numbers(text, code):
    result = _open(region="ZZ").turn(text)
    assert result.inspect.get("resources_reply") == "hotline"
    assert not any(line in result.reply for line in RENDER.hotline_request)
    assert any(line in result.reply for line in RENDER.hotline_elsewhere)
    assert "findahelpline.com" in result.reply
    assert result.reply.endswith(
        RENDER.hotline_local_emergency_intro + RENDER.local_emergency[code]
    )


def test_a_country_without_listed_numbers_gets_the_general_card_only():
    result = _open(region="ZZ").turn("我在泰国，有什么心理热线吗")
    assert "findahelpline.com" in result.reply
    assert RENDER.hotline_local_emergency_intro not in result.reply


# -- 7: /commands ---------------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["/commands", "/命令"])
def test_commands_lists_the_chat_commands(command):
    assert _open().turn(command).reply == RENDER.chat_help


# -- 8: SUDS --------------------------------------------------------------------------------------

REQUEST = "最近工作压力好大，能给我一个练习试试吗"


@pytest.mark.parametrize(("text", "value"), [("3", 3), ("大概8分", 8), ("七", 7), ("10", 10)])
def test_a_rating_while_a_card_waits_sets_the_arousal(text, value):
    session = _open()
    assert session.turn(REQUEST).reply_kind is ReplyKind.CARD
    result = session.turn(text)
    assert result.inspect.get("suds") == value
    assert result.inspect["arousal"] == pytest.approx(value / 10)


def test_a_low_rating_is_heard_and_the_card_keeps_waiting():
    session = _open()
    session.turn(REQUEST)
    result = session.turn("3")
    assert result.stage is HelpStage.S_EMPOWER
    assert result.reply.split("\n\n")[0] in RENDER.suds_heard


def test_a_rating_at_the_somatic_line_retreats_to_stabilization():
    session = _open()
    session.turn(REQUEST)
    result = session.turn("9")
    assert result.stage is HelpStage.S_EXPLORE
    assert result.reply_kind is ReplyKind.CARD
    assert result.reply.split("\n\n")[0] in RENDER.suds_high


def test_a_number_with_no_card_waiting_is_no_rating():
    result = _open().turn("8")
    assert "suds" not in result.inspect
