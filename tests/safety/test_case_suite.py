from collections import Counter
from pathlib import Path

import pytest
import yaml

from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.normalize import normalize
from olivia.core.safety.red_flags import RedFlagDetector
from olivia.core.safety.tracker import CrisisTracker
from olivia.core.taxonomy import load_taxonomy

HERE = Path(__file__).parent
CASES = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
SESSIONS = yaml.safe_load((HERE / "sessions.yaml").read_text(encoding="utf-8"))
RF_CASES = yaml.safe_load((HERE / "red_flag_cases.yaml").read_text(encoding="utf-8"))
KNOWN_FP = yaml.safe_load((HERE / "known_false_positives.yaml").read_text(encoding="utf-8"))
HOLDOUT = yaml.safe_load((HERE / "holdout_probe.yaml").read_text(encoding="utf-8"))
MINIMUMS = {
    "L3_MEANS": 40,
    "L3_TIME_PLACE": 25,
    "L3_ACT_FAREWELL": 25,
    "L2_IDEATION": 60,
    "L1_WEARY": 50,
    "HYPERBOLE": 50,
    "NEGATION_PURE": 25,
    "NEGATION_WITH_MEANS": 15,
    "BENIGN": 30,
    "DOUBLE_NEGATION_OR_METHOD": 15,
}

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)


def test_case_set_size_and_category_minimums():
    counts = Counter(c["category"] for c in CASES)
    assert len(CASES) >= 300
    for cat, minimum in MINIMUMS.items():
        assert counts[cat] >= minimum, cat
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert len({c["text"] for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_single_turn_case(case):
    assert SCREEN.assess(case["text"]).level is CrisisLevel[case["expect"]]


def test_session_count():
    assert len(SESSIONS) >= 12


@pytest.mark.parametrize("session", SESSIONS, ids=[s["id"] for s in SESSIONS])
def test_session(session):
    tracker = CrisisTracker(TAX, LEX)
    for i, turn in enumerate(session["turns"]):
        status = tracker.observe(SCREEN.assess(turn["text"]), turn["text"])
        assert status.level is CrisisLevel[turn["expect_level"]], (session["id"], i)
        assert status.in_crisis is turn["expect_in_crisis"], (session["id"], i)


def test_red_flag_case_coverage():
    positives = Counter(code for c in RF_CASES for code in c["expect"])
    assert all(positives[code] >= 3 for code in TAX.red_flags())
    assert sum(1 for c in RF_CASES if not c["expect"]) >= 10


@pytest.mark.parametrize("case", RF_CASES, ids=[c["id"] for c in RF_CASES])
def test_red_flag_case(case):
    detector = RedFlagDetector(TAX, LEX)
    assert detector.detect(case["text"]) == frozenset(case["expect"])


@pytest.mark.parametrize("case", KNOWN_FP, ids=[c["id"] for c in KNOWN_FP])
def test_known_false_positive_stays_pinned(case):
    assert SCREEN.assess(case["text"]).level is CrisisLevel[case["expect"]]


@pytest.mark.parametrize("case", HOLDOUT, ids=[c["id"] for c in HOLDOUT])
def test_holdout_probe(case):
    assert SCREEN.assess(case["text"]).level is CrisisLevel[case["expect"]]


def test_case_texts_are_not_bare_lexicon_phrases():
    # Screened sections only: confirm/veto words such as 不知道 are ordinary vocabulary.
    screened = ("stage1", "stage2", "hyperbole", "negation")
    risk = {p for sec in screened for cue in LEX.cues(sec) for p in cue.patterns}
    flags = {p for cue in LEX.red_flags.values() for p in cue.patterns}
    # The holdout probe keeps the reviewer's exact sentences, so it is not checked here.
    groups = [(CASES + KNOWN_FP, risk), (RF_CASES, flags)]
    for cases, phrases in groups:
        for case in cases:
            text = normalize(case["text"])
            assert text not in phrases, case["id"]
            splits = ((text[:i], text[i:]) for i in range(1, len(text)))
            assert not any(a in phrases and b in phrases for a, b in splits), case["id"]
