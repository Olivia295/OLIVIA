from __future__ import annotations

import random

import pytest

from olivia.core.language import LanguageEngine
from olivia.core.language.data import LanguageData, load_language_data
from olivia.core.taxonomy import Taxonomy, load_taxonomy


@pytest.fixture(scope="session")
def tax() -> Taxonomy:
    return load_taxonomy()


@pytest.fixture(scope="session")
def lang(tax: Taxonomy) -> LanguageData:
    return load_language_data(tax)


@pytest.fixture
def engine(tax: Taxonomy, lang: LanguageData) -> LanguageEngine:
    return LanguageEngine(tax, rng=random.Random(20261022), data=lang)
