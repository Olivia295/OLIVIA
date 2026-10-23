from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.perception.lexicon import (
    PerceptionLexiconError,
    load_perception_lexicon,
)
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy, load_taxonomy

PACKAGED = Path(__file__).resolve().parents[2] / "olivia" / "data" / "lexicons" / "perception.yaml"


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load_taxonomy()


def _doc() -> dict[str, Any]:
    loaded = yaml.safe_load(PACKAGED.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _write(tmp_path: Path, doc: Any) -> Path:
    (tmp_path / "perception.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return tmp_path


def _load_mutated(tax: Taxonomy, tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    doc = _doc()
    mutate(doc)
    load_perception_lexicon(tax, _write(tmp_path, doc))


def test_packaged_lexicon_loads(tax: Taxonomy) -> None:
    lex = load_perception_lexicon(tax)
    assert set(lex.emotion_cues) <= set(tax.values("emotions"))
    assert tuple(lex.spectrum_cues) == tax.spectrum_ids()
    assert all(lex.spectrum_cues.values())
    assert lex.direct_request and lex.lock_on and lex.lock_off
    assert len(lex.aversion) >= 25 and len(lex.intent_confirmed) >= 20
    assert lex.feedback_done and lex.feedback_not_now and lex.feedback_unhelpful
    assert lex.feedback_unclear and lex.answer_affirm and lex.answer_decline
    assert lex.kit_recall


def test_feedback_and_answers_are_stored_without_marks(tax: Taxonomy, tmp_path: Path) -> None:
    doc = _doc()
    doc["feedback"]["done"].append("照著做完啦！")
    doc["answers"]["affirm"].append("好滴~")
    lex = load_perception_lexicon(tax, _write(tmp_path, doc))
    assert "照着做完啦" in lex.feedback_done
    assert "好滴" in lex.answer_affirm


def test_packaged_lexicon_has_enough_cues_per_emotion(tax: Taxonomy) -> None:
    lex = load_perception_lexicon(tax)
    assert all(len(phrases) >= 15 for phrases in lex.emotion_cues.values())


def test_alias_keys_fold_into_the_canonical_emotion(tax: Taxonomy) -> None:
    lex = load_perception_lexicon(tax)
    assert "insomnia" not in lex.emotion_cues
    assert "睡不着" in lex.emotion_cues["anxiety"]  # listed under the insomnia alias
    assert "拖延" in lex.emotion_cues["overwhelm"]  # listed under procrastination


def test_emotion_key_order_is_kept_as_priority(tax: Taxonomy) -> None:
    order = list(load_perception_lexicon(tax).emotion_cues)
    # Guide §2.2 rule 4 tie-breaks.
    assert order.index("panic") < order.index("anxiety")
    assert order.index("panic") < order.index("fear")
    assert order.index("hopelessness") < order.index("sadness")
    assert order.index("hopelessness") < order.index("disappointment")
    assert order.index("shame") < order.index("guilt")
    assert order.index("overwhelm") < order.index("anxiety")


def test_phrases_are_folded(tax: Taxonomy, tmp_path: Path) -> None:
    doc = _doc()
    doc["lock_on"].append("只 想 聽 聽")
    lex = load_perception_lexicon(tax, _write(tmp_path, doc))
    assert "只想听听" in lex.lock_on


def _set(path: tuple[Any, ...], value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(doc: dict[str, Any]) -> None:
        node: Any = doc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return mutate


def _append(path: tuple[Any, ...], value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(doc: dict[str, Any]) -> None:
        node: Any = doc
        for key in path:
            node = node[key]
        node.append(value)

    return mutate


def _delete(path: tuple[Any, ...]) -> Callable[[dict[str, Any]], None]:
    def mutate(doc: dict[str, Any]) -> None:
        node: Any = doc
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return mutate


@pytest.mark.parametrize(
    "mutate,message",
    [
        (_set(("version",), 2), "version"),
        (_set(("extra",), []), "unknown sections"),
        (_set(("emotion_cues", "joy"), ["开心死了"]), "unknown emotion 'joy'"),
        (_set(("emotion_cues", "calm"), []), "emotion_cues.calm"),
        (_set(("emotion_cues",), {}), "emotion_cues"),
        (_append(("emotion_cues", "calm"), 7), "not a string"),
        (_append(("emotion_cues", "calm"), "   "), "empty after folding"),
        (_append(("emotion_cues", "calm"), "挺好"), "repeated"),
        (_append(("emotion_cues", "calm"), "焦虑"), "both anxiety and calm"),
        # The alias folds into anxiety, which already lists the phrase.
        (_append(("emotion_cues", "insomnia"), "焦虑"), "repeated|both"),
        (_set(("spectrum_cues", "12"), ["x"]), "spectrum '12'"),
        (_set(("spectrum_cues", 1), ["x"]), "spectrum 1"),
        (_delete(("spectrum_cues", "11")), r"no entry for \['11'\]"),
        (_append(("spectrum_cues", "02"), "社恐"), "both 01 and 02"),
        (_set(("intensity_modifiers", "sideways"), ["x"]), "unknown keys"),
        (_delete(("intensity_modifiers", "lower")), "intensity_modifiers.lower"),
        (_append(("intensity_modifiers", "lower"), "特别"), "both raise and lower"),
        (_set(("direct_request",), []), "direct_request"),
        (_set(("lock_off",), "下一步"), "lock_off"),
        (_append(("lock_off",), "只想说说"), "both lock_on and lock_off"),
        (_append(("direct_request",), "只想说说"), "both direct_request and lock_on"),
        (_delete(("aversion",)), "aversion"),
        (_set(("intent_confirmed",), []), "intent_confirmed"),
        (_append(("aversion",), "会试试"), "both aversion and intent_confirmed"),
        (_append(("aversion",), "别给我建议"), "both lock_on and aversion"),
        (_append(("intent_confirmed",), "给我个方法"), "both direct_request and intent_confirmed"),
        (_delete(("referral_cues",)), "referral_cues"),
        (_set(("negation", "suffixes"), ["x"]), "unknown keys"),
        (_set(("negation", "exceptions"), []), "negation.exceptions"),
        (_append(("negation", "exceptions"), "不"), "both prefixes and exceptions"),
        (_delete(("feedback",)), "'feedback' must be"),
        (_set(("feedback", "maybe"), ["x"]), "feedback: unknown keys"),
        (_delete(("feedback", "unclear")), "feedback.unclear"),
        (_append(("feedback", "done"), "！！"), "only marks"),
        (_append(("feedback", "done"), "做完了！"), "repeated"),
        (_append(("feedback", "done"), "先存着"), "both feedback.done and feedback.not_now"),
        (_append(("feedback", "unhelpful"), "什么破练习"), "both feedback.unhelpful and aversion"),
        (_append(("feedback", "not_now"), "锦囊里的"), "both feedback.not_now and kit_recall"),
        (_append(("answers", "affirm"), "不用了"), "both answers.affirm and answers.decline"),
        (_append(("feedback", "unclear"), "好的"), "both feedback.unclear and answers.affirm"),
        (_set(("answers", "yes"), ["好"]), "answers: unknown keys"),
        (_set(("kit_recall",), []), "kit_recall"),
        (_append(("kit_recall",), "给我个方法"), "both direct_request and kit_recall"),
        (_delete(("situation_cues",)), "situation_cues"),
        (_set(("situation_cues", "SIT-99-01"), ["x"]), "'SIT-99-01' is not a taxonomy id"),
        (_set(("situation_cues", "SIT-06-04"), []), "situation_cues.SIT-06-04"),
        (_append(("situation_cues", "SIT-11-01"), "刚去世"), "both SIT-06-04 and SIT-11-01"),
        (_delete(("contraindication_cues",)), "contraindication_cues"),
        (_set(("contraindication_cues", "NOT_AN_ENUM"), ["x"]), "'NOT_AN_ENUM' is not"),
        (
            _append(("contraindication_cues", "TOXIC_SHAME_SPIRAL"), "家暴"),
            "both TOXIC_SHAME_SPIRAL and INTERPERSONAL_SAFETY_HAZARD",
        ),
    ],
)
def test_invalid_lexicons_are_rejected(
    tax: Taxonomy, tmp_path: Path, mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    with pytest.raises(PerceptionLexiconError, match=message):
        _load_mutated(tax, tmp_path, mutate)


def test_missing_file_is_a_lexicon_error(tax: Taxonomy, tmp_path: Path) -> None:
    with pytest.raises(PerceptionLexiconError, match="cannot read"):
        load_perception_lexicon(tax, tmp_path)


@pytest.mark.parametrize("text,message", [("a: [", "invalid YAML"), ("- 1\n", "mapping")])
def test_malformed_yaml_is_a_lexicon_error(
    tax: Taxonomy, tmp_path: Path, text: str, message: str
) -> None:
    (tmp_path / "perception.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(PerceptionLexiconError, match=message):
        load_perception_lexicon(tax, tmp_path)


def test_situation_and_contraindication_cues_borrow_no_crisis_wording(tax: Taxonomy) -> None:
    """A1: these cues never stand in for a crisis cue, so none repeats a risk.yaml phrase."""
    lex = load_perception_lexicon(tax)
    assert set(lex.situation_cues) == {"SIT-06-04", "SIT-11-01"}
    assert set(lex.contraindication_cues) == {
        "TOXIC_SHAME_SPIRAL",
        "CARDIORESPIRATORY_INSTABILITY",
        "INTERPERSONAL_SAFETY_HAZARD",
    }
    risk_doc = yaml.safe_load((PACKAGED.parent / "risk.yaml").read_text(encoding="utf-8"))
    risk_phrases = {
        normalize(p)
        for section in risk_doc.values()
        if isinstance(section, list)
        for entry in section
        if isinstance(entry, dict)
        for p in entry.get("patterns", [])
        if isinstance(p, str)
    }
    assert len(risk_phrases) > 100
    cues = [
        p
        for group in (lex.situation_cues, lex.contraindication_cues)
        for ps in group.values()
        for p in ps
    ]
    assert not set(cues) & risk_phrases
