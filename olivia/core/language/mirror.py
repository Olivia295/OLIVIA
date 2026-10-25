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
5. Exclamations "X死我了" become "你X坏了" ("气死我了" -> "你气坏了"). The phrase
   "想死你了" says how much the speaker misses someone (F6b): "你很想念对方", "你很想念
   他"; "想死我了" is the speaker's longing: "你盼了很久". A bare "想死" is never this phrase.
6. The result starts with 你, with at most one frame (F5b: "你感到" frames only a
   feeling or a view): as it is when the first clause already does; with 你 in front of a
   leading time word ("今天上班好累" -> "你今天上班好累") when that clause names nobody
   else; with a subject 我 in the middle brought to the front ("每次组会我都很紧张" ->
   "你每次组会都很紧张"). In a third-party conflict about the user it is the user's view
   ("你感到领导当众批评你", COLBO-01); a relative's news takes 你 ("外婆上个月走了" ->
   "你外婆上个月走了"), other news is reported ("你提到他走了"), and so is what someone
   else says or asks of the user (F6b: "爸妈总说让我别太累" -> "你爸妈总说让你别太累",
   "老板要求我周末加班" -> "你提到老板要求你周末加班", never "你感到老板要求…"). A
   view of someone else stays the user's view ("你感到她从来没夸过你"). Otherwise a feeling or
   state is "你感到…" ("活着好累" -> "你感到活着好累"), a clause that drops its subject
   takes 你 ("在美国读博第三年" -> "你在美国读博第三年"), and any other fact is reported
   ("你提到…"). Never "你感到每次组会你都…".
7. Trim to at most 20 characters at a clause boundary (，); a single over-long first clause
   is cut at the last boundary that does not split a Latin word. A clause the user repeats
   is mirrored once, and a filler at a clause's front ("就是", "其实") is dropped (F5b),
   as is a list opener ("首先", "其次", "总而言之"), which the output gate refuses (F14).

A message whose statements are only a goodbye for now ("今天就到这里吧", "我去睡了") is
CLOSING, and a one-character or one-word answer ("有") is BRIEF: neither is mirrored. A
clause that is only an acknowledgement ("好的", "行", "嗯好") is a filler, so "好的，拜拜"
is CLOSING, never "你感到好的" (F6b).

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
# F5b: a fact or someone else's news is reported, never framed as a feeling.
_SAID_PREFIX: Final = "你提到"


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
    CLOSING = "CLOSING"
    """Only a goodbye for now ("今天就到这里吧", "我去睡了"), F5b."""
    FOREIGN = "FOREIGN"
    """No Chinese at all (the mirror would only echo another language back)."""
    HAVEN_EXIT = "HAVEN_EXIT"
    """The words that leave the quiet company ("我好多了", "换个话题吧"; FSM-15, F10). Only
    the session sets it, on the turn that leaves S_haven on them; :func:`utterance_kind`
    never returns it."""


