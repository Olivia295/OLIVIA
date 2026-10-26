import json
import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from olivia.core.methods.bandit import STANDALONE_EVIDENCE_LEVEL, Feedback, ThompsonSampler
from olivia.core.taxonomy import Taxonomy, UnknownActionError, load_taxonomy

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load_taxonomy()


def _method_with_level(tax: Taxonomy, level: str) -> str:
    return next(m.id for m in tax.methods().values() if m.evidence_level == level)


def _two_level_i_methods(tax: Taxonomy) -> tuple[str, str]:
    ids = [m.id for m in tax.methods().values() if m.evidence_level == "Level I"]
    return ids[0], ids[1]


@pytest.mark.parametrize(
    "level,expected", [("Level I", (4.0, 1.0)), ("Level II", (3.0, 1.0)), ("Level III", (2.0, 1.0))]
)
def test_prior_follows_evidence_level(
    tax: Taxonomy, level: str, expected: tuple[float, float]
) -> None:
    sampler = ThompsonSampler(tax)
    assert sampler.posterior(_method_with_level(tax, level), "01", NOW) == expected


def test_sub_action_uses_parent_prior_and_alias_resolves(tax: Taxonomy) -> None:
    sampler = ThompsonSampler(tax)
    parent = tax.methods()[tax.action_registry()["30:grounding"].parent_method_id or ""]
    assert parent.evidence_level == "Level III"
    assert sampler.posterior("GROUNDING_54321", "01", NOW) == (2.0, 1.0)
    sampler.update("GROUNDING_54321", "01", Feedback.HELPFUL, NOW)
    assert sampler.posterior("30:grounding", "01", NOW) == (3.0, 1.0)


def test_helpful_increments_alpha(tax: Taxonomy) -> None:
    mid = _method_with_level(tax, "Level I")
    sampler = ThompsonSampler(tax)
    sampler.update(mid, "01", Feedback.HELPFUL, NOW)
    sampler.update(mid, "01", Feedback.HELPFUL, NOW)
    assert sampler.posterior(mid, "01", NOW) == (6.0, 1.0)


def test_unhelpful_increments_beta_and_records_time(tax: Taxonomy) -> None:
    mid = _method_with_level(tax, "Level II")
    sampler = ThompsonSampler(tax)
    sampler.update(mid, "01", Feedback.UNHELPFUL, NOW)
    assert sampler.posterior(mid, "01", NOW) == (3.0, 2.0)
    arm = sampler.to_dict()["spectra"]["01"][mid]  # type: ignore[index]
    assert arm["last_unhelpful_at"] == NOW.isoformat()


def test_not_now_changes_nothing(tax: Taxonomy) -> None:
    mid = _method_with_level(tax, "Level I")
    sampler = ThompsonSampler(tax)
    sampler.update(mid, "01", Feedback.NOT_NOW, NOW)
    assert sampler.posterior(mid, "01", NOW) == (4.0, 1.0)
    assert sampler.to_dict() == {"spectra": {}}


def test_decay_halves_excess_beta_after_half_life(tax: Taxonomy) -> None:
    mid = _method_with_level(tax, "Level I")
    sampler = ThompsonSampler(tax)
    for _ in range(4):
        sampler.update(mid, "01", Feedback.UNHELPFUL, NOW)
    lam = tax.threshold("thompson_sampling_index.lambda_decay_per_day")
    later = NOW + timedelta(days=math.log(2) / lam)
    _, beta_eff = sampler.posterior(mid, "01", later)
    assert beta_eff == pytest.approx(1.0 + 4.0 / 2)
    _, beta_now = sampler.posterior(mid, "01", NOW)
    assert beta_now == pytest.approx(5.0)
    # A clock running backwards never amplifies the penalty.
    _, beta_past = sampler.posterior(mid, "01", NOW - timedelta(days=3))
    assert beta_past == pytest.approx(5.0)


