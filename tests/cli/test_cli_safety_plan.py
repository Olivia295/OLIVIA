"""``olivia safety-plan`` and the plan in ``olivia chat`` (next-phase B10, decision D8).

Scripted input fills, shows, edits and clears the plan; it is sealed at rest, never saved
without a keychain, shown in a crisis reply, and the suggestion line comes once per
device. Names and numbers are made up.
"""

from __future__ import annotations

from datetime import timedelta

from cli_support import L3_SENTENCE, NOW, save_profile

from olivia.core.chang.safety_plan import (
    MAX_ENTRY_CHARS,
    MAX_NAME_CHARS,
    SAFETY_PLAN_FILENAME,
    SAFETY_PLAN_STORE,
    SUGGESTED_FILENAME,
    Contact,
    SafetyPlan,
    SafetyPlanStore,
    load_safety_plan_text,
)
from olivia.core.crypto.errors import NoKeychainError
from olivia.core.models import HelpStage
from olivia.core.session import ReplyKind

TEXT = load_safety_plan_text()
CMD = TEXT.command

# Section by section: one warning sign, two coping entries (one too long first), one
# distraction, two people (an unreadable phone first, then none for the second), one
# environment entry.
FILL = [
    "整夜睡不着觉",
    "",
    "听" * (MAX_ENTRY_CHARS + 1),
    "听一首喜欢的歌",
    "洗个热水澡",
    "",
    "楼下的小公园",
    "",
    "阿青",
    "打给她",
    "138-0000-0000",
    "小周",
    "",
    "",
    "把那盒东西交给阿青保管",
    "",
]
FILLED = SafetyPlan(
    warning_signs=("整夜睡不着觉",),
    coping=("听一首喜欢的歌", "洗个热水澡"),
    distraction=("楼下的小公园",),
    people=(Contact("阿青", "138-0000-0000"), Contact("小周")),
    environment=("把那盒东西交给阿青保管",),
)


def _stored(home) -> SafetyPlan | None:
    return SafetyPlanStore(home).load()


def test_fill_show_edit_clear_round_trip(run_cli, data_home):
    save_profile(data_home)
    filled = run_cli(["safety-plan"], FILL)
    assert filled.code == 0
    assert CMD["intro"].splitlines()[0] in filled.out
    assert _fill_count(filled.out, "entry_too_long") == 1
    assert CMD["phone_invalid"] in filled.out
    assert CMD["saved"] in filled.out
    assert _stored(data_home) == FILLED
    # Encrypted at rest: no 4-byte fragment of any entry is in the file.
    raw = (data_home / SAFETY_PLAN_FILENAME).read_bytes()
    for line in ("整夜睡不着觉", "听一首喜欢的歌", "楼下的小公园", "阿青", "138-0000-0000"):
        data = line.encode("utf-8")
        for i in range(len(data) - 3):
            assert data[i : i + 4] not in raw, line
    assert (data_home / "keys" / f"{SAFETY_PLAN_STORE}.key").is_file()

    shown = run_cli(["safety-plan"], [""])
    assert shown.code == 0
    assert CMD["show_heading"] in shown.out and CMD["unchanged"] in shown.out
    for title in TEXT.titles.values():
        assert title in shown.out
    # Section 5 is shown here, in the command.
    assert "· 把那盒东西交给阿青保管" in shown.out and "· 阿青：138-0000-0000" in shown.out

    edited = run_cli(["safety-plan"], ["1", "2", "出门散步十分钟", "", "5", "0", ""])
    assert edited.code == 0 and CMD["saved"] in edited.out
    assert CMD["current_heading"] in edited.out
    assert _stored(data_home) == SafetyPlan(
        warning_signs=FILLED.warning_signs,
        coping=("出门散步十分钟",),
        distraction=FILLED.distraction,
        people=FILLED.people,
    )

    kept = run_cli(["safety-plan"], ["1", "4", "", ""])
    assert CMD["unchanged"] in kept.out
    assert _stored(data_home) is not None and _stored(data_home).people == FILLED.people  # type: ignore[union-attr]

    cancelled = run_cli(["safety-plan"], ["2", ""])
    assert CMD["unchanged"] in cancelled.out and _stored(data_home) is not None

    cleared = run_cli(["safety-plan"], ["2", "1"])
    assert cleared.code == 0 and CMD["cleared"] in cleared.out
    assert not (data_home / SAFETY_PLAN_FILENAME).exists()
    assert not (data_home / "keys" / f"{SAFETY_PLAN_STORE}.key").exists()


