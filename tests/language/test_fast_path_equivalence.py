"""The G-3 fast paths of the language step give exactly the output of the code they replace.

``oracle`` is the ``replace_longest`` that shipped before G-3 (it tried every phrase at
every position). The indexed matcher must agree with it on every text the product holds
(templates, cards, language data and lexicons), on the phrases themselves and on random
Chinese strings, for the real W.I.L.L.O.W. tables and for random tables built to collide.
The other oracles below do the same for the rest of the W.I.L.L.O.W. pass, the output gate
and the mirror's pronoun swap.
"""

from __future__ import annotations

import importlib
import random
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from olivia.core.language import gate as gate_module
from olivia.core.language.data import ContentKind, LanguageData, WillowData
from olivia.core.language.filters import (
    _BLANK_RUNS_RE,
    _MASK_BASE,
    _TOKEN_RE,
    apply_willow,
    drop_diagnosis_sentences,
    find_diagnosis_terms,
    mask_terms,
    replace_longest,
)
from olivia.core.language.gate import DIDACTIC_BANNED, OutputGate, digits_of, phone_like_runs
from olivia.core.models import HelpStage
from olivia.core.taxonomy import Taxonomy

# The package re-exports the function mirror(), which shadows the module attribute.
mirror_module = importlib.import_module("olivia.core.language.mirror")
DATA = Path(__file__).resolve().parents[2] / "olivia" / "data"


def oracle(text: str, table: Mapping[str, str]) -> str:
    """The original O(phrases x length) scan, kept verbatim as the reference."""
    if not table:
        return text
    keys = sorted(table, key=len, reverse=True)
    out: list[str] = []
    i = 0
    while i < len(text):
        for key in keys:
            if text.startswith(key, i):
                out.append(table[key])
                i += len(key)
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _strings(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, Mapping):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, list | tuple):
        for item in node:
            yield from _strings(item)


@cache
def corpus() -> tuple[str, ...]:
    """Every string in every packaged YAML file (templates, cards, data, lexicons)."""
    texts: list[str] = []
    for path in sorted(DATA.rglob("*.yaml")):
        texts.extend(_strings(yaml.safe_load(path.read_text(encoding="utf-8"))))
    return tuple(dict.fromkeys(t for t in texts if t))


def _tables(lang: LanguageData) -> dict[str, Mapping[str, str]]:
    willow = lang.willow
    masks = {term: chr(_MASK_BASE + i) for i, term in enumerate(willow.protected_terms)}
    return {
        "depathologize": willow.depathologize,
        "didactic_rewrites": willow.didactic_rewrites,
        "protected_terms": masks,
    }


TABLES = ["depathologize", "didactic_rewrites", "protected_terms"]


def test_the_corpus_covers_templates_cards_and_lexicons() -> None:
    texts = corpus()
    assert len(texts) > 1000
    assert {p.parent.name for p in DATA.rglob("*.yaml")} >= {
        "templates",
        "cards",
        "language",
        "lexicons",
    }


@pytest.mark.parametrize("name", TABLES)
def test_every_packaged_text_matches_the_oracle(lang: LanguageData, name: str) -> None:
    table = _tables(lang)[name]
    for text in corpus():
        assert replace_longest(text, table) == oracle(text, table), (name, text)


@pytest.mark.parametrize("name", TABLES)
def test_phrases_and_their_runs_match_the_oracle(lang: LanguageData, name: str) -> None:
    tables = _tables(lang)
    table = tables[name]
    phrases = [p for t in tables.values() for kv in t.items() for p in kv]
    rng = random.Random(20261023)
    texts = list(phrases)
    texts += ["".join(phrases)]
    texts += ["".join(rng.choices(phrases, k=rng.randint(2, 12))) for _ in range(2000)]
    # Phrases cut and glued mid-word: partial prefixes must fall back to single characters.
    texts += [
        "".join(p[: rng.randint(0, len(p))] for p in rng.sample(phrases, 6)) for _ in range(2000)
    ]
    for text in texts:
        assert replace_longest(text, table) == oracle(text, table), (name, text)


def _alphabet(lang: LanguageData) -> str:
    chars = {ch for t in _tables(lang).values() for k in t for ch in k}
    return "".join(sorted(chars)) + "的了我你很是在有，。！？\n 9-:"