def test_new_unhelpful_does_not_revive_decayed_penalties(tax: Taxonomy) -> None:
    mid = _method_with_level(tax, "Level I")
    sampler = ThompsonSampler(tax)
    for _ in range(4):
        sampler.update(mid, "01", Feedback.UNHELPFUL, NOW)
    lam = tax.threshold("thompson_sampling_index.lambda_decay_per_day")
    later = NOW + timedelta(days=math.log(2) / lam)
    sampler.update(mid, "01", Feedback.UNHELPFUL, later)
    # The four old penalties had halved to 2 before the new one was added.
    assert sampler.posterior(mid, "01", later) == pytest.approx((4.0, 1.0 + 2.0 + 1.0))


def test_exploit_only_above_threshold_picks_max_mean(tax: Taxonomy) -> None:
    good, bad = _two_level_i_methods(tax)
    sampler = ThompsonSampler(tax)
    sampler.update(good, "01", Feedback.HELPFUL, NOW)
    sampler.update(bad, "01", Feedback.UNHELPFUL, NOW)
    above = tax.threshold("arousal.thresholds.exploration_allow") + 0.01
    for seed in range(50):
        rng = random.Random(seed)
        assert sampler.choose([bad, good], "01", above, rng, NOW, explore=True) == good


def test_exploit_only_ties_break_by_candidate_order(tax: Taxonomy) -> None:
    first, second = _two_level_i_methods(tax)
    sampler = ThompsonSampler(tax)
    rng = random.Random(0)
    assert sampler.choose([second, first], "01", 0.95, rng, NOW) == second
    assert sampler.choose([first, second], "01", 0.95, rng, NOW) == first


def test_exploit_only_does_not_consume_randomness(tax: Taxonomy) -> None:
    first, second = _two_level_i_methods(tax)
    sampler = ThompsonSampler(tax)
    rng = random.Random(7)
    sampler.choose([first, second], "01", 0.9, rng, NOW)
    assert rng.getstate() == random.Random(7).getstate()


def test_exploration_boundary_samples_at_0_60_and_exploits_at_0_61(tax: Taxonomy) -> None:
    # CHANG-03b: "Arousal > 0.60" is exploit only, so 0.60 itself still samples.
    assert tax.threshold("arousal.thresholds.exploration_allow") == 0.60
    first, second = _two_level_i_methods(tax)
    sampler = ThompsonSampler(tax)  # equal priors: only a draw can pick the second arm
    sampled = set()
    for seed in range(40):
        rng = random.Random(seed)
        sampled.add(sampler.choose([first, second], "01", 0.60, rng, NOW, explore=True))
        assert rng.getstate() != random.Random(seed).getstate()  # a Beta draw was made
    assert sampled == {first, second}
    for seed in range(40):
        rng = random.Random(seed)
        assert sampler.choose([first, second], "01", 0.61, rng, NOW, explore=True) == first
        assert rng.getstate() == random.Random(seed).getstate()  # no draw: exploit only


def test_sampling_below_threshold_favours_much_better_arm(tax: Taxonomy) -> None:
    good, bad = _two_level_i_methods(tax)
    sampler = ThompsonSampler(tax)
    for _ in range(20):
        sampler.update(good, "01", Feedback.HELPFUL, NOW)
        sampler.update(bad, "01", Feedback.UNHELPFUL, NOW)
    rng = random.Random(2026)
    at_threshold = tax.threshold("arousal.thresholds.exploration_allow")
    picks = [
        sampler.choose([bad, good], "01", at_threshold, rng, NOW, explore=True) for _ in range(1000)
    ]
    assert picks.count(good) >= 900


def test_sampling_explores_between_equal_arms(tax: Taxonomy) -> None:
    first, second = _two_level_i_methods(tax)
    sampler = ThompsonSampler(tax)
    rng = random.Random(11)
    picks = {sampler.choose([first, second], "01", 0.2, rng, NOW, explore=True) for _ in range(200)}
    assert picks == {first, second}


