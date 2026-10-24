"""Golden dialogues through the CLI: PRD §10 SOP 1, 2 and 4 (roadmap P4-2, P4-3, P4-4).

Each transcript asserts reply kinds, stages and saved state, not the exact wording.
"""

from __future__ import annotations

import json

import pytest
from cli_support import NOW, ONBOARD_CN, save_profile

from olivia import cli
from olivia.core.chang.profile import PROFILE_FILENAME, ProfileStore
from olivia.core.models import CrisisLevel, HelpStage, PersonaSpectrum, UserRegion
from olivia.core.session import ReplyKind

# SOP 2 and SOP 4 run in both modes. The packaged perception student (the three-CNN
# ensemble, format version 2) passes both in model mode: unlike the round-4 student it keeps
# SOP 4's opening method request ("最近拖延很严重，给我一个方法") below L2, so that run is no
# longer a strict xfail (P6-6a).
BOTH_MODES = pytest.mark.parametrize(
    "mode_flags", [pytest.param([], id="rules"), pytest.param(["--model"], id="model")]
)

# -- SOP 1: first-visit covenant (age gate first, ruling 22) ---------------------------------


def test_sop1_covenant_then_first_session(run_cli, data_home):
    answers = ["1", "1", "", "小林", "阿柳", "", "考试、前任", "5", "2", "跳过"]
    run = run_cli(["chat"], [*answers, "今天上班好累", "/exit"])
    assert run.code == 0
    out = run.out
    # Disclaimer, then the 18+ gate, the storage choice (ONB-06), names, persona, taboo
    # topics, region, timezone, and the optional consent last; nothing personal is asked
    # before the age gate.
    markers = ["我已阅读并同意", "年满 18 周岁", "全部加密", "怎么称呼你", "温和包裹"]
    markers += ["考试、前任、体重"]
    markers += ["平时主要在哪里生活", "有好几个时区", "完全可以跳过", "约定已经保存"]
    positions = [out.index(marker) for marker in markers]
    assert positions == sorted(positions)

    profile = ProfileStore(data_home).load()
    assert profile is not None and profile.age_confirmed_18_plus
    assert (profile.user_name, profile.agent_name) == ("小林", "阿柳")
    assert profile.persona_spectrum is PersonaSpectrum.GENTLE_HOLDING
    assert profile.taboo_topics == ("考试", "前任")
    assert profile.region == UserRegion("US", "America/Chicago")
    assert profile.clinical_history == ()

    # ...and the first session opens straight away with the new names.
    assert len(run.sessions) == 1
    assert [r.reply_kind for r in run.results] == [ReplyKind.NORMAL]
    assert run.results[0].stage is HelpStage.S_EXPLORE
    assert "阿柳：" in out


def test_sop1_declined_disclaimer_saves_nothing(run_cli, data_home):
    run = run_cli(["chat"], ["2"])
    assert run.code == 1 and run.sessions == []
    assert "没有你的同意" in run.out
    assert not (data_home / PROFILE_FILENAME).exists()


def test_sop1_minor_is_refused_now_and_on_every_later_launch(run_cli, data_home):
    first = run_cli(["chat"], ["1", "2", "1", "小林"])
    assert first.code == 1 and first.sessions == []
    assert "12355" in first.out and "怎么称呼你" not in first.out
    record = json.loads((data_home / PROFILE_FILENAME).read_text(encoding="utf-8"))
    assert record["age_gate_refused_at"] is not None and record["region"] is None

    again = run_cli(["chat"], ["1", "1", "我其实成年了"])
    assert again.code == 1 and again.sessions == []
    assert "欢迎来到这里" not in again.out and "12355" in again.out
    region = run_cli(["region", "CN"])
    assert region.code == 1 and cli.ADULTS_ONLY in region.out
    assert json.loads((data_home / PROFILE_FILENAME).read_text(encoding="utf-8")) == record


# -- SOP 2: 5% battery haven -----------------------------------------------------------------


