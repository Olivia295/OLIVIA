"""Cross-turn crisis tracking: L1 escalation, crisis entry and confirmed exit.

Escalation (PRD 9.1, owner decision 2026-10-24): ``risk.ewma_streak`` (3) L1 turns in a
row *without improvement* raise the third one to L2, which enters crisis. An L1 turn
improves when its valence is known and higher than the last L1 turn's known valence; the
count then starts again at 0. An L0 turn improves when it is calm (a known valence at or
above 0, that is a calm or positive feeling) or its known valence is higher than the last
L1 turn's; it then resets the count. Valence ``None`` (no emotion evidence) is never an
improvement. Any other L0 turn pauses the count (neither counts nor resets it), and
``risk.l1_clear_streak`` L0 turns in a row reset it whatever their valence. Every turn at
L2 or above, crisis entry included, and crisis exit reset it too.

Exit from crisis needs an explicit safety confirmation followed by N safe (L0) turns, so
a single calm message never switches emergency resources off. After confirmation an L1
turn pauses the count: it neither counts as safe nor resets the turns already counted.
Round 4 (2026-10-28, SDD §8.2 "L1 轮暂停计数"): the L1 escalation applies outside a crisis
only. In a crisis an L1 turn does not join an L1 run and never escalates, so a run of L1
turns after a confirmation (a model's score band, "活着好累" three times) no longer turns
the third one into L2 and voids the confirmation; an L2/L3 turn still does.
While a confirmation is awaited, an explicit confirmation that only an injected model
raises to L2 or L3 (the turn's ``rule_level`` is below L2, and the model did not fail) is
tracked at the rules' level, so the model's L2 alone does not make it a relapse (F8a).
Outside a crisis, an L1 turn that only an injected model gives (the rules' level is L0)
is reported as L1 but counts for the escalation trend as an L0 turn would (F8a), so a
run of everyday turns the student alone rates L1 never escalates into crisis.
The screen's denial cap (F10: a first-person denial or all-clear that only an injected
model rates L2/L3 counts as L1) is for a turn outside a crisis: in a crisis the tracker
reads the turn's uncapped level (``CrisisAssessment.uncapped_level``), so in a crisis
such a turn is tracked exactly as without the cap.
A farewell, last words, affairs arranged or a resolve (a D3 cue marked ``raise_with_risk``
in risk.yaml) outside a crisis escalates to L2 at once, instead of asking, when the session
already showed risk: an earlier L1 turn of the current run or an earlier crisis
(2026-10-26).
The "X得 / 到想死" figure of speech that the screen reads as a D3 question (owner decision
2026-10-28, ``ASK_INTENT_HYPERBOLE_DIE``) escalates to L2 at once, outside a crisis, when
the session showed any other risk before: an earlier turn whose rule level was L1 or
above or that carried a D3 cue (the figure itself does not count, so a second one after a
clear no asks again), or an earlier crisis.
S5 (2026-10-26): besides the ``safety_confirm`` phrases and the whole-message short yes, one
clause of a longer message that says the user is safe ("我现在在家，是安全的", "是的，我现在
安全，已经给我姐打了电话") confirms, but only when the screen found no rule risk cue in the
message (``CrisisAssessment.rule_clear``) and no F10 denial veto or contrast and no
confirm veto occurs in it; the exit rule after a confirmation is unchanged.
Round 3 (2026-10-27, re-test r2 第 5 节): a promise not to harm oneself ("我答应你今晚不会
做什么傻事", "我保证不会做傻事") confirms like a safe clause, under the same guards, and
"I am safe now" is a short yes; the exit rule after a confirmation is unchanged.
Round 6 (2026-10-29, re-test q2 第 3 节, q4 F4):

* Cantonese 而家 / 宜家 / 依家 ("now") is a filler like 现在, and 好 is a degree before 安全
  ("我而家好安全").
* A status report confirms ("我好好的，人在家，什么都没做"): two or more of its clauses are
  each a different kind of calm status (``_STATUS_KINDS``: being well, being at home or in
  the dormitory, someone with the user, nothing done), under the safe clause's guards (no
  rule risk cue, no F10 veto or contrast). One kind alone ("人在家，门锁着") is no
  confirmation.
* :meth:`CrisisTracker.observe` takes ``confirm_on_entry``: on the turn that enters a
  crisis from the answer to the direct question, an explicit confirmation in that answer
  ("我现在是安全的") counts, so the crisis reply does not ask for the very sentence the user
  just said. The crisis flow is entered all the same and the exit rule is unchanged.

The tracker keeps numbers and flags only; it never stores user text.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Final

from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import MODEL_FAILURE, CrisisAssessment
from olivia.core.safety.lexicon import SafetyLexicons
from olivia.core.safety.matcher import PhraseMatcher
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy

# The spec requires the user to *explicitly confirm* safety ("明确确认安全"). A safety_confirm
# phrase therefore counts only when it is not negated, questioned or sarcastic. Anything
# ambiguous fails toward staying in crisis, which keeps emergency resources visible.
# Directly preceding the hit: "我不觉得…", "我哪里…", "我没有…" negate or deflect the phrase.
_NEGATING_PREFIXES: Final[tuple[str, ...]] = ("不", "没", "没有", "不是", "并非", "哪里")
# Trailing punctuation ignored before the question check (NFKC already folds "？" to "?").
_TRAILING_PUNCTUATION: Final = "。.!！~…"
# A message ending in a question particle asks about safety rather than confirming it.
_QUESTION_ENDINGS: Final[tuple[str, ...]] = ("吗", "么", "?")
# Gap tolerance: these adverbs are dropped from both the message and the safety_confirm
# phrases before matching, so "我已经联系上朋友了" matches "我联系上朋友了" and
# "我现在是安全的" matches "我是安全的". Vetoes are still read on the whole message.
_CONFIRM_FILLERS: Final[tuple[str, ...]] = ("已经", "现在", "都", "而家", "宜家", "依家")
# Punctuation dropped before reading a short direct answer ("是的，安全的。").
_ANSWER_PUNCTUATION: Final = str.maketrans("", "", ",.!~…、。！ ")
# A short yes to the question every crisis reply asks until safety is confirmed
# ("你现在是安全的吗？"), as the whole
# message: an optional 嗯, an optional 是(的)/对(的), then an optional "(我)(是|很|挺)安全
# (的|了|啦)". It must contain 是, 对 or 安全, so a bare "嗯" (an acknowledgement, not an
# answer) never counts. Anything with a negation, a hedge or a new cue does not match.
_DIRECT_ANSWER: Final = re.compile(
    r"(?:嗯+|恩+)?(?:(?:是|对)的?)?(?:我?(?:是|很|挺|好)?安全(?:的|了|啦)?)?(?:哦|呀|啊)?"
)
_DIRECT_ANSWER_WORDS: Final[tuple[str, ...]] = ("是", "对", "安全")
# S5 (2026-10-26): one clause of a longer message that says the user is safe ("我现在在家，
# 是安全的", "是的，我现在安全，已经给我姐打了电话"), read after the fillers are dropped. It
# is the short answer's grammar, optionally after "在家", and must say 安全; the message
# must carry no rule risk cue, no F10 denial veto or contrast and no confirm veto.
_CLAUSE_SPLIT: Final = re.compile(r"[,.!?;:、。！？，；：~…\s]+")
_SAFE_CLAUSE: Final = re.compile(
    r"(?:嗯+|恩+)?(?:(?:是|对)的?)?我?(?:在家里?)?(?:是|很|挺|好)?安全(?:的|了|啦)?(?:哦|呀|啊|呢)?"
)
_DIRECT_ANSWER_ENGLISH: Final[frozenset[str]] = frozenset(
    {"yes", "yeah", "yep", "i'msafe", "iamsafe", "imsafe", "yesi'msafe", "yesiamsafe"}
)
# Round 3 (2026-10-27): "I am safe now", "yes, I'm safe right now" (folded, no spaces, no
# punctuation), as the whole message.
# Round 4 (2026-10-28): a promise may lead ("I promise I'm safe now"), and one clause of a
# longer English message may say it ("I'm safe now, I promise. My friend is here with me."),
# read like the Chinese safe clause (no rule risk cue, no F10 veto or contrast such as "for
# now", "yet", "but", no confirm veto).
_ENGLISH_SAFE: Final = re.compile(
    r"(?:yes|yeah|yep|ok|okay)?(?:ipromise|honestly|really|don'tworry|dontworry)?"
    r"(?:i'm|im|iam)(?:totally|really|completely|perfectly)?"
    r"safe(?:now|rightnow)?(?:thanks|thankyou|don'tworry|dontworry|promise|ipromise)?"
)
# Round 3 (2026-10-27, re-test r2 第 5 节): a promise not to harm oneself, as the whole
# message or one clause of it ("我答应你今晚不会做什么傻事", "我答应你，今晚不会做什么",
# "我保证不会做傻事"). Either a promise verb or an object that names the harm (傻事, 伤害
# 自己); never a plain "不会" alone. Read like the safe clause: no rule risk cue, no F10
# veto or contrast and no confirm veto in the message.
_PROMISE_TIMES: Final = frozenset({"今晚", "今天", "今天晚上", "晚上", "这几天"})
_PROMISE_TIME = r"(?:今晚|今天|今天晚上|晚上|这几天)?"
# A clause of the normalized message (between clause punctuation).
_CLAUSE_TEXT: Final = re.compile(r"[^,.!?;:、。！？，；：~…\s]+")
_PROMISE_SURE = r"(?:绝对|肯定|一定)?"
# Round 4 (2026-10-28, re-test q2 第 3 节): "我保证今晚好好的，不会乱来". A promise may also be
# to be well ("会好好的", "好好的") and a harm word may be a figure for it (乱来, 想不开, 寻短见),
# both closed classes.
_PROMISE_WELL = r"(?:会|都会)?好好(?:的|地|活着|照顾自己)(?:过|待着|睡觉|休息)?"
_PROMISE_NO_HARM = (
    r"不会(?:做|干|去做)?(?:什么|啥|任何)?(?:傻事|蠢事|事|伤害自己的事)?"
    r"|不会(?:乱来|想不开|寻短见|伤害自己)"
)
_PROMISE: Final = re.compile(
    rf"(?:嗯+|好+的?|放心吧?)?我?(?:答应你|向你保证|跟你保证|保证|发誓)我?"
    rf"{_PROMISE_TIME}{_PROMISE_SURE}(?:{_PROMISE_NO_HARM}|{_PROMISE_WELL})(?:的|了|啦)?"
    rf"|我?{_PROMISE_TIME}{_PROMISE_SURE}(?:不会(?:做|干|去做)(?:傻事|蠢事|伤害自己的事)"
    rf"|不会(?:乱来|寻短见|伤害自己))(?:的|了|啦)?"
)
# Round 4 (re-test q2 x06: "我已经从天台下来了，现在在家，安全的"): a place the user has come
# down from or left is no means or place veto. Only these spans are dropped before the F10
# guard reads the message; "我在天台上，挺安全的" and "从楼顶下来了，但明天还会上去" keep it.
_LEFT_PLACE: Final = re.compile(
    r"从(?:天台|楼顶|顶楼|阳台|窗台|桥上|桥边|大桥上|江边|河边|湖边|海边|铁轨边?)上?"
    r"(?:下来|回来|走下来|撤下来|走开|回到家|回家)(?:了|啦)"
)
# Round 5 (2026-10-29, re-test q2 第 3 节): three more ways to say it, each a closed
# grammar read as one clause of the message:
# - a safe clause with its own time ("今晚我很安全", "我这几天都是安全的") or a future
#   ("我会安全的"): the time word is the clause's scope, as in a promise;
# - letting go of the thought ("那个念头我放下了", "我把这个想法打消了"): it confirms;
# - staying in a safe place for a time ("今晚就在家里待着"): no confirmation alone, but its
#   time word is its scope, so it no longer voids a confirmation next to it.
# A time or the word for the thought is exempt from the vetoes only inside such a clause,
# and only when the rest of the message passes the F10 denial guard and the rules found no
# risk cue in it (``_scoped_clear``), so "今晚我是安全的，明天就不一定了" stays no confirmation.
_SCOPE_TIME = r"(?:今晚|今夜|今天|今天晚上|晚上|这几天|这两天|这周|周末|这个周末)?"
_TIMED_SAFE: Final = re.compile(
    rf"(?:嗯+|放心吧?)?我?{_SCOPE_TIME}我?(?:都|也)?(?:会|是|很|挺|都是|会是)?安全(?:的|了|啦)?(?:哦|呀|啊|呢)?"
)
_THOUGHT = r"(?:念头|想法|打算|主意|傻念头|坏念头)"
_LET_GO: Final = re.compile(
    rf"我?(?:已经)?(?:把)?(?:这个|那个|刚才的|刚才那个|这种|那种|那些|这些)?{_THOUGHT}"
    rf"(?:我)?(?:已经)?(?:放下|打消|放弃|丢掉|扔掉|收起来|压下去|断)(?:了|啦)"
)
_STAY_SAFE_PLACE: Final = re.compile(
    rf"我?{_SCOPE_TIME}我?(?:都|会|就|会好好|就好好|好好)?(?:待|呆|留|躺|睡)?在"
    r"(?:家|家里|宿舍|寝室|房间|屋里)(?:里)?(?:待着|呆着|睡觉|休息|不出去|不出门)?(?:的|了|啦)?"
)
_SCOPE_WORDS: Final = frozenset(
    {"今晚", "今夜", "今天", "今天晚上", "晚上", "这几天", "这两天", "这周", "周末", "这个周末",
     "打算", "主意"}
)  # fmt: skip
# A message ending in 什么 / 啥 after a negated verb says what the user will not do ("不会
# 做什么"), not a question.
_NOT_DOING: Final = re.compile(
    r"(?:不会|不去|不想|不打算|不准备|没想)[^,.!?;:、。]{0,4}(?:什么|啥)$"
)
# Round 5: a means handed over or thrown away ("药也交给室友了", "刀扔掉了") is no means veto
# for a confirm phrase next to it; only these spans are dropped before the guard.
_MEANS_GONE: Final = re.compile(
    r"(?:药|安眠药|刀|刀片|绳子|绳|炭)(?:也|都|已经|全)*"
    r"(?:交给[^,.!?;:、。]{1,6}|给了[^,.!?;:、。]{1,6}|扔了|扔掉了|丢了|丢掉了|冲掉了|上交了|剪掉了|剪断了|"
    r"交出去了|收走了)(?:了|啦)?"
)
# Round 5: what voids a confirm phrase in the same message: a hedge, a later time, a means
# or place, a farewell or a plan (with the F10 contrasts). Narrower than the F10 vetoes,
# whose 那边 or 最后 are everyday words next to "热线接通了".
_PHRASE_GUARD: Final = (
    "暂时", "目前", "至少", "可能", "也许", "说不定", "不一定", "不确定", "现在还", "如果",
    "要是", "万一", "明天", "后天", "待会", "等会", "过几天", "以后", "迟早", "早晚", "药", "绳",
    "刀", "炭", "农药", "煤气", "楼顶", "天台", "桥", "铁轨", "跳", "割", "遗书", "遗言", "后事",
    "买好", "攒", "囤", "计划", "打算", "决定", "想好了", "下定决心", "一了百了", "解脱", "再见",
    "永别", "告别",
)  # fmt: skip
# Round 6: the clauses of a status report, each one kind of calm status, read on the
# compacted clause (已经 / 现在 / 都 / 而家 dropped). Two different kinds confirm.
_STATUS_END = r"(?:的|了|啦|呢|啊|呀|哦|嘅|喇|呀)*"
# The people who can be with the user, a closed class (kin, partner, flatmate, friend).
_PERSON = (
    r"(?:我的?|我家)?(?:妈妈?|爸爸?|老妈|老爸|家人|家里人|屋企人|老公|老婆|爱人|伴侣|对象|男朋友|"
    r"女朋友|室友|舍友|朋友|闺蜜|同学|同事|姐姐?|哥哥?|弟弟?|妹妹?|爷爷|奶奶|外婆|外公|阿妈|阿爸|"
    r"老豆|老母|孩子|家里|一家人)(?:们|都|也)*"
)
_STATUS_KINDS: Final = (
    (
        "well",
        re.compile(rf"我?(?:还|也|挺|很)?(?:好好|没事|冇事|冇嘢|挺好|很好)(?:的|地)?{_STATUS_END}"),
    ),
    (
        "home",
        re.compile(
            rf"(?:我|人)?(?:就|也)?(?:在|喺|待在|呆在)(?:家|家里|屋里|屋企|宿舍|寝室|房间|自己房间)"
            rf"(?:里|度)?{_STATUS_END}"
        ),
    ),
    (
        "company",
        re.compile(
            rf"{_PERSON}(?:在|喺)(?:旁边|身边|这|这里|这儿|度|家|家里|屋企)(?:陪着我|陪我)?{_STATUS_END}"
            rf"|{_PERSON}(?:在|正)?陪着?我{_STATUS_END}"
        ),
    ),
    (
        "nothing",
        re.compile(
            rf"我?(?:什么|啥|乜|乜嘢)(?:也|都)?(?:没|没有|冇)(?:做|干|动)(?:过)?{_STATUS_END}"
            rf"|我?(?:没|没有|冇)(?:做|干)(?:什么|啥|乜嘢|任何事)?{_STATUS_END}"
        ),
    ),
)
# An L0 turn with a known valence at or above this is calm: it resets the escalation count.
_CALM_VALENCE: Final = 0.0
# Valence must rise by more than this to count as an improvement (float noise guard).
_VALENCE_EPSILON: Final = 1e-9


@dataclass(frozen=True)
class CrisisStatus:
    level: CrisisLevel
    in_crisis: bool
    entry_level: CrisisLevel | None
    escalated: bool
    awaiting_confirmation: bool
    safe_turns_remaining: int
    just_entered: bool
    just_exited: bool
    consecutive_l1_count: int = 0
    """L1 turns without improvement in the current run (see ``CrisisTracker``)."""


def _whole_threshold(tax: Taxonomy, path: str) -> int:
    value = tax.threshold(path)
    if not value.is_integer() or value < 1:
        raise ValueError(f"taxonomy threshold {path} must be a positive whole number, got {value}")
    return int(value)


def _compact(text: str) -> str:
    for filler in _CONFIRM_FILLERS:
        text = text.replace(filler, "")
    return text


def _promise_spans(normalized: str) -> list[tuple[int, int]]:
    """Spans of the clauses of ``normalized`` that are each a whole promise (round 4): a
    time word inside one ("我保证今晚好好的") is the promise's scope, not a confirm veto."""
    spans: list[tuple[int, int]] = []
    for clause in _CLAUSE_TEXT.finditer(normalized):
        bare = _compact(clause.group(0)).translate(_ANSWER_PUNCTUATION)
        if bare and _PROMISE.fullmatch(bare) is not None:
            spans.append(clause.span())
    return spans