def test_choose_is_deterministic_for_a_seed(tax: Taxonomy) -> None:
    first, second = _two_level_i_methods(tax)
    sampler = ThompsonSampler(tax)

    def picks() -> list[str]:
        rng = random.Random(5)
        return [
            sampler.choose([first, second], "01", 0.3, rng, NOW, explore=True) for _ in range(5)
        ]

    assert picks() == picks()


def test_without_explore_low_arousal_is_exploit_only(tax: Taxonomy) -> None:
    # SDD §6.3: below the arousal line too, a pool that is not the regular Grade A pool
    # (the caller leaves ``explore`` off) gets the highest posterior mean, with no draw.
    good, bad = _two_level_i_methods(tax)
    sampler = ThompsonSampler(tax)
    sampler.update(good, "01", Feedback.HELPFUL, NOW)
    for seed in range(50):
        rng = random.Random(seed)
        assert sampler.choose([bad, good], "01", 0.1, rng, NOW) == good
        assert rng.getstate() == random.Random(seed).getstate()
    first, second = _two_level_i_methods(tax)
    fresh = ThompsonSampler(tax)  # equal means: the earlier candidate, every seed
    picks = {fresh.choose([second, first], "01", 0.1, random.Random(s), NOW) for s in range(50)}
    assert picks == {second}


def test_choose_returns_canonical_id(tax: Taxonomy) -> None:
    sampler = ThompsonSampler(tax)
    assert sampler.choose(["GROUNDING_54321"], "01", 0.9, random.Random(0), NOW) == "30:grounding"


def test_to_dict_round_trips_through_json(tax: Taxonomy) -> None:
    good, bad = _two_level_i_methods(tax)
    sampler = ThompsonSampler(tax)
    sampler.update(good, "03", Feedback.HELPFUL, NOW)
    sampler.update(bad, "03", Feedback.UNHELPFUL, NOW)
    sampler.update("GROUNDING_54321", "08", Feedback.UNHELPFUL, NOW)
    state = json.loads(json.dumps(sampler.to_dict()))
    restored = ThompsonSampler(tax, state)
    assert restored.to_dict() == sampler.to_dict()
    later = NOW + timedelta(days=2)
    for aid, spectrum in ((good, "03"), (bad, "03"), ("30:grounding", "08")):
        assert restored.posterior(aid, spectrum, later) == sampler.posterior(aid, spectrum, later)


def test_spectrum_isolation(tax: Taxonomy) -> None:
    mid = _method_with_level(tax, "Level I")
    sampler = ThompsonSampler(tax)
    sampler.update(mid, "02", Feedback.HELPFUL, NOW)
    sampler.update(mid, "02", Feedback.UNHELPFUL, NOW)
    assert sampler.posterior(mid, "01", NOW) == (4.0, 1.0)
    assert sampler.posterior(mid, "02", NOW) == (5.0, 2.0)


def test_choose_errors(tax: Taxonomy) -> None:
    mid = _method_with_level(tax, "Level I")
    sampler = ThompsonSampler(tax)
    rng = random.Random(0)
    with pytest.raises(ValueError, match="candidate"):
        sampler.choose([], "01", 0.3, rng, NOW)
    with pytest.raises(ValueError, match="spectrum"):
        sampler.choose([mid], "12", 0.3, rng, NOW)
    with pytest.raises(ValueError, match="spectrum"):
        sampler.choose([mid], "ANXIETY_PANIC", 0.3, rng, NOW)
    with pytest.raises(ValueError, match="arousal"):
        sampler.choose([mid], "01", math.nan, rng, NOW)
    with pytest.raises(ValueError, match="timezone"):
        sampler.choose([mid], "01", 0.3, rng, datetime(2026, 10, 22))
    with pytest.raises(UnknownActionError):
        sampler.choose(["NOT_AN_ACTION"], "01", 0.3, rng, NOW)


