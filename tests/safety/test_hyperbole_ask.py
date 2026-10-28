"""Owner decision 2026-10-28: the "X得 / 到想死" figure of speech asks first.

"烦得想死", "加班加到想死", "激到我想死", "气得想死" are no longer L2 for the rules: when every
Stage 2 phrase of the message lies inside such a frame (``risk.yaml`` ``hyperbole_ask``: an
everyday stem, 得 / 到 with an optional 我 / 人 / 都 / 快, then 想死), no other rule cue occurs
(no other Stage 2, negation or pair-anchor phrase, no composition, no pair cue) and no veto
does (seriousness such as 真的 / 不是开玩笑 / 那种, a run of days, a plan, a time, a means, a
farewell or another death word), the rules give L1 with the D3 question
(``ASK_INTENT_HYPERBOLE_DIE``) and an injected model counts at most as L1 (a model failure
still L2). Anything else keeps the old reading, so d40, d41 and d43 of ``cases.yaml`` stay
L2. The session side (the question, the answer, an earlier risk cue in the session) is in
``tests/session/test_owner_decisions_1028.py``.

The sentences are written here; none is taken from an evaluation set.
"""

from __future__ import annotations

import shutil
from importlib import resources

import pytest

from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import RiskPrediction, SafetyScreen
from olivia.core.safety.lexicon import LexiconError, load_safety_lexicons
from olivia.core.safety.tracker import CrisisTracker
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
RULES = SafetyScreen(TAX, LEX)
CUE = "ASK_INTENT_HYPERBOLE_DIE"

ASKS = [
    # The owner's examples.
    "烦得想死",
    "我烦得想死",
    "这个月加班加到想死",
    "激到我想死",
    "气得想死",
    # More of the same frame.
    "被老板骂得想死",
    "写论文写到想死了",
    "今天热得我都想死",
    "堵车堵得想死，还要一个小时",
    "累得我快想死了",
]

STAYS_L2 = [
    "烦得想死 真的不想活了",  # cases.yaml d40: another Stage 2 phrase
    "烦得想死 是真的想死那种",  # d41: a 想死 outside the frame
    "加班加到想死 不是开玩笑",  # d43: seriousness
    "我真的烦得想死",  # seriousness
    "每天都累得想死",  # a run of days
    "气得想死，想好了",  # a plan
    "烦得想死，今晚就走",  # a time
    "烦得想死，药都攒够了",  # a means (a composition fires)
    "烦得想死，我不会自杀的",  # a negation phrase: the rules saw a death word
    "烦得想死，想去死",  # another death word
    "我觉得想死",  # 觉得 is no stem: real ideation
    "最近变得很想死",
    "痛苦得想死",  # psychological pain is no stem
    "累得想死掉",  # 想死掉 is longer than the frame
]


@pytest.mark.parametrize("text", ASKS)
def test_the_frame_alone_is_l1_with_the_question(text):
    assessment = RULES.assess(text)
    assert assessment.level is CrisisLevel.L1, assessment
    assert assessment.asks_intent is True
    assert assessment.cue_ids == (CUE,)
    assert assessment.rule_level is CrisisLevel.L1
    assert assessment.rule_clear is False


@pytest.mark.parametrize("text", STAYS_L2)
def test_any_other_cue_or_veto_keeps_l2_or_above(text):
    assert RULES.assess(text).level >= CrisisLevel.L2, text


def test_everyday_death_idioms_are_unchanged():
    for text in ("累死了", "笑死", "气死我了", "想死你了"):
        assert RULES.assess(text).level is CrisisLevel.L0


def test_someone_elses_reported_words_are_still_theirs():
    """Reported speech voids its Stage 2 phrases first; the frame never brings them back."""
    assessment = RULES.assess("她跟我说她想死，被老板骂得")
    assert assessment.rule_level is CrisisLevel.L0 and not assessment.asks_intent


class Fixed:
    def __init__(self, level: CrisisLevel, score: float) -> None:
        self.prediction = RiskPrediction(level, score, ())

    def predict(self, text: str) -> RiskPrediction:
        return self.prediction