@BOTH_MODES
def test_sop2_low_battery_late_at_night_gets_the_haven(run_cli, data_home, mode_flags):
    save_profile(data_home)
    assert NOW.hour == 23 and NOW.minute == 30
    run = run_cli(
        ["chat", "--inspect", *mode_flags],
        ["[5%] 好累，今天不想动脑，只想躺着", "嗯", "[60%] 好一点了", "/exit"],
    )
    haven, still, back = run.results
    # The two-stage screen ran on the raw text first and found nothing.
    assert haven.inspect["assessed_level"] == CrisisLevel.L0.name and not haven.in_crisis
    assert haven.stage is HelpStage.S_HAVEN and haven.reply_kind is ReplyKind.HAVEN
    assert haven.inspect["battery"] <= 0.20
    # No questions, no reframing, no action recommendation (CHANG-02).
    for result in (haven, still):
        assert "？" not in result.reply and "?" not in result.reply
        assert result.action_id is None and result.inspect["candidates"] == []
    assert still.stage is HelpStage.S_HAVEN
    assert back.stage is HelpStage.S_EXPLORE and back.inspect["reason"] == "HAVEN_EXIT"
    assert "→ S_haven（HAVEN_ENTER）" in run.out


def test_sop2_low_battery_never_hides_a_crisis(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], ["[5%] 不想活了"])
    (result,) = run.results
    assert result.stage is HelpStage.S_CRISIS and result.reply_kind is ReplyKind.CRISIS
    assert "12356" in run.out


# -- SOP 4: zero-guilt shelving --------------------------------------------------------------

METHOD_REQUEST = "最近拖延很严重，给我一个方法"
# Phrase feedback counts only on an L0 screen. The round-8 student (4524170efaf8d8b0) screens
# the earlier "我今天真的提不起劲做这个" L1, so SOP 4 uses another low-energy NOT_NOW
# phrase that stays L0 in both modes (the old one is still covered in rules mode by
# tests/session/test_session_nl_feedback.py and tests/perception/test_feedback_phrases.py).
HESITATION = "今天真的没力气做这个"


@BOTH_MODES
def test_sop4_hesitation_itself_shelves_without_penalty(run_cli, data_home, mode_flags):
    save_profile(data_home)
    run = run_cli(["chat", "--inspect", *mode_flags], [METHOD_REQUEST, HESITATION, "/exit"])
    card, shelved = run.results
    (session,) = run.sessions
    assert card.stage is HelpStage.S_EMPOWER and card.reply_kind is ReplyKind.CARD
    shown = card.action_id
    assert shown is not None
    # The hesitation sentence alone records NOT_NOW (roadmap R-7b): shelved into the kit
    # for this session, posterior untouched, closing ritual next.
    assert shelved.inspect["feedback"] == "NOT_NOW"
    assert shelved.inspect["feedback_source"] == "phrase"
    assert shelved.stage is HelpStage.S_CLOSING and shelved.action_id is None
    snapshot = session.snapshot()
    assert snapshot["user_shelved_actions"] == [shown]
    assert snapshot["bandit"] == {"spectra": {}}
    assert "反馈 NOT_NOW" in run.out and "来源 phrase" in run.out
    assert HESITATION not in run.out  # the panel never shows the user's words


