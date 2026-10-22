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

# SOP 2 and SOP 4 run in both modes (P6-6a). SOP 2 passes with the packaged perception
# student. The round-3 student still raises one of SOP 4's ordinary turns to L2 (a false
# alarm), so its model-mode run is a strict xfail and a better student fails the suite
# until it moves to BOTH_MODES.
BOTH_MODES = pytest.mark.parametrize(
    "mode_flags", [pytest.param([], id="rules"), pytest.param(["--model"], id="model")]
)
BOTH_MODES_MODEL_FALSE_ALARM = pytest.mark.parametrize(
    "mode_flags",
    [
        pytest.param([], id="rules"),
        pytest.param(
            ["--model"],
            id="model",
            marks=pytest.mark.xfail(
                strict=True, reason="model false alarm: the student raises an ordinary turn to L2"
            ),
        ),
    ],
)

# -- SOP 1: first-visit covenant (age gate first, ruling 22) ---------------------------------


def test_sop1_covenant_then_first_session(run_cli, data_home):
    answers = ["1", "1", "小林", "阿柳", "", "考试、前任", "5", "2", "跳过"]
    run = run_cli(["chat"], [*answers, "今天上班好累", "/exit"])
    assert run.code == 0
    out = run.out
    # Disclaimer, then the 18+ gate, then names, persona, taboo topics, region, timezone,
    # and the optional consent last; nothing personal is asked before the age gate.
    markers = ["我已阅读并同意", "年满 18 周岁", "怎么称呼你", "温和包裹", "考试、前任、体重"]
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
    assert run.code == 0 and run.sessions == []
    assert "没有你的同意" in run.out
    assert not (data_home / PROFILE_FILENAME).exists()


def test_sop1_minor_is_refused_now_and_on_every_later_launch(run_cli, data_home):
    first = run_cli(["chat"], ["1", "2", "小林"])
    assert first.code == 0 and first.sessions == []
    assert "12355" in first.out and "怎么称呼你" not in first.out
    record = json.loads((data_home / PROFILE_FILENAME).read_text(encoding="utf-8"))
    assert record["age_gate_refused_at"] is not None and record["region"] is None

    again = run_cli(["chat"], ["1", "1", "我其实成年了"])
    assert again.code == 0 and again.sessions == []
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
HESITATION = "我今天真的提不起劲做这个"


@BOTH_MODES_MODEL_FALSE_ALARM
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


def test_onboarding_answers_cover_the_cn_default(run_cli, data_home):
    run = run_cli(["chat"], ONBOARD_CN)
    assert run.code == 0
    profile = ProfileStore(data_home).load()
    assert profile is not None and profile.region == UserRegion("CN", "Asia/Shanghai")