def test_candidates_without_an_evidence_level_are_rejected(tax: Taxonomy) -> None:
    sampler = ThompsonSampler(tax)
    rng = random.Random(0)
    ungraded = next(m.id for m in tax.methods().values() if m.evidence_level is None)
    with pytest.raises(ValueError, match="evidence level"):
        sampler.choose([ungraded], "01", 0.3, rng, NOW)


def test_standalone_actions_take_the_weakest_listed_prior(tax: Taxonomy) -> None:
    # D-3 (F13, draft G-0): a red-flag-only action has no evidence level of its own.
    sampler = ThompsonSampler(tax)
    weakest = _method_with_level(tax, STANDALONE_EVIDENCE_LEVEL)
    for aid in ("SAFE_PLACE_CONTAINER", "CIRCADIAN_RHYTHM_STABILIZATION"):
        assert sampler.posterior(aid, "01", NOW) == sampler.posterior(weakest, "01", NOW)
    assert sampler.posterior(weakest, "01", NOW) == (2.0, 1.0)
    sampler.update("SAFE_PLACE_CONTAINER", "01", Feedback.HELPFUL, NOW)
    assert sampler.posterior("SAFE_PLACE_CONTAINER", "01", NOW) == (3.0, 1.0)
    rng = random.Random(0)
    assert sampler.choose(["SAFE_PLACE_CONTAINER"], "01", 0.3, rng, NOW) == "SAFE_PLACE_CONTAINER"
    restored = ThompsonSampler(tax, sampler.to_dict())
    assert restored.posterior("SAFE_PLACE_CONTAINER", "01", NOW) == (3.0, 1.0)


def test_update_errors(tax: Taxonomy) -> None:
    mid = _method_with_level(tax, "Level I")
    sampler = ThompsonSampler(tax)
    with pytest.raises(ValueError, match="spectrum"):
        sampler.update(mid, "00", Feedback.HELPFUL, NOW)
    with pytest.raises(ValueError, match="timezone"):
        sampler.update(mid, "01", Feedback.HELPFUL, datetime(2026, 10, 22))
    with pytest.raises(UnknownActionError):
        sampler.update("NOT_AN_ACTION", "01", Feedback.HELPFUL, NOW)
    with pytest.raises(ValueError):
        sampler.update(mid, "01", "MAYBE", NOW)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "state",
    [
        {},
        {"spectra": [], "extra": 1},
        {"spectra": []},
        {"spectra": {"99": {}}},
        {"spectra": {"01": []}},
        {"spectra": {"01": {"NOT_AN_ACTION": {}}}},
        {"spectra": {"01": {"SAFE_PLACE_CONTAINER": {}}}},
        {"spectra": {"01": {"30:grounding": {"alpha": 1.0}}}},
        {"spectra": {"01": {"30:grounding": {"alpha": 0, "beta": 1, "last_unhelpful_at": None}}}},
        {
            "spectra": {
                "01": {"30:grounding": {"alpha": True, "beta": 1, "last_unhelpful_at": None}}
            }
        },
        {"spectra": {"01": {"30:grounding": {"alpha": 2, "beta": "x", "last_unhelpful_at": None}}}},
        {"spectra": {"01": {"30:grounding": {"alpha": 2, "beta": 1, "last_unhelpful_at": 5}}}},
        {
            "spectra": {
                "01": {
                    "30:grounding": {
                        "alpha": 2,
                        "beta": 1,
                        "last_unhelpful_at": "2026-10-22T12:00:00",
                    }
                }
            }
        },
        {
            "spectra": {
                "01": {
                    "30:grounding": {"alpha": 2, "beta": 1, "last_unhelpful_at": None},
                    "GROUNDING_54321": {"alpha": 2, "beta": 1, "last_unhelpful_at": None},
                }
            }
        },
    ],
)
def test_malformed_state_is_rejected(tax: Taxonomy, state: dict[str, object]) -> None:
    with pytest.raises((ValueError, UnknownActionError)):
        ThompsonSampler(tax, state)
