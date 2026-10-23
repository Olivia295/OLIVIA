"""3D retrieval over the ledger (step B4; SDD §3.3, PRD MIYI-04, ruling 29, Q-7)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta, timezone

import pytest

from olivia.core.crypto.vault import Vault
from olivia.core.memory.ledger import (
    JournalEntry,
    Ledger,
    MethodRecord,
    NoteEntry,
    SessionSummary,
    SummaryEntry,
)
from olivia.core.memory.retrieval import (
    ALPHA,
    TAU_DAYS,
    TOP_K,
    W_REC,
    W_SAL,
    W_SIM,
    MemoryIndex,
    char_ngrams,
    rank,
    recency,
    searchable_text,
)
from olivia.core.memory.text import load_memory_text
from olivia.core.methods.bandit import Feedback
from olivia.core.models import CrisisLevel, HelpStage

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
PATH = (HelpStage.S_READY, HelpStage.S_EXPLORE, HelpStage.S_EMPOWER, HelpStage.S_CLOSING)
TITLES = {"12:tipp_breathing": "冷水与呼吸的快速降温", "30:grounding": "五感着陆"}


def _note(text: str, days_ago: float = 0, entry_id: str = "a" * 24) -> NoteEntry:
    return NoteEntry(entry_id, text, NOW - timedelta(days=days_ago))


def _summary(
    *,
    days_ago: float,
    entry_id: str,
    spectra: tuple[str, ...] = ("02",),
    methods: tuple[MethodRecord, ...] = (),
    crisis_level: CrisisLevel | None = None,
    marked_by_user: bool = False,
) -> SummaryEntry:
    start = NOW - timedelta(days=days_ago)
    return SummaryEntry(
        entry_id,
        SessionSummary(
            started_at=start,
            ended_at=start + timedelta(minutes=20),
            stage_path=PATH,
            spectra=spectra,
            methods=methods,
            crisis_level=crisis_level,
            marked_by_user=marked_by_user,
        ),
    )


def _ids(ranked: list[tuple[object, float]]) -> list[str]:
    return [entry.entry_id for entry, _ in ranked]  # type: ignore[attr-defined]


# -- constants: SDD §3.3, ruling 29, Q-7 ---------------------------------------------------


def test_the_constants_are_the_ones_the_spec_fixes():
    assert (W_REC, W_SIM, W_SAL) == (0.4, 0.4, 0.2)
    assert ALPHA == 1.0
    assert TAU_DAYS == 7.0
    assert TOP_K == 3


# -- the three dimensions ------------------------------------------------------------------


def test_recency_is_an_exponential_in_age_with_tau_seven_days():
    entry = _summary(days_ago=7, entry_id="a" * 24)
    assert recency(entry, NOW) == pytest.approx(math.exp(-1.0))
    assert recency(_summary(days_ago=0, entry_id="b" * 24), NOW) == pytest.approx(1.0)
    # Ages in fractions of a day count too.
    assert recency(_summary(days_ago=3.5, entry_id="c" * 24), NOW) == pytest.approx(math.exp(-0.5))


def test_an_entry_from_the_future_does_not_get_more_than_full_weight():
    assert recency(_summary(days_ago=-2, entry_id="a" * 24), NOW) == 1.0


def test_significant_entries_never_decay():
    l2 = _summary(days_ago=400, entry_id="a" * 24, crisis_level=CrisisLevel.L2)
    marked = _summary(days_ago=400, entry_id="b" * 24, marked_by_user=True)
    note = _note("妈妈的生日是三月五号", days_ago=400, entry_id="c" * 24)
    for entry in (l2, marked, note):
        assert recency(entry, NOW) == 1.0
    # An L1 crisis alone is not significant (ruling 29: L2 or above, or user-marked).
    l1 = _summary(days_ago=7, entry_id="d" * 24, crisis_level=CrisisLevel.L1)
    assert recency(l1, NOW) == pytest.approx(math.exp(-1.0))


def test_score_is_the_weighted_sum_of_recency_similarity_and_salience():
    note = _note("整理桌面让我有掌控感", days_ago=30, entry_id="a" * 24)
    plain = _summary(days_ago=7, entry_id="b" * 24, spectra=("05",))
    index = MemoryIndex([note, plain])
    note_sim, plain_sim = index.similarities("整理桌面")  # in the order given
    scores = {e.entry_id: s for e, s in index.rank("整理桌面", NOW, k=2)}
    # The note is significant: full recency, salience 1.
    assert scores["a" * 24] == pytest.approx(W_REC * 1.0 + W_SIM * note_sim + W_SAL)
    assert scores["b" * 24] == pytest.approx(W_REC * math.exp(-1.0) + W_SIM * plain_sim)
    assert plain_sim == 0.0
    assert 0.0 < note_sim <= 1.0


# -- ranking orders --------------------------------------------------------------------------


def test_a_strong_match_beats_a_more_recent_entry_that_does_not_match():
    # Under the SDD weights a match wins once 0.4 x cosine exceeds the recency it lost:
    # two days cost 0.4 x (1 - e^(-2/7)) ~ 0.10, so a cosine above ~0.25 is enough.
    match = _summary(days_ago=2, entry_id="a" * 24, spectra=("08",))  # 睡眠和身体的不舒服
    fresh = _summary(days_ago=0, entry_id="b" * 24, spectra=("11",))  # 关于意义的困惑
    query = "最近睡眠和身体都不舒服"
    assert MemoryIndex([match]).similarities(query)[0] > 0.25
    assert _ids(rank(query, [fresh, match], NOW, k=2)) == ["a" * 24, "b" * 24]


def test_a_weak_match_does_not_beat_recency():
    match = _summary(days_ago=14, entry_id="a" * 24, spectra=("08",))
    fresh = _summary(days_ago=0, entry_id="b" * 24, spectra=("11",))
    assert _ids(rank("身体有点不舒服", [fresh, match], NOW, k=2)) == ["b" * 24, "a" * 24]


def test_with_equal_relevance_the_more_recent_entry_ranks_first():
    old = _summary(days_ago=20, entry_id="a" * 24)
    new = _summary(days_ago=1, entry_id="b" * 24)
    ranked = rank("低落", [old, new], NOW, k=2)
    assert _ids(ranked) == ["b" * 24, "a" * 24]
    assert ranked[0][1] > ranked[1][1]


def test_a_significant_entry_outranks_an_equally_relevant_ordinary_one_however_old():
    ordinary = _summary(days_ago=0, entry_id="a" * 24)
    flagged = _summary(days_ago=365, entry_id="b" * 24, marked_by_user=True)
    assert _ids(rank("低落", [ordinary, flagged], NOW, k=2)) == ["b" * 24, "a" * 24]


def test_among_notes_the_one_that_matches_comes_first():
    notes = [
        _note("妈妈的生日是三月五号", days_ago=10, entry_id="a" * 24),
        _note("整理桌面会让我有掌控感", days_ago=200, entry_id="b" * 24),
        _note("我喜欢下雨天去河边散步", days_ago=1, entry_id="c" * 24),
    ]
    assert _ids(rank("工作好乱，想先整理一下桌面", notes, NOW, k=1)) == ["b" * 24]


def test_ties_are_broken_by_newer_first_then_by_id():
    a = _note("一样的话", days_ago=5, entry_id="b" * 24)
    b = _note("一样的话", days_ago=5, entry_id="a" * 24)
    c = _note("一样的话", days_ago=1, entry_id="c" * 24)
    for order in ([a, b, c], [c, b, a], [b, c, a]):
        assert _ids(rank("一样的话", order, NOW, k=3)) == ["c" * 24, "a" * 24, "b" * 24]


def test_ranking_is_deterministic_and_k_limits_the_result():
    entries = [_summary(days_ago=d, entry_id=f"{d:024x}") for d in range(10)]
    first = rank("低落", entries, NOW, k=4)
    assert len(first) == 4
    assert first == rank("低落", list(reversed(entries)), NOW, k=4)
    assert len(rank("低落", entries, NOW)) == TOP_K
    assert rank("低落", entries, NOW, k=0) == []
    assert len(rank("低落", entries[:2], NOW, k=5)) == 2
    with pytest.raises(ValueError):
        rank("低落", entries, NOW, k=-1)


def test_journal_records_are_left_out_of_the_index():
    # A B6 journal record holds no text; it is bookkeeping, never a retrieved event.
    journal = JournalEntry("c" * 24, offered_at=NOW, shown=True, helpful=True)
    index = MemoryIndex([journal, _note("又失眠了")])
    assert [type(e) for e in index.entries] == [NoteEntry]
    assert _ids(index.rank("失眠", NOW)) == ["a" * 24]


def test_an_empty_ledger_gives_nothing():
    assert rank("随便说点什么", [], NOW) == []
    assert MemoryIndex([]).similarities("随便") == ()


def test_an_empty_or_punctuation_only_query_matches_nothing_but_still_ranks():
    entries = [_summary(days_ago=1, entry_id="a" * 24), _note("记住这句", 9, "b" * 24)]
    for query in ("", "   ", "……！？"):
        assert MemoryIndex(entries).similarities(query) == (0.0, 0.0)
        assert _ids(rank(query, entries, NOW, k=2)) == ["b" * 24, "a" * 24]


def test_now_must_be_timezone_aware():
    with pytest.raises(ValueError):
        rank("低落", [_summary(days_ago=1, entry_id="a" * 24)], datetime(2026, 10, 23))


# -- text: Chinese, mixed, and what a summary is searchable by -------------------------------


def test_mixed_chinese_and_latin_text_matches_across_width_and_case():
    notes = [
        _note("下周六考ＩＥＬＴＳ，口语是弱项", entry_id="a" * 24),
        _note("周末想去看电影", entry_id="b" * 24),
    ]
    index = MemoryIndex(notes)
    sims = index.similarities("ielts 口语好紧张")
    assert sims[0] > 0.0
    assert sims[1] == 0.0


def test_char_ngrams_are_two_and_three_grams_within_word_runs():
    grams = char_ngrams("好累，ok")
    assert grams == {"好累": 1, "ok": 1}
    assert char_ngrams("整理桌面") == {
        "整理": 1,
        "理桌": 1,
        "桌面": 1,
        "整理桌": 1,
        "理桌面": 1,
    }
    assert char_ngrams("") == {}
    assert char_ngrams("累") == {}


def test_a_summary_is_searchable_only_by_its_templated_labels():
    text = load_memory_text()
    entry = _summary(
        days_ago=2,
        entry_id="a" * 24,
        spectra=("02", "05"),
        methods=(MethodRecord("12:tipp_breathing", Feedback.HELPFUL), MethodRecord("99:x")),
        crisis_level=CrisisLevel.L2,
    )
    found = searchable_text(entry, text=text, method_titles=TITLES)
    for label in ("低落和没劲", "累和耗尽", "冷水与呼吸的快速降温", "有帮助", "99:x", "还没有反馈"):
        assert label in found
    for stage in PATH:
        assert text.stages[stage.value] in found
    assert text.summary.crisis.lstrip("- ") in found
    assert text.summary.significant.lstrip("- ") in found
    # Times, dates and the heading boilerplate are not part of it.
    assert "2026" not in found
    assert ":" not in found.replace("99:x", "")


def test_a_note_is_searchable_by_its_own_text_verbatim():
    note = _note("记得周三给外婆打电话")
    assert searchable_text(note) == "记得周三给外婆打电话"


def test_method_titles_make_a_method_findable_by_the_name_the_user_saw():
    entry = _summary(
        days_ago=1, entry_id="a" * 24, methods=(MethodRecord("30:grounding", Feedback.HELPFUL),)
    )
    other = _summary(days_ago=1, entry_id="b" * 24)
    titled = MemoryIndex([entry, other], method_titles=TITLES)
    assert titled.similarities("五感着陆")[0] > 0.0
    assert MemoryIndex([entry, other]).similarities("五感着陆")[0] == 0.0


# -- with a real ledger ---------------------------------------------------------------------


def test_ranking_a_real_ledger_reads_entries_and_writes_nothing(tmp_path, keychain):
    ledger = Ledger(tmp_path, Vault(tmp_path, keychain), method_titles=TITLES)
    shanghai = timezone(timedelta(hours=8))
    start = datetime(2026, 10, 20, 21, 0, tzinfo=shanghai)
    ledger.append_summary(
        SessionSummary(
            started_at=start,
            ended_at=start + timedelta(minutes=15),
            stage_path=PATH,
            spectra=("01",),
            methods=(MethodRecord("30:grounding", Feedback.HELPFUL),),
        ),
        key="s1",
    )
    note_id = ledger.add_note("整理桌面会让我有掌控感", now=start - timedelta(days=90))
    before = sorted((p.name, p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))

    index = MemoryIndex(ledger.entries(), text=ledger.text, method_titles=TITLES)
    ranked = index.rank("桌面好乱", NOW, k=1)

    assert _ids(ranked) == [note_id]
    assert sorted((p.name, p.stat().st_mtime_ns) for p in tmp_path.rglob("*")) == before
