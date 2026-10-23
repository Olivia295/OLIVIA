"""Release gate G-1 (PRD §11.2): every feature works with the network cut off.

One scripted walk through the whole product, in process through ``olivia.cli.main``, with
``OLIVIA_HOME`` under ``tmp_path`` and the in-memory keychain (``tests/conftest.py``).
Every way to open a connection or resolve a name raises and is recorded for the whole
walk; the walk then asserts that nothing tried. Each step checks its visible effect
structurally (reply kinds, stages, stored records, the text the command owns), not copy.

Covered: onboarding (disclaimer, age gate, encryption switch, names, persona choice, taboo,
region, the health consent sentence, clinical history and the D2 checklist), an ordinary
talk, a card and ``/done``, the closing self-rating, a 「记住：」 note, a crisis turn and its
confirmed exit, the care greeting on the next chat, the opening self-rating, the journal
offer after two sessions, ``olivia journal``, ``olivia safety-plan`` and the plan in a
crisis reply, ``olivia health``, ``olivia persona``, ``olivia resources``, ``olivia
region``, ``olivia memory``, ``olivia forget --entry``, ``chat --model`` (the packaged
perception student) and ``olivia forget --all`` followed by a fresh onboarding.
"""

from __future__ import annotations

import re
import socket
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from cli_support import L3_SENTENCE, NOW, Run, files_under

from olivia import cli
from olivia.core.chang.journal import load_journal_text
from olivia.core.chang.onboarding import load_onboarding_text
from olivia.core.chang.profile import ProfileStore
from olivia.core.chang.safety_plan import load_safety_plan_text
from olivia.core.memory.forget import load_forget_text
from olivia.core.memory.ledger import JournalEntry, Ledger, NoteEntry, SummaryEntry
from olivia.core.memory.text import load_memory_text
from olivia.core.models import PROFILE_CONTRAINDICATIONS, CrisisLevel, HelpStage, PersonaSpectrum
from olivia.core.session import ReplyKind
from olivia.core.taxonomy import load_taxonomy

ONB = load_onboarding_text()
JOURNAL = load_journal_text()
PLAN = load_safety_plan_text()
FORGET = load_forget_text()
MEMORY = load_memory_text()
RED_FLAGS = tuple(load_taxonomy().red_flags())
CARDIO, SAFETY, _PSYCHOSIS = PROFILE_CONTRAINDICATIONS
# The checklist numbers the three disclosures after the red flags (``olivia health`` too).
SAFETY_NO = len(RED_FLAGS) + 2
CARDIO_NO = len(RED_FLAGS) + 1

# Every onboarding step answered: accept, 18+, encrypt the whole profile, user name,
# agent name, persona 1 (explicit), no taboo topics, region 1 (CN), the consent sentence,
# no clinical history, one D2 disclosure (the checklist numbers its three items 1-3).
ONBOARD_ALL = ["1", "1", "2", "小林", "", "1", "", "1", ONB.consent_sentence, "", "2"]
NOTE = "下周三面试，我有点紧张"
# L3 exit (tests/safety/sessions.yaml s06): an explicit confirmation, then three safe turns.
CRISIS_EXIT = ["谢谢你 我现在安全了", "我去喝点热水", "室友在陪我看电视", "有点困了"]
# One entry per safety-plan section (an empty line ends it), a person with a made-up number.
PLAN_FILL = [
    *("整夜睡不着觉", ""),
    *("听一首喜欢的歌", ""),
    *("楼下的小公园", ""),
    *("阿青", "138-0000-0000", ""),
    *("把那盒东西交给阿青保管", ""),
]

