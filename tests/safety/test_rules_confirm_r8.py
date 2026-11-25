"""Rules round 8, task G2b-2 (2026-11-25): the screen side.

1. 负责人 2026-11-25 决定: a means "put away" (收好) next to a death word that is itself a
   denial ("我不想死，刀我已经收好了") is still Stage 1 for the screen, but it is a plan
   candidate (``CrisisAssessment.plan_candidate``) when nothing else in the message is a risk
   cue: no plan, time, farewell, hedge or contrast, no other Stage 1 phrase or composition, no
   Stage 2 phrase of the user's own. The session then asks once first. Anything else keeps
   the plain L3.
2. The answer to a direct question (D3, or a model-only alarm's) "不是 + 不想活 / a feeling
   that starts with 不, 就是 / 只是 + something else" is a no, read like §9.4 第 32 条's
   "不是难过，就是好奇": the 不是不 inside that first clause is the double negation of not
   wanting to live (or of an unhappy feeling), no hedge. "不是不想死" is the double negation
   of not wanting to die, a wish to die: the rules rate it L2 and it stays no no.
3.-5. The compositions that count only in a session context (``compositions.
   context_entries``: going at a time or all the same, starting over, a plan and a time with
   nothing named) are no cue for the screen: it only reports them
   (``SafetyScreen.context_cues``), and the session reads them.

Every sentence here was written for this round; none comes from an evaluation set or the
red-team suite.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.intent_check import IntentAnswer, read_answer
from olivia.core.safety.lexicon import LexiconError, load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)

# -- 1. a means put away ---------------------------------------------------------------------

PUT_AWAY_ALONE = [
    "我不想死，刀我已经收好了",
    "我不会伤害自己的，刀我已经收好了",
    "放心，我不会做傻事，药都收好了",
    "我没想自杀，刀片我都收好了",
    "我不会想不开的，安眠药我已经收好了",
]

PUT_AWAY_WITH_MORE = [
    "我想死，刀我已经收好了",  # a death wish of the user's own
    "我不想活了 刀已经收好了",
    "我不想死，刀我已经收好了，今晚再说",  # a time
    "我不想死，但刀已经收好了",  # a contrast
    "我不想死，刀收好了，遗书也写好了",  # a farewell
    "我不想死，药我已经收好了，准备好了",  # a plan word
    "我不想死，刀我先收好了，万一用得上",  # a hedge
    "我不想死，刀我收好了，藏在枕头底下",  # hidden at hand
    "我不想死，可是绳子都准备好了，刀也收好了",  # another means made ready
]


@pytest.mark.parametrize("text", PUT_AWAY_ALONE)
def test_a_means_put_away_alone_is_a_plan_candidate(text: str) -> None:
    result = SCREEN.assess(text)
    assert result.level is L.L3
    assert result.has_plan_evidence
    assert result.plan_candidate
    assert "S1_MEANS_PUT_AWAY" in result.cue_ids


@pytest.mark.parametrize("text", PUT_AWAY_WITH_MORE)
def test_a_means_put_away_with_more_stays_plain_l3(text: str) -> None:
    result = SCREEN.assess(text)
    assert result.level is L.L3
    assert not result.plan_candidate


@pytest.mark.parametrize(
    "text",
    [
        "我不想死，刀我已经藏好了",  # a strong ready mark, as before
        "我不想死，可是绳子都准备好了",
    ],
)
def test_other_ready_marks_are_no_candidate(text: str) -> None:
    result = SCREEN.assess(text)
    assert result.level is L.L3
    assert not result.plan_candidate


@pytest.mark.parametrize(
    "text",
    [
        "刀我已经收好了",  # no death word: no cue at all, as before
        "厨房的刀我都收好了，孩子够不着",
        "切完西瓜，刀我已经收好了",
    ],
)
def test_a_means_put_away_with_no_death_word_is_no_cue(text: str) -> None:
    result = SCREEN.assess(text)
    assert result.level is L.L0
    assert not result.plan_candidate


def test_the_put_away_rules_name_l3_compositions() -> None:
    rules = LEX.put_away_ask
    assert rules.ids == frozenset({"S1_MEANS_PUT_AWAY"})
    entries = {e.id: e for e in LEX.compositions.entries}
    assert all(entries[i].level is L.L3 for i in rules.ids)
    assert "收好" in entries["S1_MEANS_PUT_AWAY"].tails
    assert "收好" not in entries["S1_MEANS_PREPARED"].tails


# -- 2. "不是……就是……" -------------------------------------------------------------------------


def _read(text: str, *, strict: bool) -> IntentAnswer:
    """The session's reading of an answer: D3 (``strict`` False) or a model-only alarm's."""
    rules = SCREEN.assess(text)
    reading = read_answer(LEX.intent_answers, text, rules, None if strict else SCREEN.assess)
    guarded = text if reading.guard_text is None else reading.guard_text
    if (
        (strict or reading.reason_split)
        and reading.answer is IntentAnswer.DENIED
        and guarded
        and not SCREEN.clear_denial(guarded)
    ):
        return IntentAnswer.UNCLEAR
    return reading.answer


NOT_THAT_JUST = [
    "不是，就是不开心",
    "不是那个意思，就是有点累",
    "不是不想活，就是太累了",
    "我不是不想活，只是太累了",
    "并不是不想活，就是压力大",
    "不是不想活着，就是累",
    "不是不开心，就是累",
    "不是不高兴，只是有点困",
    "不是不开心啦，就是有点烦",
]

STILL_UNCLEAR = [
    "不是不想死，就是太累了",  # 不是不想死: a wish to die
    "不是不想死，只是累",
    "我不是不想死，就是没力气",
    "不是不想活，就是活不下去了",  # risk after it
    "不是不开心，就是想死",
    "不是不想活，但是太累了",  # a contrast
    "不是不想活，就是有时候会想",  # a hedge
    "不是不想活",  # nothing after it: "not that I don't want to live, but ..."
    "不是不想活，就是今晚不想醒",
]


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("text", NOT_THAT_JUST)
def test_not_that_just_something_else_is_a_no(text: str, strict: bool) -> None:
    assert _read(text, strict=strict) is IntentAnswer.DENIED


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("text", STILL_UNCLEAR)
def test_not_wanting_to_die_negated_or_risk_after_stays_unclear(text: str, strict: bool) -> None:
    assert _read(text, strict=strict) is not IntentAnswer.DENIED


@pytest.mark.parametrize("text", ["不是不想死，就是太累了", "我不是不想死，就是没力气"])
def test_not_not_wanting_to_die_is_a_risk_for_the_screen(text: str) -> None:
    assert SCREEN.assess(text).level >= L.L2


# -- 3.-5. cues that count only in a session context ------------------------------------------

CONTEXT_ONLY = [
    ("下礼拜一我就走", "ASK_INTENT_GO_AT_TIME_AFTER_CRISIS"),
    ("我还是打算走", "ASK_INTENT_STILL_GO_AFTER_CRISIS"),
    ("我决定了还是要走", "ASK_INTENT_STILL_GO_AFTER_CRISIS"),
    ("这局想去重开了", "ASK_INTENT_RESTART_AFTER_CRISIS"),
]


@pytest.mark.parametrize(("text", "cue"), CONTEXT_ONLY)
def test_a_context_only_cue_is_reported_and_counts_for_nothing(text: str, cue: str) -> None:
    result = SCREEN.assess(text)
    assert cue in SCREEN.context_cues(text)
    assert cue not in result.cue_ids
    assert result.level is L.L0
    assert result.rule_clear
    assert not result.asks_intent


@pytest.mark.parametrize(
    "text",
    [
        "下礼拜一我就走，去新公司报到",
        "我还是打算走，回老家发展",
        "这把游戏输了，想重开",
    ],
)
def test_everyday_denied_or_someone_elses_words_are_no_context_cue(text: str) -> None:
    assert not SCREEN.context_cues(text)


def test_context_entries_are_apart_from_the_entries() -> None:
    rules = LEX.compositions
    ids = {e.id for e in rules.context_entries}
    assert ids == {cue for _, cue in CONTEXT_ONLY}
    assert ids.isdisjoint(e.id for e in rules.entries)
    for entry in rules.context_entries:
        assert entry.after in {"crisis", "own_risk"}
        assert entry.ask == (entry.after == "crisis")
        assert entry.level is (L.L1 if entry.ask else L.L3)
    assert all(e.after is None for e in rules.entries)


PKG_LEX = Path(__file__).resolve().parents[2] / "olivia" / "data" / "lexicons"


def _copy(tmp_path: Path, change: Any) -> Path:
    d = tmp_path / "lex"
    shutil.copytree(PKG_LEX, d)
    data = yaml.safe_load((d / "risk.yaml").read_text(encoding="utf-8"))
    change(data)
    (d / "risk.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return d


def _first_context(data: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = data["compositions"]["context_entries"][0]
    return entry


@pytest.mark.parametrize(
    "change",
    [
        lambda d: _first_context(d).update(after="later"),
        lambda d: _first_context(d).pop("after"),
        lambda d: _first_context(d).update(after="own_risk"),  # an ASK entry after own_risk
        lambda d: d["compositions"]["entries"][0].update(after="crisis"),
        lambda d: d["put_away_ask"].update(ids=["S1_NO_SUCH_ENTRY"]),
    ],
)
def test_a_wrong_context_entry_or_put_away_id_is_rejected(tmp_path: Path, change: Any) -> None:
    with pytest.raises(LexiconError):
        load_safety_lexicons(TAX, _copy(tmp_path, change))


def test_without_the_put_away_section_it_is_plain_l3(tmp_path: Path) -> None:
    lex = load_safety_lexicons(TAX, _copy(tmp_path, lambda d: d.pop("put_away_ask")))
    result = SafetyScreen(TAX, lex).assess("我不想死，刀我已经收好了")
    assert result.level is L.L3
    assert not result.plan_candidate
