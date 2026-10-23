"""Pronoun-safe mirroring (COLBO-01, SDD §4.1) and what kind of message a turn is (F3).

``utterance_kind(user_text)`` says whether a message is a statement worth mirroring or
something else: a question, a request, a greeting, thanks, a note to remember
("记住：……"), a one-word answer or a message with no Chinese at all. Only statements are
mirrored; the engine answers every other kind with a short acknowledgement from
``language/utterances.yaml`` (``LanguageEngine.safe_mirror``), so "谢谢你一直在" never
becomes "你感到谢谢……".

``mirror(user_text)`` turns the user's own statement into a short second-person clause
for the ``{mirror}`` slot (templates wrap it, e.g. "听起来，{mirror}。").

1. Every clause is tagged. Clauses addressed to the companion ("你别给我建议",
   "你听我说就好"), questions, thanks, greetings and fillers ("唉", "嗯") are dropped;
   what remains are the statement clauses.
2. Pick the first sentence whose statement clauses speak in the first person (else the
   first sentence that has any) and take its statement clauses.
3. Self-talk (no 你/您 and no third party): flip the first-person clauses.
   我 -> 你; 我的/我自己 -> 你的/你自己; 我们/咱们 -> 你们. A later 我 becomes 自己
   only when the clause's own subject 我 does something to it ("我觉得我很失败" ->
   "你觉得自己很失败", "我讨厌我这样" -> "你讨厌自己这样"); an object 我 of someone
   else is always 你 ("我妈又骂我" -> "你妈又骂你", never "骂自己").
4. Third-party conflict (the clauses name 你/您, 你们 or another person such as 伴侣、
   领导、我妈): never flip mechanically. 你/您 -> 对方, 你们 -> 他们, every 我 -> 你, a
   leading "我觉得/我感觉…" is dropped. "我觉得你根本不在乎我" -> "你感到对方根本不
   在乎你" (never "你觉得我不在乎你").
5. Exclamations "X死我了" become "你X坏了" ("气死我了" -> "你气坏了").
6. The result starts with 你: as it is when the first clause already does; with 你 in
   front of a leading time word ("今天上班好累" -> "你今天上班好累") when that clause
   names nobody else; otherwise framed as the user's feeling ("你感到…").
7. Trim to at most 20 characters at a clause boundary (，); a single over-long first clause
   is cut at the last boundary that does not split a Latin word.

The result never contains the pronoun 我 (words like 自我 are kept as written) and always
starts with 你.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

MAX_MIRROR: Final = 20
FALLBACK_MIRROR: Final = "你心里装着不少事"
_FEEL_PREFIX: Final = "你感到"


class Utterance(StrEnum):
    """What a message is, for the mirror slot (F3)."""

    STATEMENT = "STATEMENT"
    QUESTION = "QUESTION"
    REQUEST = "REQUEST"
    GREETING = "GREETING"
    THANKS = "THANKS"
    NOTE = "NOTE"
    """A request to remember something ("记住：……")."""
    BRIEF = "BRIEF"
    """A one-word answer, an emoji or punctuation only."""
    FOREIGN = "FOREIGN"
    """No Chinese at all (the mirror would only echo another language back)."""


class _Tag(StrEnum):
    STATEMENT = "statement"
    QUESTION = "question"
    REQUEST = "request"
    GREETING = "greeting"
    THANKS = "thanks"
    FILLER = "filler"


@dataclass(frozen=True)
class _Clause:
    text: str
    tag: _Tag


_BATTERY_RE: Final = re.compile(r"^\s*[\[［【]\s*\d{1,3}\s*[%％]\s*[\]］】]\s*")
# A sentence ends at one of these; ? and ？ also mark the sentence as a question.
_SENTENCE_END_RE: Final = re.compile(r"([。！？!?\n…；;]+)")
_CLAUSE_RE: Final = re.compile(r"[，,、：:]+")
_EDGE_PUNCT: Final = " \t　～~。，,、！？!?；;：:…“”\"'‘’（）()"
_CJK_RE: Final = re.compile(r"[一-鿿]")
_MEANINGFUL_RE: Final = re.compile(r"[一-鿿A-Za-z0-9]")
_FIRST_PERSON: Final = ("我", "咱")
# Words that hold 我/你 without being a pronoun for the speaker or the listener.
_NON_PRONOUN: Final = ("你死我活", "自我", "忘我", "无我", "唯我", "敌我", "你我", "你好")
# The characters at which _swap can do anything but copy: a _NON_PRONOUN word's first
# character, 我们/咱们/你们 and the pronouns 你/您/我.
_SWAP_STARTS: Final = frozenset(w[0] for w in _NON_PRONOUN) | frozenset("我咱你您")
_LEADS: Final = (
    "我总是觉得",
    "我总觉得",
    "我感觉到",
    "我觉得",
    "我感觉",
    "我感到",
    "我认为",
    "我觉着",
)
_THIRD_PARTY: Final = (
    "他们",
    "她们",
    "他",
    "她",
    "对方",
    "别人",
    "人家",
    "大家",
    "伴侣",
    "对象",
    "男朋友",
    "女朋友",
    "男友",
    "女友",
    "老公",
    "老婆",
    "丈夫",
    "妻子",
    "前任",
    "前夫",
    "前妻",
    "领导",
    "老板",
    "上司",
    "同事",
    "主管",
    "经理",
    "客户",
    "甲方",
    "房东",
    "邻居",
    "妈",
    "爸",
    "母亲",
    "父亲",
    "父母",
    "家人",
    "家里人",
    "外婆",
    "外公",
    "奶奶",
    "爷爷",
    "姥姥",
    "姥爷",
    "哥",
    "姐",
    "弟",
    "妹",
    "舅",
    "姨",
    "婆婆",
    "公公",
    "孩子",
    "朋友",
    "闺蜜",
    "兄弟",
    "室友",
    "同学",
    "老师",
    "manager",
    "boss",
)
_NOT_THIRD_PARTY: Final = ("其他", "其她")
# Verbs after which the subject's own later 我 is itself ("我觉得我…" -> "你觉得自己…").
_REFLEXIVE_VERBS: Final = (
    "总是觉得",
    "总觉得",
    "觉得",
    "感觉",
    "认为",
    "发现",
    "怀疑",
    "相信",
    "讨厌",
    "嫌弃",
    "看不起",
    "瞧不起",
    "恨",
    "怪",
    "骂",
    "逼",
    "原谅",
    "接受",
    "放过",
    "心疼",
    "喜欢",
    "对",
)
# "X死我了" exclamations; X -> the mirrored wording, else "你X坏了".
_EXCLAIM_RE: Final = re.compile(r"^(.{1,3}?)死我了$")
_EXCLAIM_WORDS: Final = {"烦": "你烦透了", "难受": "你难受极了"}
_TIME_WORDS: Final = (
    "这段时间",
    "这阵子",
    "这几天",
    "这两天",
    "上个月",
    "这个月",
    "最近",
    "今天",
    "昨天",
    "前天",
    "今晚",
    "昨晚",
    "每天",
    "天天",
    "晚上",
    "早上",
    "上午",
    "下午",
    "中午",
    "刚才",
    "刚刚",
    "现在",
    "周末",
    "上周",
    "这周",
    "今年",
    "去年",
    "一直",
    "总是",
    "经常",
    "老是",
)
_FILLERS: Final = frozenset(
    {
        "唉",
        "哎",
        "哎呀",
        "唉呀",
        "嗯",
        "嗯嗯",
        "啊",
        "哦",
        "噢",
        "哈",
        "哈哈",
        "呜",
        "呜呜",
        "其实",
        "就是",
        "那个",
        "然后",
        "怎么说呢",
        "说真的",
        "天哪",
        "天呐",
        "好吧",
    }
)
# Whole-message one-word answers (punctuation stripped).
_BRIEF: Final = frozenset(
    {
        "嗯",
        "嗯嗯",
        "嗯呢",
        "好",
        "好的",
        "好吧",
        "哦",
        "噢",
        "行",
        "是",
        "是的",
        "对",
        "对的",
        "没",
        "没有",
        "不",
        "不是",
        "还好",
        "可以",
        "知道了",
        "不知道",
        "随便",
        "算了",
        "也许",
        "可能吧",
        "ok",
        "okay",
    }
)
_GREETINGS: Final = frozenset(
    {
        "你好",
        "您好",
        "你好呀",
        "你好啊",
        "嗨",
        "哈喽",
        "hi",
        "hello",
        "在吗",
        "在不在",
        "你在吗",
        "你在不在",
        "早",
        "早上好",
        "晚上好",
        "下午好",
        "中午好",
        "晚安",
    }
)
_THANKS: Final = ("谢谢", "感谢", "多谢", "谢了", "thank", "thx")
_NOTE_CUES: Final = (
    "请帮我记住",
    "请帮我记一下",
    "帮我记一下",
    "帮我记住",
    "帮我记下",
    "帮我记着",
    "你记一下",
    "请记得",
    "请记住",
)
_NOTE_CUES_SEPARATED: Final = ("你记住", "记住", "记一下", "记下来")
_NOTE_SEPARATORS: Final = "：:，,、；; 　"
# A clause is addressed to the companion when, after these optional openers, it starts
# with one of _DIRECTIVES.
_OPENERS: Final = (
    "能不能",
    "可不可以",
    "那你",
    "你就",
    "现在",
    "可以",
    "麻烦",
    "拜托",
    "那",
    "就",
    "你",
    "您",
    "能",
    "请",
)
_DIRECTIVES: Final = (
    "再给我",
    "给我",
    "帮帮我",
    "帮我",
    "教教我",
    "教我",
    "带我",
    "陪我",
    "告诉我",
    "听我说",
    "听我讲",
    "别给",
    "别问",
    "别劝",
    "别管",
    "别说教",
    "不要给",
    "不要问",
    "不要劝",
    "不用给",
    "不用问",
    "不用劝",
    "再来一个",
    "换一个",
    "推荐",
)
_A_NOT_A: Final = (
    "是不是",
    "能不能",
    "可不可以",
    "有没有",
    "要不要",
    "会不会",
    "行不行",
    "好不好",
    "对不对",
    "算不算",
    "该不该",
    "用不用",
)
_QUESTION_ENDS: Final = (
    "是什么",
    "是啥",
    "什么意思",
    "啥意思",
    "怎么办",
    "为什么",
    "怎么样",
    "如何",
    "多少",
    "对吧",
    "是吧",
)
_QUESTION_PARTICLES: Final = ("吗", "嘛")
# Words ending in 么 that are not the question particle.
_NOT_PARTICLE_ME: Final = ("什么", "怎么", "那么", "这么", "多么", "要么")
_UNSURE: Final = ("不知道", "不清楚", "不明白", "说不清", "想知道", "在想", "考虑", "犹豫", "纠结")


def utterance_kind(user_text: str) -> Utterance:
    """What kind of message ``user_text`` is (see the module docstring)."""
    raw = _BATTERY_RE.sub("", user_text)
    text = raw.strip(_EDGE_PUNCT)
    if not _MEANINGFUL_RE.search(text):
        return Utterance.BRIEF
    if _is_note(text):
        return Utterance.NOTE
    if not _CJK_RE.search(text):
        if _plain(text).casefold() in _BRIEF | _GREETINGS:
            return Utterance.BRIEF if _plain(text).casefold() in _BRIEF else Utterance.GREETING
        if any(t in text.casefold() for t in _THANKS):
            return Utterance.THANKS
        return Utterance.FOREIGN
    plain = _plain(text)
    if plain in _GREETINGS:
        return Utterance.GREETING
    if plain in _BRIEF:
        return Utterance.BRIEF
    tags = [c.tag for sentence in _sentences(raw) for c in sentence]
    if _Tag.STATEMENT in tags:
        return Utterance.STATEMENT
    for tag, kind in (
        (_Tag.THANKS, Utterance.THANKS),
        (_Tag.REQUEST, Utterance.REQUEST),
        (_Tag.QUESTION, Utterance.QUESTION),
        (_Tag.GREETING, Utterance.GREETING),
    ):
        if tag in tags:
            return kind
    return Utterance.BRIEF


def mirror(user_text: str) -> str:
    """A ≤ 20-character, pronoun-safe second-person reflection of ``user_text``."""
    text = _BATTERY_RE.sub("", user_text)
    clauses = _pick_clauses(text)
    if not clauses:
        return FALLBACK_MIRROR
    conflict = _has_conflict("".join(clauses))
    out: list[str] = []
    for i, clause in enumerate(clauses):
        body = clause
        exclaimed = _exclamation(body)
        if exclaimed is not None:
            out.append(exclaimed)
            continue
        if conflict and i == 0:
            for lead in _LEADS:
                if body.startswith(lead) and len(body) > len(lead):
                    body = body[len(lead) :]
                    break
        body = _swap(body, conflict)
        if i == 0 and not body.startswith("你"):
            body = _lead(clause, body)
        out.append(body)
    return _trim(out)


# -- sentences and clauses ---------------------------------------------------------------


def _sentences(text: str) -> list[list[_Clause]]:
    """Tagged clauses per sentence, empty clauses dropped."""
    parts = _SENTENCE_END_RE.split(text)
    sentences: list[list[_Clause]] = []
    for i in range(0, len(parts), 2):
        body = parts[i].strip(_EDGE_PUNCT)
        end = parts[i + 1] if i + 1 < len(parts) else ""
        if not body:
            continue
        asked = "?" in end or "？" in end
        raw = [c.strip(_EDGE_PUNCT) for c in _CLAUSE_RE.split(body)]
        raw = [c for c in raw if c]
        tagged = [_Clause(c, _tag(c, asked=asked and j == len(raw) - 1)) for j, c in enumerate(raw)]
        sentences.append(tagged)
    return sentences


def _pick_clauses(text: str) -> list[str]:
    statements = [
        [c.text for c in sentence if c.tag is _Tag.STATEMENT] for sentence in _sentences(text)
    ]
    statements = [s for s in statements if s]
    if not statements:
        return []
    return next((s for s in statements if any(_speaks_first_person(c) for c in s)), statements[0])


def _tag(clause: str, *, asked: bool) -> _Tag:
    plain = _plain(clause).casefold()
    if plain in _FILLERS:
        return _Tag.FILLER
    if plain in _GREETINGS:
        return _Tag.GREETING
    if any(t in plain for t in _THANKS):
        return _Tag.THANKS
    if _directive(clause):
        return _Tag.REQUEST
    if asked or _question(clause):
        return _Tag.QUESTION
    return _Tag.STATEMENT


def _directive(clause: str) -> bool:
    head = clause
    stripped = True
    while stripped:
        stripped = False
        for opener in _OPENERS:
            rest = head[len(opener) :]
            if head.startswith(opener) and rest and not rest.startswith(("们", "人")):
                head = rest
                stripped = True
                break
    return head.startswith(_DIRECTIVES)


def _question(clause: str) -> bool:
    if any(word in clause for word in _UNSURE):
        return False
    if clause.endswith(_QUESTION_PARTICLES):
        return True
    if clause.endswith("么") and not clause.endswith(_NOT_PARTICLE_ME):
        return True
    if clause.endswith(_QUESTION_ENDS):
        return True
    return any(pattern in clause for pattern in _A_NOT_A)


def _is_note(text: str) -> bool:
    if text.startswith(_NOTE_CUES):
        return True
    for cue in _NOTE_CUES_SEPARATED:
        rest = text[len(cue) :]
        if text.startswith(cue) and rest and rest[0] in _NOTE_SEPARATORS:
            return True
    return False


def _plain(text: str) -> str:
    """``text`` with punctuation, symbols and spaces removed."""
    return "".join(ch for ch in text if ch.isalnum())


# -- pronouns ------------------------------------------------------------------------------


def _speaks_first_person(text: str) -> bool:
    plain = _strip_non_pronouns(text)
    return any(p in plain for p in _FIRST_PERSON)


def _has_conflict(text: str) -> bool:
    plain = _strip_non_pronouns(text).casefold()
    for word in _NOT_THIRD_PARTY:
        plain = plain.replace(word, "")
    return "你" in plain or "您" in plain or any(w in plain for w in _THIRD_PARTY)


def _strip_non_pronouns(text: str) -> str:
    for word in _NON_PRONOUN:
        text = text.replace(word, "")
    return text


def _lead(clause: str, body: str) -> str:
    """``body`` (the swapped ``clause``) made to start with 你.

    A clause that opens with a time word takes 你 in front when the user is not in the
    rest of it ("今天上班好累" -> "你今天上班好累", "上个月外婆也走了" -> "你上个月外婆
    也走了") or is its subject ("最近我老是失眠" -> "你最近老是失眠"); anything else is
    framed as the user's feeling ("你感到领导当众批评你").
    """
    word = next((w for w in _TIME_WORDS if clause.startswith(w)), None)
    if word is not None:
        rest = body[len(word) :]
        if not _speaks_first_person(clause[len(word) :]):
            return "你" + body
        if rest.startswith("你") and not rest.startswith("你们"):
            return "你" + word + rest[1:]
    return _FEEL_PREFIX + body


def _exclamation(clause: str) -> str | None:
    match = _EXCLAIM_RE.match(clause)
    if match is None:
        return None
    word = match.group(1)
    if not all(_CJK_RE.fullmatch(ch) for ch in word) or any(ch in "我你您咱他她" for ch in word):
        return None
    return _EXCLAIM_WORDS.get(word, f"你{word}坏了")


def _subject_is_me(clause: str) -> bool:
    """The clause opens with 我 as its subject, not as 我的/我们 or a possessor (我妈)."""
    if not clause.startswith("我") or clause.startswith(("我的", "我们")):
        return False
    return not _has_conflict(clause[1:3])


def _swap(clause: str, conflict: bool) -> str:
    """Swap pronouns in one clause, left to right, never rescanning swapped text."""
    out: list[str] = []
    subject_me = _subject_is_me(clause)
    seen_self = False
    i = 0
    while i < len(clause):
        if clause[i] not in _SWAP_STARTS:  # no word, pair or pronoun starts here
            out.append(clause[i])
            i += 1
            continue
        word = next((w for w in _NON_PRONOUN if clause.startswith(w, i)), None)
        if word is not None:
            out.append(word)
            i += len(word)
            continue
        for src, dst in (("我们", "你们"), ("咱们", "你们"), ("你们", "他们")):
            if clause.startswith(src, i):
                out.append(dst)
                i += len(src)
                break
        else:
            ch = clause[i]
            if ch in "你您":
                out.append("对方")
            elif ch == "我":
                owned = clause.startswith("我的", i) or clause.startswith("我自己", i)
                reflexive = (
                    not conflict
                    and subject_me
                    and seen_self
                    and not owned
                    and clause[:i].endswith(_REFLEXIVE_VERBS)
                )
                out.append("自己" if reflexive else "你")
                seen_self = True
            else:
                out.append(ch)
            i += 1
    return "".join(out)


# -- trimming ------------------------------------------------------------------------------


def _trim(clauses: list[str]) -> str:
    text = clauses[0]
    if len(text) > MAX_MIRROR:
        return _cut(text)
    for clause in clauses[1:]:
        candidate = f"{text}，{clause}"
        if len(candidate) > MAX_MIRROR:
            break
        text = candidate
    return text


def _cut(text: str) -> str:
    """The longest prefix of at most MAX_MIRROR characters that ends between words."""
    for end in range(MAX_MIRROR, 1, -1):
        before, after = text[end - 1], text[end]
        if _latin(before) and _latin(after):
            continue
        head = text[:end].rstrip()
        if len(head) > 1:
            return head
    return text[:MAX_MIRROR]


def _latin(char: str) -> bool:
    return char.isascii() and char.isalnum()
