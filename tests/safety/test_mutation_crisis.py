"""Crisis screen behaviour that mutation testing found unchecked (``safety/crisis.py``).

Each test kills one or more surviving mutants listed in ``docs/safety/mutation-report.md``
and asserts a documented rule: the plan-evidence switch (SDD §8.2: ``model_plan_evidence``
is the only switch and ships off), a farewell-family cue raised next to the user's own risk
(``raise_with_risk``, §9.4 item 18) and the habit rules of the "X得 / 到想死" figure (§9.4
items 27 and 32). Every example message is written here.
"""

from __future__ import annotations

import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.compose import CompositionHit
from olivia.core.safety.crisis import RiskPrediction, RuleRiskModel, SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.matcher import Match
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)


class _Fixed:
    def __init__(self, level: L, score: float) -> None:
        self.prediction = RiskPrediction(level, score, ("FAKE",))

    def predict(self, text: str) -> RiskPrediction:
        return self.prediction


# -- the plan-evidence switch on a shared screen (SDD §8.2; SafetyScreen.with_model) --------


def test_a_shared_screen_keeps_the_plan_evidence_switch_off_by_default():
    a = SCREEN.with_model(_Fixed(L.L3, 0.95)).assess("今天就随便聊聊")
    assert (a.level, a.has_plan_evidence) == (L.L2, False)


def test_a_shared_screen_passes_the_plan_evidence_switch_on():
    shared = SCREEN.with_model(_Fixed(L.L3, 0.95), model_plan_evidence=True)
    alone = SafetyScreen(TAX, LEX, _Fixed(L.L3, 0.95), model_plan_evidence=True)
    a = shared.assess("今天就随便聊聊")
    assert (a.level, a.has_plan_evidence) == (L.L3, True)
    assert a == alone.assess("今天就随便聊聊")


# -- raise_with_risk: a Stage 2 phrase outside the raised cue's span is the user's own risk --


def test_a_stage2_phrase_right_after_a_raised_cue_is_outside_its_span():
    # Spans are half-open (CompositionHit.end is exclusive): a phrase that starts where the
    # raised cue ends lies outside it, one that starts inside it does not.
    model = RuleRiskModel(TAX, LEX)
    entry = next(e for e in LEX.compositions.entries if e.raise_with_risk)
    raised = [CompositionHit(entry, 2, 5)]
    assert model._has_own_risk([Match("X", 5, 7)], [], [], raised)
    assert not model._has_own_risk([Match("X", 4, 7)], [], [], raised)
    assert model._has_own_risk([Match("X", 0, 2)], [], [], raised)


# -- rule_clear: "the rules found no risk cue" (owner decision 2026-10-26, §9.4 item 1) -------


def test_a_negated_death_word_is_a_rule_cue():
    # "我不想死" is L0, but the rules saw a death word: no all-clear.
    a = SCREEN.assess("我不想死")
    assert a.level is L.L0 and not a.rule_clear


def test_a_pair_anchor_inside_its_exception_is_still_a_rule_cue():
    a = SCREEN.assess("今天学校讲了预防自杀的知识")
    assert a.level is L.L0 and not a.rule_clear


def test_a_pair_request_word_alone_is_no_rule_cue():
    a = SCREEN.assess("这道题有什么好方法")
    assert a.level is L.L0 and a.rule_clear
    assert SCREEN.assess("今天天气不错").rule_clear


# -- cue ids: an all-figurative message carries its hyperbole cue ids (F8a) ------------------


def test_a_figure_of_speech_alone_reports_its_hyperbole_cue():
    a = SCREEN.assess("想死的心都有了")
    assert a.level is L.L0 and a.cue_ids
    assert all(LEX.risk[cue].section == "hyperbole" for cue in a.cue_ids)


# -- the "X得想死" figure needs no other rule cue: a negation phrase or a pair anchor next to
# it keeps the frame's L2 (crisis.py docstring, owner decision 2026-10-28, §9.4 item 4) -------


