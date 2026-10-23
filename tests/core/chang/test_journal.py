"""Self-ratings and the weekly journal: parsing, the card, when it is due (B6, ruling 30).

Every test uses the in-memory keychain from conftest; nothing reaches the OS keychain.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from olivia.core.chang.journal import (
    MIN_SESSIONS,
    WINDOW,
    JournalTextError,
    Week,
    gather,
    is_due,
    load_journal_text,
    parse_rating,
    parse_yes_no,
    render_journal,
    run_command,
)
from olivia.core.crypto.errors import NoKeychainError
from olivia.core.crypto.vault import Vault
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate, phone_like_runs
from olivia.core.memory.ledger import JournalEntry, Ledger, MethodRecord, SessionSummary
from olivia.core.memory.text import load_memory_text
from olivia.core.methods.bandit import Feedback
from olivia.core.models import CrisisLevel, HelpStage
from olivia.core.taxonomy import load_taxonomy

SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 25, 20, 30, tzinfo=SHANGHAI)
TEXT = load_journal_text()
MEMORY = load_memory_text()
TITLES = {"12:tipp_breathing": "冷水呼吸", "30:grounding": "五感着陆"}
PATH = (HelpStage.S_READY, HelpStage.S_EXPLORE, HelpStage.S_CLOSING)


@pytest.fixture
def ledger(tmp_path, keychain):
    return Ledger(tmp_path, Vault(tmp_path, keychain), method_titles=TITLES)


def _summary(days_ago: float, **overrides: object) -> SessionSummary:
    start = NOW - timedelta(days=days_ago)
    fields: dict[str, object] = {
        "started_at": start,
        "ended_at": start + timedelta(minutes=20),
        "stage_path": PATH,
        "spectra": (),
        "methods": (),
    }
    fields.update(overrides)
    return SessionSummary(**fields)  # type: ignore[arg-type]


def _seed(ledger: Ledger) -> None:
    """A fixed week: three sessions, a note, plus one session too old to count."""
    ledger.append_summary(
        _summary(
            6,
            spectra=("05", "02"),
            methods=(MethodRecord("12:tipp_breathing", Feedback.HELPFUL),),
            self_rating_before=4,
            self_rating_after=6,
        ),
        key="a",
    )
    ledger.append_summary(
        _summary(
            3,
            spectra=("02",),
            methods=(
                MethodRecord("30:grounding", Feedback.NOT_NOW),
                MethodRecord("12:tipp_breathing", Feedback.UNHELPFUL),
            ),
            self_rating_before=5,
        ),
        key="b",
    )
    ledger.append_summary(_summary(1, spectra=("05", "07")), key="c")
    ledger.append_summary(_summary(9, spectra=("11",), self_rating_before=1), key="old")
    ledger.add_note("下周三面试", now=NOW - timedelta(days=2))


# -- parsing ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "rating"),
    [
        ("0", 0),
        ("10", 10),
        (" 7 ", 7),
        ("７", 7),
        ("05", 5),
        ("11", None),
        ("-1", None),
        ("七", None),
        ("", None),
        ("   ", None),
        ("6.5", None),
        ("6分", None),
        ("100", None),
    ],
)
def test_rating_parsing(raw, rating):
    assert parse_rating(raw) == rating


@pytest.mark.parametrize(
    ("raw", "answer"),
    [("好", True), ("好的。", True), ("有", True), ("Yes", True), ("不用", False)]
    + [("没有", False), ("先不了！", False), ("", None), ("今天好累", None)],
)
def test_yes_no_parsing(raw, answer):
    assert parse_yes_no(raw, TEXT) is answer


# -- wording ----------------------------------------------------------------------------------


def test_every_sentence_passes_willow_and_the_gate():
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    for sentence in TEXT.all_texts():
        assert apply_willow(sentence, ContentKind.NORMAL, data.willow) == sentence, sentence
        assert gate.reasons(sentence, kind=ContentKind.NORMAL, stage=HelpStage.S_READY) == ()
        assert "！" not in sentence and "!" not in sentence
        assert phone_like_runs(sentence) == (), sentence
        # No numbers of its own beyond the 0-10 scale in the rating question.
        assert set(re.findall(r"\d+", sentence)) <= {"0", "10"}, sentence


def test_text_file_is_validated(tmp_path: Path):
    (tmp_path / "journal.yaml").write_text("version: 1\nprompts: {}\n", encoding="utf-8")
    with pytest.raises(JournalTextError):
        load_journal_text(tmp_path)


# -- the card ---------------------------------------------------------------------------------


def test_journal_from_a_seeded_ledger(ledger):
    _seed(ledger)
    week = gather(ledger, NOW)
    assert len(week.sessions) == 3 and week.notes == 1 and week.journals == ()
    assert render_journal(week, TEXT, MEMORY, TITLES) == "\n".join(
        [
            "## 这一周的小结",
            "这一周聊过的点滴，都整理在这里了。",
            "- 聊天：3 次",
            "- 心情分（开始 → 结束）：4 → 6、5 → 没打",
            "- 有 1 次聊完以后，心情分比开始时高。",
            "- 常聊到的：累和耗尽、低落和没劲、关系里的牵挂",
            "- 试过的小练习：冷水呼吸（有帮助、不太合适）、五感着陆（先收进锦囊）",
            "- 你让我记住的话：1 条，原话都留在记忆账本里。",
            "下一周也慢慢来，累了就停下来歇一歇。",
        ]
    )


def test_journal_card_holds_no_note_text_and_passes_the_gate(ledger):
    _seed(ledger)
    card = render_journal(gather(ledger, NOW), TEXT, MEMORY, TITLES)
    assert "面试" not in card
    tax = load_taxonomy()
    gate = OutputGate(tax, load_language_data(tax))
    for line in card.splitlines():
        assert gate.reasons(line, kind=ContentKind.NORMAL, stage=HelpStage.S_READY) == (), line


def test_a_week_without_ratings_or_exercises(ledger):
    ledger.append_summary(_summary(2), key="a")
    card = render_journal(gather(ledger, NOW), TEXT, MEMORY).splitlines()
    assert TEXT.card["no_ratings"] in card and TEXT.card["no_methods"] in card
    assert not any(line.startswith("- 常聊到的") for line in card)
    assert not any("记住" in line for line in card)


def test_a_week_with_a_crisis_uses_the_steadier_voice(ledger):
    ledger.append_summary(_summary(2, crisis_level=CrisisLevel.L3), key="a")
    card = render_journal(gather(ledger, NOW), TEXT, MEMORY).splitlines()
    assert card[1] == TEXT.card["intro_solemn"]
    assert card[-1] == TEXT.card["closing_solemn"]
    assert TEXT.card["closing"] not in card


def test_an_empty_week_has_no_card():
    with pytest.raises(ValueError):
        render_journal(Week(NOW, (), 0, ()), TEXT, MEMORY)


# -- when it is due ---------------------------------------------------------------------------


def test_due_needs_two_sessions_in_the_rolling_window(ledger):
    assert MIN_SESSIONS == 2 and timedelta(days=7) == WINDOW
    ledger.append_summary(_summary(1), key="a")
    ledger.append_summary(_summary(8), key="too-old")
    assert not is_due(gather(ledger, NOW))
    ledger.append_summary(_summary(5), key="b")
    assert is_due(gather(ledger, NOW))


@pytest.mark.parametrize(("days_since", "due"), [(6, False), (8, True)])
def test_due_waits_a_week_after_the_last_journal(ledger, days_since, due):
    ledger.append_summary(_summary(1), key="a")
    ledger.append_summary(_summary(2), key="b")
    ledger.record_journal(NOW - timedelta(days=days_since), shown=True, helpful=True)
    assert is_due(gather(ledger, NOW)) is due


def test_a_declined_offer_also_waits_a_week(ledger):
    ledger.append_summary(_summary(1), key="a")
    ledger.append_summary(_summary(2), key="b")
    ledger.record_journal(NOW - timedelta(days=1), shown=False)
    assert not is_due(gather(ledger, NOW))


# -- olivia journal ---------------------------------------------------------------------------


class Script:
    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.said: list[str] = []

    def ask(self) -> str | None:
        return self.answers.pop(0) if self.answers else None

    def say(self, line: str) -> None:
        self.said.append(line)


def test_command_on_an_empty_ledger(ledger):
    script = Script()
    assert run_command(script.ask, script.say, ledger, NOW) == 0
    assert script.said == [TEXT.replies["empty"]]
    assert ledger.entries() == ()


def test_command_shows_the_card_and_records_the_answer(ledger):
    _seed(ledger)
    script = Script("没有")
    assert run_command(script.ask, script.say, ledger, NOW, method_titles=TITLES) == 0
    assert script.said[0].startswith("## 这一周的小结")
    assert script.said[-2:] == [TEXT.prompts["helpful"], TEXT.replies["helpful_thanks"]]
    (journal,) = [e for e in ledger.entries() if isinstance(e, JournalEntry)]
    assert (journal.offered_at, journal.shown, journal.helpful) == (NOW, True, False)


def test_command_skipped_answer_keeps_the_shown_record(ledger):
    _seed(ledger)
    script = Script("")
    run_command(script.ask, script.say, ledger, NOW)
    (journal,) = [e for e in ledger.entries() if isinstance(e, JournalEntry)]
    assert journal.shown and journal.helpful is None
    assert TEXT.replies["helpful_thanks"] not in script.said


def test_command_without_a_keychain(tmp_path, keychain):
    keychain.broken = NoKeychainError("none")
    script = Script()
    ledger = Ledger(tmp_path, Vault(tmp_path, keychain))
    assert run_command(script.ask, script.say, ledger, NOW) == 1
    assert script.said == [TEXT.replies["unavailable"]]
