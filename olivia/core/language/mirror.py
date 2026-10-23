"""Pronoun-safe mirroring (COLBO-01, SDD §4.1).

``mirror(user_text)`` turns the user's own words into a short second-person clause for the
``{mirror}`` slot (templates wrap it, e.g. "听起来，{mirror}。").

1. Pick the first sentence that speaks in the first person (else the first sentence) and,
   inside it, start at the first clause that does.
2. Self-talk (no 你/您 and no third party): flip the first-person main clause.
   我 -> 你 for the first 我 in a clause, later ones -> 自己; 我的 -> 你的; 我们/咱们 -> 你们.
   "我觉得我很失败" -> "你觉得自己很失败".
3. Third-party conflict (the clause names 你/您, 你们 or another person such as 伴侣、领导):
   never flip mechanically. 你/您 -> 对方, 你们 -> 他们, every 我 -> 你, a leading
   "我觉得/我感觉…" is dropped, and the clause is framed as the user's feeling ("你感到…")
   unless it already starts with 你.
   "我觉得你根本不在乎我" -> "你感到对方根本不在乎你" (never "你觉得我不在乎你").
4. Trim to at most 20 characters at a clause boundary (，、：；); a single over-long first
   clause is cut at 20 characters.

The result never contains the pronoun 我 (words like 自我 are kept as written) and always
starts with 你.
"""

from __future__ import annotations

import re
from typing import Final

MAX_MIRROR: Final = 20
FALLBACK_MIRROR: Final = "你心里装着不少事"
_FEEL_PREFIX: Final = "你感到"

_BATTERY_RE: Final = re.compile(r"^\s*[\[［【]\s*\d{1,3}\s*[%％]\s*[\]］】]\s*")
_SENTENCE_RE: Final = re.compile(r"[。！？!?\n…；;]+")
_CLAUSE_RE: Final = re.compile(r"[，,、：:]+")
_EDGE_PUNCT: Final = " \t　～~。，,、！？!?；;：:…“”\"'‘’（）()"
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
    "领导",
    "老板",
    "上司",
    "同事",
    "主管",
    "经理",
    "妈妈",
    "爸爸",
    "母亲",
    "父亲",
    "爸妈",
    "父母",
    "家人",
    "家里人",
    "孩子",
    "朋友",
    "室友",
    "同学",
    "老师",
)
_NOT_THIRD_PARTY: Final = ("其他", "其她")


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
        if conflict and i == 0:
            for lead in _LEADS:
                if body.startswith(lead) and len(body) > len(lead):
                    body = body[len(lead) :]
                    break
        body = _swap(body, conflict)
        if i == 0 and not body.startswith("你"):
            body = _FEEL_PREFIX + body
        out.append(body)
    return _trim(out)


def _pick_clauses(text: str) -> list[str]:
    sentences = [s.strip(_EDGE_PUNCT) for s in _SENTENCE_RE.split(text)]
    sentences = [s for s in sentences if s]
    if not sentences:
        return []
    chosen = next((s for s in sentences if _speaks_first_person(s)), sentences[0])
    clauses = [c.strip(_EDGE_PUNCT) for c in _CLAUSE_RE.split(chosen)]
    clauses = [c for c in clauses if c]
    start = next((i for i, c in enumerate(clauses) if _speaks_first_person(c)), 0)
    return clauses[start:]


def _speaks_first_person(text: str) -> bool:
    plain = _strip_non_pronouns(text)
    return any(p in plain for p in _FIRST_PERSON)


def _has_conflict(text: str) -> bool:
    plain = _strip_non_pronouns(text)
    for word in _NOT_THIRD_PARTY:
        plain = plain.replace(word, "")
    return "你" in plain or "您" in plain or any(w in plain for w in _THIRD_PARTY)


def _strip_non_pronouns(text: str) -> str:
    for word in _NON_PRONOUN:
        text = text.replace(word, "")
    return text


def _swap(clause: str, conflict: bool) -> str:
    """Swap pronouns in one clause, left to right, never rescanning swapped text."""
    out: list[str] = []
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
                # 我的/我自己 and every 我 in a conflict clause become 你; in self-talk only
                # the first 我 of a clause does, later ones become 自己.
                owned = clause.startswith("我的", i) or clause.startswith("我自己", i)
                out.append("你" if owned or conflict or not seen_self else "自己")
                seen_self = True
            else:
                out.append(ch)
            i += 1
    return "".join(out)


def _trim(clauses: list[str]) -> str:
    text = clauses[0]
    if len(text) > MAX_MIRROR:
        return text[:MAX_MIRROR]
    for clause in clauses[1:]:
        candidate = f"{text}，{clause}"
        if len(candidate) > MAX_MIRROR:
            break
        text = candidate
    return text
