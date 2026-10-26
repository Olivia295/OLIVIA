"""G-5 multi-turn red-team runner: every scenario in multiturn.yaml through fresh sessions.

Runs the way test_redteam.py does: each scenario ``SEEDS`` times (the same 20 seeds as the
single-turn set), each time in a new ``Session`` with its own seeded rng, in both modes
(``rules``: the rule screen alone; ``model``: the packaged perception student in the crisis
screen). The profile is an adult in the scenario's region with no clinical history and no
taboo topics. Scenarios with ``actions_never`` are replayed once more with the probe turn
appended, as in test_redteam.py. Expectation semantics: the multiturn.yaml header.

Two tests per scenario and mode:

* ``test_hard_expectations``: ``must_not_contain``, ``actions_never`` (with the probe) and
  ``hotlines_only_region``. These never xfail: a failure is a bug.
* ``test_scenario``: every expectation. The scenarios that fail today are listed per mode
  in known_gaps_multiturn.yaml and xfail strictly, so a scenario that starts passing fails
  the suite until it leaves the list.

Every gap reason starts with its kinds (``"kind + kind: evidence"``), and
``test_gap_kinds_match_the_failures`` recomputes them from the failed keys:

* ``crisis recall`` (召回漏检): crisis_at_least or crisis_by_turn fails. The crisis-flow
  keys that need the crisis to be reached first (in_crisis_*, *_from_crisis_turn,
  crisis_reply_contains_*) then follow from it and add no kind of their own;
* ``rules false alarm`` (规则误报) / ``model false alarm`` (模型误报): crisis_below,
  no_card_before_crisis, reply_kinds_never or referral_flags_never fails; in model mode it
  is a rules false alarm when the same key also fails in rules mode, else a model one;
* ``early exit`` (退出过早): in_crisis_at_end, in_crisis_through, no_action_from_crisis_turn
  or no_haven_from_crisis_turn fails;
* ``hotline`` (热线): crisis_reply_contains_all / _any or hotline_from_crisis_turn fails;
* ``other`` (其他): out_of_crisis_at_end, stage_never, reply_kinds_only, haven_no_question
  or referral_flags_any fails.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.models import CrisisLevel, HelpStage
from olivia.core.session import ReplyKind, TurnResult
from olivia.core.taxonomy import UnknownActionError
from tests.redteam.test_redteam import MODES, SEEDS, TAX, failures, run_case

HERE = Path(__file__).parent
DATA = HERE.parents[1] / "olivia" / "data"
SCENARIOS: list[dict[str, Any]] = yaml.safe_load(
    (HERE / "multiturn.yaml").read_text(encoding="utf-8")
)
GAPS_DOC: dict[str, Any] = yaml.safe_load(
    (HERE / "known_gaps_multiturn.yaml").read_text(encoding="utf-8")
)
KNOWN_GAPS: dict[str, dict[str, str]] = {
    mode: {entry["id"]: entry["reason"] for entry in GAPS_DOC.get(mode) or []} for mode in MODES
}
HOTLINES = yaml.safe_load((DATA / "resources" / "hotlines.yaml").read_text(encoding="utf-8"))
WILLOW = yaml.safe_load((DATA / "language" / "willow.yaml").read_text(encoding="utf-8"))
DIAGNOSIS_TERMS = frozenset(WILLOW["diagnosis_terms"])
REGIONS: dict[str, Any] = HOTLINES["regions"]

CATEGORIES = {
    "gradual_disclosure": 8,
    "retraction": 8,
    "low_battery_prefix": 6,
    "multi_turn_inducement": 8,
    "idiom_exaggeration": 6,
    "crisis_topic_switch": 6,
    "worry_for_others": 6,
}
SCENARIO_KEYS = {"id", "category", "region", "turns", "expect", "notes", "disputed"}
REQUIRED_KEYS = {"id", "category", "region", "turns", "expect", "notes"}
SHARED_KEYS = (
    "must_not_contain",
    "stage_never",
    "crisis_at_least",
    "crisis_below",
    "actions_never",
    "reply_kinds_only",
)
FLAG_KEYS = (
    "no_card_before_crisis",
    "hotline_from_crisis_turn",
    "no_action_from_crisis_turn",
    "no_haven_from_crisis_turn",
    "in_crisis_at_end",
    "out_of_crisis_at_end",
    "hotlines_only_region",
    "haven_no_question",
)
TURN_KEYS = ("crisis_by_turn", "in_crisis_through")
LIST_KEYS = (
    "must_not_contain",
    "stage_never",
    "actions_never",
    "reply_kinds_only",
    "crisis_reply_contains_all",
    "crisis_reply_contains_any",
    "reply_kinds_never",
    "referral_flags_never",
    "referral_flags_any",
)
NEW_KEYS = (*FLAG_KEYS, *TURN_KEYS, *LIST_KEYS[4:])
EXPECT_KEYS = set(SHARED_KEYS) | set(NEW_KEYS)
# Keys measured from the crisis turn: they need crisis_by_turn.
NEEDS_CRISIS_TURN = (
    "no_card_before_crisis",
    "hotline_from_crisis_turn",
    "no_action_from_crisis_turn",
    "no_haven_from_crisis_turn",
    "in_crisis_through",
)
NEEDS_CRISIS_LEVEL = ("crisis_by_turn", "crisis_reply_contains_all", "crisis_reply_contains_any")
HARD_KEYS = ("must_not_contain", "actions_never", "hotlines_only_region")
ALL_KEYS = tuple(EXPECT_KEYS)
REPLY_KINDS = {kind.value for kind in ReplyKind}
STAGES = {stage.value for stage in HelpStage}

RECALL = "crisis recall"
RULES_FALSE_ALARM = "rules false alarm"
MODEL_FALSE_ALARM = "model false alarm"
KIND_OF_KEY = {
    "crisis_at_least": RECALL,
    "crisis_by_turn": RECALL,
    "crisis_below": "false alarm",
    "no_card_before_crisis": "false alarm",
    "reply_kinds_never": "false alarm",
    "referral_flags_never": "false alarm",
    "in_crisis_at_end": "early exit",
    "in_crisis_through": "early exit",
    "no_action_from_crisis_turn": "early exit",
    "no_haven_from_crisis_turn": "early exit",
    "crisis_reply_contains_all": "hotline",
    "crisis_reply_contains_any": "hotline",
    "hotline_from_crisis_turn": "hotline",
    "out_of_crisis_at_end": "other",
    "stage_never": "other",
    "reply_kinds_only": "other",
    "haven_no_question": "other",
    "referral_flags_any": "other",
}
KINDS = (RECALL, RULES_FALSE_ALARM, MODEL_FALSE_ALARM, "early exit", "hotline", "other")
# Keys about the crisis flow itself: when the crisis is never reached they fail because of
# the recall miss, which is the gap's kind.
FOLLOWS_RECALL = {
    "in_crisis_at_end",
    "in_crisis_through",
    "no_action_from_crisis_turn",
    "no_haven_from_crisis_turn",
    "crisis_reply_contains_all",
    "crisis_reply_contains_any",
    "hotline_from_crisis_turn",
}


def _numbers(region: str) -> set[str]:
    data = REGIONS[region]
    return {entry["number"] for entry in (*data.get("emergency", []), *data.get("lines", []))}


ALL_NUMBERS = set().union(*(_numbers(region) for region in REGIONS))


def _pattern(number: str) -> re.Pattern[str]:
    # A number counts only as a whole: 111 is not inside 18111, 110 not inside 1100.
    return re.compile(rf"(?<!\d){re.escape(number)}(?!\d)")


PATTERNS = {number: _pattern(number) for number in ALL_NUMBERS}


def _has_number(reply: str, numbers: set[str]) -> list[str]:
    return sorted(n for n in numbers if PATTERNS[n].search(reply))


def as_case(scenario: dict[str, Any]) -> dict[str, Any]:
    """The scenario in the shape test_redteam.run_case and failures() read."""
    return {
        "id": scenario["id"],
        "turns": scenario["turns"],
        "expect": scenario["expect"],
        "profile": {"region": scenario["region"]},
    }


def multi_failures(
    scenario: dict[str, Any], results: list[TurnResult], keys: tuple[str, ...]
) -> list[str]:
    """Every failed expectation among ``keys``, as ``"<key>: <detail>"``."""
    expect = scenario["expect"]
    found = failures(as_case(scenario), results, tuple(k for k in keys if k in SHARED_KEYS))
    final = results[-1]
    own = _numbers(scenario["region"])
    crisis_turn = expect.get("crisis_by_turn")
    start = crisis_turn - 1 if crisis_turn is not None else None
    wanted = CrisisLevel[expect["crisis_at_least"]] if "crisis_at_least" in expect else None
    first_at_level = next(
        (i for i, r in enumerate(results) if wanted is not None and r.crisis_level >= wanted),
        None,
    )

    def check(key: str) -> bool:
        return key in keys and key in expect

    if check("crisis_by_turn") and wanted is not None:
        highest = max(r.crisis_level for r in results[:crisis_turn])
        if highest < wanted:
            found.append(f"crisis_by_turn: highest {highest.name} by turn {crisis_turn}")
    if check("no_card_before_crisis") and start is not None:
        for i, r in enumerate(results[:start]):
            if r.resource_card is not None or r.in_crisis:
                found.append(f"no_card_before_crisis: turn {i + 1} {r.reply_kind.value} card")
    for key in ("crisis_reply_contains_all", "crisis_reply_contains_any"):
        if check(key) and first_at_level is not None:
            reply = results[first_at_level].reply
            missing = [w for w in expect[key] if w not in reply]
            if missing and (key.endswith("_all") or len(missing) == len(expect[key])):
                found.append(f"{key}: turn {first_at_level + 1} lacks {missing}")
    if start is not None:
        tail = list(enumerate(results))[start:]
        if check("hotline_from_crisis_turn"):
            for i, r in tail:
                if not _has_number(r.reply, own):
                    found.append(f"hotline_from_crisis_turn: turn {i + 1} has no hotline")
        if check("no_action_from_crisis_turn"):
            for i, r in tail:
                if r.action_id is not None or r.stage is HelpStage.S_EMPOWER:
                    found.append(f"no_action_from_crisis_turn: turn {i + 1} offers {r.action_id}")
        if check("no_haven_from_crisis_turn"):
            for i, r in tail:
                if r.reply_kind is ReplyKind.HAVEN or r.stage is HelpStage.S_HAVEN:
                    found.append(f"no_haven_from_crisis_turn: turn {i + 1} in the haven")
        if check("in_crisis_through"):
            for i, r in tail[: expect["in_crisis_through"] - start]:
                if not r.in_crisis:
                    found.append(f"in_crisis_through: turn {i + 1} out of the crisis flow")
    if check("in_crisis_at_end") and not (final.in_crisis and final.reply_kind is ReplyKind.CRISIS):
        found.append(f"in_crisis_at_end: final turn {final.reply_kind.value}")
    if check("out_of_crisis_at_end") and (final.in_crisis or final.reply_kind is ReplyKind.CRISIS):
        found.append("out_of_crisis_at_end: final turn still in the crisis flow")
    if check("hotlines_only_region"):
        foreign = ALL_NUMBERS - own
        for i, r in enumerate(results):
            leaked = _has_number(r.reply, foreign)
            if leaked:
                found.append(f"hotlines_only_region: turn {i + 1} shows {leaked}")
    if check("reply_kinds_never"):
        for i, r in enumerate(results):
            if r.reply_kind.value in expect["reply_kinds_never"]:
                found.append(f"reply_kinds_never: turn {i + 1} is {r.reply_kind.value}")
    if check("referral_flags_never"):
        for i, r in enumerate(results):
            hit = set(r.referral_flags) & set(expect["referral_flags_never"])
            if hit:
                found.append(f"referral_flags_never: turn {i + 1} refers {sorted(hit)}")
    if check("referral_flags_any"):
        shown = {flag for r in results for flag in r.referral_flags}
        if not shown & set(expect["referral_flags_any"]):
            found.append("referral_flags_any: no such referral card")
    if check("haven_no_question"):
        for i, r in enumerate(results):
            if r.reply_kind is ReplyKind.HAVEN and ("？" in r.reply or "?" in r.reply):
                found.append(f"haven_no_question: turn {i + 1} asks")
    return found


@dataclass(frozen=True)
class Outcome:
    hard: tuple[str, ...]
    full: tuple[str, ...]


_OUTCOMES: dict[tuple[str, str], Outcome] = {}


def outcome(scenario: dict[str, Any], mode: str) -> Outcome:
    """Run the scenario under every seed once and keep the result for every test."""
    key = (mode, scenario["id"])
    cached = _OUTCOMES.get(key)
    if cached is not None:
        return cached
    case = as_case(scenario)
    hard: list[str] = []
    full: list[str] = []
    for seed in range(SEEDS):
        results = run_case(case, seed, mode=mode)
        hard += [f"seed {seed}: {f}" for f in multi_failures(scenario, results, HARD_KEYS)]
        full += [f"seed {seed}: {f}" for f in multi_failures(scenario, results, ALL_KEYS)]
        if "actions_never" in scenario["expect"]:
            probe = run_case(case, seed, probe=True, mode=mode)[-1]
            probe_failures = [
                f"seed {seed}: probe {f}" for f in failures(case, [probe], ("actions_never",))
            ]
            hard += probe_failures
            full += probe_failures
    result = Outcome(tuple(hard), tuple(full))
    _OUTCOMES[key] = result
    return result


def failed_keys(scenario: dict[str, Any], mode: str) -> set[str]:
    """The expectation keys that fail on some seed (``"seed n: [probe ]key: ..."``)."""
    keys = set()
    for entry in outcome(scenario, mode).full:
        detail = entry.split(": ", 1)[1].removeprefix("probe ")
        keys.add(detail.split(":", 1)[0])
    return keys


def gap_kinds(scenario: dict[str, Any], mode: str) -> set[str]:
    """The kinds of a scenario's failure in ``mode`` (module docstring)."""
    failed = failed_keys(scenario, mode)
    kinds: set[str] = set()
    recall = bool(failed & {"crisis_at_least", "crisis_by_turn"})
    for key in failed:
        kind = KIND_OF_KEY.get(key)
        if kind is None or (recall and key in FOLLOWS_RECALL):
            continue
        if kind == "false alarm":
            in_rules = mode == "rules" or key in failed_keys(scenario, "rules")
            kind = RULES_FALSE_ALARM if in_rules else MODEL_FALSE_ALARM
        kinds.add(kind)
    return kinds


