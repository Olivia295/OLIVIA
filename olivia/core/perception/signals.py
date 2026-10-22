"""Per-turn control signals read from the user's message, apart from perception scores.

The rule stub (and later the perception model) fills these from the raw text; the state
machine consumes them. They carry flags and numbers only, never user text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Command(StrEnum):
    """Explicit S_empower feedback commands (SDD section 4.2)."""

    DONE = "/done"
    NOT_NOW = "/not-now"
    UNHELPFUL = "/unhelpful"


@dataclass(frozen=True)
class TurnSignals:
    battery: float | None = None
    """Social battery from a ``[NN%]`` prefix as 0.0-1.0; None when the turn has no prefix."""
    direct_request: bool = False
    """The user asks outright for a method or something to try (COLBO-03)."""
    listening_lock_on: bool = False
    """The user says they only want to talk, not get advice (PRD Q-4)."""
    listening_lock_off: bool = False
    """The user releases the pure-listening lock (PRD Q-4)."""
    aversion: bool = False
    """The user rejects the suggested practice (SDD §4.2 S_empower row "表达反感", COLBO-04
    "强烈排斥"); in S_empower it routes back to S_explore."""
    intent_confirmed: bool = False
    """The user commits to when or how they will try the practice (SDD §4.2 S_closing row
    "实施意向确认完成", the Gollwitzer implementation intention); in S_closing it ends the
    session (S_ready)."""
    command: Command | None = None

    def __post_init__(self) -> None:
        if self.battery is not None and not 0.0 <= self.battery <= 1.0:
            raise ValueError(f"battery must be within [0.0, 1.0], got {self.battery}")
        if self.listening_lock_on and self.listening_lock_off:
            raise ValueError("a turn cannot both set and release the listening lock")
