"""Someone else's words, reported by the user ("她跟我说她不想活了", "他说了句“活够了”").

A Stage 2 phrase matches whoever says it, so a user worried about a friend who quotes the
friend's words entered the crisis flow herself. This module finds the phrases that are
structurally someone else's speech (``risk.yaml`` section ``reported_speech``, described
on :class:`~olivia.core.safety.lexicon.ReportedSpeechRules`): a third-person speaker, a
speech verb, then only fillers before the phrase. It never decides a level: the rule model
voids reported phrases only when nothing else in the message is a risk cue (``crisis.py``),
so the user's own words next to a quote always keep their level.

``ReportedSpeech.contents`` (问题单第 6 条, 2026-10-26) gives the spans of those reported
words, so the screen can rate them on their own (``SafetyScreen.reported_risk``) and the
session can answer with resources for the other person.

Every check fails toward keeping the phrase: a self word anywhere between the speaker and
the phrase (except an object such as 跟我说), clause punctuation between speaker and verb,
anything but a filler after the verb, or a veto such as 我也是 in the message.

Round 3 (2026-10-27, re-test r2 第 3 节; grammar, not a list of example sentences):

* The speaker must be the subject of its clause. A self word before it in its clause
  counts only as a possessive ("我妈", "我的好朋友", "我们班有个学生"), and a recipient word
  before it ("我跟妈妈说不想活了": the user told her) makes it no speaker. Before this, the
  second 妈 of "我跟妈妈说不想活了" was read as the speaker and the user's own words as hers.
* More speakers and verbs, built in here: a kinship word after a possessive self word
  (我哥, 我姐, 我妹 ...), common words for a person (女生, 同桌, 学长 ...) and written or posted
  words (周记里写, 发了一条, 私信, 留了言 ...). A speech verb that opens the next clause
  ("我妹在朋友圈发了一条，说今晚……") is the same speaker's.
* :meth:`ReportedSpeech.contents` also reads someone else's intent told in the third
  person, with no speech verb ("我表哥打算周末去跳河", "闺蜜已经写好遗书了"): a specific
  person as the subject of the clause and an intent or preparation verb (想, 要, 打算, 写好
  ...) after it; the words are the rest of the clause.
* The reported words go on into the next clause when it has no self word, listener, veto
  or contrast and it starts with a third-person pronoun or a conclusion word (不如, 干脆,
  所以), or the clause before it began with a third-person pronoun and carried no risk cue
  of its own ("室友说她明天要去江边，不想活了": the plan's place, then why). A next clause
  that only follows a complete risk statement ("她说她不想活了，活着好累") stays the user's.
* English: "my roommate … she told me she wants to kill herself and she has pills". A
  speaker (my + a person, she, he, they), a speech or intent verb, then the words up to
  the first first-person word or the end of the sentence.
* The screen reads the words turned to the first person (``ReportedSpan.screen``: "i want
  to kill myself and i have pills"; 他要去天台跳下去 -> 我要去天台跳下去), since the risk
  phrases and compositions of ``risk.yaml`` read a third person as someone else.

Round 4 (2026-10-28, re-test q2 第 1 节): a later clause may open with the listener (我哥昨晚
喝多了，跟我说……); quoted words and words after a colon are the speaker's own, first person
included; a measure or a second verb of saying may follow the verb (发了一句, 留言说); a self
word that names a place or an owner (在我朋友圈底下) is no subject; a speaker after 被 / 让 is
none ("被同事吵得想死"), nor is 想 after a degree complement; a reflexive 自己 stays inside
the words ("我弟又开始伤害自己了"); 我也 vetoes only when the user joins in (a risk cue after it,
or no worried word: "我也不知道该怎么办了" is worry). :func:`names_death` and
:func:`farewell_strength` read the words for the session's card.

Only :meth:`ReportedSpeech.contents` (the session's card for someone else) reads the intent
clauses, the clause chain and English; :meth:`ReportedSpeech.reported` (the rule level)
gets the subject check and the extra speakers and verbs only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from olivia.core.safety.lexicon import CompositionRules, ReportedSpeechRules
from olivia.core.safety.matcher import Match, PhraseMatcher
from olivia.core.safety.normalize import fold_words, normalize

_SPEAKER = "s"
_SPEAKER_EXCEPTION = "S"
_VERB = "v"
_VERB_EXCEPTION = "V"
_SELF = "m"
_RECIPIENT = "r"
_VETO = "x"
_KIN = "k"
_INTENT = "i"
_PRONOUN = "p"
_CONNECTIVE = "c"
_CONTRAST = "t"
_LISTENER = "l"

# Round 3 (2026-10-27): speakers and verbs the ``reported_speech`` section of risk.yaml does
# not list. They are kept here, next to the grammar that reads them, because risk.yaml is
# outside this change; each is a closed word class, not an example sentence.
# Common words for a person who can be the subject of a clause.
_EXTRA_SPEAKERS: Final = (
    "女生", "男生", "女孩", "男孩", "女孩子", "男孩子", "姑娘", "小姑娘", "小伙子", "小孩",
    "家人", "亲戚", "前任", "前男友", "前女友", "学长", "学姐", "学弟", "学妹", "师兄", "师姐",
    "师弟", "师妹", "同桌", "发小", "老乡", "闺女", "媳妇", "丈夫", "妻子", "爱人", "婆婆",
    "公公", "岳母", "丈母娘", "嫂子", "姐夫", "妹夫", "侄子", "侄女", "外甥", "外甥女",
    "孙子", "孙女", "继父", "继母", "后妈", "来访者", "病友", "好友", "朋友们", "同学们",
)  # fmt: skip
# Kinship words that name a speaker only after a possessive self word (我哥, 我亲姐).
_KIN_WORDS: Final = ("哥", "姐", "弟", "妹", "舅", "姨", "叔", "婶", "嫂")
# Speech, written and posted words.
_EXTRA_VERBS: Final = (
    "写", "写了", "写着", "写下", "写过", "写的是", "发了", "发了条", "发了一条", "私信",
    "发短信", "发微信", "发语音", "打电话", "留了言", "提起", "透露", "坦白", "承认", "吐槽",
    "哭诉", "扬言", "威胁", "嚷嚷", "说过", "总说", "老说",
)  # fmt: skip
# A 写 or 发 that is no report of words (写好遗书 is read as an intent instead).
_EXTRA_VERB_EXCEPTIONS: Final = (
    "写好", "写完", "写作", "写字", "写代码", "写论文", "写报告", "写作业", "写小说", "写歌",
    "发了工资", "发了脾气", "发了火", "发了烧", "发了疯", "打电话给",
)  # fmt: skip
# Intent and preparation verbs that make a clause someone's intent ("她打算周末……").
_INTENT_VERBS: Final = (
    "想", "要", "打算", "准备", "计划", "决定", "写好", "买好", "攒了", "攒够", "藏了",
    # Round 4 (2026-10-28): someone else's self-injury told in the third person ("我弟又开始
    # 伤害自己了"); the words are rated as the user's own, so only real risk opens the card.
    "开始", "伤害", "自残", "割", "烫",
)  # fmt: skip
# Generic speakers that name nobody in particular: never the subject of an intent clause
# ("有人想死吗" may be the user asking about themselves).
_GENERIC_SPEAKERS: Final = frozenset({"有人", "别人", "他们", "她们"})
_PRONOUNS: Final = ("他", "她", "ta", "他们", "她们", "佢", "佢哋")
# A clause that starts with one of these draws the conclusion of the clause before it.
_CONNECTIVES: Final = ("不如", "还不如", "干脆", "所以", "就想", "只想", "然后就", "索性")
# A clause with one of these is no longer the other person's words for sure.
_CONTRASTS: Final = ("但", "可是", "不过", "然而", "其实", "可我", "而我", "反正我")
_LISTENERS: Final = ("你", "您")
# A self word before the speaker in its clause is a possessive only when what follows it up
# to the speaker matches this (我妈, 我的好朋友, 我们班有个学生, 我那个同事, 我家孩子).
_POSSESSIVE: Final = re.compile(
    r"(?:们)?(?:家|班|宿舍|寝室|公司|单位|学校|部门|组|群)?(?:里|上|中)?的?有?"
    r"(?:一个|一位|个|位|那个|这个|那位|这位)?(?:最好的|很好的|好|亲|新|老)?的?"
)
_KIN_POSSESSIVE: Final = re.compile(r"(?:的|家|们家)?亲?")
# Clause chain: only a comma-like stop is crossed, never a sentence end.
_CHAIN_STOPS: Final = frozenset(",、")
_CHAIN_MAX: Final = 3
# A speech verb that opens a later clause is the speaker's when it lies this close.
_NEXT_CLAUSE_GAP: Final = 20

# -- round 4 (2026-10-28, re-test q2 第 1 节) ----------------------------------------------
# A later clause may open with the listener before the verb ("我哥昨晚喝多了，跟我说……").
_TOLD_ME: Final = re.compile(r"(?:跟|对|和|同|向)(?:我们|我)")
# What may stand between a speech verb and the words: a measure ("发了一句", "留了一条"), a
# second verb of saying ("留言说", "写道") or a colon.
_AFTER_VERB: Final = re.compile(
    r"(?:了|过|着)?(?:一|几)?(?:句|条|段|篇|则|张)(?:话|消息|动态|留言|朋友圈|微博)?"
    r"|(?:着|了)?(?:说道|说|道|讲|写道)"
    r"|:"
)
# Quoted words: the opening mark and its closing mark (NFKC keeps these as they are).
_QUOTES: Final = {"“": "”", "「": "」", "『": "』", '"': '"'}
# Round 5 (re-test q2 第 1 节): a time or an adverb that may open a clause before a speech
# verb of the same speaker ("……，前天还说……").
_TIME_LEAD: Final = re.compile(
    r"(?:昨天|前天|今天|昨晚|前晚|今早|今晚|刚才|刚刚|后来|最近|这几天|前几天|这两天|那天|上周|"
    r"上次|上礼拜|上星期|上个月|前段时间|前阵子|那时候|有天|早上|晚上|半夜|夜里|有一次|有时候|"
    r"还|又|也|老|总|一直|经常|甚至|居然|竟然|突然|再)*"
)
# A possessive self word that may open a message before the person it owns (我室友, 我的好
# 朋友, 我们班的同学; round 5).
_OWNER: Final = re.compile(
    r"(?:我|俺|咱)(?:们)?(?:家|班|宿舍|寝室|公司|单位|学校|部门|组|群)?(?:里|上|中)?的?有?"
    r"(?:一个|一位|个|位|那个|这个|那位|这位)?(?:最好的|很好的|好|亲|新|老)?的?"
)
# A self word right after one of these is an object ("拖累了我们", "找我"), not a subject.
_OBJECT_BEFORE: Final = (
    "了", "找", "问", "叫", "喊", "求", "骂", "怪", "缠", "拖累", "连累", "麻烦", "烦", "打",
    "陪", "帮", "给", "对", "跟", "和", "告诉", "嘱咐", "交给", "托付", "回", "发", "劝", "安慰",
    "哄", "通知", "提醒",
)  # fmt: skip
# Words after a colon run to the end of the sentence.
_SENTENCE_END: Final = frozenset("。!?;")
# A self word right before or after these is no subject of the speech: a place or an
# owner ("在我朋友圈底下留言", "我的帖子下面").
_SELF_PLACE_BEFORE: Final = frozenset("在到从于")
_SELF_OWNED: Final = (
    "的", "朋友圈", "空间", "微博", "动态", "帖子", "评论", "主页", "群", "家", "作业", "周记",
    "日记", "本子", "手机", "微信", "相册",
)  # fmt: skip
# A speaker right after these is the agent of a passive or causative ("被同事吵得想死"),
# never the subject of the clause.
_PASSIVE: Final = frozenset("被让叫给把")
_REFLEXIVE: Final = "自己"
# A degree complement between a subject and 想 ("同事吵得想死") is a figure of speech
# about the user, not the subject's intent.
_COMPLEMENT: Final = ("得", "到")
# 我也 and its kin veto the reading only when the user joins in: a risk cue in the rest
# of its clause, or no helpless or worried word right after it ("她说她想死，我也不知道该
# 怎么办了" is the user's worry, "她说她想死，我也是" joins in).
_JOINING_VETOES: Final = frozenset({"我也", "我同样", "我自己也"})
_HELPLESS: Final = (
    "不知道", "不晓得", "不清楚", "不知所措", "不懂", "没办法", "没主意", "手足无措", "慌",
    "怕", "害怕", "担心", "着急", "急", "吓", "很担心", "很害怕", "很慌", "好担心", "好怕",
    "好慌", "挺担心", "特别担心", "非常担心",
)  # fmt: skip
_HELPLESS_LEAD: Final = ("真的", "实在", "完全", "都", "有点", "有些", "也", "就")
# Death words the session reads as someone else's risk next to a time or a means even when
# the rules miss the reported words (round 4: "下周一考完试她就去死"). A closed class of
# words for dying by one's own hand; no figure of speech ("累死了") is one.
_DEATH_WORDS: Final = (
    "去死", "死掉", "寻死", "自杀", "轻生", "自尽", "了结", "结束生命", "结束自己", "不想活",
    "不活了", "活不下去", "跳楼", "跳河", "跳江", "跳桥", "上吊", "割腕", "烧炭", "killmyself",
    "endmylife",
)  # fmt: skip
# Farewells: a strong one is someone else's risk alone ("永别了"); a weak one only with a
# means or a place in the message ("大家再见了，谢谢你们" posted with a picture of a roof).
_FAREWELL_STRONG: Final = (
    "永别", "诀别", "下辈子见", "来世见", "来生再见", "永远再见", "告别这个世界",
    "别了这个世界", "和这个世界告别", "goodbyeforever",
)  # fmt: skip
_FAREWELL_WEAK: Final = (
    "大家再见", "再见了大家", "各位再见", "再见了各位", "你们好好的", "你们要好好的", "别找我",
    "不要找我", "谢谢大家这些年", "goodbyeeveryone",
)  # fmt: skip


def names_death(words: str) -> bool:
    """A death word of :data:`_DEATH_WORDS` in someone else's reported words (round 4)."""
    return any(w in words for w in _DEATH_WORDS)