@settings(max_examples=400, deadline=None)
@given(data=st.data())
def test_random_chinese_strings_match_the_oracle(lang: LanguageData, data: st.DataObject) -> None:
    tables = _tables(lang)
    table = tables[data.draw(st.sampled_from(TABLES))]
    text = data.draw(
        st.text(
            alphabet=st.sampled_from(_alphabet(lang))
            | st.characters(min_codepoint=0x4E00, max_codepoint=0x9FFF),
            max_size=200,
        )
    )
    assert replace_longest(text, table) == oracle(text, table)


# Random tables over a tiny alphabet: keys nest, overlap and share prefixes and suffixes.
_TINY = st.text(alphabet="心理治疗病a", min_size=1, max_size=4)


@settings(max_examples=600, deadline=None)
@given(
    table=st.dictionaries(_TINY, st.text(alphabet="心理治疗病ab照料", max_size=3), max_size=12),
    text=st.text(alphabet="心理治疗病ab", max_size=60),
)
def test_random_colliding_tables_match_the_oracle(table: dict[str, str], text: str) -> None:
    assert replace_longest(text, table) == oracle(text, table)


def test_mask_terms_still_masks_longest_first(lang: LanguageData) -> None:
    terms = lang.willow.protected_terms
    for text in corpus():
        masked, key = mask_terms(text, terms)
        placeholders = {term: chr(_MASK_BASE + i) for i, term in enumerate(terms)}
        assert masked == oracle(text, placeholders)
        assert "".join(key.get(ch, ch) for ch in masked) == text


def test_regex_metacharacters_are_literal() -> None:
    table = {".": "。", "a|b": "x", "(": "（", "\\d": "D", "*": "×"}
    text = "a|b.c(\\d*ab"
    assert replace_longest(text, table) == oracle(text, table) == "x。c（D×ab"


def test_an_empty_phrase_never_matches() -> None:
    # The original scan never returned on an empty phrase; the matcher ignores it.
    assert replace_longest("焦虑", {"": "x"}) == "焦虑"
    assert replace_longest("焦虑a", {"": "x", "焦虑": "紧张"}) == "紧张a"


def test_a_table_mutated_between_calls_is_honoured() -> None:
    table = {"焦虑": "紧张"}
    assert replace_longest("焦虑", table) == "紧张"
    table["焦虑"] = "不安"
    assert replace_longest("焦虑", table) == "不安"


# -- the rest of the W.I.L.L.O.W. pass, the output gate and the mirror -----------------------
# Each oracle is the code that shipped before G-3, kept verbatim.


def oracle_find_diagnosis_terms(text: str, willow: WillowData) -> tuple[str, ...]:
    folded = text.casefold()
    return tuple(term for term in willow.diagnosis_terms if term in folded)


def oracle_drop_diagnosis_sentences(text: str, willow: WillowData) -> str:
    tokens = _TOKEN_RE.findall(text)
    kept = [t for t in tokens if t == "\n" or not oracle_find_diagnosis_terms(t, willow)]
    if len(kept) == len(tokens):
        return text
    joined = "".join(kept)
    lines = [line.rstrip() for line in joined.split("\n")]
    return _BLANK_RUNS_RE.sub("\n\n", "\n".join(lines)).strip()


def oracle_apply_willow(text: str, kind: ContentKind, willow: WillowData) -> str:
    placeholders = {term: chr(_MASK_BASE + i) for i, term in enumerate(willow.protected_terms)}
    masked = oracle(text, placeholders)
    key = {ph: term for term, ph in placeholders.items()}
    masked = oracle_drop_diagnosis_sentences(masked, willow)
    if not willow.exempt("depathologize", kind):
        masked = oracle(masked, willow.depathologize)
    if not willow.exempt("didactic_rewrites", kind):
        masked = oracle(masked, willow.didactic_rewrites)
    return "".join(key.get(ch, ch) for ch in masked)


def oracle_phone_like_runs(text: str, masked_literals: Iterable[str] = ()) -> tuple[str, ...]:
    folded = unicodedata.normalize("NFKC", text)
    for literal in sorted(set(masked_literals), key=len, reverse=True):
        folded = folded.replace(unicodedata.normalize("NFKC", literal), gate_module._MASK)
    folded = gate_module._CLOCK_RE.sub(gate_module._MASK, folded)
    runs = (digits_of(m.group()) for m in gate_module._DIGIT_RUN_RE.finditer(folded))
    return tuple(run for run in runs if len(run) >= gate_module.MIN_PHONE_DIGITS)


