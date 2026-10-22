import pytest

from olivia.core.perception.signals import Command, TurnSignals


def test_defaults_mean_no_signal():
    s = TurnSignals()
    assert s.battery is None and s.command is None
    assert not (s.direct_request or s.listening_lock_on or s.listening_lock_off)
    assert not (s.aversion or s.intent_confirmed)


def test_aversion_and_intent_are_independent_flags():
    # They act in different stages (S_empower / S_closing), so a turn may carry both.
    s = TurnSignals(aversion=True, intent_confirmed=True)
    assert s.aversion and s.intent_confirmed


@pytest.mark.parametrize("battery", [-0.01, 1.01])
def test_battery_out_of_range_is_rejected(battery):
    with pytest.raises(ValueError, match="battery"):
        TurnSignals(battery=battery)


def test_lock_cannot_be_set_and_released_together():
    with pytest.raises(ValueError, match="listening lock"):
        TurnSignals(listening_lock_on=True, listening_lock_off=True)


def test_commands_are_the_slash_forms():
    assert [c.value for c in Command] == ["/done", "/not-now", "/unhelpful"]
