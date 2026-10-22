"""Per-field accuracy of the rule stub on hand-labelled sentences (tests/perception/cases.yaml).

The floors sit just under the accuracy measured when the lexicon was frozen; they guard
against regressions and record what a phrase-matching stub can do, not a target. The
``heldout`` half was never used to edit the lexicon, so it is the honest estimate:

    split    emotion  arousal band  dominant spectrum  signals
    tuned    34/40    25/40         34/40              40/40
    heldout  20/40    24/40         18/40              39/40

Arousal-band accuracy is capped by design: the stub starts from each emotion's TAX
default arousal, so every anger message (0.80) or overwhelm message (0.85) lands in
``acute`` however calmly it is written.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub, dominant_spectrum
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import Taxonomy, load_taxonomy

CASES = Path(__file__).with_name("cases.yaml")
FIELDS = ("emotion", "arousal_band", "spectrum", "signals")
FLOORS: dict[str, dict[str, float]] = {
    "tuned": {"emotion": 0.80, "arousal_band": 0.60, "spectrum": 0.80, "signals": 1.00},
    "heldout": {"emotion": 0.45, "arousal_band": 0.55, "spectrum": 0.40, "signals": 0.95},
}
SIGNAL_KEYS = {
    "battery",
    "direct_request",
    "lock_on",
    "lock_off",
    "aversion",
    "intent_confirmed",
    "command",
}


def _cases() -> list[dict[str, Any]]:
    doc = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    assert doc["version"] == 1
    cases = doc["cases"]
    assert isinstance(cases, list)
    return cases


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load_taxonomy()


def test_case_file_is_well_formed(tax: Taxonomy) -> None:
    cases = _cases()
    emotions = set(tax.values("emotions"))
    spectra = {*tax.spectrum_ids(), "none"}
    bands = set(tax.bands("arousal"))
    texts = [c["text"] for c in cases]
    assert len(texts) == len(set(texts)), "duplicate case text"
    for case in cases:
        assert case["split"] in FLOORS
        assert case["emotion"] in emotions, case
        assert case["spectrum"] in spectra, case
        assert case["arousal_band"] in bands, case
        assert set(case.get("signals", {})) <= SIGNAL_KEYS, case
    counts = {split: sum(c["split"] == split for c in cases) for split in FLOORS}
    assert counts == {"tuned": 40, "heldout": 40}


def _expected_signals(case: dict[str, Any]) -> tuple[object, ...]:
    s = case.get("signals", {})
    return (
        s.get("battery"),
        s.get("direct_request", False),
        s.get("lock_on", False),
        s.get("lock_off", False),
        s.get("aversion", False),
        s.get("intent_confirmed", False),
        s.get("command"),
    )


def _accuracy(tax: Taxonomy, split: str) -> dict[str, float]:
    stub = RuleStub(tax, load_perception_lexicon(tax))
    screen = SafetyScreen(tax, load_safety_lexicons(tax))
    cases = [c for c in _cases() if c["split"] == split]
    correct = dict.fromkeys(FIELDS, 0)
    for case in cases:
        ctx, signals = stub.perceive(case["text"], screen.assess(case["text"]))
        got_signals = (
            signals.battery,
            signals.direct_request,
            signals.listening_lock_on,
            signals.listening_lock_off,
            signals.aversion,
            signals.intent_confirmed,
            None if signals.command is None else signals.command.value,
        )
        correct["emotion"] += ctx.fine_grained_emotion == case["emotion"]
        correct["arousal_band"] += tax.band_of("arousal", ctx.arousal) == case["arousal_band"]
        correct["spectrum"] += (dominant_spectrum(ctx.distress_vector) or "none") == case[
            "spectrum"
        ]
        correct["signals"] += got_signals == _expected_signals(case)
    return {field: correct[field] / len(cases) for field in FIELDS}


@pytest.mark.parametrize("split", sorted(FLOORS))
def test_accuracy_stays_above_the_measured_floor(tax: Taxonomy, split: str) -> None:
    accuracy = _accuracy(tax, split)
    below = {f: a for f, a in accuracy.items() if a < FLOORS[split][f]}
    assert not below, f"{split}: {accuracy} (floors {FLOORS[split]})"