def oracle_swap(clause: str, conflict: bool) -> str:
    """The pronoun swap scanned at every character (F3 rule: 自己 only for what the
    clause's own subject 我 does to itself)."""
    out: list[str] = []
    subject_me = mirror_module._subject_is_me(clause)
    seen_self = False
    i = 0
    while i < len(clause):
        word = next((w for w in mirror_module._NON_PRONOUN if clause.startswith(w, i)), None)
        if word is not None:
            out.append(word)
            i += len(word)
            continue
        for src, dst in (("我们", "你们"), ("咱们", "你们"), ("你们", "他们")):
            if clause.startswith(src, i):
                out.append(dst)
                i += len(src)
                break
        else:
            ch = clause[i]
            if ch in "你您":
                out.append("对方")
            elif ch == "我":
                owned = clause.startswith("我的", i) or clause.startswith("我自己", i)
                reflexive = (
                    not conflict
                    and subject_me
                    and seen_self
                    and not owned
                    and clause[:i].endswith(mirror_module._REFLEXIVE_VERBS)
                )
                out.append("自己" if reflexive else "你")
                seen_self = True
            else:
                out.append(ch)
            i += 1
    return "".join(out)


def _texts(lang: LanguageData) -> list[str]:
    """The corpus, plus every diagnosis term, protected term and number-bearing phrase."""
    willow = lang.willow
    extra = [f"你可能有{t}。别担心。" for t in willow.diagnosis_terms]
    extra += [f"关于{t}，你应该知道。" for t in willow.protected_terms]
    extra += ["拨 0477 13 11 14 或 1300-22-4636", "9:00-12:00", "①②③ 热线", "１２３４５"]
    return [*corpus(), *extra]


@pytest.mark.parametrize("kind", list(ContentKind))
def test_apply_willow_matches_the_oracle(lang: LanguageData, kind: ContentKind) -> None:
    for text in _texts(lang):
        assert apply_willow(text, kind, lang.willow) == oracle_apply_willow(text, kind, lang.willow)


def test_diagnosis_scans_match_the_oracle(lang: LanguageData) -> None:
    willow = lang.willow
    for text in _texts(lang):
        assert find_diagnosis_terms(text, willow) == oracle_find_diagnosis_terms(text, willow)
        assert drop_diagnosis_sentences(text, willow) == oracle_drop_diagnosis_sentences(
            text, willow
        )


def _card_titles(lang: LanguageData) -> tuple[str, ...]:
    """Every card title the gate masks: the everyday name and the taxonomy name (F3)."""
    return tuple(t for card in lang.cards.cards.values() for t in (card.title, card.taxonomy_title))


def test_phone_like_runs_match_the_oracle(lang: LanguageData) -> None:
    titles = _card_titles(lang)
    for text in _texts(lang):
        assert phone_like_runs(text) == oracle_phone_like_runs(text)
        assert phone_like_runs(text, titles) == oracle_phone_like_runs(text, titles)


def test_gate_reasons_match_the_oracle(tax: Taxonomy, lang: LanguageData) -> None:
    gate = OutputGate(tax, lang)
    titles = _card_titles(lang)
    grade_a = tuple(
        sorted((tax.methods()[m].name_zh for m in tax.grade_a_ids()), key=len, reverse=True)
    )
    willow = lang.willow
    for text in _texts(lang):
        for kind in ContentKind:
            for stage in (HelpStage.S_EXPLORE, HelpStage.S_EMPOWER):
                folded = text.casefold()
                want: list[str] = [] if text.strip() else ["empty:"]
                if text.strip():
                    want += [f"diagnosis:{t}" for t in willow.diagnosis_terms if t in folded]
                    want += [f"number:{r}" for r in oracle_phone_like_runs(text, titles)]
                    if kind is not ContentKind.CARD and stage is not HelpStage.S_EMPOWER:
                        want += [f"grade_a_title:{t}" for t in grade_a if t in text]
                    if not willow.exempt("didactic_rewrites", kind):
                        want += [f"didactic:{w}" for w in DIDACTIC_BANNED if w in text]
                got = gate.reasons(text, kind=kind, stage=stage)
                assert got == tuple(dict.fromkeys(want)), (text, kind, stage)


@settings(max_examples=400, deadline=None)
@given(
    clause=st.text(alphabet="我你您们咱自忘无唯敌死活好的己很累他" + "，a1", max_size=40),
    conflict=st.booleans(),
)
def test_mirror_swap_matches_the_oracle(clause: str, conflict: bool) -> None:
    assert mirror_module._swap(clause, conflict) == oracle_swap(clause, conflict)


def test_mirror_swap_matches_the_oracle_on_the_corpus() -> None:
    for text in corpus():
        for conflict in (False, True):
            assert mirror_module._swap(text, conflict) == oracle_swap(text, conflict)