@pytest.mark.parametrize(
    ("level", "score"), [(CrisisLevel.L2, 0.55), (CrisisLevel.L2, 0.75), (CrisisLevel.L3, 0.95)]
)
def test_an_injected_model_counts_at_most_l1_on_the_frame_alone(level, score):
    screen = SafetyScreen(TAX, LEX, Fixed(level, score), model_plan_evidence=True)
    assessment = screen.assess("烦得想死")
    assert assessment.level is CrisisLevel.L1 and assessment.asks_intent
    assert not assessment.has_plan_evidence


def test_a_model_failure_on_the_frame_is_l2():
    class Broken:
        def predict(self, text: str) -> RiskPrediction:
            raise RuntimeError("boom")

    assert SafetyScreen(TAX, LEX, Broken()).assess("烦得想死").level is CrisisLevel.L2


def test_the_model_is_not_capped_when_the_frame_has_a_veto():
    screen = SafetyScreen(TAX, LEX, Fixed(CrisisLevel.L2, 0.75))
    assert screen.assess("加班加到想死 不是开玩笑").level is CrisisLevel.L2


def test_the_tracker_escalates_the_frame_after_earlier_risk_in_the_session():
    tracker = CrisisTracker(TAX, LEX)
    tracker.observe(RULES.assess("活着好累"), "活着好累")
    tracker.observe(RULES.assess("今天去公园走了走"), "今天去公园走了走", 0.5)
    status = tracker.observe(RULES.assess("烦得想死"), "烦得想死")
    assert status.level is CrisisLevel.L2 and status.in_crisis


def test_the_tracker_does_not_count_the_frame_itself_as_earlier_risk():
    tracker = CrisisTracker(TAX, LEX)
    first = tracker.observe(RULES.assess("烦得想死"), "烦得想死")
    assert first.level is CrisisLevel.L1 and not first.in_crisis
    tracker.observe(RULES.assess("今天去公园走了走"), "今天去公园走了走", 0.5)
    second = tracker.observe(RULES.assess("气得想死"), "气得想死")
    assert second.level is CrisisLevel.L1 and not second.in_crisis


# -- the section itself ---------------------------------------------------------------------------


def _lexicons_with(tmp_path, old: str, new: str):
    source = resources.files("olivia").joinpath("data/lexicons")
    for name in ("risk.yaml", "red_flags.yaml", "perception.yaml"):
        shutil.copyfile(str(source.joinpath(name)), tmp_path / name)
    risk = tmp_path / "risk.yaml"
    text = risk.read_text(encoding="utf-8")
    assert old in text
    risk.write_text(text.replace(old, new, 1), encoding="utf-8")
    return load_safety_lexicons(TAX, tmp_path)


def test_the_packaged_section_loads():
    rules = LEX.hyperbole_ask
    assert rules.id == CUE
    assert "烦得想死" in rules.frames and "激到我想死" in rules.frames
    assert "觉得想死" not in rules.frames and "感到想死" not in rules.frames
    assert "真的" in rules.vetoes and "不是开玩笑" in rules.vetoes


def test_a_veto_inside_a_frame_does_not_load(tmp_path):
    with pytest.raises(LexiconError, match="never applies"):
        _lexicons_with(tmp_path, "  vetoes: [\n           # seriousness", '  vetoes: ["烦得",\n')


def test_an_id_without_the_ask_prefix_does_not_load(tmp_path):
    with pytest.raises(LexiconError):
        _lexicons_with(tmp_path, f"  id: {CUE}", "  id: HYPERBOLE_DIE")


def test_without_the_section_the_frame_is_l2(tmp_path):
    source = resources.files("olivia").joinpath("data/lexicons")
    for name in ("risk.yaml", "red_flags.yaml", "perception.yaml"):
        shutil.copyfile(str(source.joinpath(name)), tmp_path / name)
    risk = tmp_path / "risk.yaml"
    text = risk.read_text(encoding="utf-8")
    start = text.index("\nhyperbole_ask:\n")
    end = text.find("\n# ", start + 1)
    risk.write_text(text[: start + 1] + (text[end + 1 :] if end != -1 else ""), encoding="utf-8")
    lexicons = load_safety_lexicons(TAX, tmp_path)
    assert lexicons.hyperbole_ask.frames == ()
    assert SafetyScreen(TAX, lexicons).assess("烦得想死").level is CrisisLevel.L2
