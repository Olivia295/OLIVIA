"""Method preferences one method at a time (PRD RSK-06; ``memory/preferences.py``)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from olivia.core.memory.preferences import (
    RECENT_PENALTY,
    MethodPreference,
    PreferenceStatus,
    method_preferences,
    without_method,
)
from olivia.core.methods.bandit import Feedback, ThompsonSampler
from olivia.core.taxonomy import load_taxonomy

NOW = datetime(2026, 10, 22, 23, 30, tzinfo=timezone(timedelta(hours=8)))
GROUNDING, PMR = "30:grounding", "29:pmr_release"
TITLES = {GROUNDING: "感官着陆", PMR: "肌肉放松"}


@pytest.fixture(scope="module")
def tax():
    return load_taxonomy()


def _bandit(tax, *updates):
    sampler = ThompsonSampler(tax)
    for action_id, spectrum, feedback, when in updates:
        sampler.update(action_id, spectrum, feedback, when)
    return sampler.to_dict()


def test_statuses_and_their_order(tax):
    bandit = _bandit(
        tax,
        (GROUNDING, "05", Feedback.HELPFUL, NOW),
        (PMR, "05", Feedback.HELPFUL, NOW - timedelta(days=5)),
        (PMR, "02", Feedback.UNHELPFUL, NOW - timedelta(days=1)),
    )
    assert method_preferences(tax, bandit, NOW, TITLES) == (  # by title
        MethodPreference(GROUNDING, "感官着陆", PreferenceStatus.HELPFUL),
        MethodPreference(PMR, "肌肉放松", PreferenceStatus.UNHELPFUL_RECENTLY),  # it wins
    )


def test_a_not_for_me_recovers_as_it_decays(tax):
    bandit = _bandit(tax, (PMR, "05", Feedback.UNHELPFUL, NOW))
    decay = tax.threshold("thompson_sampling_index.lambda_decay_per_day")
    days = math.log(1 / RECENT_PENALTY) / decay
    recent = method_preferences(tax, bandit, NOW + timedelta(days=days - 0.1), TITLES)
    later = method_preferences(tax, bandit, NOW + timedelta(days=days + 0.1), TITLES)
    assert recent[0].status is PreferenceStatus.UNHELPFUL_RECENTLY
    assert later[0].status is PreferenceStatus.RECOVERED


def test_no_feedback_lists_nothing_and_titles_fall_back_to_the_taxonomy(tax):
    assert method_preferences(tax, {"spectra": {}}, NOW) == ()
    assert method_preferences(tax, {"spectra": {"05": {"nope": {}}}}, NOW) == ()  # unknown arm
    (only,) = method_preferences(tax, _bandit(tax, (PMR, "05", Feedback.HELPFUL, NOW)), NOW)
    assert only.title == tax.action_registry()[PMR].name_zh


def test_without_method_removes_it_from_every_spectrum(tax):
    bandit = _bandit(
        tax,
        (GROUNDING, "05", Feedback.HELPFUL, NOW),
        (GROUNDING, "02", Feedback.UNHELPFUL, NOW),
        (PMR, "05", Feedback.HELPFUL, NOW),
    )
    left = without_method(tax, bandit, GROUNDING)
    assert left == {"spectra": {"05": {PMR: bandit["spectra"]["05"][PMR]}}}
    assert method_preferences(tax, left, NOW, TITLES) == (
        MethodPreference(PMR, "肌肉放松", PreferenceStatus.HELPFUL),
    )