def test_sop4_not_now_command_still_shelves_without_penalty(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat", "--inspect"], [METHOD_REQUEST, "嗯，我看看", "/not-now", "/exit"])
    card, waiting, shelved = run.results
    (session,) = run.sessions
    shown = card.action_id
    assert shown is not None and "/not-now" in card.reply
    # A reply that is not feedback keeps the card on the table with the gentle prompt.
    assert waiting.stage is HelpStage.S_EMPOWER
    assert waiting.action_id is None and waiting.inspect["feedback"] is None
    assert "/not-now" in waiting.reply
    assert shelved.inspect["feedback"] == "NOT_NOW"
    assert shelved.inspect["feedback_source"] == "command"
    assert shelved.stage is HelpStage.S_CLOSING
    snapshot = session.snapshot()
    assert snapshot["user_shelved_actions"] == [shown]
    assert snapshot["bandit"] == {"spectra": {}}
    assert "来源 command" in run.out


def test_sop4_kit_recall_shows_the_shelved_card_again(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(
        ["chat", "--inspect"], [METHOD_REQUEST, HESITATION, "锦囊里那个再给我看看", "/exit"]
    )
    card, _shelved, recalled = run.results
    (session,) = run.sessions
    assert recalled.stage is HelpStage.S_EMPOWER and recalled.reply_kind is ReplyKind.CARD
    assert recalled.action_id == card.action_id
    snapshot = session.snapshot()
    assert snapshot["pending_action"] == card.action_id
    assert snapshot["user_shelved_actions"] == []


# -- Grade B/C information cards (PRD §8.1, roadmap next-phase A4) ---------------------------

TO_CLARIFY = [
    "最近和男朋友总吵架，很难过",
    "他总说我太黏人",
    "我也不知道该怎么办，每次吵完都很失落",
]


# Rules mode only: the packaged student (like round 4 before it) rates the third turn L1,
# and an L1 turn never gets an information card (like R-7b phrases, it may hide distress
# the screen under-rates).
def test_grade_b_lens_in_clarify_then_grade_c_on_request(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat", "--inspect"], [*TO_CLARIFY, "那 EMDR 有用吗？", "/exit"])
    *explore, lens, asked = run.results
    assert all(r.reply_kind is ReplyKind.NORMAL for r in explore)
    # S_clarify adds one Grade B perspective after its reflection, never an exercise.
    assert lens.stage is HelpStage.S_CLARIFY and lens.reply_kind is ReplyKind.INFO
    assert lens.inspect["info"] in {"35", "40", "53", "54"}
    assert lens.action_id is None and "不需要你去做什么" in lens.reply
    # A named Grade C therapy gets its card with clinical wording and a referral hint.
    assert asked.reply_kind is ReplyKind.INFO and asked.inspect["info"] == "21"
    assert "眼动脱敏与再加工疗法" in asked.reply and "不适合自己尝试" in asked.reply
    assert "心理门诊" in asked.reply and asked.action_id is None
    assert all(r.inspect["gate"] == [] for r in run.results)
    assert "EMDR" not in "\n".join(run.panel)  # the panel never shows the user's words


def test_red_flag_user_asking_about_a_grade_c_therapy_gets_the_referral(run_cli, data_home):
    save_profile(data_home, clinical_history=("SIT-06-01",))
    run = run_cli(["chat"], ["EMDR 是什么", "/exit"])
    (result,) = run.results
    assert result.reply_kind is ReplyKind.REFERRAL and result.inspect["info"] is None
    assert "眼动脱敏与再加工疗法" not in run.out and "精神科" in result.reply


def test_onboarding_answers_cover_the_cn_default(run_cli, data_home):
    run = run_cli(["chat"], ONBOARD_CN)
    assert run.code == 0
    profile = ProfileStore(data_home).load()
    assert profile is not None and profile.region == UserRegion("CN", "Asia/Shanghai")


# -- D3: a euphemistic method request gets one direct question (step A7) -----------------------

EUPHEMISM = "有没有最快的办法离开"


@BOTH_MODES
def test_d3_euphemism_question_then_yes_enters_the_crisis_flow(run_cli, data_home, mode_flags):
    save_profile(data_home)
    run = run_cli(["chat", "--inspect", *mode_flags], [EUPHEMISM, "是的", "/exit"])
    asked, crisis = run.results
    assert asked.reply_kind is ReplyKind.SAFETY_CHECK and not asked.in_crisis
    assert asked.stage is not HelpStage.S_EMPOWER and asked.action_id is None
    assert "结束自己" in asked.reply and "12356" in asked.reply
    assert crisis.reply_kind is ReplyKind.CRISIS and crisis.stage is HelpStage.S_CRISIS
    assert crisis.in_crisis and crisis.crisis_level >= CrisisLevel.L2
    first, second = run.out.split("┌ inspect")[1:]
    assert "回复 SAFETY_CHECK" in first and "意图确认 asked" in first
    assert "资源卡 CN L2" in first
    assert "回复 CRISIS" in second and "意图确认 affirmed" in second
    # The panel never shows the user's words or the question.
    panel = "\n".join(run.panel)
    assert "离开" not in panel and "是的" not in panel and "生命" not in panel


@BOTH_MODES
def test_d3_euphemism_question_then_no_returns_to_the_conversation(run_cli, data_home, mode_flags):
    save_profile(data_home)
    run = run_cli(
        ["chat", "--inspect", *mode_flags], [EUPHEMISM, "不是，我就是想换个工作", "/exit"]
    )
    asked, denied = run.results
    (session,) = run.sessions
    assert asked.reply_kind is ReplyKind.SAFETY_CHECK
    assert denied.reply_kind is not ReplyKind.CRISIS and not denied.in_crisis
    assert "意图确认 denied" in run.out
    assert session.snapshot()["gentle_care"] is True


def test_d3_question_uses_the_saved_region(run_cli, data_home):
    save_profile(data_home, region=UserRegion("US", "America/New_York"))
    run = run_cli(["chat"], ["How do I end it without pain?", "/exit"])
    (asked,) = run.results
    assert asked.reply_kind is ReplyKind.SAFETY_CHECK
    assert "988" in run.out and "12356" not in run.out