def test_the_figure_with_a_negation_phrase_or_a_pair_anchor_stays_l2():
    figure = LEX.hyperbole_ask.id
    assert SCREEN.assess("烦得想死").cue_ids == (figure,)
    for text in ("烦得想死，不会想不开", "烦得想死，别劝我"):
        a = SCREEN.assess(text)
        assert a.level is L.L2 and figure not in a.cue_ids, text


# -- direction controls (round 5, 复测 q4 IN-4): the kept reading is assessed last -----------


class _Recording:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def predict(self, text: str) -> RiskPrediction:
        self.texts.append(text)
        return RiskPrediction(L.L0, 0.05, ())


def test_the_reading_kept_is_the_one_the_model_saw_last():
    # Typed, the message is a death wish; shown (reversed), it is not. The typed reading
    # is kept, and the injected model's last prediction is for it.
    model = _Recording()
    screen = SafetyScreen(TAX, LEX, model)
    a = screen.assess("\u202e我要去死了\u202c")
    assert a.level is L.L2
    assert model.texts[-1] == "我要去死了"


# -- a run of days next to the "X得想死" figure (round 6, §9.4 item 27: someone else's habit
# in a clause of its own; 负责人 2026-11-01 决定 B, §9.4 item 32: a habit of the cause) -------


@pytest.mark.parametrize(
    "text",
    [
        # Someone else's habit, in a clause that names its own subject.
        "做题做得想死，她天天都那样",
        "练琴练得想死，教练天天都这样",
        "教练天天都这样，练琴练得想死",
        "练琴练得想死，我也没办法，教练天天都这样",
        "教练天天都这样，练琴练得想死，真烦",
        # A habit of the cause, in a clause of its own.
        "洗碗洗得想死，难受，每天都要洗一大堆",
        "洗碗洗得想死，每天都要洗一大堆，真难受，唉",
    ],
)
def test_a_run_of_days_that_is_someone_elses_or_the_causes_asks_first(text):
    a = SCREEN.assess(text)
    assert (a.level, a.asks_intent) == (L.L1, True), text
    assert a.cue_ids == (LEX.hyperbole_ask.id,)


@pytest.mark.parametrize(
    "text",
    [
        # The user's own run of days, one with no subject, or one in the figure's own clause.
        "做题做得想死，我天天都那样",
        "做题做得想死，最近天天都那样",
        "真烦，做题天天做得想死",
        # A run of days in a clause about the pain itself.
        "洗碗洗得想死，难受的是我每天都要洗，唉",
    ],
)
def test_a_run_of_days_of_the_users_own_keeps_the_figure_at_l2(text):
    assert SCREEN.assess(text).level is L.L2, text


# -- clear_denial: the F10 conditions on a no (owner decision 2026-10-26, §9.4 items 6, 26) ---


def test_a_plain_no_with_a_denial_passes_the_f10_conditions():
    assert SCREEN.clear_denial("不是，我不想死")
    # A hyperbole outside the denial is no Stage 2 phrase.
    assert SCREEN.clear_denial("不是，我不想死，累死了")


@pytest.mark.parametrize(
    "text",
    [
        "不是，下辈子见",  # a Stage 1 phrase
        "不是，我没想自杀",  # a pair anchor
        "不是，人生真的没什么意义",  # a composition
        "不是，我觉得自己是个累赘",  # an ask composition
        "谁说我不想死",  # a negated denial
        "不是，就是想死",  # a Stage 2 phrase outside every denial
        "不是，我不想死，可是好累",  # a contrast
        "不是，我不想死，今晚再说",  # a veto
    ],
)
def test_a_no_with_a_rule_cue_or_a_negated_denial_is_not_clear(text):
    assert not SCREEN.clear_denial(text), text


# -- reported_risk: someone else's words read on their own (问题单第 6 条, §9.4 item 8) -------


def test_someone_elses_death_wish_is_read_as_said_with_every_field():
    r = SCREEN.reported_risk("她跟我说她想自杀")
    assert r is not None
    assert (r.level, r.plan, r.user_clear, r.rule_risk) == (L.L2, False, True, True)
    assert (r.anchor, r.farewell, r.user_speaks) == (True, 0, False)