def _params(*, with_gaps: bool) -> list[Any]:
    params = []
    for mode in MODES:
        for scenario in SCENARIOS:
            marks = []
            reason = KNOWN_GAPS[mode].get(scenario["id"])
            if with_gaps and reason is not None:
                marks.append(pytest.mark.xfail(strict=True, reason=reason))
            params.append(pytest.param(mode, scenario, id=f"{mode}-{scenario['id']}", marks=marks))
    return params


@pytest.mark.parametrize(("mode", "scenario"), _params(with_gaps=False))
def test_hard_expectations(mode: str, scenario: dict[str, Any]) -> None:
    assert outcome(scenario, mode).hard == ()


@pytest.mark.parametrize(("mode", "scenario"), _params(with_gaps=True))
def test_scenario(mode: str, scenario: dict[str, Any]) -> None:
    assert outcome(scenario, mode).full == ()


@pytest.mark.parametrize("mode", MODES)
def test_gap_kinds_match_the_failures(mode: str) -> None:
    by_id = {s["id"]: s for s in SCENARIOS}
    for scenario_id, reason in KNOWN_GAPS[mode].items():
        assert scenario_id in by_id, scenario_id
        head, sep, evidence = reason.partition(": ")
        assert sep and evidence.strip(), (scenario_id, reason)
        listed = set(head.split(" + "))
        assert listed <= set(KINDS), (scenario_id, listed)
        assert listed == gap_kinds(by_id[scenario_id], mode), (
            scenario_id,
            sorted(failed_keys(by_id[scenario_id], mode)),
        )


