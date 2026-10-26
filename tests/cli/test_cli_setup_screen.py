"""A crisis sentence typed while setting up is never taken as an answer (QA 2026-10-26 #4).

Onboarding, ``olivia profile``, ``olivia health`` and ``olivia safety-plan`` screen every
reply first, as ``olivia chat`` screens a turn; at L2 or above the region's numbers (the
global ones before a region is chosen) come with one gentle line, and the user chooses
to go on or to leave. The sentences are the QA report's own.
"""

from __future__ import annotations

import pytest
from cli_support import ONBOARD_CN, save_profile

from olivia import cli
from olivia.core.chang import setup_screen
from olivia.core.chang.onboarding import load_onboarding_text
from olivia.core.chang.profile import ProfileStore
from olivia.core.chang.safety_plan import SafetyPlanStore, load_safety_plan_text
from olivia.core.chang.setup_screen import SetupScreen
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
TEXT = load_onboarding_text()
GO_ON, LEAVE = "1", "2"


def _numbers_then_choice(out: str, first_number: str) -> None:
    """The gentle line, then the numbers, then the question; in that order."""
    assert out.index(cli.SETUP_CRISIS) < out.index(first_number) < out.index(cli.SETUP_CHOICE)


def _saved():
    profile = ProfileStore().load()
    assert profile is not None
    return profile


# -- onboarding ------------------------------------------------------------------------------


def test_a_crisis_sentence_on_the_disclaimer_shows_the_global_numbers(run_cli, data_home):
    run = run_cli(["chat", "--rules"], ["我想死了不想活了", LEAVE])
    assert run.code == 1 and not run.results
    _numbers_then_choice(run.out, "112")
    assert "求助资源 · 其他地区（ZZ）" in run.out
    assert TEXT.hints["unrecognized"] not in run.out  # no longer "我没太看懂"
    assert run.lines[-1] == cli.SETUP_LEFT
    assert cli.GOODBYE not in run.out
    assert not data_home.exists() or not list(data_home.rglob("profile.json"))


def test_a_crisis_sentence_as_a_name_is_not_taken(run_cli, data_home):
    run = run_cli(
        ["chat", "--rules"], ["1", "1", "", "我不想活了", GO_ON, "小林", *ONBOARD_CN[4:], "/exit"]
    )
    assert run.code == 0
    assert "好的，我不想活了" not in run.out
    _numbers_then_choice(run.out, "112")
    after = run.out[run.out.index(cli.SETUP_RETRY) :]
    assert "你希望我怎么称呼你" in after  # the question again
    assert _saved().user_name == "小林"


def test_a_crisis_sentence_as_a_taboo_topic_is_not_saved(run_cli, data_home):
    lines = ["1", "1", "", "小林", "", "", "不想活了", GO_ON, "考试", "1", "跳过", "/exit"]
    run = run_cli(["chat", "--rules"], lines)
    assert run.code == 0
    assert _saved().taboo_topics == ("考试",)
    _numbers_then_choice(run.out, "112")


def test_after_the_region_the_regions_numbers_are_shown(run_cli, data_home):
    lines = ["1", "1", "", "小林", "", "", "", "1", "真想睡过去不醒了", LEAVE]
    run = run_cli(["chat", "--rules"], lines)
    assert run.code == 1
    _numbers_then_choice(run.out, "12356")
    assert "求助资源 · 中国大陆（CN）" in run.out
    assert "睡过去" not in run.out


def test_end_of_input_at_the_choice_leaves(run_cli, data_home):
    run = run_cli(["chat", "--rules"], ["我不想活了"])
    assert run.code == 1 and run.lines[-1] == cli.SETUP_LEFT


def test_the_choice_asks_again_and_screens_its_own_reply(run_cli, data_home):
    run = run_cli(["chat", "--rules"], ["我不想活了", "嗯？", "我想死", LEAVE])
    assert cli.SETUP_CHOICE_UNKNOWN in run.out
    assert run.out.count(cli.SETUP_CRISIS) == 2  # the numbers again for the second one
    assert run.lines[-1] == cli.SETUP_LEFT


@pytest.mark.parametrize("reply", ["1", "１", "继续", "1。"])
def test_going_on_is_understood(run_cli, data_home, reply):
    run = run_cli(["chat", "--rules"], ["我不想活了", reply, "2"])
    assert cli.SETUP_RETRY in run.out


def test_an_ordinary_onboarding_screens_nothing(run_cli, data_home):
    run = run_cli(["chat"], [*ONBOARD_CN, "/exit"])
    assert run.code == 0 and cli.SETUP_CRISIS not in run.out


@pytest.mark.parametrize(("argv", "student"), [(["chat", "--rules"], False), (["chat"], True)])
def test_onboarding_screens_like_the_chat_that_follows(run_cli, monkeypatch, argv, student):
    seen: list[bool] = []
    real = cli.SetupScreen

    def spy(tax, *, student: bool = True, screen=None):
        seen.append(student)
        return real(tax, student=student, screen=screen)

    monkeypatch.setattr(cli, "SetupScreen", spy)
    run_cli(argv, ["我不想活了", LEAVE])
    assert seen == [student]