def test_someone_elses_plan_and_farewell_are_reported():
    plan = SCREEN.reported_risk("她跟我说她遗书都写好了")
    assert plan is not None and (plan.level, plan.plan) == (L.L3, True)
    strong = SCREEN.reported_risk("她说永别了")
    assert strong is not None and strong.farewell == 2
    weak = SCREEN.reported_risk("她说大家再见了")
    assert weak is not None and (weak.farewell, weak.rule_risk) == (1, False)


@pytest.mark.parametrize(
    "text",
    [
        "她跟我说她不想活了，活着好累",  # a cue of the user's own outside her words
        "她问我怎么自杀最快",  # a way asked for is never someone else's business alone
    ],
)
def test_a_rule_cue_outside_the_reported_words_is_no_user_all_clear(text):
    r = SCREEN.reported_risk(text)
    assert r is not None and not r.user_clear, text


def test_the_user_speaking_outside_the_reported_words_is_reported():
    r = SCREEN.reported_risk("她说她很好，我想死")
    assert r is not None and r.user_speaks and not r.user_clear


def test_no_reported_words_and_plain_reported_words():
    assert SCREEN.reported_risk("今天天气不错") is None
    r = SCREEN.reported_risk("他说他压力好大")
    assert r is not None
    assert (r.level, r.plan, r.rule_risk, r.anchor, r.user_clear) == (
        L.L0,
        False,
        False,
        False,
        True,
    )


def test_the_models_own_l3_on_reported_words_is_their_plan_but_no_rule_risk():
    screen = SafetyScreen(TAX, LEX, _Fixed(L.L3, 0.7))
    r = screen.reported_risk("他说他压力好大")
    assert r is not None
    assert (r.level, r.plan, r.rule_risk) == (L.L2, True, False)


def test_a_request_word_alone_outside_the_reported_words_keeps_the_all_clear():
    r = SCREEN.reported_risk("她跟我说她想自杀，有什么办法能帮她")
    assert r is not None and r.user_clear


def test_a_composition_of_the_users_own_outside_the_reported_words_is_no_all_clear():
    r = SCREEN.reported_risk("她说她没事，可我觉得人生真的没什么意义")
    assert r is not None and not r.user_clear and r.user_speaks


def test_reported_words_in_english_are_read_on_the_raw_text():
    r = SCREEN.reported_risk("She told me she wants to die")
    assert r is not None and r.level is L.L2 and r.user_clear


def test_the_anchor_flag_needs_a_death_word_and_an_l1_is_rule_risk():
    dying = SCREEN.reported_risk("她说她要去死")
    assert dying is not None and dying.anchor
    weary = SCREEN.reported_risk("她说活着没意思")
    assert weary is not None
    assert (weary.level, weary.rule_risk, weary.anchor) == (L.L1, True, False)


@pytest.mark.parametrize(
    "text",
    [
        "她跟我说她不想活了",  # a word for dying by one's own hand (reported.names_death)
        "he said he wants to take his own life",  # a pair anchor only
    ],
)
def test_either_kind_of_death_word_sets_the_anchor_flag(text):
    r = SCREEN.reported_risk(text)
    assert r is not None and r.anchor, text


def test_a_report_inside_the_reported_words_is_not_voided_again():
    # The reported words are rated as the user's own words: a second report inside them
    # ("同事说……") is no reason to void their risk.
    r = SCREEN.reported_risk("我妈说她同事说想死")
    assert r is not None and r.level is L.L2


@pytest.mark.parametrize("text", ["活着活得想死", "哭着哭得想死"])
def test_the_figure_with_a_verb_of_living_or_pain_said_twice_stays_l2(text):
    # Round 5: a verb of inner pain or of living is no everyday verb, so the repeated-verb
    # figure stays L2 for it; an everyday verb said twice asks first.
    assert SCREEN.assess(text).level is L.L2, text
    assert SCREEN.assess("整理整理得想死").cue_ids == (LEX.hyperbole_ask.id,)