class _Tag(StrEnum):
    STATEMENT = "statement"
    QUESTION = "question"
    REQUEST = "request"
    GREETING = "greeting"
    THANKS = "thanks"
    CLOSING = "closing"
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
# "累死了" says the same about the speaker, for these words only (F5b).
_EXCLAIM_BARE_RE: Final = re.compile(r"^(累|烦|气|困|急|忙|吓|难受)死了$")
_EXCLAIM_WORDS: Final = {"烦": "你烦透了", "难受": "你难受极了"}
# "想死你了": missing someone very much, never a wish to die (F6b). The person is named
# after 死 and the clause ends with 了, so "我真的想死" or "想死了" never matches.
_MISSING_RE: Final = re.compile(
    r"^我?(?:真的?|好|可|太)?想死(你们|您们|他们|她们|大家|你|您|他|她|我)了[啊呀啦哦]*$"
)
_MISSED: Final = {"你": "对方", "您": "对方", "你们": "他们", "您们": "他们"}
_LONGING: Final = "你盼了很久"
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
    "明天",
    "后天",
    "今晚",
    "昨晚",
    "明晚",
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
        # F14: a list opener on its own ("首先，我……") is no statement either.
        "首先",
        "其次",
        "总而言之",
        "总之",
        # F6b: an acknowledgement clause ("好的，拜拜") is not a statement.
        "好",
        "好的",
        "好啊",
        "好呀",
        "好嘞",
        "嗯好",
        "行",
        "行吧",
        "可以",
        "收到",
        "知道了",
        "ok",
        "okay",
    }
)
# Fillers dropped from a clause's front ("就是想有人听我说说", F5b).
_LEAD_FILLERS: Final = (
    "怎么说呢",
    # F14: list openers, which the output gate refuses at a clause's front.
    "总而言之",
    "综上所述",
    "总的来说",
    "首先",
    "其次",
    "总之",
    "说真的",
    "就是",
    "其实",
    "然后",
    "反正",
    "嗯嗯",
    "嗯",
    "唉",
    "哎",
)
# Whole-message one-word answers (punctuation stripped).
_BRIEF: Final = frozenset(
    {
        "有",
        "有的",
        "有啊",
        "有吧",
        "会",
        "会的",
        "不会",
        "能",
        "不能",
        "还行",
        "一般",
        "一般般",
        "差不多",
        "没呢",
        "是啊",
        "对啊",
        "好啊",
        "好呀",
        "行吧",
        "嗯",
        "嗯嗯",
        "嗯呢",
        "好",
        "好的",
        "好吧",
        "好嘞",
        "嗯好",
        "收到",
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
# A clause that is only a goodbye for now (F5b): one of these at its end, once the
# trailing particles are dropped, with at most _CLOSING_SLACK characters in front.
_CLOSINGS: Final = (
    "就到这里",
    "先到这里",
    "到此为止",
    "聊到这里",
    "先这样",
    "不聊了",
    "下次再聊",
    "改天再聊",
    "晚点再聊",
    "回头再聊",
    "明天再聊",
    "先下了",
    "去睡了",
    "去睡觉了",
    "要睡了",
    "睡觉了",
    "想睡了",
    "下线了",
    "拜拜",
    "再见",
)
_CLOSING_PARTICLES: Final = "吧啦呀哦啊"
_CLOSING_SLACK: Final = 4
# Not a goodbye when the words in front negate it ("我不想睡觉了").
_CLOSING_NEGATIONS: Final = "不没别"
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
    # F5b: "褪黑素一次吃多少比较好", "那个人是谁来着".
    "比较好",
    "比较合适",
    "多少合适",
    "怎么做",
    "怎么弄",
    "咋办",
    "咋整",
    "为啥",
    "来着",
    "好呢",
    "什么时候",
    "多久",
)
_QUESTION_PARTICLES: Final = ("吗", "嘛")
# Words ending in 么 that are not the question particle.
_NOT_PARTICLE_ME: Final = ("什么", "怎么", "那么", "这么", "多么", "要么")
_UNSURE: Final = ("不知道", "不清楚", "不明白", "说不清", "想知道", "在想", "考虑", "犹豫", "纠结")
# F5b framing: only a clause with a feeling or a state ("活着好累", "心里堵得慌",
# "工作好多") may be framed "你感到…".
_FEELINGS: Final = (
    "累",
    "难过",
    "难受",
    "伤心",
    "委屈",
    "孤单",
    "孤独",
    "寂寞",
    "烦",
    "焦虑",
    "紧张",
    "害怕",
    "怕",
    "慌",
    "崩溃",
    "绝望",
    "无力",
    "迷茫",
    "失落",
    "压抑",
    "痛苦",
    "空虚",
    "没意思",
    "没劲",
    "撑不住",
    "受不了",
    "丢人",
    "丢脸",
    "愧疚",
    "内疚",
    "自责",
    "后悔",
    "生气",
    "郁闷",
    "不安",
    "疲惫",
    "无聊",
    "沮丧",
    "堵",
    "闷",
    "心酸",
    "心疼",
    "舍不得",
    "好受",
    "舒服",
    "开心",
    "高兴",
    "轻松",
    "踏实",
    "安心",
    "难熬",
    "煎熬",
)
# A degree word and a short predicate at the clause's end is a state ("工作好多").
_STATE_RE: Final = re.compile(
    r"(?:好|很|太|真|超|挺|蛮|特别|非常|有点|有些|越来越|那么|这么)[一-鿿]{1,4}[了啊呀哦的]?$"
)
# A clause that opens with one of these has dropped its subject, the user
# ("在美国读博第三年", "想有人听我说说"): 你 goes in front.
_SUBJECTLESS: Final = (
    "想",
    "不",
    "没",
    "又",
    "还",
    "也",
    "刚",
    "已经",
    "一直",
    "总",
    "老",
    "在",
    "要",
    "得",
    "会",
    "能",
    "一",
    "看到",
    "听到",
    "看着",
    "每次",
    "每天",
    "天天",
    "经常",
    "被",
    "怕",
    "担心",
    "希望",
    "睡",
    "吃不",
    "失眠",
    "哭",
    "加班",
    "考",
)
# A clause that opens with a view verb already frames itself: never "你感到觉得…".
_VIEW_VERBS: Final = ("总是觉得", "总觉得", "觉得", "感觉到", "感觉", "感到", "认为", "觉着")
# Of those, the ones that keep the user as subject when the user is also their object
# ("想有人听我说说" -> "你想有人听你说说", but "没人理我" -> "你感到没人理你").
_WANTING: Final = ("想", "希望", "怕", "担心", "看到", "听到", "看着")
# Relatives: their news takes 你 in front ("外婆上个月走了" -> "你外婆上个月走了").
_KIN: Final = (
    "外婆",
    "外公",
    "奶奶",
    "爷爷",
    "姥姥",
    "姥爷",
    "妈",
    "爸",
    "父母",
    "家里",
    "家人",
    "哥",
    "姐",
    "弟",
    "妹",
    "老公",
    "老婆",
    "孩子",
    "男朋友",
    "女朋友",
    "男友",
    "女友",
)
# Someone else's words to or about the user, at the clause's front (F6b): reported, never
# "你感到爸妈总说让你…". 让 counts only before an instruction ("让我别太累"), not as a
# cause ("他让我很失望" is a feeling); 说的/说话 are not a report.
_SPEECH_ADVERBS: Final = "总是|老是|一直|经常|常常|天天|每次都|总|老|又|还|也|都|就|非要|偏要|常"
_REPORTED_RE: Final = re.compile(
    "^(?:"
    + "|".join(sorted((w for w in _THIRD_PARTY if _CJK_RE.match(w)), key=len, reverse=True))
    + ")[妈爸哥姐弟妹们]?"
    + f"(?:{_SPEECH_ADVERBS})?"
    + "(?:跟我|对我|和我)?"
    + "(?:说(?!的|话)|叫|要求|劝|催|告诉"
    + "|让我?(?:别|不要|不许|不准|去|来|早点|赶紧|快|多|少|好好|必须|一定))"
)
# The character before 我 that makes it an object ("听我说", "把我逼疯", "对我很不满意").
_OBJECT_MARKERS: Final = frozenset(
    "把被让叫给对跟和同与向替为帮陪找听骂说问教逼管催烦怪打看理等带喊劝求夸爱恨疼懂害惹吵嫌评骗厌欢使令"
)
# The character after a subject 我 in the middle of a clause ("每次组会我都很紧张").
_SUBJECT_FOLLOWERS: Final = frozenset("都也就还又总一已真很好太特有不没会要是在才却常经老")


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
    if plain in _BRIEF or (len(plain) == 1 and not _feeling(plain)):
        return Utterance.BRIEF
    tags = [c.tag for sentence in _sentences(raw) for c in sentence]
    if _Tag.STATEMENT in tags:
        return Utterance.STATEMENT
    for tag, kind in (
        (_Tag.CLOSING, Utterance.CLOSING),
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
        missed = _missing(body)
        if missed is not None:
            out.append(missed)
            continue
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
            body = _lead(clause, body, conflict)
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
        raw = [_drop_lead_fillers(c.strip(_EDGE_PUNCT)) for c in _CLAUSE_RE.split(body)]
        raw = [c for c in raw if c]
        tagged = [_Clause(c, _tag(c, asked=asked and j == len(raw) - 1)) for j, c in enumerate(raw)]
        sentences.append(tagged)
    return sentences


def _drop_lead_fillers(clause: str) -> str:
    """``clause`` without the fillers at its front, unless that leaves nothing (F5b)."""
    stripped = True
    while stripped:
        stripped = False
        for filler in _LEAD_FILLERS:
            rest = clause[len(filler) :].lstrip(_EDGE_PUNCT)
            if clause.startswith(filler) and rest:
                clause = rest
                stripped = True
                break
    return clause


def _pick_clauses(text: str) -> list[str]:
    statements = [
        [c.text for c in sentence if c.tag is _Tag.STATEMENT] for sentence in _sentences(text)
    ]
    statements = [s for s in statements if s]
    if not statements:
        return []
    picked = next((s for s in statements if any(_speaks_first_person(c) for c in s)), statements[0])
    # A clause the user repeats ("最近真的很乱，最近真的很乱") is mirrored once (F5b).
    return list(dict.fromkeys(picked))


def _tag(clause: str, *, asked: bool) -> _Tag:
    plain = _plain(clause).casefold()
    if plain in _FILLERS:
        return _Tag.FILLER
    if plain in _GREETINGS:
        return _Tag.GREETING
    if any(t in plain for t in _THANKS):
        return _Tag.THANKS
    if _closing(plain):
        return _Tag.CLOSING
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


def _closing(plain: str) -> bool:
    """The clause (punctuation removed) is only a goodbye for now (F5b)."""
    bare = plain.rstrip(_CLOSING_PARTICLES)
    for phrase in _CLOSINGS:
        front = bare[: len(bare) - len(phrase)]
        if (
            bare.endswith(phrase)
            and len(front) <= _CLOSING_SLACK
            and not any(ch in _CLOSING_NEGATIONS for ch in front)
        ):
            return True
    return False


def _feeling(text: str) -> bool:
    """``text`` names a feeling or a state: only such a clause is "你感到…" (F5b)."""
    return any(word in text for word in _FEELINGS) or _STATE_RE.search(text) is not None


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


def _lead(clause: str, body: str, conflict: bool) -> str:
    """``body`` (the swapped ``clause``) made to start with 你, with at most one frame.

    A clause that opens with a time word takes 你 in front when the user is not in the
    rest of it ("今天上班好累" -> "你今天上班好累", "上个月外婆也走了" -> "你上个月外婆
    也走了") or is its subject ("最近我老是失眠" -> "你最近老是失眠"); so does a subject
    我 in the middle ("每次组会我都很紧张" -> "你每次组会都很紧张"). In a third-party
    conflict about the user the clause is the user's view ("你感到领导当众批评你",
    COLBO-01), but someone else's words are reported (F6b: "你爸妈总说让你别太累",
    "你提到老板要求你周末加班"); a relative's news takes 你 ("你外婆上个月走了"),
    other news is reported ("你提到他走了"). Otherwise (F5b): a feeling or state is
    "你感到…" ("你感到活着好累"), a clause that drops its subject takes 你
    ("你在美国读博第三年", "你想有人听你说说而已"), a clause about the user is still the
    user's view, and any other fact is reported ("你提到考研又没考上").
    """
    word = next((w for w in _TIME_WORDS if clause.startswith(w)), None)
    if word is not None:
        rest = body[len(word) :]
        if not _speaks_first_person(clause[len(word) :]):
            return "你" + body
        if rest.startswith("你") and not rest.startswith("你们"):
            return "你" + word + rest[1:]
    fronted = _front_subject(clause, body)
    if fronted is not None:
        return fronted
    if _REPORTED_RE.match(clause):
        return ("你" if clause.startswith(_KIN) else _SAID_PREFIX) + body
    about_user = bool(_me_positions(clause))
    view = next((v for v in _VIEW_VERBS if clause.startswith(v) and len(body) > len(v)), None)
    if view is not None:
        # "觉得好孤单" -> "你觉得好孤单"; "觉得他不爱我了" -> "你感到他不爱你了".
        return _FEEL_PREFIX + body[len(view) :] if conflict and about_user else "你" + body
    if conflict:
        if about_user:
            return _FEEL_PREFIX + body
        if clause.startswith(_KIN) or clause.startswith(_SUBJECTLESS):
            return "你" + body
        if _feeling(clause):
            return _FEEL_PREFIX + body
        return _SAID_PREFIX + body
    if _feeling(clause) and not about_user:
        return _FEEL_PREFIX + body
    if clause.startswith(_SUBJECTLESS) and not about_user:
        return "你" + body
    if about_user and _only_object_me(clause) and clause.startswith(_WANTING):
        return "你" + body
    if about_user:
        return _FEEL_PREFIX + body
    return _SAID_PREFIX + body


def _me_positions(clause: str) -> list[int]:
    """Where the pronoun 我 stands in ``clause`` (not 我们 or a word like 自我)."""
    found: list[int] = []
    i = 0
    while i < len(clause):
        word = next((w for w in _NON_PRONOUN if clause.startswith(w, i)), None)
        if word is not None:
            i += len(word)
            continue
        if clause.startswith("我们", i):
            i += 2
            continue
        if clause[i] == "我":
            found.append(i)
        i += 1
    return found


def _only_object_me(clause: str) -> bool:
    """Every 我 in ``clause`` is someone's object ("听我说说", "把我逼疯")."""
    return all(i > 0 and clause[i - 1] in _OBJECT_MARKERS for i in _me_positions(clause))


def _front_subject(clause: str, body: str) -> str | None:
    """The one subject 我 in the middle of ``clause`` brought to the front ("每次组会我
    都很紧张" -> "你每次组会都很紧张"); None when there is no such 我."""
    positions = _me_positions(clause)
    if len(positions) != 1 or len(clause) != len(body):
        return None
    i = positions[0]
    if i == 0 or i + 1 >= len(clause) or clause[i - 1] in _OBJECT_MARKERS:
        return None
    if clause[i + 1] not in _SUBJECT_FOLLOWERS or _has_conflict(clause[:i]):
        return None
    if body[i] != "你":
        return None
    return "你" + body[:i] + body[i + 1 :]


def _missing(clause: str) -> str | None:
    """The "想死你了" phrase: "你很想念对方"; "想死我了": "你盼了很久" (F6b); else None."""
    match = _MISSING_RE.match(clause)
    if match is None:
        return None
    who = match.group(1)
    if who == "我":
        return _LONGING
    return "你很想念" + _MISSED.get(who, who)


def _exclamation(clause: str) -> str | None:
    match = _EXCLAIM_RE.match(clause) or _EXCLAIM_BARE_RE.match(clause)
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
