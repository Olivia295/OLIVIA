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

The taboo topics (QA r3, 2026-10-27): someone bereaved by suicide writes "自杀、死亡、前任"
as the topics not to be raised, and the screen alarms on the bare word. A reply to the
topic question that :func:`topic_words_only` finds to be a list of topic words is saved
(the CLI still shows the numbers, with one gentle line, and asks nothing). The narrowing is
structural, not a word list: every item must be short and carry no sign of a sentence
about the speaker -- no first-person word, no wanting or planning, no negation, no time,
no sentence-final particle or punctuation. "我想死" or "不想活了" in the same place is
still a crisis sentence and is never taken as a topic.
"""

from __future__ import annotations

import re
from typing import Final

from olivia.core.chang.onboarding import parse_taboo
from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import Taxonomy

ALARM_LEVEL: Final = CrisisLevel.L2
"""The level from which a reply is not taken and the hotlines are shown."""

TOPIC_MAX_CHARS: Final = 10
"""A topic word longer than this is read as a sentence (the topic list allows 20)."""
_SPEAKER: Final = re.compile(r"我|俺|咱|本人|自己|人家|(?i:\b(?:i|im|i'm|me|my|myself)\b)")
_SENTENCE: Final = re.compile(
    # wanting, planning, ability and obligation
    r"想|要|打算|准备|决定|计划|宁愿|宁可|希望|干脆|会|该|能|得去|"
    # negation ("不想活", "活不下去", "没意思", "别管")
    r"不|没|别|无法|"
    # aspect and sentence-final particles
    r"了|过了|吧|啊|呢|吗|啦|呀|哦|嘛|"
    # time ("今晚", "明天", "现在", "周末", "这次")
    r"今|明|昨|现在|马上|立刻|待会|等会|一会|周末|晚上|这次|下次|"
    r"[?？!！…~～.。]|"
    r"(?i:\b(?:want|wanna|gonna|going|will|plan|tonight|tomorrow|today|now|"
    r"can't|cannot|don't|not|no)\b)"
)


def topic_words_only(reply: str) -> bool:
    """Whether ``reply`` to the taboo-topic question is a list of topic words ("自杀、
    死亡、前任"), not a sentence about the speaker ("我想死", "不想活了"): every item short
    and free of first-person words, wanting or planning, negation, time and sentence-final
    particles (module docstring). False for a list over the limits."""
    topics = parse_taboo(reply)
    if not topics:
        return False
    return not any(
        len(topic) > TOPIC_MAX_CHARS or _SPEAKER.search(topic) or _SENTENCE.search(topic)
        for topic in topics
    )


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
