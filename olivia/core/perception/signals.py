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


class Answer(StrEnum):
    """A whole-message yes or no ("好的" / "不用了"), for a question the session asked."""

    AFFIRM = "affirm"
    DECLINE = "decline"


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
    feedback: Command | None = None
    """Natural-language feedback on a practice, as the command it stands for (roadmap
    R-7b): "做完了" -> ``DONE``, "今天先不做了" -> ``NOT_NOW``, "这个不适合我" ->
    ``UNHELPFUL``. The session reads it only while a card waits for feedback, and a
    slash ``command`` on the same turn wins."""
    feedback_unclear: bool = False
    """A reply that may be about the card but does not say which way ("唉", "再说吧");
    while a card waits, the session asks once whether to shelve it."""
    answer: Answer | None = None
    """The whole message is a plain yes or no; only a question the session just asked
    gives it a meaning."""
    kit_recall: bool = False
    """The user asks to see a method they shelved earlier ("锦囊里那个再给我看看")."""
    therapy_question: str | None = None
    """The Grade B/C method the user asks about by name ("EMDR 有用吗" -> ``"21"``), as a
    taxonomy method id; None when the turn asks about none (roadmap next-phase A4)."""

    def __post_init__(self) -> None:
        if self.battery is not None and not 0.0 <= self.battery <= 1.0:
            raise ValueError(f"battery must be within [0.0, 1.0], got {self.battery}")
        if self.listening_lock_on and self.listening_lock_off:
            raise ValueError("a turn cannot both set and release the listening lock")
        if self.feedback is not None and self.feedback_unclear:
            raise ValueError("feedback cannot be both read and unclear")