# -- olivia profile, health, safety-plan -------------------------------------------------------


def test_profile_never_takes_a_crisis_sentence_as_a_name(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["profile"], ["1", "我不想活了", GO_ON, "林林"])
    assert run.code == 0
    assert _saved().user_name == "林林"
    _numbers_then_choice(run.out, "12356")
    assert run.out.count("你希望我怎么称呼你") == 2  # asked again


def test_profile_topics_leave_without_saving(run_cli, data_home):
    save_profile(data_home, taboo_topics=("考试",))
    run = run_cli(["profile"], ["3", "不想活了", LEAVE])
    assert run.code == 0 and run.lines[-1] == cli.SETUP_LEFT
    assert _saved().taboo_topics == ("考试",)


def test_health_never_reads_a_crisis_sentence_back(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["health"], ["真想睡过去不醒了", GO_ON, ""])
    assert run.code == 0
    assert "睡过去" not in run.out
    _numbers_then_choice(run.out, "12356")
    assert run.lines[-1] == TEXT.health["unchanged"]


def test_health_does_not_read_an_unknown_reply_back(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["health"], ["猫猫狗狗", ""])
    assert "猫猫狗狗" not in run.out
    assert TEXT.hints["clinical_unknown"] in run.out


def test_the_safety_plan_keeps_a_warning_sign_after_the_numbers(run_cli, data_home):
    """The plan's sections are where such words belong: the numbers come once, nothing
    is asked, and the entry is kept."""
    save_profile(data_home)
    lines = ["我想死的念头又来了", "开始想死的时候", "", "", "", "", "把那盒安眠药交给室友保管", ""]
    run = run_cli(["safety-plan"], lines)
    assert run.code == 0
    assert run.out.index(cli.SETUP_CRISIS) < run.out.index("12356") < run.out.index(cli.SETUP_KEPT)
    assert run.out.count(cli.SETUP_CRISIS) == 1 and cli.SETUP_CHOICE not in run.out
    plan = SafetyPlanStore().load()
    assert plan is not None
    assert plan.warning_signs == ("我想死的念头又来了", "开始想死的时候")
    assert plan.environment == ("把那盒安眠药交给室友保管",)


def test_leaving_the_safety_plan_after_the_numbers_saves_nothing(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["safety-plan"], ["我想死的念头又来了"])
    assert run.code == 0 and cli.SETUP_CRISIS in run.out
    assert run.lines[-1] == load_safety_plan_text().command["left"]
    assert SafetyPlanStore().load() is None


# -- the screen itself -------------------------------------------------------------------------


ORDINARY = (
    TEXT.consent_sentence,
    *TEXT.region_labels.values(),
    *TEXT.persona_labels.values(),
    *TEXT.clinical_labels.values(),
    *TEXT.disclosure_labels.values(),
    "小林",
    "张老师",
    "Olivia",
    "考试、前任、体重",
    "跳过",
    "Asia/Shanghai",
    "整夜睡不着觉",
    "听一首喜欢的歌",
    "楼下的小公园",
)
CRISIS = ("我想死了不想活了", "我不想活了", "不想活了", "真想睡过去不醒了")


@pytest.mark.parametrize("student", [False, True])
def test_the_reports_sentences_alarm_and_setup_words_do_not(student):
    screen = SetupScreen(TAX, student=student)
    assert all(screen.alarms(text) for text in CRISIS)
    assert not [text for text in ORDINARY if screen.alarms(text)]


def test_menu_numbers_are_not_screened(monkeypatch):
    screen = SetupScreen(TAX, student=False)
    for reply in ("", "1", "2, 3", "  ", "0"):
        assert not screen.alarms(reply)
    assert screen._screen is None  # nothing built, no model loaded


def test_a_missing_student_leaves_the_rules(monkeypatch):
    from olivia.core.perception import student as student_module

    monkeypatch.setattr(
        student_module, "default_student", lambda: student_module.StudentLoad(None, "missing")
    )
    screen = SetupScreen(TAX, student=True)
    assert screen.alarms("我不想活了")
    assert not screen.alarms("小林")


def test_a_screen_that_fails_counts_as_an_alarm():
    class Broken:
        def assess(self, _text: str) -> None:
            raise RuntimeError("broken")

    assert SetupScreen(TAX, screen=Broken()).alarms("小林")  # type: ignore[arg-type]


def test_the_setup_wording_passes_willow():
    willow = load_language_data(TAX).willow
    for text in (
        cli.SETUP_CRISIS,
        cli.SETUP_RETRY,
        cli.SETUP_LEFT,
        cli.SETUP_CHOICE,
        cli.SETUP_KEPT,
    ):
        assert apply_willow(text, ContentKind.NORMAL, willow) == text
        assert "！" not in text and "!" not in text
    assert setup_screen.ALARM_LEVEL.name == "L2"