def farewell_strength(words: str) -> int:
    """2 for a strong farewell in someone else's reported words, 1 for a weak one, else 0
    (round 4)."""
    if any(w in words for w in _FAREWELL_STRONG):
        return 2
    return 1 if any(w in words for w in _FAREWELL_WEAK) else 0


# -- English ------------------------------------------------------------------------------
_EN_PERSON = (
    r"(?:friend|roommate|flatmate|housemate|sister|brother|sis|bro|mom|mum|mother|dad|father|"
    r"son|daughter|kid|child|wife|husband|partner|boyfriend|girlfriend|bf|gf|fianc[eé]e?|"
    r"cousin|aunt|uncle|niece|nephew|grandma|grandpa|grandmother|grandfather|colleague|"
    r"coworker|co-worker|classmate|student|teammate|neighbou?r|ex|buddy|pal|bestie|bff)s?"
)
_EN_SPEAKER: Final = re.compile(
    rf"\b(?:(?:my|our)\s+(?:(?:best|close|old|older|younger|little|big|twin|dear)\s+)?"
    rf"{_EN_PERSON}|(?:a|one)\s+(?:of\s+my\s+)?{_EN_PERSON}(?:\s+of\s+mine)?|she|he|they)\b"
)
_EN_SPEECH: Final = re.compile(
    r"\s*(?:,\s*)?(?:said|says|told\s+(?:me|us|everyone)|tells\s+(?:me|us)|texted(?:\s+me)?|"
    r"texts(?:\s+me)?|messaged(?:\s+me)?|wrote|writes|posted|keeps\s+saying|kept\s+saying|"
    r"mentioned|admitted|confessed|threatened|called\s+me\s+and\s+said)\b(?:\s+that)?\s*"
)
_EN_INTENT: Final = re.compile(
    r"\s*(?:wants|wanted|is\s+going|was\s+going|'s\s+going|is\s+gonna|'s\s+gonna|plans|"
    r"planned|is\s+planning|has\s+been\s+planning|is\s+thinking|has\s+been\s+thinking|"
    r"has\s+been\s+talking|tried|attempted|is\s+trying|has|had|keeps|doesn't\s+want|"
    r"does\s+not\s+want|can't|cannot|will|'ll|is|was|'s)\b"
)
_EN_SENTENCE_END: Final = re.compile(r"[.!?;。！？；]")
_EN_FIRST_PERSON: Final = re.compile(r"\b(?:i|i'm|im|i've|i'd|i'll|me|my|mine|myself|we|us|our)\b")
_EN_GAP: Final = 60
# The user joins in ("my friend wants to die and so do i"): no English words are reported.
_EN_VETO: Final = re.compile(
    r"\b(?:so do i|so am i|me too|same here|i do too|i feel the same|i want to too|"
    r"same for me|me as well|i do as well)\b"
)
# Third person -> first person, in order (the screen's English phrases say "myself").
_EN_SHIFT: Final[tuple[tuple[re.Pattern[str], str], ...]] = tuple(
    (re.compile(pattern), repl)
    for pattern, repl in (
        (r"\b(?:herself|himself|themselves|themself)\b", "myself"),
        (r"\b(?:she's|he's|they're)\b", "i'm"),
        (r"\b(?:she|he|they)\s+(?:is|are)\b", "i am"),
        (r"\b(?:she|he|they)\b", "i"),
        (r"\b(?:her|his|their)\b", "my"),
        (r"\bwants\b", "want"),
        (r"\bhas\b", "have"),
        (r"\bplans\b", "plan"),
        (r"\bneeds\b", "need"),
        (r"\bkeeps\b", "keep"),
        (r"\bfeels\b", "feel"),
        (r"\bthinks\b", "think"),
        (r"\bdoesn't\b", "don't"),
        (r"\bdoes\b", "do"),
        (r"\bhates\b", "hate"),
        (r"\btries\b", "try"),
        (r"\bgoes\b", "go"),
        (r"\bsays\b", "say"),
    )
)


