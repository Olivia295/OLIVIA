"""Round 7 performance (2026-11-01): the same mirror guard with less memory.

Round 7 grew the crisis lexicon and ``guarded.semantic``; peak RSS went back up by about
6 MB in rules mode. Every ``Session.open`` built its own ``MirrorGuard`` (about 1.8 MB of
indexes and sets) and dropped it with the session. Now:

* the guard is built once per (crisis lexicon, utterances) pair and shared, as it reads
  nothing else and never changes after it is built;
* its composition sets are the crisis screen's composer sets (one set per distinct list).

Nothing here changes what the guard returns.
"""

from __future__ import annotations

import random
import tracemalloc
from datetime import UTC, datetime

import pytest

from olivia.core.language import guard as guard_module
from olivia.core.language.data import load_language_data
from olivia.core.language.engine import LanguageEngine
from olivia.core.language.guard import MirrorGuard, shared_guard
from olivia.core.models import PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.safety.compose import Composer, shared_set
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
DATA = load_language_data(TAX)
NOW = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)
TEXTS = (
    "我打算明天下班后去江边那座桥上往下跳",
    "累死了，今天加班到十点",
    "药我已经准备好了",
    "我现在是安全的",
    "周末去跳伞了，好刺激",
    "心跳很快，睡不着",
    "想把后事安排一下",
    "嗯",
)


def _fresh(said=DATA.utterances) -> MirrorGuard:  # type: ignore[no-untyped-def]
    return MirrorGuard(LEX, said.extra_risk_words, said.components, semantic=said.semantic)


def test_engines_over_the_same_data_share_one_guard() -> None:
    a = LanguageEngine(TAX, rng=random.Random(1), data=DATA, lexicons=LEX)
    b = LanguageEngine(
        TAX,
        rng=random.Random(2),
        data=DATA.for_persona(PersonaSpectrum.ZEN_PHILOSOPHER),
        lexicons=LEX,
    )
    assert a._guard is b._guard
    other = LanguageEngine(TAX, rng=random.Random(1), data=DATA, lexicons=None)
    assert other._guard is not a._guard


@pytest.mark.parametrize("text", TEXTS)
def test_the_shared_guard_reads_as_a_fresh_one(text: str) -> None:
    fresh, shared = _fresh(), shared_guard(LEX, DATA.utterances)
    for name in ("risky", "flagged", "kinds", "confirms_safety", "about_risk"):
        assert getattr(shared, name)(text) == getattr(fresh, name)(text), name


def test_the_cache_is_keyed_by_identity_and_bounded() -> None:
    first = shared_guard(LEX, DATA.utterances)
    for _ in range(guard_module._GUARDS_MAX + 2):
        shared_guard(load_safety_lexicons(TAX), DATA.utterances)
    assert len(guard_module._GUARDS) <= guard_module._GUARDS_MAX
    again = shared_guard(LEX, DATA.utterances)
    assert again is first or again.risky(TEXTS[0]) == first.risky(TEXTS[0])


def test_the_guard_shares_the_composers_sets() -> None:
    composer = Composer(LEX.compositions)
    relaxed = shared_guard(LEX, DATA.utterances)
    sets = {id(s.unless) for _, s in composer._sets}
    guard_sets = {id(r.unless) for rs in relaxed._by_word.values() for r in rs}
    assert guard_sets <= sets
    assert shared_set(["甲", "乙"]) is shared_set(("乙", "甲"))


def test_opening_a_session_builds_no_guard() -> None:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )

    def open_one(seed: int) -> Session:
        return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW, student=False)

    open_one(0)  # loads and caches the shared data
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        session = open_one(1)
        held = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    assert session is not None
    # A guard of its own per session held about 1.8 MB (round 7).
    assert held < 400 * 1024, held
