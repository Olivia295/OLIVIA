"""Engine fixes from usage testing (dogfood I3, P6, P8; 2026-10-26).

* The same opening sentence came back 3-6 times in one conversation: the "no repeat" rule
  compared whole paragraphs, and the mirror inside made every paragraph look new. A reply
  now opens with a variant this engine has not used yet while one is left.
* S_clarify named a "need" on every reply, even after "嗯" ("嗯，确定感。想要这个，一点也不
  过分"): without a ``need`` slot the reply has no need paragraph (an image instead).
* The low-battery haven line came back word for word.
* "Olivia都在": a Latin name filled in next to a Chinese character gets a space.
"""

from __future__ import annotations

import random

import pytest

from olivia.core.chang.onboarding import fill_slots
from olivia.core.language import LanguageEngine
from olivia.core.language.data import load_language_data
from olivia.core.language.engine import Slots
from olivia.core.models import HelpStage, PersonaSpectrum
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
DATA = load_language_data(TAX)
PERSONAS = list(PersonaSpectrum)
MIRRORS = [f"你提到第{i}件事一直压在心上" for i in "一二三四五六七八九十"]


def _engine(persona: PersonaSpectrum, seed: int = 3) -> LanguageEngine:
    return LanguageEngine(TAX, rng=random.Random(seed), data=DATA.for_persona(persona))


def _slots(mirror: str, need: str = "确定感") -> Slots:
    return Slots(
        user_name="小林",
        agent_name="Olivia",
        emotion="委屈",
        mirror=mirror,
        metaphor="一盏留在窗边的小灯",
        need=need,
    )


@pytest.mark.parametrize("persona", PERSONAS)
@pytest.mark.parametrize("stage", [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY])
def test_no_opening_twice_while_another_is_left(persona: PersonaSpectrum, stage: HelpStage) -> None:
    engine = _engine(persona)
    openings = engine.data.templates.parts[stage][0].variants
    seen: list[str] = []
    for mirror in MIRRORS[: len(openings)]:
        text = engine.compose(stage, _slots(mirror))
        seen.append(text.split("\n\n")[0].replace(mirror, "{mirror}"))
    assert len(set(seen)) == len(seen), seen


@pytest.mark.parametrize("persona", PERSONAS)
def test_clarify_without_a_need_names_none(persona: PersonaSpectrum) -> None:
    engine = _engine(persona)
    parts = engine.data.templates.parts[HelpStage.S_CLARIFY]
    need_heads = [
        v.split("{")[0] for p in parts if p.name == "need" for v in p.variants if v.split("{")[0]
    ]
    for mirror in MIRRORS[:6]:
        text = engine.compose(HelpStage.S_CLARIFY, _slots(mirror, need=""))
        assert "确定感" not in text and "渴望" not in text, text
        assert not any(p.startswith(tuple(need_heads)) for p in text.split("\n\n")), text
        if persona is not PersonaSpectrum.SILENT_ANCHOR:
            assert len(text.split("\n\n")) == 3, text


@pytest.mark.parametrize("persona", PERSONAS)
def test_haven_line_not_repeated_while_another_is_left(persona: PersonaSpectrum) -> None:
    engine = _engine(persona)
    pool = engine.data.templates.haven
    said = [engine.compose(HelpStage.S_HAVEN, _slots("")) for _ in pool]
    assert len(set(said)) == len(said), said


def test_latin_name_next_to_chinese_gets_a_space() -> None:
    engine = _engine(PersonaSpectrum.GENTLE_HOLDING)
    slots = Slots(user_name="Lin", agent_name="Olivia")
    text = engine.compose(HelpStage.S_READY, slots)
    assert "Lin，" in text or "Lin " in text or "Lin" not in text
    assert fill_slots("之后想聊聊，{agent_name}都在。", agent_name="Olivia") == (
        "之后想聊聊，Olivia 都在。"
    )
    assert fill_slots("叫「{agent_name}」了", agent_name="Olivia") == "叫「Olivia」了"
    assert fill_slots("{agent_name}都在", agent_name="小O") == "小O 都在"
    assert fill_slots("我是{agent_name}", agent_name="Olivia") == "我是 Olivia"