def _scoped_spans(normalized: str) -> list[tuple[int, int]]:
    """Spans of the clauses that scope their own time or thought word (round 5): a timed
    safe clause, letting go of the thought, staying in a safe place."""
    spans: list[tuple[int, int]] = []
    for clause in _CLAUSE_TEXT.finditer(normalized):
        bare = _compact(clause.group(0)).translate(_ANSWER_PUNCTUATION)
        if bare and any(
            p.fullmatch(bare) is not None for p in (_TIMED_SAFE, _LET_GO, _STAY_SAFE_PLACE)
        ):
            spans.append(clause.span())
    return spans


def _confirms_scoped(clause: str) -> bool:
    """A clause that confirms on its own (round 5): a timed safe clause or letting go."""
    return _TIMED_SAFE.fullmatch(clause) is not None or _LET_GO.fullmatch(clause) is not None


def _status_kinds(clauses: list[str]) -> int:
    """How many different kinds of calm status the clauses report (round 6)."""
    kinds: set[str] = set()
    for clause in clauses:
        for kind, pattern in _STATUS_KINDS:
            if pattern.fullmatch(clause) is not None:
                kinds.add(kind)
                break
    return len(kinds)


def _is_direct_answer(compact: str) -> bool:
    bare = compact.translate(_ANSWER_PUNCTUATION)
    if bare in _DIRECT_ANSWER_ENGLISH or _ENGLISH_SAFE.fullmatch(bare) is not None:
        return True
    return _DIRECT_ANSWER.fullmatch(bare) is not None and any(
        word in bare for word in _DIRECT_ANSWER_WORDS
    )