def _fill_count(out: str, key: str) -> int:
    text = CMD[key].replace("{max_chars}", str(MAX_ENTRY_CHARS))
    return out.count(text)


def _people_only(run_cli, data_home, people_lines):
    """Skip sections 1-3 and 5; ``people_lines`` are the replies in section 4."""
    save_profile(data_home)
    run = run_cli(["safety-plan"], ["", "", "", *people_lines, ""])
    assert run.code == 0, run.out
    return run


def test_a_name_and_phone_on_one_line_are_both_saved(run_cli, data_home):
    """Dogfood I10: "表姐 13800000000" was refused as too long, and the next Enter
    skipped the section, so no contact was saved."""
    run = _people_only(run_cli, data_home, ["表姐 13800000000", ""])
    assert CMD["person_with_phone"].replace("{name}", "表姐") in run.out
    assert CMD["person_phone"].replace("{name}", "表姐") not in run.out  # not asked again
    assert _stored(data_home) == SafetyPlan(people=(Contact("表姐", "13800000000"),))


def test_a_phone_number_alone_asks_for_the_name_and_keeps_the_number(run_cli, data_home):
    run = _people_only(run_cli, data_home, ["13800000000", "表姐", ""])
    assert CMD["name_for_phone"] in run.out
    assert _stored(data_home) == SafetyPlan(people=(Contact("表姐", "13800000000"),))


def test_a_long_name_is_explained_and_the_phone_kept(run_cli, data_home):
    long_name = "楼上的王阿姨也就是妈妈的老朋友"
    assert len(long_name) > MAX_NAME_CHARS
    run = _people_only(run_cli, data_home, [f"{long_name} 13900000000", "王阿姨", ""])
    assert CMD["name_too_long"].replace("{max_chars}", str(MAX_NAME_CHARS)) in run.out
    assert _stored(data_home) == SafetyPlan(people=(Contact("王阿姨", "13900000000"),))


def test_enter_after_a_long_name_says_it_was_not_saved_and_goes_on(run_cli, data_home):
    """Never a silent drop: Enter after the too-long notice says so, then the section
    goes on, so the next person can still be written."""
    run = _people_only(run_cli, data_home, ["楼上的王阿姨也就是妈妈的老朋友", "", "阿青", "", ""])
    assert CMD["entry_not_saved"] in run.out
    assert _stored(data_home) == SafetyPlan(people=(Contact("阿青"),))


