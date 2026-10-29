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

QA q4 (2026-10-28):

* The topic check comes before the alarm, so the screen (often the student alone, "我妈的病，
  遗书" at 0.66) no longer decides about a list of topic words; a 我 that only says whose
  ("我妈的病", "我家的狗") is no first-person word.
* :func:`sensitive_topics`: a topic list that names death, suicide, self-harm or a means
  ("自杀", "跳楼", "安乐死、葬礼") always brings the numbers with the gentle line (README:
  "温和地附上求助电话"), not only when the screen happened to alarm on it. The list only
  adds numbers, so it can only make the screen more cautious.
* :meth:`SetupScreen.verdict` tells :attr:`Verdict.UNSURE` apart: an alarm that only the
  student gives, with no rule cue and a crisis score below ``risk.yaml`` ``model_ask``'s
  ``direct_from_score`` (0.6). In a chat that alarm asks first instead of entering the
  crisis flow (owner decisions 2026-10-26 and 2026-10-28); the safety plan does the same
  (the CLI asks once whether the user is safe now, and shows the numbers on anything but
  a yes) instead of the crisis card for "把家里的酒都送人" or "去河边散散步" (0.45-0.51).
  It is never silent: a real crisis sentence the student is unsure about is still asked
  about. A rule cue, a model failure or a sure student still bring the numbers at once.

Round 5 (复测 q4 SP-10, 2026-10-29): :meth:`SetupScreen.risky_words` reads a reply for the
words a reply never says back (``language/guard.py``: a risk phrase, a death, place or
means word, two kinds of risk component). A crisis reply reads safety-plan sections 2-4
back, so the chat leaves out an entry with such words ("去天台上一个人待着吹风") even when
the screen let it through. It only leaves entries out of that block; nothing is screened
less.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum
from typing import Final

from olivia.core.chang.onboarding import parse_taboo
from olivia.core.language.data import load_language_data
from olivia.core.language.guard import MirrorGuard
from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import MODEL_FAILURE, CrisisAssessment, SafetyScreen
from olivia.core.safety.lexicon import ModelAskRules, load_safety_lexicons
from olivia.core.taxonomy import Taxonomy

ALARM_LEVEL: Final = CrisisLevel.L2
"""The level from which a reply is not taken and the hotlines are shown."""

TOPIC_MAX_CHARS: Final = 10
"""A topic word longer than this is read as a sentence (the topic list allows 20)."""
_SPEAKER: Final = re.compile(
    # 我 before a relative, a friend or 家 only says whose ("我妈的病", "我家的狗", QA q4).
    r"我(?!们家|家|妈|爸|父|母|奶奶|爷爷|外公|外婆|姥姥|姥爷|哥|姐|弟|妹|老公|老婆|男朋友|女朋友|"
    r"对象|孩子|儿子|女儿|朋友|同学|室友|闺蜜|同事)"
    r"|俺|咱|本人|自己|人家|(?i:\b(?:i|im|i'm|me|my|myself)\b)"
)
_SENSITIVE: Final = re.compile(
    # Death, suicide, self-harm and the means: a topic list naming one brings the numbers.
    r"死|杀|自残|自伤|伤害自己|割腕|割伤|跳楼|跳河|跳江|跳海|跳桥|上吊|轻生|寻短见|自尽|遗书|遗言|"
    r"葬|丧|安眠药|农药|烧炭|过量|"
    r"(?i:suicid|kill|death|dead|die|self[- ]?harm|overdose|funeral)"
)
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


class Verdict(StrEnum):
    """What the screen made of one setup reply (:meth:`SetupScreen.verdict`)."""

    CLEAR = "clear"
    UNSURE = "unsure"
    """Only the student alarms, unsure, with no rule cue: the chat would ask first."""
    ALARM = "alarm"


def sensitive_topics(reply: str) -> bool:
    """Whether a topic list names death, suicide, self-harm or a means (module docstring):
    the numbers then come with it, whatever the screen says."""
    return any(_SENSITIVE.search(topic) for topic in parse_taboo(reply) or ())


class SetupScreen:
    """The crisis screen for setup replies; built on first use."""

    def __init__(
        self, tax: Taxonomy, *, student: bool = True, screen: SafetyScreen | None = None
    ) -> None:
        self._tax = tax
        self._student = student
        self._screen = screen
        self._take_turn: Callable[[], tuple[str | None, float | None]] = lambda: (None, None)
        self._model_ask = ModelAskRules()
        self._guard: MirrorGuard | None = None

    def risky_words(self, text: str) -> bool:
        """Whether ``text`` holds words a reply never says back (module docstring, round 5):
        a risk phrase, a death, place or means word, or two kinds of risk component."""
        if self._guard is None:
            said = load_language_data(self._tax).utterances
            lexicons = load_safety_lexicons(self._tax)
            self._guard = MirrorGuard(lexicons, said.extra_risk_words, said.components)
        return self._guard.risky(text) or self._guard.flagged(text)

    def alarms(self, text: str) -> bool:
        """Whether ``text`` screens at L2 or above (a screen that fails counts as yes)."""
        return self.verdict(text) is not Verdict.CLEAR

    def verdict(self, text: str) -> Verdict:
        """:attr:`Verdict.CLEAR` below L2; :attr:`Verdict.UNSURE` for an alarm only the
        student gives, with no rule cue and a crisis score below ``model_ask``'s threshold
        (module docstring); :attr:`Verdict.ALARM` otherwise, a failed screen included."""
        if not any(ch.isalpha() for ch in text):
            return Verdict.CLEAR
        try:
            screen = self._built()
            assessment = screen.assess(text)
            model_level, model_score = self._take_turn()
            if assessment.level < ALARM_LEVEL:
                return Verdict.CLEAR
            if self._unsure_model_only(assessment, model_level, model_score):
                return Verdict.UNSURE
            return Verdict.ALARM
        except Exception:  # noqa: BLE001 - never miss a crisis sentence for a failed screen
            return Verdict.ALARM

    def _unsure_model_only(
        self, assessment: CrisisAssessment, model_level: str | None, model_score: float | None
    ) -> bool:
        """The session's test for a model-only alarm that asks first (``session.py``
        ``_model_only_alarm``): no rule cue, no model failure, a score under the line."""
        return (
            assessment.rule_clear
            and MODEL_FAILURE not in assessment.cue_ids
            and model_level in CrisisLevel.__members__
            and model_score is not None
            and self._model_ask.asks_first(model_score)
        )

    def _built(self) -> SafetyScreen:
        if self._screen is None:
            from olivia.core.perception.student import choose_risk_model  # numpy: lazy

            choice = choose_risk_model(student=self._student)
            lexicons = load_safety_lexicons(self._tax)
            self._screen = SafetyScreen(self._tax, lexicons, choice.model)
            self._take_turn = choice.take_turn
            self._model_ask = lexicons.model_ask
        return self._screen
