"""Crisis flow, someone else's risk and the session, round 6 (re-test 2026-10-29).

* q2 第 2 节: a rhetorical no as a clause of its own ("开什么玩笑，……") and a no with a
  reassurance in the same clause ("没有的你放心") are noes; a yes after the rhetorical no,
  an unsure word or a risk cue after either keeps the answer unclear.
* q2 第 2 节: the "X得想死" figure next to a clause where someone else does something every
  day asks first; a run of days in the user's own words still keeps it L2.
* q2 第 3 节, q4 F4: a status report (well, at home, someone there, nothing done) and a
  Cantonese "now safe" confirm; an explicit confirmation given as the answer to the
  question enters the crisis flow already confirmed.
* q2 第 1 节: someone else's plan the rules miss gets the card to pass on, urgent; a
  question in the turns after it ("开口第一句怎么讲", Cantonese 点) gets concrete steps.
* q3 第四节: a new request while a card waits is answered, not met with the /done prompt;
  "别总问我感受" holds for the rest of the session.

Every example message is written here; none comes from an evaluation set or the re-test.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, UserRegion
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
FIGURE = "ASK_INTENT_HYPERBOLE_DIE"
CRISIS_OPENER = "我已经撑不住了，真的不想活了"


class Scripted:
    """A risk model that rates the listed messages and everything else L0."""

    def __init__(self, levels: dict[str, tuple[CrisisLevel, float]]) -> None:
        self.levels = levels

    def predict(self, text: str) -> RiskPrediction:
        level, score = self.levels.get(text, (CrisisLevel.L0, 0.05))
        return RiskPrediction(level, score, ())


def _open(*, model: object | None = None, region: str = "CN", seed: int = 5) -> Session:
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
        rng=random.Random(seed),
        now=lambda: NOW,
        model=model,  # type: ignore[arg-type]
    )


def _answer(text: str) -> IntentAnswer:
    """The D3 reading as the session takes it: a no that needs the F10 check gets it."""
    reading = read_answer(LEX.intent_answers, text, RULES.assess(text), RULES.assess)
    guarded = text if reading.guard_text is None else reading.guard_text
    if reading.reason_split and guarded and not RULES.clear_denial(guarded):
        return IntentAnswer.UNCLEAR
    return reading.answer


# -- q2 第 2 节: noes -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "开什么玩笑，我好着呢，只是这周事多",
        "怎么可能，我状态还行，就是有点忙",
        "不可能的，我周末还约了朋友吃饭",
        "怎么可能",
        "没有的你放心，我下个月还要搬新家",
        "不是的别担心，我就是想吐吐槽",
        "不会你放心吧，年底我还要回家过年",
    ],
)
def test_a_rhetorical_no_or_a_reassured_no_is_a_no(text: str) -> None:
    assert _answer(text) is IntentAnswer.DENIED


@pytest.mark.parametrize(
    "text",
    [
        "怎么可能不想呢",
        "开什么玩笑，我当然想过",
        "怎么可能，我确实想过好多次",
        "不可能的，可能有一点吧",
        "没有的你放心，反正药都备好了",
        "放心吧，再过几天就都结束了",
        "开什么玩笑，我早就活够了",
        "不是的别担心，但有时候会冒出来",
    ],
)
def test_a_yes_doubt_or_risk_after_it_keeps_the_answer_unclear(text: str) -> None:
    assert _answer(text) is not IntentAnswer.DENIED


@pytest.mark.parametrize("student", [False, True], ids=["rules", "model"])
def test_a_reassured_no_returns_to_the_ordinary_flow(student: bool) -> None:
    model = Scripted({}) if student else None
    session = _open(model=model)
    asked = session.turn("洗衣服洗得想死")
    assert asked.inspect["safety_check"] == "asked"
    assert not asked.in_crisis
    result = session.turn("没有的你放心，我下个月还要搬新家")
    assert result.inspect["safety_check"] == "denied"
    assert not result.in_crisis


# -- q2 第 2 节: the figure next to someone else's habit -----------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "剪片剪得想死，甲方天天改需求",
        "做题做得想死，家教老是拖堂",
        "排班排得想死，领导总是临时调人",
        "跑步跑得想死，教官每天加练",
    ],
)
def test_the_figure_beside_someone_elses_habit_asks_first(text: str) -> None:
    assessment = RULES.assess(text)
    assert assessment.level is CrisisLevel.L1
    assert FIGURE in assessment.cue_ids and assessment.asks_intent


@pytest.mark.parametrize(
    "text",
    [
        "剪片剪得想死，天天都是这样",
        "做题做得想死，我每天都这么想",
        "累得想死，感觉每天都一样",
        "排班排得想死，总是想一了百了",
        "跑步天天跑得想死",
    ],
)
def test_a_run_of_days_of_the_users_own_still_vetoes(text: str) -> None:
    assert RULES.assess(text).level >= CrisisLevel.L2


# -- q2 第 3 节, q4 F4: confirmations ------------------------------------------------------


def _tracker_confirms(text: str) -> bool:
    tracker = CrisisTracker(TAX, LEX)
    tracker.observe(RULES.assess(CRISIS_OPENER), CRISIS_OPENER)
    status = tracker.observe(RULES.assess(text), text)
    return status.in_crisis and not status.awaiting_confirmation


@pytest.mark.parametrize(
    "text",
    [
        "我好好的，在寝室，啥也没干",
        "没事，我在屋里，老公在旁边",
        "我挺好的，我妈在身边",
        "什么都没做，人就在家里",
        "我依家好安全",
        "我宜家冇事，喺屋企",
    ],
)
def test_a_status_report_confirms(text: str) -> None:
    assert _tracker_confirms(text)


@pytest.mark.parametrize(
    "text",
    [
        "我好好的",
        "人在宿舍，窗户关着",
        "我好好的，就是绳子还没扔",
        "在家里，还是很想死",
        "什么都没做，暂时而已",
        "我好好的，明天就难说了",
        "我依家喺楼顶",
        "我好好的吗？",
    ],
)
def test_one_status_or_a_danger_cue_is_no_confirmation(text: str) -> None:
    assert not _tracker_confirms(text)


def test_a_confirmation_as_the_answer_enters_the_crisis_flow_confirmed() -> None:
    opener = "要不我干脆找个没人的地方待着算了"
    session = _open(model=Scripted({opener: (CrisisLevel.L2, 0.4)}))
    asked = session.turn(opener)
    assert asked.inspect["safety_check"] == "asked"
    answer = session.turn("我现在是安全的")
    assert answer.in_crisis
    status = session._last_status
    assert status is not None and not status.awaiting_confirmation
    assert "我现在是安全的」" not in answer.reply
    nxt = session.turn("今天下午去超市买了点水果")
    assert "我现在是安全的」" not in nxt.reply


def test_a_rules_question_answered_with_a_confirmation_is_also_counted() -> None:
    session = _open()
    asked = session.turn("搬砖搬得想死")
    assert asked.inspect["safety_check"] == "asked"
    session.turn("嗯，我现在挺安全的")
    status = session._last_status
    assert status is not None
    assert not status.in_crisis or not status.awaiting_confirmation


# -- q2 第 1 节: someone else's plan --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "我堂哥昨天说他煤气都备好了，等这个月底",
        "我同桌讲她打算周日去水库那边，跟我说了再见",
        "我舍友说她准备从顶楼跳，时间都挑好了",
        "我叔叔说过几天要开车冲下山崖",
        "我前女友发消息说遗言写好了，今晚就走",
    ],
)
def test_someone_elses_plan_the_rules_miss_gets_the_urgent_card(text: str) -> None:
    assert names_plan(normalize(text))
    result = _open().turn(text)
    assert result.reply_kind is ReplyKind.RESOURCES
    assert result.inspect.get("resources_reply") == "third_party"
    assert not result.in_crisis
    assert "紧急电话" in result.reply


@pytest.mark.parametrize(
    "text",
    [
        "我堂哥说他月底去水库钓鱼",
        "我同桌说她周日要去跳绳比赛",
        "我舍友说她今晚在顶楼晾衣服",
        "我叔叔说过几天要开车去山里",
        "我前女友说明天跟我说再见就出国了",
    ],
)
def test_everyday_plans_are_no_plan(text: str) -> None:
    assert not names_plan(normalize(text))


@pytest.mark.parametrize(
    ("report", "question", "region"),
    [
        ("我室友跟我说她把安眠药都囤好了，周五就吃", "那我等下见到她，开口第一句怎么讲", "CN"),
        ("我朋友话佢听日去天台跳，佢已经写咗遗书", "咁我点同佢讲好", "HK"),
        ("我同事跟我说他准备这周末从桥上跳", "那我现在能做点什么", "CN"),
    ],
)
def test_a_question_after_the_card_gets_what_to_do(report: str, question: str, region: str) -> None:
    session = _open(region=region)
    first = session.turn(report)
    assert first.inspect.get("resources_reply") == "third_party"
    follow = session.turn(question)
    assert follow.reply_kind is ReplyKind.RESOURCES
    assert follow.inspect.get("resources_reply") == "third_party"
    assert not follow.in_crisis
    assert "紧急电话" in follow.reply


def test_how_to_say_it_gets_the_words_to_start_with() -> None:
    session = _open()
    session.turn("我表弟跟我讲他攒了一瓶药，下周就吃")
    follow = session.turn("我打电话过去的话，先说些什么")
    assert "你是不是" in follow.reply or "结束自己的生命" in follow.reply


# -- q3 第四节: the session ----------------------------------------------------------------


@pytest.mark.parametrize(
    "request_text",
    [
        "你能帮我理一理租房和买房各要考虑哪些吗",
        "陪我想想下周去医院复查要准备什么好吗",
    ],
)
def test_a_new_request_while_a_card_waits_is_answered(request_text: str) -> None:
    session = _open(seed=7)
    shown = session.turn("今天上班好累，给我一个方法")
    assert shown.reply_kind is ReplyKind.CARD
    result = session.turn(request_text)
    assert "/done" not in result.reply
    assert result.stage is HelpStage.S_EXPLORE
    assert result.inspect["feedback"] is None
    assert session.snapshot()["pending_action"] is None


@pytest.mark.parametrize("text", ["嗯，我看看", "这个练习要做几遍", "给我一个方法"])
def test_words_about_the_card_keep_it_waiting(text: str) -> None:
    session = _open(seed=7)
    shown = session.turn("今天上班好累，给我一个方法")
    assert shown.reply_kind is ReplyKind.CARD
    waiting = session.turn(text)
    assert "/done" in waiting.reply
    assert session.snapshot()["pending_action"] == shown.action_id


_FEELING_QUESTIONS = ("感受", "感觉", "心情", "什么滋味")


def test_no_more_feeling_questions_once_asked_not_to() -> None:
    session = _open(seed=3)
    session.turn("你别老问我心情了，我就是想闲聊几句")
    for text in (
        "今天中午吃了碗牛肉面，汤有点咸",
        "下午同事拉我去楼下买咖啡",
        "晚上打算早点睡，明天还要早起",
        "周末可能去爬山，看天气吧",
        "说起来最近楼下新开了家面包店",
    ):
        result = session.turn(text)
        assert result.reply_kind is ReplyKind.NORMAL, text
        closing = result.reply.split("\n\n")[-1]
        assert not any(word in closing for word in _FEELING_QUESTIONS), result.reply
        assert result.inspect["lock"] is True


# -- q2 第 1 节: joining someone else's plan ----------------------------------------------

_REPORT = "我表哥跟我说他把安眠药都囤好了，这周六就吃"


@pytest.mark.parametrize(
    "text",
    [
        "其实我也挺想跟他一起结束的",
        "那我和他一块儿走好了",
        "我们俩一起去死吧",
        "我也想陪他一起了断",
        "要不我同他一起解脱算了",
    ],
)
def test_wanting_to_go_along_with_them_enters_the_crisis_flow(text: str) -> None:
    session = _open()
    assert session.turn(_REPORT).inspect.get("resources_reply") == "third_party"
    result = session.turn(text)
    assert result.in_crisis
    assert result.reply_kind is ReplyKind.CRISIS


@pytest.mark.parametrize(
    "text",
    [
        "我想陪他一起去挂个急诊",
        "我和他一起把药扔掉了",
        "我们一起走出这段日子",
        "我跟他一起去散会儿步",
    ],
)
def test_going_along_to_get_help_is_no_crisis(text: str) -> None:
    session = _open()
    assert session.turn(_REPORT).inspect.get("resources_reply") == "third_party"
    assert not session.turn(text).in_crisis


def test_going_along_counts_only_after_the_card() -> None:
    assert not _open().turn("周末我想跟他一起走走").in_crisis