class CrisisTracker:
    """Stateful per-session tracker; call ``observe`` exactly once per user turn."""

    def __init__(self, tax: Taxonomy, lexicons: SafetyLexicons) -> None:
        self._tax = tax
        self._streak = _whole_threshold(tax, "risk.ewma_streak")
        self._clear_streak = _whole_threshold(tax, "risk.l1_clear_streak")
        phrases: dict[str, str] = {}
        for cue in lexicons.cues("safety_confirm"):
            for phrase in cue.patterns:
                compact = _compact(phrase)
                if compact:
                    phrases.setdefault(compact, cue.id)
        self._confirm_matcher = PhraseMatcher(phrases)
        self._veto_matcher = PhraseMatcher(
            {phrase: cue.id for cue in lexicons.cues("confirm_veto") for phrase in cue.patterns}
        )
        self._raise_ids = frozenset(
            entry.id for entry in lexicons.compositions.entries if entry.raise_with_risk
        )
        self._figure_id = lexicons.hyperbole_ask.id
        # The F10 denial conditions guard the clause reading (S5): any veto or contrast of
        # the ``denial`` section anywhere in the message voids it.
        guards = (*lexicons.denial.vetoes, *lexicons.denial.contrasts)
        self._clause_guard = PhraseMatcher({p: p for p in guards}) if guards else None
        # Round 5: a confirm phrase ("我很安全") is voided by a contrast, a hedge, a later
        # time, a means or place, or a plan word next to it (``_PHRASE_GUARD``).
        self._phrase_guard = PhraseMatcher(
            {p: p for p in (*lexicons.denial.contrasts, *_PHRASE_GUARD)}
        )

        self._run = 0
        self._last_l1_valence: float | None = None
        self._l0_streak = 0

        self._in_crisis = False
        self._entry_level: CrisisLevel | None = None
        self._confirmed = False
        self._safe_turns = 0
        self._had_crisis = False
        # Some turn of this session carried a rule risk cue other than the figure of speech
        # (owner decision 2026-10-28).
        self._risk_seen = False

    @property
    def consecutive_l1_count(self) -> int:
        """L1 turns without improvement in the current run: the session's one count of record.

        An improving turn (see the module docstring), ``risk.l1_clear_streak`` L0 turns in a
        row, any L2/L3 turn and crisis exit reset it to 0; any other L0 turn leaves it as it
        is. ``SessionState.consecutive_l1_count`` mirrors this value each turn and is never
        counted separately.
        """
        return self._run

    def observe(
        self,
        assessment: CrisisAssessment,
        text: str,
        valence: float | None = None,
        *,
        confirmable: bool = True,
        confirm_on_entry: CrisisAssessment | None = None,
    ) -> CrisisStatus:
        """Track one user turn. ``valence`` is ``None`` when there is no emotion evidence.

        ``confirmable=False`` (round 6): the turn answers another question the session asked
        (whether the user is under 18), so a short yes in it is no safety confirmation; the
        safety question is asked again. Everything else is tracked as usual.

        ``confirm_on_entry`` (round 6): the rule screen of an answer to the direct question;
        when this turn enters a crisis, an explicit confirmation in it counts."""
        if self._in_crisis and assessment.uncapped_level is not None:
            # The denial cap (F10) applies outside a crisis only.
            assessment = replace(assessment, level=assessment.uncapped_level)
        rules_level = self._model_only_relapse(assessment, text) if confirmable else None
        assessed = assessment.level if rules_level is None else rules_level
        usable = valence if valence is not None and math.isfinite(valence) else None
        trend = assessed
        if (
            not self._in_crisis
            and assessed is CrisisLevel.L1
            and assessment.rule_level is CrisisLevel.L0
        ):
            trend = CrisisLevel.L0  # a model-only L1 is not part of an L1 run (F8a)
        # Round 4 (SDD §8.2): the L1 escalation rule applies outside a crisis only. In a
        # crisis an L1 turn neither joins a run nor escalates: after a confirmation it
        # pauses the exit count (neither counts nor resets it), so the third L1 turn after
        # "我现在是安全的" no longer voids the confirmation.
        in_crisis_l1 = self._in_crisis and trend is CrisisLevel.L1
        if not in_crisis_l1:
            self._update_trend(trend, usable)

        level = assessed
        escalated = (
            not in_crisis_l1
            and trend is CrisisLevel.L1
            and (
                self._run >= self._streak
                or self._asks_again(assessment)
                or self._figure_after_risk(assessment)
            )
        )
        self._note_risk(assessment)
        if escalated:
            level = CrisisLevel.L2

        just_entered = False
        just_exited = False
        if level >= CrisisLevel.L2:
            self._had_crisis = True
            if not self._in_crisis:
                self._in_crisis = True
                self._entry_level = level
                just_entered = True
            elif self._entry_level is not None:
                self._entry_level = max(self._entry_level, level)
            self._confirmed = just_entered and (
                confirm_on_entry is not None
                and self._is_explicit_confirmation(normalize(text), confirm_on_entry)
            )
            self._safe_turns = 0
            # The L1 escalation count starts afresh after any crisis-level turn, so earlier
            # L1 turns never lift later ones into a spurious escalation.
            self._reset_trend()
        elif self._in_crisis:
            just_exited = self._observe_safe_candidate(
                level, text, assessment, confirmable=confirmable
            )

        return self._status(level, escalated, just_entered, just_exited)

    def _model_only_relapse(self, assessment: CrisisAssessment, text: str) -> CrisisLevel | None:
        """The rules' level of an awaited explicit confirmation that only an injected model
        puts at L2 or above (F8a), else None."""
        rule = assessment.rule_level
        if (
            self._in_crisis
            and not self._confirmed
            and rule is not None
            and rule < CrisisLevel.L2 <= assessment.level
            and MODEL_FAILURE not in assessment.cue_ids
            and self._is_explicit_confirmation(normalize(text), assessment)
        ):
            return rule
        return None

    def _asks_again(self, assessment: CrisisAssessment) -> bool:
        """A farewell, last words, affairs arranged or a resolve (a D3 cue marked
        ``raise_with_risk``) outside a crisis in a session that already showed risk: an
        earlier L1 turn of the current run (this turn is already counted, so the run is at
        least 2) or an earlier crisis. It escalates to L2 like a full L1 run instead of
        asking (2026-10-26)."""
        return (
            not self._in_crisis
            and assessment.asks_intent
            and not self._raise_ids.isdisjoint(assessment.cue_ids)
            and (self._run >= 2 or self._had_crisis)
        )

    def _is_figure(self, assessment: CrisisAssessment) -> bool:
        return bool(self._figure_id) and self._figure_id in assessment.cue_ids

    def _figure_after_risk(self, assessment: CrisisAssessment) -> bool:
        """The "X得 / 到想死" figure (a D3 cue) outside a crisis in a session that already
        showed other risk or a crisis: L2 at once instead of the question (owner decision
        2026-10-28)."""
        return (
            not self._in_crisis
            and assessment.asks_intent
            and self._is_figure(assessment)
            and (self._risk_seen or self._had_crisis)
        )

    def _note_risk(self, assessment: CrisisAssessment) -> None:
        """Remember a turn whose rules saw risk (rule level L1 or above, or a D3 cue), the
        figure of speech alone excepted."""
        if self._is_figure(assessment):
            return
        rule = assessment.rule_level or CrisisLevel.L0
        if rule >= CrisisLevel.L1 or assessment.asks_intent:
            self._risk_seen = True

    def _update_trend(self, assessed: CrisisLevel, valence: float | None) -> None:
        if assessed is CrisisLevel.L1:
            self._l0_streak = 0
            self._run = 0 if self._rose(valence) else self._run + 1
            if valence is not None:
                self._last_l1_valence = valence
        elif assessed is CrisisLevel.L0:
            self._l0_streak += 1
            calm = valence is not None and valence >= _CALM_VALENCE
            if calm or self._rose(valence) or self._l0_streak >= self._clear_streak:
                self._reset_trend()
        else:
            self._l0_streak = 0

    def _rose(self, valence: float | None) -> bool:
        last = self._last_l1_valence
        return valence is not None and last is not None and valence - last > _VALENCE_EPSILON

    def _reset_trend(self) -> None:
        self._run = 0
        self._last_l1_valence = None

    def _observe_safe_candidate(
        self, level: CrisisLevel, text: str, assessment: CrisisAssessment, *, confirmable: bool
    ) -> bool:
        """Handle a turn at effective level <= L1 while in crisis; True when it exits."""
        entry = self._entry_level
        if entry is None:  # unreachable: in_crisis always has an entry level
            return False
        if not self._confirmed:
            if confirmable and self._is_explicit_confirmation(normalize(text), assessment):
                self._confirmed = True
            return False
        # Only L0 counts as safe; an L1 turn pauses the count without resetting it.
        if level is not CrisisLevel.L0:
            return False
        self._safe_turns += 1
        if self._safe_turns < self._tax.crisis_exit_safe_turns(entry):
            return False
        self._in_crisis = False
        self._entry_level = None
        self._confirmed = False
        self._safe_turns = 0
        self._reset_trend()
        return True

    def _is_explicit_confirmation(self, normalized: str, assessment: CrisisAssessment) -> bool:
        """A safety_confirm phrase, a short yes to the crisis reply's safety question, or a
        clause that says so in a longer message (S5, :meth:`_safe_clause`).

        Every crisis reply asks whether the user is safe now until a confirmation counts
        (after it, the opening no longer asks, F5b), so while a confirmation is awaited the
        previous reply always asked it: a whole-message yes ("是的", "安全的",
        "嗯 安全") then answers it. That closed grammar leaves no room for a negation, a
        hedge or a crisis cue, so it is read whatever level a risk model gave the turn;
        vetoes, a question and a negation in front of a phrase still win over both paths.
        """
        promised = _promise_spans(normalized)
        scoped = _scoped_spans(normalized)
        exempted = False
        for hit in self._veto_matcher.find_all(normalized):
            word = normalized[hit.start : hit.end]
            if any(s <= hit.start and hit.end <= e for s, e in promised) and word in _PROMISE_TIMES:
                continue
            if any(s <= hit.start and hit.end <= e for s, e in scoped) and word in _SCOPE_WORDS:
                exempted = True  # round 5: the clause's own scope; the rest is guarded below
                continue
            return False
        if exempted and not self._scoped_clear(normalized, assessment):
            return False
        ending = normalized.rstrip(_TRAILING_PUNCTUATION)
        if ending.endswith(_QUESTION_ENDINGS) and _NOT_DOING.search(ending) is None:
            return False
        compact = _compact(normalized)
        hits = self._confirm_matcher.find_all(compact)
        if any(not compact[: hit.start].endswith(_NEGATING_PREFIXES) for hit in hits):
            # Round 5: a danger cue next to the phrase ("我很安全，但药还在") voids it, as for
            # the safe clause (the F10 denial guard outside a clause's own scope).
            return self._guard_clear(normalized, self._phrase_guard)
        if _is_direct_answer(compact):
            return True
        return self._safe_clause(normalized, compact, assessment)

    def _safe_clause(self, normalized: str, compact: str, assessment: CrisisAssessment) -> bool:
        """One clause says the user is safe ("我现在在家，是安全的"; S5, 2026-10-26).

        Only when the screen found no rule risk cue in the message
        (``CrisisAssessment.rule_clear``) and no F10 denial veto or contrast occurs in it,
        so "我是安全的，可是药还在" or "我现在安全，就是今晚不想睡" never counts."""
        if not assessment.rule_clear:
            return False
        # Round 3: a message that is nothing but a promise ("我答应你，今晚不会做什么"): its
        # time word is the promise's own scope, so the F10 time vetoes do not apply to it.
        if _PROMISE.fullmatch(compact.translate(_ANSWER_PUNCTUATION)) is not None:
            return True
        # Round 4: "从天台下来了" says the user has left the place; the rest is read as before.
        # A time word inside a promise clause is the promise's scope ("我保证今晚好好的，不会
        # 乱来"), as for the whole-message promise above.
        if not self._guard_clear(normalized):
            return False
        clauses = [c.translate(_ANSWER_PUNCTUATION) for c in _CLAUSE_SPLIT.split(compact)]
        if _status_kinds(clauses) >= 2:
            return True
        return any(
            c
            and (
                _SAFE_CLAUSE.fullmatch(c) is not None
                or _PROMISE.fullmatch(c) is not None
                or _ENGLISH_SAFE.fullmatch(c) is not None
                or _confirms_scoped(c)
            )
            for c in clauses
        )

    def _guard_clear(self, normalized: str, guard: PhraseMatcher | None = None) -> bool:
        """No F10 denial veto or contrast (or, with ``guard``, none of its phrases) in the
        message outside the clauses that scope their own time (a promise, round 4) or time
        or thought word (round 5)."""
        matcher = self._clause_guard if guard is None else guard
        if matcher is None:
            return True
        guarded = _MEANS_GONE.sub("", _LEFT_PLACE.sub("", normalized))
        promised = _promise_spans(guarded)
        scoped = _scoped_spans(guarded)
        for hit in matcher.find_all(guarded):
            word = guarded[hit.start : hit.end]
            if any(s <= hit.start and hit.end <= e for s, e in promised) and word in _PROMISE_TIMES:
                continue
            if any(s <= hit.start and hit.end <= e for s, e in scoped) and word in _SCOPE_WORDS:
                continue
            return False
        return True

    def _scoped_clear(self, normalized: str, assessment: CrisisAssessment) -> bool:
        """A confirm veto was let through as a clause's own scope (round 5): the rest of the
        message must carry no rule risk cue and pass the F10 denial guard."""
        return assessment.rule_clear and self._guard_clear(normalized)

    def _status(
        self, level: CrisisLevel, escalated: bool, just_entered: bool, just_exited: bool
    ) -> CrisisStatus:
        remaining = 0
        if self._in_crisis and self._entry_level is not None:
            needed = self._tax.crisis_exit_safe_turns(self._entry_level)
            remaining = needed - self._safe_turns if self._confirmed else needed
        return CrisisStatus(
            level=level,
            in_crisis=self._in_crisis,
            entry_level=self._entry_level,
            escalated=escalated,
            awaiting_confirmation=self._in_crisis and not self._confirmed,
            safe_turns_remaining=remaining,
            just_entered=just_entered,
            just_exited=just_exited,
            consecutive_l1_count=self._run,
        )
