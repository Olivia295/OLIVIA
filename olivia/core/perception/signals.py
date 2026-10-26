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


class NoteRecall(StrEnum):
    """How a message asks about something the user had OLIVIA remember (MIYI-04, F15)."""

    EXPLICIT = "explicit"
    """The message names the notes ("我上次让你记住什么了"): always answered."""
    QUESTION = "question"
    """A question about a fact the user cannot recall ("周四要见的那个人是谁来着"):
    answered only when a note matches it."""


@dataclass(frozen=True)
class TurnSignals:
    battery: float | None = None
    """Social battery from a ``[NN%]`` prefix as 0.0-1.0; None when the turn has no prefix."""
    direct_request: bool = False
    """The user asks outright for a method or something to try (COLBO-03)."""
    another_method: bool = False
    """The direct request asks for another or a different method (F16b): a whole
    ``direct_request_whole`` message ("再给我一个", "换一个") or a ``direct_request``
    phrase that says so ("再给我一个方法", "给我一个别的", "换个练习", "有没有其他方法").
    The stub sets ``direct_request`` with it; the session reads the pair only while a
    card waits for feedback, as not_now for that card and a request for another one."""
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
    haven_exit: bool = False
    """The user says they feel better or want another topic ("我好多了", "换个话题吧";
    FSM-15): a non-negated ``haven_exit`` phrase. Only S_haven reads it, and leaves for
    S_explore."""
    leave_taking: bool = False
    """The user is leaving for now ("我去睡了", "今天就到这里吧"; F5d): a non-negated
    ``leave_taking`` phrase that is not asked as a question ("今天就到这里？" is not).
    While a card waits it is read as ``feedback`` (not_now) instead; with no card
    waiting, a turn the rules screen L0 outside a crisis gets a short goodbye, also when
    an injected model alone lifts it to L1 (F10)."""
    core_belief_confirmed: bool = False
    """The user affirmed the schema mirror question asked on the turn before (PRD C_2
    "核心信念识别", decision D4; model mode only). Set by the session, never by the stub;
    in S_clarify it opens S_empower like the auto-advance, through the same gates."""
    therapy_question: str | None = None
    """The method the user asks about by name ("EMDR 有用吗" -> ``"21"``, "正念是什么" ->
    ``"15"``), as a taxonomy method or practice id; None when the turn asks about none
    (roadmap next-phase A4, F3)."""
    therapy_request: str | None = None
    """The Grade A practice the user asks to do by name ("能带我做一下正念吗" -> ``"15"``;
    F3); the stub sets ``direct_request`` with it."""
    situation_codes: frozenset[str] = frozenset()
    """Taxonomy situation codes the message reveals (``situation_cues``: "亲人刚走" ->
    ``SIT-06-04``, "一切都没有意义" -> ``SIT-11-01``; roadmap next-phase A1)."""
    contraindication_cues: frozenset[str] = frozenset()
    """Contraindication enum ids the message reveals (``contraindication_cues``: "我有
    心脏病" -> ``CARDIORESPIRATORY_INSTABILITY``; roadmap next-phase A1)."""
    note_recall: NoteRecall | None = None
    """The user asks about something they had OLIVIA remember (``note_recall`` /
    ``note_recall_questions``, F15); an explicit phrase wins over a question one. The
    session passes it on only on a calm turn; the recorder looks up the notes."""
    prolonged_grief: bool = False
    """``SIT-06-04`` in ``situation_codes`` comes only from the three-list
    ``prolonged_grief`` rule (a loss long past and still not borne), with no acute
    bereavement cue on the same turn (F13, draft pending G-0): the session then keeps m0
    but does not set ``ACUTE_BEREAVEMENT_SHOCK``, whose source is the early phase."""
    contraindicated_practice: frozenset[str] = frozenset()
    """Contraindication enum ids whose masked practice the message names, not negated
    ("憋气那种" -> ``CARDIORESPIRATORY_INSTABILITY``; dogfood I2, 草稿：待 G-0). The stub
    also sets ``direct_request``; the session acts on it only while that contraindication
    is active."""
    why_not: bool = False
    """The message asks why not ("为什么不行"; dogfood I2): the session reads it only right
    after it said a named practice may not suit the user."""
    cardiac_symptom: bool = False
    """A heart or breathing symptom ("胸口发紧", "心跳很快"; dogfood I2): with a heart or
    breathing condition active, the reply ends with a line about getting medical help."""
    privacy_question: bool = False
    """The message asks whether its words are kept or sent anywhere ("你会把我说的话存下来
    吗"; dogfood I8): the session answers with the privacy facts, never a mirror."""
    advice_request: bool = False
    """The message asks how to say or do something ("我该怎么开口跟妈妈聊"; dogfood I1):
    advice, which the PRD has no mechanism for; the reply says it heard the question."""
    hotline_pushback: bool = False
    """The message asks not to be sent hotlines ("别老给我发热线电话"; dogfood I1): outside
    a crisis the reply says it heard that, and when hotlines do show."""

    def __post_init__(self) -> None:
        if self.battery is not None and not 0.0 <= self.battery <= 1.0:
            raise ValueError(f"battery must be within [0.0, 1.0], got {self.battery}")
        if self.listening_lock_on and self.listening_lock_off:
            raise ValueError("a turn cannot both set and release the listening lock")
        if self.feedback is not None and self.feedback_unclear:
            raise ValueError("feedback cannot be both read and unclear")
