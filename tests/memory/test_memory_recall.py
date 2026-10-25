"""Bringing back a note in the conversation (F15; PRD MIYI-04, SDD §3.3)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from importlib import resources

import pytest

from olivia.cli import inspect_panel
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.crypto.vault import Vault
from olivia.core.memory.ledger import Ledger, NoteEntry, SessionSummary
from olivia.core.memory.notes import load_note_cues
from olivia.core.memory.recall import RecallOutcome, query_terms, recall_note
from olivia.core.memory.recorder import SessionRecorder
from olivia.core.memory.text import MemoryTextError, load_memory_text
from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, UserRegion
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.perception.signals import NoteRecall
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
STUB = RuleStub(TAX, load_perception_lexicon(TAX))
CALM = CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE1", False, ())
IGNORE = load_note_cues().recall_ignore
TEXT = load_memory_text()
SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 25, 20, 0, tzinfo=SHANGHAI)
MOVERS = "周四下午要去见搬家公司的人"
RENT = "下周一交房租"
DOCTOR = "王医生的电话在抽屉里"


def _note(letter: str, text: str, days_ago: float) -> NoteEntry:
    return NoteEntry(letter * 24, text, NOW - timedelta(days=days_ago))


NOTES = (_note("a", MOVERS, 3), _note("b", RENT, 1), _note("c", DOCTOR, 40))


# -- the recognition signal (rule phrases, the same in both modes) ----------------------------


@pytest.mark.parametrize(
    "text",
    ["我上次让你记住什么了", "你帮我记的那个是什么", "我讓你記住的是什麼", "你都记了什么呀"],
)
def test_explicit_note_questions(text):
    assert STUB.perceive(text, CALM)[1].note_recall is NoteRecall.EXPLICIT


@pytest.mark.parametrize("text", ["周四要见的那个人是谁来着", "那部电影叫什么来着"])
def test_forgotten_fact_questions(text):
    assert STUB.perceive(text, CALM)[1].note_recall is NoteRecall.QUESTION


@pytest.mark.parametrize(
    "text",
    [
        "我昨天跟他吵架来着",  # bare 来着 is a past-tense marker
        "我没让你记住什么",  # negated
        "我记住了他说的话",
        "记住：周四见搬家公司的人",  # a note request, not a question about one
        "今天上班好累",
    ],
)
def test_not_note_questions(text):
    assert STUB.perceive(text, CALM)[1].note_recall is None


def test_no_recall_phrase_starts_with_a_note_cue():
    cues = load_note_cues()
    lexicon = load_perception_lexicon(TAX)
    for phrase in (*lexicon.note_recall, *lexicon.note_recall_questions):
        assert cues.find(phrase + "：x") is None, phrase


# -- choosing the note (notes only; SDD §3.3 order within them) -------------------------------


def test_a_specific_question_gets_the_matching_note():
    found = recall_note("周四要见的那个人是谁来着", NOTES, NOW, IGNORE)
    assert found.outcome is RecallOutcome.FOUND and found.note == NOTES[0]
    found = recall_note("你帮我记的那个电话在哪来着", NOTES, NOW, IGNORE)
    assert found.outcome is RecallOutcome.FOUND and found.note == NOTES[2]  # 40 days: no decay


def test_a_general_question_gets_the_newest_note():
    found = recall_note("我上次让你记住什么了", NOTES, NOW, IGNORE)
    assert found.outcome is RecallOutcome.LATEST and found.note == NOTES[1]
    assert query_terms("我上次让你记住什么了", IGNORE).strip() == ""


def test_traditional_script_is_folded_on_both_sides():
    notes = (_note("d", "週四下午見搬家公司", 2),)
    found = recall_note("周四要见的是谁来着", notes, NOW, IGNORE)
    assert found.outcome is RecallOutcome.FOUND and found.note == notes[0]
    assert recall_note("我讓你記住的是什麼", NOTES, NOW, IGNORE).outcome is RecallOutcome.LATEST


def test_an_unrelated_note_is_never_read_back():
    found = recall_note("我让你记住的那个生日是哪天来着", NOTES, NOW, IGNORE)
    assert found.outcome is RecallOutcome.NO_MATCH and found.note is None


def test_no_notes():
    assert recall_note("我上次让你记住什么了", (), NOW, IGNORE).outcome is RecallOutcome.NONE


def test_the_question_words_leave_a_gap():
    # "记住" removed must not join "上" and "周" into a gram that is not in the message.
    assert "上周" not in query_terms("上记住周", IGNORE)


# -- the recorder answers in the reply ---------------------------------------------------------


def _profile() -> PersonaProfile:
    return PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )


class Chat:
    def __init__(self, ledger: Ledger, *, student: bool = False) -> None:
        self.now = NOW
        clock = lambda: self.now  # noqa: E731
        self.session = Session.open(
            TAX, _profile(), rng=random.Random(7), now=clock, student=student
        )
        self.recorder = SessionRecorder(ledger, self.session.state.session_id, clock)

    def say(self, message: str):
        self.now += timedelta(minutes=1)
        return self.recorder.observe(message, self.session.turn(message))


@pytest.fixture
def ledger(tmp_path, keychain):
    return Ledger(tmp_path, Vault(tmp_path, keychain))


def _found(note: str) -> str:
    return TEXT.replies["recall_found"].replace("{note}", note)


def test_a_note_comes_back_in_the_reply_only(ledger):
    chat = Chat(ledger)
    chat.say(f"记住：{MOVERS}")
    chat.say("今天上班好累")
    result = chat.say("周四要见的那个人是谁来着")
    assert result.reply == _found(MOVERS) + TEXT.replies["note_continue"]
    assert result.inspect["note_recall"] == "question"
    assert result.inspect["note_recall_result"] == "found"
    panel = "\n".join(inspect_panel(result))
    assert "调出笔记 question（found）" in panel
    assert "周四" not in panel and "搬家" not in panel
    for value in result.inspect.values():
        assert "搬家" not in str(value)
    chat.recorder.close()
    summaries = [e for e in ledger.entries() if not isinstance(e, NoteEntry)]
    raw = "\n".join(ledger.read_markdown(e.entry_id) for e in summaries)
    assert "搬家" not in raw  # the summary never holds the note it brought back


def test_explicit_questions_are_always_answered(ledger):
    chat = Chat(ledger)
    none = chat.say("我上次让你记住什么了")
    assert none.reply == TEXT.replies["recall_none"] + TEXT.replies["note_continue"]
    chat.say(f"记住：{MOVERS}")
    chat.say(f"记住：{RENT}")
    latest = chat.say("我上次让你记住什么了")
    expected = TEXT.replies["recall_latest"].replace("{note}", RENT)
    assert latest.reply == expected + TEXT.replies["note_continue"]
    missing = chat.say("我让你记住的那个生日是哪天来着")
    assert missing.reply == TEXT.replies["recall_no_match"] + TEXT.replies["note_continue"]
    assert MOVERS not in missing.reply and RENT not in missing.reply


def test_a_forgotten_fact_without_a_matching_note_is_ordinary_talk(ledger):
    chat = Chat(ledger)
    chat.say(f"记住：{MOVERS}")
    result = chat.say("那部电影叫什么来着")
    assert MOVERS not in result.reply
    assert "note_recall_result" not in result.inspect
    for key in ("recall_no_match", "recall_none", "recall_unavailable"):
        assert TEXT.replies[key] not in result.reply


def test_summaries_are_never_recalled(ledger):
    crisis = SessionSummary(
        started_at=NOW - timedelta(days=1),
        ended_at=NOW - timedelta(days=1),
        stage_path=(HelpStage.S_READY, HelpStage.S_CRISIS),
        spectra=(),
        methods=(),
        crisis_level=CrisisLevel.L3,
    )
    ledger.append_summary(crisis, key="old")
    chat = Chat(ledger)
    result = chat.say("我上次让你记住什么了")
    assert result.reply == TEXT.replies["recall_none"] + TEXT.replies["note_continue"]
    assert TEXT.summary.crisis.removeprefix("- ") not in result.reply


def test_without_a_keychain_it_says_so(tmp_path, keychain):
    keychain.broken = NoKeychainError("none")
    chat = Chat(Ledger(tmp_path, Vault(tmp_path, keychain)))
    explicit = chat.say("我上次让你记住什么了")
    assert explicit.reply == TEXT.replies["recall_unavailable"] + TEXT.replies["note_continue"]
    question = chat.say("周四要见的那个人是谁来着")
    # Maybe not about a note at all: the session's reply stays, the line follows it.
    assert question.reply.endswith("\n\n" + TEXT.replies["recall_unavailable"])
    assert len(question.reply) > len(TEXT.replies["recall_unavailable"]) + 2
    assert question.inspect["note_recall_result"] == "unavailable"


def test_a_locked_keychain_says_so(tmp_path, ledger, keychain):
    ledger.add_note(MOVERS, now=NOW)
    chat = Chat(Ledger(tmp_path, Vault(tmp_path, keychain)))  # no data key cached yet
    keychain.broken = KeychainUnavailableError("locked")
    result = chat.say("我上次让你记住什么了")
    assert result.reply.startswith(TEXT.replies["recall_unavailable"])
    assert MOVERS not in result.reply


def test_never_while_a_crisis_lasts(ledger):
    chat = Chat(ledger)
    chat.say(f"记住：{MOVERS}")
    chat.say("我写了一封遗书")
    result = chat.say("我上次让你记住什么了")
    assert result.in_crisis and result.reply_kind is ReplyKind.CRISIS
    assert result.inspect["note_recall"] is None
    assert MOVERS not in result.reply


def test_not_on_a_turn_that_screens_l1(ledger):
    chat = Chat(ledger)
    chat.say(f"记住：{MOVERS}")
    result = chat.say("我上次让你记住什么了，活着好累")
    assert result.inspect["note_recall"] is None
    assert MOVERS not in result.reply


def test_not_when_the_turn_asks_for_a_method(ledger):
    chat = Chat(ledger)
    chat.say(f"记住：{MOVERS}")
    result = chat.say("给我一个方法，我上次让你记住什么了")
    assert result.inspect["note_recall"] is None
    assert MOVERS not in result.reply


def test_model_mode_reads_the_same_signal(ledger):
    chat = Chat(ledger, student=True)
    chat.say(f"记住：{MOVERS}")
    result = chat.say("周四要见的那个人是谁来着")
    assert result.inspect["note_recall"] == "question"
    assert result.reply.startswith(_found(MOVERS))


# -- the wording ---------------------------------------------------------------------------------


def test_only_the_two_found_lines_have_the_note_slot(tmp_path):
    for key, line in TEXT.replies.items():
        assert ("{note}" in line) is (key in ("recall_found", "recall_latest")), key
    doc = (resources.files("olivia") / "data/templates/memory.yaml").read_text(encoding="utf-8")
    (tmp_path / "memory.yaml").write_text(doc.replace('「{note}」。"', '。"', 1), encoding="utf-8")
    with pytest.raises(MemoryTextError):
        load_memory_text(tmp_path)