def test_enter_after_a_long_entry_says_it_was_not_saved(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(
        ["safety-plan"], ["听" * (MAX_ENTRY_CHARS + 1), "", "整夜睡不着觉", "", "", "", "", ""]
    )
    assert CMD["entry_not_saved"] in run.out
    assert _stored(data_home) == SafetyPlan(warning_signs=("整夜睡不着觉",))


def test_editing_an_empty_section_says_it_is_not_written_yet(run_cli, data_home):
    """Dogfood P7: "现在写的是：" with nothing after it."""
    save_profile(data_home)
    SafetyPlanStore(data_home).save(SafetyPlan(warning_signs=("整夜睡不着觉",)))
    run = run_cli(["safety-plan"], ["1", "4", "阿青", "", "", ""])
    assert CMD["current_empty"] in run.out
    assert CMD["current_heading"] not in run.out
    assert _stored(data_home) == SafetyPlan(
        warning_signs=("整夜睡不着觉",), people=(Contact("阿青"),)
    )


def test_skipping_everything_saves_nothing(run_cli, data_home):
    save_profile(data_home)
    result = run_cli(["safety-plan"], [""] * 5)
    assert result.code == 0 and CMD["nothing_saved"] in result.out
    assert not (data_home / SAFETY_PLAN_FILENAME).exists()


def test_end_of_input_keeps_what_was_written(run_cli, data_home):
    # QA q4 SP-12: what was typed before the input ended is saved, and said so.
    save_profile(data_home)
    result = run_cli(["safety-plan"], ["整夜睡不着觉"])
    assert result.code == 0 and result.lines[-1] == CMD["left_saved"]
    plan = SafetyPlanStore(data_home).load()
    assert plan is not None and plan.warning_signs == ("整夜睡不着觉",)


def test_end_of_input_before_anything_is_written_saves_nothing(run_cli, data_home):
    save_profile(data_home)
    result = run_cli(["safety-plan"], [])
    assert result.code == 0 and result.lines[-1] == CMD["left"]
    assert not (data_home / SAFETY_PLAN_FILENAME).exists()


def test_no_keychain_saves_nothing_and_says_so(run_cli, data_home, keychain):
    save_profile(data_home)
    keychain.broken = NoKeychainError("none")
    result = run_cli(["safety-plan"], FILL)
    assert result.code == 1
    assert CMD["no_keychain"] in result.out
    assert CMD["intro"].splitlines()[0] not in result.out
    assert not (data_home / SAFETY_PLAN_FILENAME).exists()
    assert not (data_home / "keys" / f"{SAFETY_PLAN_STORE}.key").exists()


def test_needs_an_adult_profile(run_cli, data_home):
    first = run_cli(["safety-plan"], FILL)
    assert first.code == 1 and CMD["not_onboarded"] in first.out
    save_profile(data_home, age_confirmed_18_plus=False, region=None, age_gate_refused_at=NOW)
    minor = run_cli(["safety-plan"], FILL)
    assert minor.code == 1 and CMD["adults_only"] in minor.out
    assert not (data_home / SAFETY_PLAN_FILENAME).exists()


# -- in olivia chat ---------------------------------------------------------------------------


def test_chat_shows_the_plan_in_a_crisis_reply(run_cli, data_home):
    save_profile(data_home)
    SafetyPlanStore(data_home).save(FILLED)
    before = (data_home / SAFETY_PLAN_FILENAME).read_bytes()
    chat = run_cli(["chat", "--rules", "--inspect"], ["今天上班好累", L3_SENTENCE])
    ordinary, crisis = chat.results
    assert crisis.reply_kind is ReplyKind.CRISIS
    assert crisis.inspect["safety_plan_shown"] is True
    assert ordinary.inspect["safety_plan_shown"] is False
    assert TEXT.crisis_intro in crisis.reply and "· 阿青：138-0000-0000" in crisis.reply
    assert "把那盒东西交给阿青保管" not in chat.out and "整夜睡不着觉" not in chat.out
    assert "安全计划 已展示" in "\n".join(chat.panel)
    for number in ("110", "120", "12356"):
        assert number in crisis.reply
    # The chat never writes the plan.
    assert (data_home / SAFETY_PLAN_FILENAME).read_bytes() == before


def test_chat_suggests_the_command_once_per_device(run_cli, data_home):
    save_profile(data_home)
    script = ["今天上班好累", "给我一个方法吧", "/done"]
    first = run_cli(["chat", "--rules"], script)
    closing = first.results[-1]
    assert closing.stage is HelpStage.S_CLOSING
    assert closing.reply.endswith(TEXT.suggestion)
    assert first.out.count(TEXT.suggestion) == 1
    assert (data_home / SUGGESTED_FILENAME).read_bytes() == b""
    second = run_cli(["chat", "--rules"], script, now=NOW + timedelta(days=1))
    assert TEXT.suggestion not in second.out


def test_no_suggestion_with_a_plan_or_in_a_crisis(run_cli, data_home):
    save_profile(data_home)
    crisis = run_cli(["chat", "--rules"], [L3_SENTENCE, "我现在安全了", "嗯", "嗯", "嗯"])
    assert TEXT.suggestion not in crisis.out
    assert not (data_home / SUGGESTED_FILENAME).exists()
    SafetyPlanStore(data_home).save(FILLED)
    planned = run_cli(["chat", "--rules"], ["今天上班好累", "给我一个方法吧", "/done"])
    assert TEXT.suggestion not in planned.out


def test_no_suggestion_without_a_keychain(run_cli, data_home, keychain):
    save_profile(data_home)
    keychain.broken = NoKeychainError("none")
    chat = run_cli(["chat", "--rules"], ["今天上班好累", "给我一个方法吧", "/done"])
    assert chat.code == 0 and TEXT.suggestion not in chat.out