@dataclass(frozen=True)
class ReportedSpan:
    """Someone else's words in a message: ``start`` and ``end`` index the normalized text;
    ``screen`` is what the screen rates as if the user had said it (the words themselves,
    or English words turned to the first person)."""

    start: int
    end: int
    screen: str


def _covered(span: Match, covers: Iterable[Match]) -> bool:
    return any(c.start <= span.start and span.end <= c.end for c in covers)


class ReportedSpeech:
    """Answers "is this Stage 2 phrase someone else's reported words?"."""

    def __init__(self, rules: ReportedSpeechRules, compositions: CompositionRules) -> None:
        self._enabled = bool(rules.speakers and rules.verbs)
        self._gap = rules.speaker_gap
        self._stops = compositions.stops
        # Longest first, so "他们" is stripped before "他".
        self._fillers = tuple(sorted(rules.fillers, key=len, reverse=True))
        roles: dict[str, set[str]] = {}
        extras: tuple[tuple[str, Iterable[str]], ...] = ()
        if self._enabled:
            extras = (
                (_SPEAKER, _EXTRA_SPEAKERS),
                (_VERB, _EXTRA_VERBS),
                (_VERB_EXCEPTION, _EXTRA_VERB_EXCEPTIONS),
                (_KIN, _KIN_WORDS),
                (_INTENT, _INTENT_VERBS),
                (_PRONOUN, _PRONOUNS),
                (_CONNECTIVE, _CONNECTIVES),
                (_CONTRAST, _CONTRASTS),
                (_LISTENER, _LISTENERS),
            )
        for role, phrases in (
            (_SPEAKER, rules.speakers),
            (_SPEAKER_EXCEPTION, rules.speaker_exceptions),
            (_VERB, rules.verbs),
            (_VERB_EXCEPTION, rules.verb_exceptions),
            (_SELF, compositions.selves),
            (_RECIPIENT, compositions.recipients),
            (_VETO, rules.vetoes),
            *extras,
        ):
            for phrase in phrases:
                roles.setdefault(normalize(phrase), set()).add(role)
        self._roles = {phrase: frozenset(r) for phrase, r in roles.items() if phrase}
        self._matcher = PhraseMatcher({phrase: phrase for phrase in self._roles})

    # -- the rule level -------------------------------------------------------------------

    def reported(self, text: str, phrases: Sequence[Match]) -> list[Match]:
        """The ``phrases`` (spans in the normalized ``text``) that are reported speech.

        Empty when the message carries a veto (the user joins in: 我也是, 一起)."""
        if not self._enabled or not phrases:
            return []
        found = self._found(text)
        if found.get(_VETO) or not found.get(_VERB):
            return []
        recipient_ends = {m.end for m in found.get(_RECIPIENT, ())}
        selves = found.get(_SELF, [])
        verbs = self._verbs(found)
        speakers = self._speakers(text, found, recipient_ends)
        if not speakers:
            return []
        return [
            phrase
            for phrase in phrases
            if not any(phrase.start <= m.start and m.end <= phrase.end for m in selves)
            and any(
                self._after_verb(text, verb, phrase)
                and self._spoken_by(text, verb, speakers, selves, recipient_ends)
                for verb in verbs
                if verb.end <= phrase.start
            )
        ]

    # -- the session's card for someone else ----------------------------------------------

    def contents(
        self, text: str, *, cues: Sequence[Match] = (), raw: str | None = None
    ) -> list[ReportedSpan]:
        """Spans of someone else's words in the normalized ``text`` (问题单第 6 条,
        2026-10-26; round 3, 2026-10-27).

        * Speech: from a speech verb whose third-person speaker is the subject of its
          clause and stands shortly before it, with no self word as subject in between
          (as for :meth:`reported`), leading fillers dropped ("他说周末要……" -> "周末
          要……"). A speech verb that opens a later clause counts too.
        * Intent: a specific person as the subject of a clause with an intent or
          preparation verb after it ("我表哥打算周末去跳河"): the rest of the clause.
        * The words go on into the next clauses as the module docstring says; ``cues``
          (risk cue spans in ``text``) tell whether a clause carried risk of its own.
        * English, read on ``raw`` (the message as typed; word breaks matter).

        Every check fails toward the user: a span that would hold a self word ends before
        it (or is left out when that leaves nothing), and the message has none when it
        carries a veto (我也, 一起). Only the session reads them, to tell the level of the
        reported words themselves."""
        if not self._enabled:
            return []
        found = self._found(text)
        if any(self._joins_in(text, veto, cues) for veto in found.get(_VETO, ())):
            return []
        spans = self._chinese_contents(text, found, cues)
        if raw is not None:
            spans.extend(self._english_contents(raw, text))
        kept: list[ReportedSpan] = []
        for span in sorted(spans, key=lambda s: (s.start, -s.end)):
            if any(k.start <= span.start and span.end <= k.end for k in kept):
                continue
            kept.append(span)
        return kept

    def about_others(self, text: str) -> bool:
        """The normalized ``text`` is about a specific other person (round 5, re-test q2
        第 1 节): a speaker that is the subject of its clause and names someone (not 有人 /
        别人), and every self word is a possessive before such a speaker (我室友), an object
        (跟我说, 拖累了我们, 找我), a place or an owner (我的帖子) or a reflexive 自己 after
        the speaker. No veto (我也, 一起) may occur. It reads grammar only: whether the
        message carries risk, and whose, is the caller's business."""
        if not self._enabled:
            return False
        found = self._found(text)
        if found.get(_VETO):
            return False
        recipient_ends = {m.end for m in found.get(_RECIPIENT, ())}
        speakers = [
            s
            for s in self._speakers(text, found, recipient_ends)
            if text[s.start : s.end] not in _GENERIC_SPEAKERS
        ]
        # The message opens with the person: the first clause's subject, after a time or an
        # adverb or a possessive self word ("我室友……"). A clause with no subject of its own
        # is the user's ("计划好了，先把猫送到朋友家"), so a speaker later on is not enough.
        timed = _TIME_LEAD.match(text)
        first = timed.end() if timed is not None else 0
        owner = _OWNER.match(text, first)
        if not any(s.start in (first, owner.end() if owner else -1) for s in speakers):
            return False
        for m in found.get(_SELF, ()):
            if text[m.start : m.end] == _REFLEXIVE and any(s.end <= m.start for s in speakers):
                continue
            if m.start in recipient_ends or self._placed(text, m) or self._object(text, m):
                continue
            if any(
                m.end <= s.start
                and self._clause_start(text, s.start) <= m.start
                and (
                    _POSSESSIVE.fullmatch(text[m.end : s.start]) is not None
                    or _KIN_POSSESSIVE.fullmatch(text[m.end : s.start]) is not None
                )
                for s in speakers
            ):
                continue
            return False
        return True

    def _chinese_contents(
        self, text: str, found: dict[str, list[Match]], cues: Sequence[Match]
    ) -> list[ReportedSpan]:
        if not found.get(_SPEAKER) and not found.get(_KIN):
            return []
        recipient_ends = {m.end for m in found.get(_RECIPIENT, ())}
        selves = found.get(_SELF, [])
        speakers = self._speakers(text, found, recipient_ends)
        # (where the words start, the verb or speaker start): right after the verb or the
        # subject, so a cue that begins with a filler (已经写好遗书) lies inside them.
        starts: list[tuple[int, int]] = []
        for verb in self._verbs(found):
            if self._spoken_by(text, verb, speakers, selves, recipient_ends, cross=True):
                starts.append((verb.end, verb.start))
        for speaker in speakers:
            if text[speaker.start : speaker.end] in _GENERIC_SPEAKERS:
                continue
            if self._intends(text, speaker, found, selves):
                starts.append((speaker.end, speaker.start))
        spans: list[ReportedSpan] = []
        verb_starts = {verb.end for verb in self._verbs(found)}
        for start, anchor in sorted(starts):
            if start in verb_starts:
                quoted = self._quoted(text, start)
                if quoted is not None:
                    # Round 4: quoted words, or words after a colon, are the speaker's own,
                    # first person included ("发了一句“我真的撑不下去了，想死”").
                    spans.append(ReportedSpan(quoted[0], quoted[1], text[quoted[0] : quoted[1]]))
                    continue
                start = self._past_verb(text, start)
            end = self._clause_end(text, self._skip_fillers(text, start, len(text)))
            words = self._skip_fillers(text, start, end)
            if words >= end:
                continue
            pronoun = self._starts_with(text, anchor, found.get(_PRONOUN, ()), words)
            end = self._chain(text, start, end, found, cues, pronoun=pronoun)
            # A reflexive 自己 inside the words is the speaker's ("他又开始伤害自己"; round 4).
            end = min(
                [
                    end,
                    *(
                        m.start
                        for m in selves
                        if start <= m.start < end and text[m.start : m.end] != _REFLEXIVE
                    ),
                ]
            )
            end = self._trim(text, start, end)
            if start < end:
                spans.append(ReportedSpan(start, end, self._first_person(text, start, end, found)))
        return spans

    def _first_person(self, text: str, start: int, end: int, found: dict[str, list[Match]]) -> str:
        """``text[start:end]`` with each third-person pronoun turned into 我, so the screen
        rates the words as if the user had said them: a composition reads "他要去天台跳下去"
        as someone else's plan, but "我要去天台跳下去" as a plan (round 3)."""
        exceptions = found.get(_SPEAKER_EXCEPTION, ())
        pronouns = [
            p
            for p in found.get(_PRONOUN, ())
            if start <= p.start and p.end <= end and not _covered(p, exceptions)
        ]
        out: list[str] = []
        at = start
        for p in sorted(pronouns, key=lambda m: (m.start, -m.end)):
            if p.start < at:
                continue
            out.append(text[at : p.start])
            out.append("我")
            at = p.end
        out.append(text[at:end])
        return "".join(out)

    def _english_contents(self, raw: str, text: str) -> list[ReportedSpan]:
        """English reported words in ``raw``, located in the normalized ``text``."""
        folded = fold_words(raw)
        if not _EN_SPEAKER.search(folded) or _EN_VETO.search(folded):
            return []
        # Index of each folded character in the normalized text (spaces have none).
        if folded.replace(" ", "") != text:
            return []  # the two folds disagree: read nothing rather than guess
        positions: list[int] = []
        count = 0
        for ch in folded:
            positions.append(count)
            if ch != " ":
                count += 1
        positions.append(count)
        spans: list[ReportedSpan] = []
        for speaker in _EN_SPEAKER.finditer(folded):
            rest = folded[speaker.end() : speaker.end() + _EN_GAP]
            if _EN_SENTENCE_END.search(rest[:1]):
                continue
            speech = _EN_SPEECH.match(folded, speaker.end())
            intent = None if speech is not None else _EN_INTENT.match(folded, speaker.end())
            if speech is not None:
                start = speech.end()
            elif intent is not None:
                start = speaker.end() + (len(intent.group(0)) - len(intent.group(0).lstrip()))
            else:
                continue
            stop = _EN_SENTENCE_END.search(folded, start)
            end = stop.start() if stop is not None else len(folded)
            first = _EN_FIRST_PERSON.search(folded, start, end)
            if first is not None:
                end = first.start()
            words = folded[start:end].strip(" ,")
            if not words or not re.search(r"[a-z]", words):
                continue
            shifted = words
            for pattern, repl in _EN_SHIFT:
                shifted = pattern.sub(repl, shifted)
            begin = positions[start]
            finish = positions[end]
            if begin < finish:
                spans.append(ReportedSpan(begin, finish, normalize(shifted)))
        return spans

    # -- shared pieces --------------------------------------------------------------------

    def _found(self, text: str) -> dict[str, list[Match]]:
        found: dict[str, list[Match]] = {}
        for match in self._matcher.find_all(text):
            for role in self._roles[match.key]:
                found.setdefault(role, []).append(match)
        return found

    def _verbs(self, found: dict[str, list[Match]]) -> list[Match]:
        exceptions = found.get(_VERB_EXCEPTION, ())
        return sorted(
            (v for v in found.get(_VERB, ()) if not _covered(v, exceptions)),
            key=lambda m: m.start,
        )

    def _speakers(
        self, text: str, found: dict[str, list[Match]], recipient_ends: set[int]
    ) -> list[Match]:
        """Speakers that are the subject of their clause (round 3): not inside a speaker
        exception (吉他), not right after a recipient word (跟她说), a kinship word only
        after a possessive self word (我哥), and no recipient word and no self word but a
        possessive one before it in its clause."""
        exceptions = found.get(_SPEAKER_EXCEPTION, ())
        recipients = found.get(_RECIPIENT, ())
        selves = found.get(_SELF, ())
        candidates = [
            s
            for s in found.get(_SPEAKER, ())
            if not _covered(s, exceptions)
            and s.start not in recipient_ends
            and not (s.start > 0 and text[s.start - 1] in _PASSIVE)
        ]
        for kin in found.get(_KIN, ()):
            if _covered(kin, candidates):
                continue
            owner = [m for m in selves if m.end <= kin.start]
            if owner and _KIN_POSSESSIVE.fullmatch(text[owner[-1].end : kin.start]):
                candidates.append(kin)
        speakers: list[Match] = []
        for s in candidates:
            clause = self._clause_start(text, s.start)
            if any(clause <= r.start and r.end <= s.start for r in recipients):
                continue
            before = [m for m in selves if clause <= m.start and m.end <= s.start]
            if all(_POSSESSIVE.fullmatch(text[m.end : s.start]) for m in before):
                speakers.append(s)
        return speakers

    def _clause_start(self, text: str, index: int) -> int:
        start = index
        while start > 0 and text[start - 1] not in self._stops:
            start -= 1
        return start

    def _clause_end(self, text: str, start: int) -> int:
        return next((i for i in range(start, len(text)) if text[i] in self._stops), len(text))

    def _past_verb(self, text: str, start: int) -> int:
        """Past a measure or a second verb of saying after a speech verb ("发了一句",
        "留言说"; round 4), so the words start where the speech does."""
        while True:
            match = _AFTER_VERB.match(text, start)
            if match is None or not match.group(0):
                return start
            start = match.end()

    def _quoted(self, text: str, start: int) -> tuple[int, int] | None:
        """The words in quotes, or after a colon, right after a speech verb ("说：", "发了
        一句“……”"; round 4): (start, end) in ``text``, else None. Quoted words end at the
        closing mark (or the end of the message), words after a colon at the end of the
        sentence."""
        at = self._past_verb(text, start)
        colon = text.startswith(":", start) or text.startswith(":", at - 1)
        while at < len(text) and text[at] in ",":
            at += 1
        if at < len(text) and text[at] in _QUOTES:
            close = text.find(_QUOTES[text[at]], at + 1)
            end = len(text) if close < 0 else close
            return (at + 1, end) if at + 1 < end else None
        if colon:
            end = next((i for i in range(at, len(text)) if text[i] in _SENTENCE_END), len(text))
            end = self._trim(text, at, end)
            return (at, end) if at < end else None
        return None

    def _joins_in(self, text: str, veto: Match, cues: Sequence[Match]) -> bool:
        """Whether a veto (我也, 一起 ...) means the user joins in (round 4): always, but for
        我也 and its kin with no risk cue in the rest of their clause and a helpless or
        worried word right after them."""
        if text[veto.start : veto.end] not in _JOINING_VETOES:
            return True
        end = self._clause_end(text, veto.end)
        if any(veto.end <= c.start < end for c in cues):
            return True
        at = veto.end
        moved = True
        while moved:
            moved = False
            for lead in _HELPLESS_LEAD:
                if text.startswith(lead, at, end):
                    at += len(lead)
                    moved = True
        return not any(text.startswith(w, at, end) for w in _HELPLESS)

    def _intends(
        self,
        text: str,
        speaker: Match,
        found: dict[str, list[Match]],
        selves: Sequence[Match],
    ) -> bool:
        """An intent or preparation verb after ``speaker`` in its clause, within the gap,
        with no self word in between ("我表哥打算……", "闺蜜已经写好遗书了")."""
        end = self._clause_end(text, speaker.end)
        for verb in found.get(_INTENT, ()):
            if not speaker.end <= verb.start < end or verb.start - speaker.end > self._gap:
                continue
            if any(speaker.end <= m.start < verb.start for m in selves):
                continue
            if any(c in text[speaker.end : verb.start] for c in _COMPLEMENT):
                continue  # round 4: "同事吵得想死" is no intent of the colleague's
            return True
        return False

    def _starts_with(self, text: str, anchor: int, pronouns: Sequence[Match], start: int) -> bool:
        """A third-person pronoun stands between the anchor (a verb or the subject) and the
        words, or opens them: the words are about that person ("说她明天要……")."""
        return any(anchor <= p.start <= start for p in pronouns)

    def _chain(
        self,
        text: str,
        start: int,
        end: int,
        found: dict[str, list[Match]],
        cues: Sequence[Match],
        *,
        pronoun: bool,
    ) -> int:
        """Where the words end once the next clauses are read as theirs (module docstring)."""
        blocking = (
            *found.get(_SELF, ()),
            *found.get(_LISTENER, ()),
            *found.get(_CONTRAST, ()),
        )
        pronouns = found.get(_PRONOUN, ())
        connectives = found.get(_CONNECTIVE, ())
        about_them = pronoun and not any(start <= c.start < end for c in cues)
        for _ in range(_CHAIN_MAX):
            if end >= len(text) or text[end] not in _CHAIN_STOPS:
                break
            nxt = end + 1
            nxt_end = self._clause_end(text, nxt)
            if nxt >= nxt_end or any(nxt <= m.start < nxt_end for m in blocking):
                break
            opens = self._skip_fillers(text, nxt, nxt_end)
            opener = any(p.start == nxt for p in pronouns) or any(
                c.start in (nxt, opens) for c in connectives
            )
            if not (opener or about_them):
                break
            end = nxt_end
            about_them = about_them and not any(nxt <= c.start < nxt_end for c in cues)
        return end

    def _trim(self, text: str, start: int, end: int) -> int:
        while end > start and text[end - 1] in self._stops:
            end -= 1
        return end

    def _skip_fillers(self, text: str, start: int, end: int) -> int:
        """The first index from ``start`` that does not begin a filler (他, 也, 已经 ...)."""
        while start < end:
            filler = next((f for f in self._fillers if text.startswith(f, start, end)), None)
            if filler is None:
                break
            start += len(filler)
        return start

    def _placed(self, text: str, self_word: Match) -> bool:
        """A self word that names a place or an owner, not the subject ("在我朋友圈底下",
        "我的帖子"; round 4)."""
        before = text[self_word.start - 1] if self_word.start > 0 else ""
        return before in _SELF_PLACE_BEFORE or text.startswith(_SELF_OWNED, self_word.end)

    def _object(self, text: str, self_word: Match) -> bool:
        """A self word right after a verb or 了 is its object, not the subject ("她说她拖累
        了我们", "他总找我"; round 5)."""
        return text.endswith(_OBJECT_BEFORE, 0, self_word.start)

    def _after_verb(self, text: str, verb: Match, phrase: Match) -> bool:
        """Only fillers stand between the verb and the phrase."""
        rest = text[verb.end : phrase.start]
        while rest:
            filler = next((f for f in self._fillers if rest.startswith(f)), None)
            if filler is None:
                return False
            rest = rest[len(filler) :]
        return True

    def _spoken_by(
        self,
        text: str,
        verb: Match,
        speakers: Sequence[Match],
        selves: Sequence[Match],
        recipient_ends: set[int],
        *,
        cross: bool = False,
    ) -> bool:
        """A third-person speaker shortly before the verb, with no self word in between
        that is not an object (跟我说) or part of the verb (告诉我). In its clause, or, with
        ``cross`` (round 3, :meth:`contents` only), in an earlier clause when the verb
        opens its own clause after fillers only ("我妹在朋友圈发了一条，说……")."""
        clause = self._clause_start(text, verb.start)
        lead = self._skip_fillers(text, clause, verb.start)
        told = _TOLD_ME.match(text, lead)
        if told is not None and told.end() <= verb.start:
            # Round 4: "……，跟我说……" opens its clause with the listener, then the verb.
            lead = self._skip_fillers(text, told.end(), verb.start)
        # Round 5: a time or an adverb may open the clause before the verb ("……，昨天还说
        # ……"); the verb still opens it.
        timed = _TIME_LEAD.match(text, lead)
        if timed is not None and timed.end() <= verb.start:
            lead = self._skip_fillers(text, timed.end(), verb.start)
        opens = lead == verb.start
        for speaker in speakers:
            if speaker.end > verb.start:
                continue
            between = text[speaker.end : verb.start]
            crosses = any(ch in self._stops for ch in between)
            if crosses:
                if not (cross and opens) or verb.start - speaker.end > _NEXT_CLAUSE_GAP:
                    continue
            elif verb.start - speaker.end > self._gap:
                continue
            subject = any(
                speaker.end <= m.start
                and m.end <= verb.start
                and m.start not in recipient_ends
                and not self._placed(text, m)
                and not self._object(text, m)
                for m in selves
            )
            if not subject:
                return True
        return False
