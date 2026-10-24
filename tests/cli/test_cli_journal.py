"""``olivia chat`` self-ratings and the weekly journal; ``olivia journal`` (B6, ruling 30)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from cli_support import L3_SENTENCE, NOW, save_profile

from olivia import cli
from olivia.core.chang.journal import load_journal_text
from olivia.core.chang.profile import ProfileStore
from olivia.core.crypto.errors import NoKeychainError
from olivia.core.memory.ledger import LEDGER_DIRNAME, JournalEntry, Ledger, SummaryEntry
from olivia.core.models import HelpStage
from olivia.core.session import ReplyKind

TEXT = load_journal_text()
RATING = TEXT.prompts["rating"]
OFFER = TEXT.prompts["offer"]
HELPFUL = TEXT.prompts["helpful"]


def _ledger(home) -> Ledger:
    return Ledger(home, ProfileStore(home).vault)


def _summaries(home) -> list[SummaryEntry]:
    return [e for e in _ledger(home).entries() if isinstance(e, SummaryEntry)]


def _journals(home) -> list[JournalEntry]:
    return [e for e in _ledger(home).entries() if isinstance(e, JournalEntry)]


def _ratings(home) -> list[tuple[int | None, int | None]]:
    return [(e.summary.self_rating_before, e.summary.self_rating_after) for e in _summaries(home)]


def _two_sessions(run_cli, data_home) -> None:
    save_profile(data_home)
    run_cli(["chat"], ["4", "今天上班好累", "/exit", "6"])
    run_cli(["chat"], ["", "老板又临时加了好多活", "/exit", ""], now=NOW + timedelta(days=1))


# -- self-ratings -----------------------------------------------------------------------------


def test_ratings_before_and_after_are_kept_in_the_summary(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], ["4", "今天上班好累", "/exit", "7"])
    assert run.code == 0 and run.lines[-1] == cli.GOODBYE
    assert run.out.count(RATING) == 2
    assert run.out.index(cli.CHAT_HINT) < run.out.index(RATING)
    assert run.texts == ["今天上班好累"]
    assert _ratings(data_home) == [(4, 7)]


@pytest.mark.parametrize("answer", ["11", "-1", "七", ""])
def test_anything_but_0_to_10_is_a_skip_and_not_asked_again(run_cli, data_home, answer):
    save_profile(data_home)
    run = run_cli(["chat"], [answer, "今天上班好累", "/exit", answer])
    assert run.out.count(RATING) == 2
    assert _ratings(data_home) == [(None, None)]


def test_text_typed_at_the_rating_question_is_the_first_message(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], [L3_SENTENCE, "/exit"])
    assert run.texts == [L3_SENTENCE]
    assert run.results[0].reply_kind is ReplyKind.CRISIS
    assert run.out.count(RATING) == 1  # no after-rating once the session entered a crisis
    (entry,) = _summaries(data_home)
    assert entry.summary.entered_crisis
    assert (entry.summary.self_rating_before, entry.summary.self_rating_after) == (None, None)


def test_no_after_rating_once_a_session_entered_crisis(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], ["5", "今天上班好累", L3_SENTENCE, "/exit", "3"])
    assert run.out.count(RATING) == 1
    assert _ratings(data_home) == [(5, None)]


def test_no_after_rating_in_the_haven(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], ["5", "[5%] 好累，今天不想动脑，只想躺着", "/exit", "3"])
    assert run.results[-1].stage is HelpStage.S_HAVEN
    assert run.out.count(RATING) == 1
    assert _ratings(data_home) == [(5, None)]


def test_no_after_rating_at_end_of_input(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], ["5", "今天上班好累"])  # ends at EOF
    assert run.out.count(RATING) == 1 and run.lines[-1] == cli.GOODBYE
    assert _ratings(data_home) == [(5, None)]


def test_exit_right_away_asks_no_after_rating_and_writes_nothing(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], ["5", "/exit", "3"])
    assert run.out.count(RATING) == 1
    assert not (data_home / LEDGER_DIRNAME).exists()


def test_exit_at_the_opening_question_ends_the_chat(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], ["/exit", "今天上班好累"])
    assert run.code == 0 and run.texts == [] and run.lines[-1] == cli.GOODBYE


def test_the_state_machine_closing_asks_for_the_after_rating(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], ["3", "给我一个方法", "/done", "我明天试试", "8", "今天上班好累"])
    assert [r.stage for r in run.results][2] is HelpStage.S_READY
    assert run.out.count(RATING) == 2  # the opening one and the one after S_ready
    # The test clock stands still, so both segments start at the same moment and the
    # ledger's order between them falls to their random ids; compare as a multiset.
    assert sorted(_ratings(data_home), key=repr) == sorted([(3, 8), (None, None)], key=repr)


def test_text_at_the_closing_rating_goes_on_as_the_conversation(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], ["4", "今天上班好累", "/exit", "其实还想再说一句", "/exit", ""])
    assert run.texts == ["今天上班好累", "其实还想再说一句"]
    assert run.out.count(RATING) == 3
    assert _ratings(data_home) == [(4, None)]


def test_without_a_keychain_nothing_is_asked(run_cli, data_home, keychain):
    save_profile(data_home)
    keychain.broken = NoKeychainError("none")
    run = run_cli(["chat"], ["今天上班好累", "/exit"])
    assert RATING not in run.out and OFFER not in run.out
    assert run.texts == ["今天上班好累"]


# -- the journal at the opening ---------------------------------------------------------------


def test_one_session_is_not_enough_for_a_journal(run_cli, data_home):
    save_profile(data_home)
    run_cli(["chat"], ["4", "今天上班好累", "/exit", "6"])
    later = run_cli(["chat"], ["", "今天还行", "/exit", ""], now=NOW + timedelta(days=1))
    assert OFFER not in later.out


def test_two_sessions_bring_the_offer_and_yes_shows_it(run_cli, data_home):
    _two_sessions(run_cli, data_home)
    when = NOW + timedelta(days=2)
    run = run_cli(["chat"], ["5", "好", "有", "今天还行", "/exit", ""], now=when)
    out = run.out
    assert out.index(RATING) < out.index(OFFER) < out.index("## 这一周的小结") < out.index(HELPFUL)
    assert "- 聊天：2 次" in out and "- 心情分（开始 → 结束）：4 → 6" in out
    assert TEXT.replies["helpful_yes"] in out
    assert run.texts == ["今天还行"]
    (journal,) = _journals(data_home)
    assert journal.shown and journal.helpful is True
    assert journal.offered_at == when
    # Shown once in the window: the next opening does not offer it again.
    again = run_cli(["chat"], ["", "/exit"], now=NOW + timedelta(days=3))
    assert OFFER not in again.out


def test_declining_waits_a_week_and_says_how_to_find_it(run_cli, data_home):
    _two_sessions(run_cli, data_home)
    run = run_cli(["chat"], ["", "不用", "/exit"], now=NOW + timedelta(days=2))
    assert OFFER in run.out and "## 这一周的小结" not in run.out
    assert TEXT.replies["offer_declined"] in run.out
    (journal,) = _journals(data_home)
    assert not journal.shown and journal.helpful is None
    again = run_cli(["chat"], ["", "/exit"], now=NOW + timedelta(days=3))
    assert OFFER not in again.out


def test_text_typed_at_the_offer_is_the_first_message(run_cli, data_home):
    _two_sessions(run_cli, data_home)
    run = run_cli(["chat"], ["", "今天上班好累", "/exit", ""], now=NOW + timedelta(days=2))
    assert run.texts == ["今天上班好累"]
    assert "## 这一周的小结" not in run.out


def test_a_care_greeting_opening_stays_alone(run_cli, data_home):
    _two_sessions(run_cli, data_home)
    crisis = run_cli(["chat"], ["", "好", "", L3_SENTENCE, "/exit"], now=NOW + timedelta(days=2))
    assert crisis.results[-1].reply_kind is ReplyKind.CRISIS
    run = run_cli(["chat"], ["今天还行", "/exit", "6"], now=NOW + timedelta(days=5))
    # No opening rating and no journal offer, though two sessions fall in the window.
    assert RATING in run.out and run.out.count(RATING) == 1
    assert OFFER not in run.out
    assert run.texts == ["今天还行"]
    assert run.out.index(f"Olivia：{run.results[0].reply}") < run.out.index(RATING)


def test_a_crisis_week_journal_uses_the_steadier_voice(run_cli, data_home):
    save_profile(data_home)
    run_cli(["chat"], ["", L3_SENTENCE, "/exit"])
    run_cli(["chat"], ["", "今天还行", "/exit", ""], now=NOW + timedelta(days=8))
    run = run_cli(["journal"], [""], now=NOW + timedelta(days=5))
    assert TEXT.card["intro_solemn"] in run.out and TEXT.card["closing_solemn"] in run.out


# -- olivia journal ---------------------------------------------------------------------------


def test_journal_command_with_an_empty_ledger(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["journal"])
    assert run.code == 0 and run.out.strip() == TEXT.replies["empty"]
    assert not (data_home / LEDGER_DIRNAME).exists()


def test_journal_command_shows_it_any_time(run_cli, data_home):
    save_profile(data_home)
    run_cli(["chat"], ["4", "今天上班好累", "/exit", "6"])
    run = run_cli(["journal"], ["没有"], now=NOW + timedelta(hours=1))
    assert run.code == 0
    assert "## 这一周的小结" in run.out and "- 聊天：1 次" in run.out
    (journal,) = _journals(data_home)
    assert journal.shown and journal.helpful is False
    assert run.lines[-1] == TEXT.replies["helpful_no"]


def test_journal_command_before_onboarding(run_cli, data_home):
    run = run_cli(["journal"])
    assert run.code == 1 and TEXT.replies["not_onboarded"] in run.out


def test_journal_command_refuses_minors(run_cli, data_home):
    save_profile(data_home, age_confirmed_18_plus=False, region=None, age_gate_refused_at=NOW)
    run = run_cli(["journal"])
    assert run.code == 1 and TEXT.replies["adults_only"] in run.out


def test_journal_command_without_a_keychain(run_cli, data_home, keychain):
    save_profile(data_home)
    keychain.broken = NoKeychainError("none")
    run = run_cli(["journal"])
    assert run.code == 1 and TEXT.replies["unavailable"] in run.out


def test_the_journal_leaves_nothing_readable_on_disk(run_cli, data_home):
    _two_sessions(run_cli, data_home)
    run_cli(["chat"], ["5", "好", "有", "/exit"], now=NOW + timedelta(days=2))
    for path in (data_home / LEDGER_DIRNAME).iterdir():
        data = path.read_bytes()
        for needle in ("小结", "上班", "journal", "helpful"):
            assert needle.encode() not in data
