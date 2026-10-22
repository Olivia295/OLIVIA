"""The output gate blocks each forbidden class and passes clean text."""

from __future__ import annotations

import pytest

from olivia.core.language import ContentKind, OutputGate
from olivia.core.language.data import LanguageData
from olivia.core.language.gate import phone_like_runs
from olivia.core.models import HelpStage
from olivia.core.taxonomy import Taxonomy

CLEAN = "谢谢你愿意说出来。我在这里，慢慢来就好。"


@pytest.fixture(scope="module")
def gate(tax: Taxonomy, lang: LanguageData) -> OutputGate:
    return OutputGate(tax, lang)


def _check(
    gate: OutputGate,
    text: str,
    *,
    kind: ContentKind = ContentKind.NORMAL,
    stage: HelpStage = HelpStage.S_EXPLORE,
    allowed_numbers: tuple[str, ...] = (),
) -> tuple[bool, tuple[str, ...]]:
    result = gate.check(text, kind=kind, stage=stage, allowed_numbers=allowed_numbers)
    return result.ok, result.reasons


@pytest.mark.parametrize("kind", list(ContentKind))
def test_clean_text_passes_unchanged(gate: OutputGate, kind: ContentKind) -> None:
    result = gate.check(CLEAN, kind=kind, stage=HelpStage.S_EXPLORE)
    assert result.ok and result.text == CLEAN and result.reasons == ()


@pytest.mark.parametrize("kind", list(ContentKind))
@pytest.mark.parametrize("text", ["你可能有抑郁症。", "This looks like PTSD.", "确诊之后呢"])
def test_diagnosis_terms_are_blocked_for_every_kind(
    gate: OutputGate, kind: ContentKind, text: str
) -> None:
    ok, reasons = _check(gate, text, kind=kind)
    assert not ok and any(r.startswith("diagnosis:") for r in reasons)


@pytest.mark.parametrize(
    "text",
    [
        "可以打 13800138000 试试。",
        "号码是 138 0013 8000。",
        "拨 400-161-9995。",
        "全角１２３５６也算。",
        "1 2 3 4 5",
        "9-8-8",
        "12356",
    ],
)
def test_stray_numbers_are_blocked(gate: OutputGate, text: str) -> None:
    ok, reasons = _check(gate, text)
    assert not ok and any(r.startswith("number:") for r in reasons)


def test_numbers_of_the_card_are_allowed_in_any_spacing(gate: OutputGate) -> None:
    text = "香港撒玛利亚防止自杀会：2389 2222，或 9-8-8，或 12356。"
    ok, _ = _check(
        gate, text, kind=ContentKind.CRISIS, allowed_numbers=("23892222", "988", "12356")
    )
    assert ok
    ok, reasons = _check(gate, text, kind=ContentKind.CRISIS, allowed_numbers=("988",))
    assert not ok and set(reasons) == {"number:23892222", "number:12356"}


@pytest.mark.parametrize(
    "text",
    [
        "0 是平静，10 是最难受。",
        "数 4 秒，再呼气 6 到 8 秒，重复 3 到 5 轮。",
        "打个 0–10 分。",
        "周一至周六 9:00-12:00、14:00-17:00、18:00-21:30。",
        "「5-4-3-2-1 感官外感受着陆法」",
        "24/7",
    ],
)
def test_short_counts_times_and_card_titles_are_not_phone_numbers(
    gate: OutputGate, text: str
) -> None:
    assert _check(gate, text, kind=ContentKind.CARD) == (True, ())


def test_phone_like_runs_reads_digits_across_single_separators() -> None:
    assert phone_like_runs("拨 0477 13 11 14 或 1300-22-4636") == ("0477131114", "1300224636")
    assert phone_like_runs("12 34") == ("1234",)
    assert phone_like_runs("12  34") == ()
    # A name that ends in digits next to "：" is not a clock time.
    assert phone_like_runs("热线 99999：12356") == ("99999", "12356")
    assert phone_like_runs("9:00-12:00") == ()


def test_grade_a_titles_only_in_empower_or_cards(gate: OutputGate) -> None:
    text = "要不要试试「接纳承诺疗法」？"
    ok, reasons = _check(gate, text, stage=HelpStage.S_EXPLORE)
    assert not ok and reasons == ("grade_a_title:接纳承诺疗法",)
    assert _check(gate, text, stage=HelpStage.S_CLARIFY)[0] is False
    assert _check(gate, text, kind=ContentKind.GRADE_B_INFO, stage=HelpStage.S_CLARIFY)[0] is False
    assert _check(gate, text, stage=HelpStage.S_EMPOWER) == (True, ())
    assert _check(gate, text, kind=ContentKind.CARD, stage=HelpStage.S_EXPLORE) == (True, ())


@pytest.mark.parametrize("word", ["你应该", "必须"])
@pytest.mark.parametrize("kind", [ContentKind.NORMAL, ContentKind.CARD])
def test_didactic_words_are_blocked_where_the_filter_applies(
    gate: OutputGate, word: str, kind: ContentKind
) -> None:
    ok, reasons = _check(gate, f"{word}好好休息。", kind=kind)
    assert not ok and reasons == (f"didactic:{word}",)


@pytest.mark.parametrize("word", ["你应该", "必须"])
def test_grade_b_info_is_exempt_from_the_didactic_check(gate: OutputGate, word: str) -> None:
    # Grade B/C explainers go to the G-0 reviewers verbatim; filters must not rewrite them.
    assert _check(gate, f"{word}好好休息。", kind=ContentKind.GRADE_B_INFO) == (True, ())


@pytest.mark.parametrize(
    "kind", [ContentKind.CRISIS, ContentKind.REFERRAL, ContentKind.GRADE_C_INFO]
)
def test_safety_wording_is_allowed_where_exempt(gate: OutputGate, kind: ContentKind) -> None:
    assert _check(gate, "必须确保安全。", kind=kind) == (True, ())


def test_block_returns_a_slot_free_haven_line(gate: OutputGate, lang: LanguageData) -> None:
    result = gate.check(
        "你患有焦虑症，你应该打 13800138000。", kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE
    )
    assert not result.ok
    assert result.text == gate.fallback
    assert result.text in lang.templates.haven and "{" not in result.text
    assert {r.split(":")[0] for r in result.reasons} == {"diagnosis", "number", "didactic"}


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_text_is_blocked(gate: OutputGate, text: str) -> None:
    assert _check(gate, text) == (False, ("empty:",))


def test_fallback_line_itself_passes(gate: OutputGate) -> None:
    for stage in HelpStage:
        for kind in ContentKind:
            assert gate.check(gate.fallback, kind=kind, stage=stage).ok