_NETWORK_ENTRY_POINTS = (
    "socket",
    "create_connection",
    "getaddrinfo",
    "gethostbyname",
    "gethostbyname_ex",
    "socketpair",
)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Cut the network for the whole test; every attempt is recorded and raises."""
    attempts: list[str] = []

    def blocked(name: str) -> Callable[..., object]:
        def refuse(*args: object, **_kwargs: object) -> object:
            attempts.append(f"{name}{args[:2]!r}")
            raise OSError(f"network access is forbidden in the G-1 test ({name})")

        return refuse

    for name in _NETWORK_ENTRY_POINTS:
        monkeypatch.setattr(socket, name, blocked(name))
    # The guard is live: a connection attempt raises and is recorded.
    with pytest.raises(OSError):
        socket.create_connection(("example.com", 443))
    assert attempts == ["create_connection(('example.com', 443),)"]
    attempts.clear()
    return attempts


def _ledger(home: Path) -> Ledger:
    return Ledger(home, ProfileStore(home).vault)


def _entry_number(memory_out: str, verbatim: str) -> int:
    """The number ``olivia memory`` shows for the entry whose text is ``verbatim``."""
    lines = memory_out.splitlines()
    at = lines.index(f"   {verbatim}")
    for line in reversed(lines[:at]):
        found = re.match(r"^(\d+)\. ", line)
        if found:
            return int(found.group(1))
    raise AssertionError(f"no numbered entry above {verbatim!r}")


def _replies(run: Run) -> list[ReplyKind]:
    return [r.reply_kind for r in run.results]


def test_every_feature_works_offline(run_cli, data_home, keychain, no_network):
    # -- first visit: onboarding, talk, card, note, crisis and its exit -----------------------
    first = run_cli(
        ["chat", "--inspect"],
        [
            *ONBOARD_ALL,
            "4",  # the opening self-rating
            "今天上班好累",
            "给我一个方法",
            "/done",
            "我明天试试",  # S_closing -> S_ready: the segment closes and asks the after-rating
            "8",
            f"记住：{NOTE}",
            L3_SENTENCE,
            *CRISIS_EXIT,
            "/exit",
        ],
    )
    assert first.code == 0 and first.lines[-1] == cli.GOODBYE
    profile = ProfileStore(data_home).load()
    assert profile is not None and profile.age_confirmed_18_plus
    assert profile.enable_at_rest_encryption
    assert profile.persona_spectrum is PersonaSpectrum.GENTLE_HOLDING
    assert profile.region is not None and profile.region.country_code == "CN"
    assert profile.clinical_history == () and profile.contraindications == (SAFETY,)
    raw = b"".join(p.read_bytes() for p in files_under(data_home))
    assert SAFETY.encode() not in raw and NOTE.encode() not in raw

    kinds = _replies(first)
    talk = first.results[0]
    assert talk.reply_kind is ReplyKind.NORMAL and talk.stage is HelpStage.S_EXPLORE
    carded = [r for r in first.results if r.reply_kind is ReplyKind.CARD]
    assert carded and carded[0].action_id is not None
    stages = [r.stage for r in first.results]
    assert HelpStage.S_CLOSING in stages and HelpStage.S_READY in stages
    assert MEMORY.replies["note_saved"] in first.out
    crisis_at = kinds.index(ReplyKind.CRISIS)
    crisis = first.results[crisis_at]
    assert crisis.crisis_level is CrisisLevel.L3 and crisis.in_crisis
    assert crisis.resource_card is not None and "12356" in crisis.reply
    assert all(r.in_crisis for r in first.results[crisis_at:-1])
    assert not first.results[-1].in_crisis  # the confirmed exit
    assert first.panel  # --inspect printed its panel

    entries = _ledger(data_home).entries()
    assert [e.text for e in entries if isinstance(e, NoteEntry)] == [NOTE]
    summaries = [e.summary for e in entries if isinstance(e, SummaryEntry)]
    assert (4, 8) in [(s.self_rating_before, s.self_rating_after) for s in summaries]
    assert any(s.entered_crisis for s in summaries)

    # -- the next day: the care greeting opens the chat ----------------------------------------
    second = run_cli(["chat", "--inspect"], ["今天还行", "/exit", "6"], now=NOW + timedelta(days=1))
    assert second.code == 0
    assert "关怀问候 是" in "\n".join(second.panel)
    assert JOURNAL.prompts["offer"] not in second.out  # a care opening stays alone
    assert second.out.count(JOURNAL.prompts["rating"]) == 1  # only the closing one

    # -- two days on: the opening rating and the journal offer -------------------------------
    third = run_cli(
        ["chat"], ["5", "好", "有", "今天还行", "/exit", ""], now=NOW + timedelta(days=2)
    )
    assert third.code == 0
    out = third.out
    rating, offer = JOURNAL.prompts["rating"], JOURNAL.prompts["offer"]
    assert out.index(rating) < out.index(offer) < out.index(JOURNAL.prompts["helpful"])
    assert third.texts == ["今天还行"]
    journals = [e for e in _ledger(data_home).entries() if isinstance(e, JournalEntry)]
    assert len(journals) == 1 and journals[0].shown and journals[0].helpful is True

    later = NOW + timedelta(days=2, hours=1)
    journal = run_cli(["journal"], ["没有"], now=later)
    assert journal.code == 0 and JOURNAL.prompts["helpful"] in journal.out
    assert len([e for e in _ledger(data_home).entries() if isinstance(e, JournalEntry)]) == 2

    # -- the safety plan, then a crisis reply that shows it ------------------------------------
    filled = run_cli(["safety-plan"], PLAN_FILL, now=later)
    assert filled.code == 0 and PLAN.command["saved"] in filled.out
    planned = run_cli(["chat", "--inspect"], [L3_SENTENCE, "/exit"], now=later)
    (plan_crisis,) = planned.results
    assert plan_crisis.reply_kind is ReplyKind.CRISIS
    assert plan_crisis.inspect["safety_plan_shown"] is True
    assert PLAN.crisis_intro in plan_crisis.reply and "阿青" in plan_crisis.reply
    assert "安全计划 已展示" in "\n".join(planned.panel)

    # -- health, persona, resources, region ----------------------------------------------------
    health = run_cli(["health"], [f"{CARDIO_NO} {SAFETY_NO}"], now=later)
    assert health.code == 0 and health.lines[-1] == ONB.health["saved"]
    stored = ProfileStore(data_home).load()
    assert stored is not None and stored.contraindications == (CARDIO, SAFETY)

    shown = run_cli(["persona"], now=later)
    assert shown.code == 0 and shown.out.count(cli.PERSONA_CURRENT_MARK) == 1
    switched = run_cli(["persona", "2"], now=later)
    assert switched.code == 0
    stored = ProfileStore(data_home).load()
    assert stored is not None and stored.persona_spectrum is PersonaSpectrum.ZEN_PHILOSOPHER

    resources = run_cli(["resources"], now=later)
    assert resources.code == 0
    assert "12356" in resources.out and "（CN）" in resources.lines[0]
    region = run_cli(["region"], now=later)
    assert region.code == 0 and "（CN）" in region.out

    # -- memory and forgetting one entry -------------------------------------------------------
    memory = run_cli(["memory"], now=later)
    assert memory.code == 0 and f"   {NOTE}" in memory.lines
    number = _entry_number(memory.out, NOTE)
    forgot = run_cli(["forget", "--entry", str(number), "--yes"], now=later)
    assert forgot.code == 0
    assert forgot.lines[0] == FORGET.forget["done_entry"].replace("{n}", str(number))
    assert _ledger(data_home).notes() == ()
    assert NOTE not in run_cli(["memory"], now=later).out

    # -- the perception student (--model) ------------------------------------------------------
    modelled = run_cli(["chat", "--model", "--inspect"], ["今天上班好累", "/exit"], now=later)
    assert modelled.code == 0 and modelled.results
    risk_model = modelled.results[0].inspect["risk_model"]
    assert isinstance(risk_model, str) and risk_model.startswith("student:")
    assert modelled.results[0].inspect["risk_model_reason"] is None

    # -- forget everything: no file, no keychain item, onboarding again ------------------------
    gone = run_cli(["forget", "--all", "--yes"], now=later)
    assert gone.code == 0 and gone.lines[-1] == FORGET.forget["done_all"]
    assert files_under(data_home) == [] and keychain.items == {}
    again = run_cli(["chat"], [], now=later)
    assert again.code == 1 and cli.CHAT_HINT not in again.out  # input ended before setup
    assert ProfileStore(data_home).load() is None

    # -- nothing tried the network -------------------------------------------------------------
    assert no_network == []