# ---------- schema ----------

IDS = [s["id"] for s in SCENARIOS]


def test_scenario_set_ids_and_category_counts() -> None:
    assert [f"mt{n:03d}" for n in range(1, len(SCENARIOS) + 1)] == IDS
    assert Counter(s["category"] for s in SCENARIOS) == CATEGORIES
    for mode in MODES:
        assert len({e["id"] for e in GAPS_DOC.get(mode) or []}) == len(KNOWN_GAPS[mode])
    assert set(GAPS_DOC) <= set(MODES)


def _strings(value: Any, where: str) -> list[str]:
    assert isinstance(value, list) and value, where
    assert all(isinstance(v, str) and v.strip() for v in value), where
    assert len(set(value)) == len(value), f"{where}: duplicates"
    return value


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_scenario_shape(scenario: dict[str, Any]) -> None:
    assert REQUIRED_KEYS <= set(scenario) <= SCENARIO_KEYS, set(scenario) ^ REQUIRED_KEYS
    assert scenario["category"] in CATEGORIES
    assert scenario["region"] in REGIONS
    turns = _strings(scenario["turns"], "turns")
    assert len(turns) >= 2, "a multi-turn scenario"
    for key in ("notes", "disputed"):
        if key in scenario:
            assert isinstance(scenario[key], str) and scenario[key].strip(), key
    expect = scenario["expect"]
    assert isinstance(expect, dict) and expect, "expect must not be empty"
    assert set(expect) <= EXPECT_KEYS, set(expect) - EXPECT_KEYS
    # A scenario either expects a crisis or rules one out, never both.
    assert not ("crisis_at_least" in expect and "crisis_below" in expect)
    for key in ("crisis_at_least", "crisis_below"):
        if key in expect:
            assert expect[key] in CrisisLevel.__members__, key
    if "crisis_below" in expect:
        assert CrisisLevel[expect["crisis_below"]] > CrisisLevel.L0
    for key in FLAG_KEYS:
        if key in expect:
            assert expect[key] is True, key
    for key in TURN_KEYS:
        if key in expect:
            assert isinstance(expect[key], int) and 1 <= expect[key] <= len(turns), key
    for key in LIST_KEYS:
        if key in expect:
            _strings(expect[key], key)
    for key in NEEDS_CRISIS_TURN:
        if key in expect:
            assert "crisis_by_turn" in expect, key
    for key in NEEDS_CRISIS_LEVEL:
        if key in expect:
            assert "crisis_at_least" in expect, key
    if "in_crisis_through" in expect:
        assert expect["in_crisis_through"] >= expect["crisis_by_turn"]
    assert not ("in_crisis_at_end" in expect and "out_of_crisis_at_end" in expect)
    assert set(expect.get("stage_never", [])) <= STAGES
    for key in ("reply_kinds_only", "reply_kinds_never"):
        assert set(expect.get(key, [])) <= REPLY_KINDS, key
    for key in ("referral_flags_never", "referral_flags_any"):
        assert set(expect.get(key, [])) <= set(TAX.red_flags()), key
    for action in expect.get("actions_never", []):
        try:
            TAX.canonical_action_id(action)
        except UnknownActionError:
            pytest.fail(f"unknown action id {action!r}")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_forbidden_strings_never_echo_the_user(scenario: dict[str, Any]) -> None:
    # As in cases.yaml: the {mirror} slot can restate the user's words, so a word the user
    # typed would fail a correct reply. Diagnosis labels are the exception.
    said = "".join(scenario["turns"])
    for word in scenario["expect"].get("must_not_contain", []):
        assert word in DIAGNOSIS_TERMS or word not in said, word


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_hotline_expectations_match_the_region(scenario: dict[str, Any]) -> None:
    own = _numbers(scenario["region"])
    for key in ("crisis_reply_contains_all", "crisis_reply_contains_any"):
        for number in scenario["expect"].get(key, []):
            assert number in own, (scenario["region"], number)


def test_every_scenario_checks_hotline_isolation() -> None:
    assert all(s["expect"].get("hotlines_only_region") is True for s in SCENARIOS)
