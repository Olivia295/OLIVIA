"""Composition engine behaviour that mutation testing found unchecked (``safety/compose.py``).

Each test kills one or more surviving mutants listed in ``docs/safety/mutation-report.md``
and asserts a documented rule of the engine (PRD §9.1 and SDD §8.1 F1: negation, a third
person as the subject, exceptions, ``unless`` words; the field contracts on
``lexicon.Composition`` / ``CompositionRules``), never a lexicon entry: the rules run on
neutral placeholder words, as in ``test_compositions.py``, so a rule change in
``risk.yaml`` cannot break them.
"""

from __future__ import annotations

from typing import Any

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.compose import Composer
from olivia.core.safety.lexicon import Composition, CompositionRules


def _rules(*, section: dict[str, Any] | None = None, **entry: Any) -> CompositionRules:
    base: dict[str, Any] = {
        "id": "L2_TEST",
        "level": L.L2,
        "score": 0.7,
        "ask": False,
        "heads": ("甲",),
        "tails": ("乙",),
        "max_gap": 2,
    }
    shared: dict[str, Any] = {
        "stops": frozenset(",。"),
        "lookback": 2,
        "subject_window": 6,
        "negators": ("不",),
        "non_negators": ("忍不住",),
        "selves": ("我", "自己"),
        "others": ("他", "你"),
        "recipients": ("跟",),
        "listeners": ("你",),
    }
    return CompositionRules(
        **{**shared, **(section or {})}, entries=(Composition(**{**base, **entry}),)
    )


def _fires(rules: CompositionRules, text: str) -> bool:
    return bool(Composer(rules).find(text))


# -- negators (PRD §9.1 F1: a negator in the gap or just before the first part voids the
# match; 忍不住-like words and A-not-A questions are no negation) ---------------------------


def test_a_non_negating_word_earlier_does_not_hide_a_later_real_negator():
    rules = _rules()
    assert _fires(rules, "忍不住哭,甲乙")
    assert not _fires(rules, "忍不住哭,不甲乙")


def test_an_a_not_a_question_earlier_does_not_hide_a_later_real_negator():
    rules = _rules()
    assert _fires(rules, "好不好,甲乙")
    assert not _fires(rules, "好不好,不甲乙")


def test_a_negator_at_the_very_start_is_not_read_as_an_a_not_a_question():
    # Only the characters around the negator decide the A-not-A reading; the message's
    # last character is not the one before a negator at position 0.
    rules = _rules()
    assert not _fires(rules, "不甲乙,一甲")
    assert not _fires(rules, "不甲乙")


# -- exceptions (lexicon.Composition: a part wholly inside one of ``exceptions`` is no part)


def test_a_part_inside_the_later_of_two_exceptions_is_excepted():
    # Coverage is read against every exception that starts before the part, the nearest
    # one included, not only the earlier ones.
    rules = _rules(exceptions=("甲丁", "一甲"))
    assert _fires(rules, "甲丁,甲乙")
    assert not _fires(rules, "甲丁,一甲乙")
    assert not _fires(rules, "一甲乙")


# -- ``unless`` words (lexicon.CompositionRules: an ``unless_negators`` word or a negator at
# most ``unless_negation_gap`` characters before an ``unless`` phrase denies it, 不是为了烧烤;
# a negator of the match itself, 不用再醒那么早, does not) -------------------------------------


def test_a_denied_unless_phrase_that_starts_with_the_match_no_longer_voids_it():
    rules = _rules(
        section={"unless_negators": ("并非",), "unless_negation_gap": 2},
        unless=("甲乙丙",),
        unless_window=3,
    )
    assert _fires(rules, "甲乙") and not _fires(rules, "甲乙丙")
    assert _fires(rules, "并非甲乙丙")


def test_a_negator_that_ends_the_match_does_not_deny_the_unless_phrase_after_it():
    rules = _rules(
        tails=("乙不",), unless=("丁",), unless_window=2, section={"unless_negation_gap": 2}
    )
    assert _fires(rules, "甲乙不")
    assert not _fires(rules, "甲乙不丁")
    # A negator outside the match still denies the unless phrase.
    plain = _rules(unless=("丁",), unless_window=3, section={"unless_negation_gap": 2})
    assert not _fires(plain, "甲乙丁") and _fires(plain, "甲乙不丁")


# -- a third person as the subject (PRD §9.1 F1: 主语是他人; SDD §8.1) ---------------------


def test_a_self_word_inside_a_part_does_not_hide_the_real_subject():
    # The head itself names the self (把自己 ...); the subject is still the person before it.
    rules = _rules(heads=("把自己",), tails=("弄伤",))
    assert _fires(rules, "我把自己弄伤") and _fires(rules, "把自己弄伤")
    assert not _fires(rules, "他把自己弄伤")


def test_a_listener_in_the_clause_before_does_not_hide_its_subject():
    # A clause naming nobody keeps the subject of the clause before it; a listener (你) in
    # that clause is not carried over, but the subject before it still is.
    rules = _rules()
    assert not _fires(rules, "他骂你,甲乙")
    assert _fires(rules, "我骂你,甲乙")
