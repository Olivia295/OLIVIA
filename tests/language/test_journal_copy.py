"""The journal's persona voices and battery line pass the template checks (Q-6, CHANG-04).

The same readings as ``test_persona_templates.py``: a paragraph counts every
non-whitespace character and holds at most 80; every sentence passes WILLOW unchanged and
the output gate, with no exclamation marks, no question marks and no advice words.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from olivia.core.chang.journal import load_journal_text
from olivia.core.language.data import ContentKind, LanguageData
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate, phone_like_runs
from olivia.core.models import HelpStage, PersonaSpectrum
from olivia.core.taxonomy import Taxonomy

DATA = Path(__file__).resolve().parents[2] / "olivia/data"
WHITESPACE = re.compile(r"\s")
TEXT = load_journal_text()
SLOTS = ("intro", "bridge", "closing", "intro_solemn", "bridge_solemn", "closing_solemn")
ADVICE = ["你应该", "应该", "必须", "一定要", "症状", "病", "诊断", "患者", "治疗", "加油"]
# The battery line with the largest numbers it can carry in a week.
BATTERY = (
    TEXT.card["battery_low"].format(known=99, count=99)
    + TEXT.card["battery_last_week"].format(count=99),
    TEXT.card["battery_fine"].format(known=99) + TEXT.card["battery_last_week"].format(count=0),
)


def _all(text: str) -> int:
    return len(WHITESPACE.sub("", text))


def _voice_lines(persona: PersonaSpectrum) -> list[str]:
    voice = TEXT.voice(persona)
    return [line for slot in SLOTS for line in getattr(voice, slot)]


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
def test_every_voice_line_is_one_short_paragraph(persona):
    for line in _voice_lines(persona):
        assert "\n" not in line and _all(line) <= 80, line


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
def test_every_voice_line_passes_willow_and_the_gate(
    tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum
) -> None:
    data = lang.for_persona(persona)
    gate = OutputGate(tax, data)
    for line in _voice_lines(persona):
        assert apply_willow(line, ContentKind.NORMAL, data.willow) == line, line
        assert gate.reasons(line, kind=ContentKind.NORMAL, stage=HelpStage.S_READY) == (), line
        assert not any(mark in line for mark in "！!？?"), line
        assert not any(word in line for word in ADVICE), line
        assert not re.search(r"\d", line) and phone_like_runs(line) == (), line


def test_the_battery_line_is_short_and_passes_willow_and_the_gate(
    tax: Taxonomy, lang: LanguageData
) -> None:
    gate = OutputGate(tax, lang)
    for line in BATTERY:
        assert _all(line) <= 80, line
        assert apply_willow(line, ContentKind.NORMAL, lang.willow) == line, line
        assert gate.reasons(line, kind=ContentKind.NORMAL, stage=HelpStage.S_READY) == (), line
        assert not any(mark in line for mark in "！!？?"), line
        assert not any(word in line for word in ADVICE), line


def test_the_battery_line_does_not_judge():
    for line in BATTERY:
        for word in ("好转", "变好", "变差", "进步", "退步", "太低", "要注意", "多了", "少了"):
            assert word not in line, line


def test_the_journal_copy_is_a_g0_draft():
    head = (DATA / "templates/journal.yaml").read_text(encoding="utf-8").splitlines()[0]
    assert head.startswith("# 草稿：待 G-0")
