"""COLBO-02a: S_explore and S_clarify replies that are not cards carry no method talk.

Rules mode, several seeds, over the rules golden script and every red-team case: an
ordinary, haven or referral reply in S_explore or S_clarify never names a Grade A method
(taxonomy name or card title) and never uses an advice word, unless the user's own turn
had that word (the mirror slot may echo it). Cards (the S_explore stabilization channel,
COLBO-02's second clause) and Grade B/C information are other reply kinds.
"""

from __future__ import annotations

import importlib.util
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language.data import load_language_data
from olivia.core.models import HelpStage, PersonaProfile, PersonaSpectrum, SafetyGrade, UserRegion
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

HERE = Path(__file__).resolve().parent
TAX = load_taxonomy()
LANG = load_language_data(TAX)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
SEEDS = range(5)
STAGES = frozenset({HelpStage.S_EXPLORE, HelpStage.S_CLARIFY})
NON_CARD = frozenset({ReplyKind.NORMAL, ReplyKind.HAVEN, ReplyKind.REFERRAL})
ADVICE_WORDS = ("建议", "试试", "试着", "方法", "练习")


def _golden_script() -> tuple[str, ...]:
    spec = importlib.util.spec_from_file_location(
        "rules_golden", HERE / "test_session_rules_golden.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    script: tuple[str, ...] = module.SCRIPT
    return script


def _method_names() -> frozenset[str]:
    names = {
        part.strip()
        for m in TAX.methods().values()
        if m.grade is SafetyGrade.GRADE_A
        for part in m.name_zh.split("/")
    }
    for card in LANG.cards.cards.values():
        names |= {card.title, card.taxonomy_title}
    return frozenset(n for n in names if n)


CASES: list[dict[str, Any]] = yaml.safe_load(
    (HERE.parent / "redteam" / "cases.yaml").read_text(encoding="utf-8")
)
SCRIPTS = [pytest.param("golden", _golden_script(), {}, id="golden")] + [
    pytest.param(c["id"], tuple(c["turns"]), c.get("profile") or {}, id=c["id"]) for c in CASES
]
FORBIDDEN = (*ADVICE_WORDS, *sorted(_method_names()))


def _profile(raw: dict[str, Any]) -> PersonaProfile:
    return PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        persona_spectrum=PersonaSpectrum[raw.get("persona_spectrum", "GENTLE_HOLDING")],
        taboo_topics=tuple(raw.get("taboo_topics", ())),
        region=UserRegion(raw.get("region", "CN"), "UTC"),
        clinical_history=tuple(raw.get("clinical_history", ())),
    )


def test_the_word_lists_are_loaded() -> None:
    assert len(_method_names()) >= 32
    assert len(CASES) > 100


@pytest.mark.parametrize(("name", "turns", "profile"), SCRIPTS)
def test_explore_and_clarify_replies_name_no_method(
    name: str, turns: tuple[str, ...], profile: dict[str, Any]
) -> None:
    for seed in SEEDS:
        session = Session.open(
            TAX, _profile(profile), rng=random.Random(f"{name}/{seed}"), now=lambda: NOW
        )
        for text in turns:
            result = session.turn(text)
            if result.stage not in STAGES or result.reply_kind not in NON_CARD:
                continue
            said = [w for w in FORBIDDEN if w in result.reply and w not in text]
            assert not said, (name, seed, result.stage, said)
