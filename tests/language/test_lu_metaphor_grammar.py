"""Image slot grammar smoke test (dogfood P6, 2026-10-26).

"我把云在天上走，不急也不赶这个画面放在这里": a template ran straight on from
``{metaphor}`` into more of the same clause ("……这个画面"), and an image that is a whole
clause with a comma in it ("云在天上走，不急也不赶") then breaks the sentence. Every
template variant with ``{metaphor}`` is filled with every image its persona can draw, and
the result must read: an image with a comma only where the slot ends the clause, no doubled
punctuation. After a loss (grief, the bereavement spectrum) no image is food.
"""

from __future__ import annotations

import re

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import PersonaSpectrum
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
DATA = load_language_data(TAX)
_CLAUSE_END = "。，！？；：、」”…"
_DOUBLED = re.compile(r"[。，！？；：、][。，！？；：、]")
FOOD = ("汤", "饭", "饼干", "牛奶", "热茶")


def _images(persona: PersonaSpectrum) -> set[str]:
    metaphors = DATA.metaphors
    own = metaphors.by_persona.get(persona)
    if own is not None:
        return {*own.fallback, *(i for images in own.by_spectrum.values() for i in images)}
    images = set(metaphors.fallback)
    images |= {
        i for cells in metaphors.by_spectrum_yearning.values() for c in cells.values() for i in c
    }
    images |= {i for images in metaphors.by_situation.values() for i in images}
    return images


def _metaphor_variants(persona: PersonaSpectrum) -> list[str]:
    tpl = DATA.for_persona(persona).templates
    return [
        v
        for parts in tpl.parts.values()
        for part in parts
        for v in (*part.variants, *part.unnamed)
        if "{metaphor}" in v
    ]


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
def test_every_image_reads_in_every_slot(persona: PersonaSpectrum) -> None:
    for variant in _metaphor_variants(persona):
        after = variant.split("{metaphor}", 1)[1][:1]
        for image in _images(persona):
            text = variant.replace("{metaphor}", image)
            if "，" in image:
                # A whole clause only where the slot ends a clause or is quoted.
                assert after in _CLAUSE_END, (variant, image)
            assert not _DOUBLED.search(text), text


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
def test_no_food_after_a_loss(persona: PersonaSpectrum) -> None:
    metaphors = DATA.metaphors
    own = metaphors.by_persona.get(persona)
    if own is None:
        grief = [*metaphors.by_situation.get("SIT-06-04", ())]
    else:
        grief = [*own.by_spectrum.get("06", ())]
    assert grief
    assert not [image for image in grief if any(word in image for word in FOOD)]
