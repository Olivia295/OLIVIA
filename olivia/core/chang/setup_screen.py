"""Crisis screening for what is typed while setting up (QA 2026-10-26 #4).

Onboarding, ``olivia profile``, ``olivia health`` and ``olivia safety-plan`` take free
text: a name, the taboo topics, a health-list reply, the plan's sections. A crisis
sentence typed there ("我不想活了" as a name, "真想睡过去不醒了" in the health list) was
taken as an answer, or read back, and no number was shown. Every reply there now goes
through the same crisis screen as a chat turn first: the rules, and by default the
packaged student as well (``olivia chat``'s default; ``olivia chat --rules`` screens its
onboarding with the rules alone). A student that is missing or fails verification leaves
the rules alone, as in a chat. The screen is the session's :class:`SafetyScreen`, used as
it is (read-only); nothing typed is kept or logged here.

:meth:`SetupScreen.alarms` is true at L2 or above. Only replies with a letter in them are
screened: a menu number or an empty line cannot be a crisis sentence, and the student is
loaded on the first reply that could.
"""

from __future__ import annotations

from typing import Final

from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import Taxonomy

ALARM_LEVEL: Final = CrisisLevel.L2
"""The level from which a reply is not taken and the hotlines are shown."""


class SetupScreen:
    """The crisis screen for setup replies; built on first use."""

    def __init__(
        self, tax: Taxonomy, *, student: bool = True, screen: SafetyScreen | None = None
    ) -> None:
        self._tax = tax
        self._student = student
        self._screen = screen

    def alarms(self, text: str) -> bool:
        """Whether ``text`` screens at L2 or above (a screen that fails counts as yes)."""
        if not any(ch.isalpha() for ch in text):
            return False
        try:
            return self._built().assess(text).level >= ALARM_LEVEL
        except Exception:  # noqa: BLE001 - never miss a crisis sentence for a failed screen
            return True

    def _built(self) -> SafetyScreen:
        if self._screen is None:
            from olivia.core.perception.student import choose_risk_model  # numpy: lazy

            model = choose_risk_model(student=self._student).model
            self._screen = SafetyScreen(self._tax, load_safety_lexicons(self._tax), model)
        return self._screen
