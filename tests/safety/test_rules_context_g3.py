"""Task G3 (2026-11-25): the context gaps metamorphic testing found across clauses and
sentences (tests/safety/metamorphic.py, scripts/metamorphic_report.py).

* A clause that names nobody keeps the subject of the clause before it, but never across
  the end of a sentence (。！？!?… or a line break): "室友今天搬走了。遗书已经写好了" is the
  user's own plan. Inside one sentence (a comma) the subject still carries over: "我朋友
  最近很难过，总说要自杀" stays someone else's.
* For an entry whose ``unless`` reaches across clauses, another sentence's words do not
  void a match whose other parts (the ``also`` groups) are all in its own sentence (室友今天
  搬走了。我想死，今晚就动手); when the death is named only in the other sentence (我弟弟
  不想活了。我今晚就走) they still do.
* The whitespace the text was typed with ends a clause for the subject, ``leading``,
  ``trailing`` and clause-bound ``unless`` checks (我想过死 不止一次), but two parts still
  join across it and a negator still reaches across it (我打算 今晚 去死, 我没有 想死).
* ``trailing`` ignores emoji, other symbols, punctuation and emote codes after the match.
* A message said twice over: nothing spans the place where one copy meets the next.

Every sentence here was written for this task (the metamorphic seeds stay in their own
files); none is from an evaluation set or the red-team suite.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.normalize import clause_breaks, normalize, repeat_copy, spans_copies
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)
NOW = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)


def _ids(text: str) -> set[str]:
    return set(SCREEN.assess(text).cue_ids)


def _composed(text: str) -> set[str]:
    index = SCREEN._index
    return {hit.entry.id for hit in index.compose(normalize(text), clause_breaks(text))}


def _session() -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(3), now=lambda: NOW, student=False)


# --- normalize.clause_breaks and repeat_junctions --------------------------------------


@pytest.mark.parametrize(
    ("text", "breaks"),
    [
        ("今天加班到九点 我们正在吃饭", ((7, False),)),
        ("今天加班到九点\n我们正在吃饭", ((7, True),)),
        ("今天加班到九点\r\n 我们正在吃饭", ((7, True),)),
        ("今天加班到九点　我们正在吃饭", ((7, False),)),
        ("好累 真的 好累", ((2, False), (4, False))),
        # Letter spacing and one-character words are no break.
        ("我 想 死", ()),
        ("我想 死", ()),
        # The spaces of English words are no break; one next to Chinese is.
        ("i want to go home", ()),
        ("最近真的好想 sui 了", ((6, False),)),
        # Whitespace around a word of invisible characters alone is one run.
        ("好累​ ​ 今天", ((2, False),)),
        # A stray letter between two Han characters is dropped before the break is placed.
        ("我们a 今天走", ((2, False),)),
        ("今天好累", ()),
        ("", ()),
    ],
)
def test_clause_breaks(text: str, breaks: tuple[tuple[int, bool], ...]) -> None:
    assert clause_breaks(text) == breaks
    for position, _ in breaks:
        assert 0 < position < len(normalize(text))


@pytest.mark.parametrize(
    ("normalized", "copy"),
    [
        ("药钱我都攒够了药钱我都攒够了", 7),
        ("今天好累啊今天好累啊今天好累啊", 5),
        ("abcabcabcabc", 6),
        ("zs" * 1000, 4),
        # A word said over is no message said twice.
        ("哈哈哈哈", 0),
        ("去死去死", 0),
        ("我想死我想死", 0),
        ("今天好累啊今天好累", 0),
        ("", 0),
    ],
)
def test_repeat_copy(normalized: str, copy: int) -> None:
    assert repeat_copy(normalized) == copy


@pytest.mark.parametrize(
    ("start", "end", "spans"),
    [(5, 9, True), (6, 8, True), (0, 7, False), (7, 14, False), (8, 13, False), (6, 7, False)],
)
def test_spans_copies(start: int, end: int, spans: bool) -> None:
    # Two copies of seven characters: they meet at 7.
    assert spans_copies(start, end, 7, 14) is spans
    assert not spans_copies(start, end, 0, 14)


# --- the subject is not carried over the end of a sentence -----------------------------

OWN_AFTER_SENTENCE = [
    ("闺蜜下午来过了。干脆去死好了", L.L2, "L2_INTENT_ACT"),
    ("同学都去聚餐了……不如自杀算了", L.L2, "L2_INTENT_ACT"),
    ("老板今天又骂人了！遗书已经写好了", L.L3, "S1_NOTE_PREPARED"),
    ("室友今天搬走了\n遗言都想好了", L.L3, "S1_NOTE_PREPARED"),
    ("妹妹明天要回家？真希望睡着就不要醒来了", L.L2, "L2_WISH_NO_WAKE"),
    ("邻居家在装修. 希望明天早上醒不过来", L.L2, "L2_WISH_NO_WAKE"),
]


@pytest.mark.parametrize(("text", "level", "cue"), OWN_AFTER_SENTENCE)
def test_a_sentence_naming_nobody_is_the_users_own(text: str, level: L, cue: str) -> None:
    result = SCREEN.assess(text)
    assert result.level is level, (text, result)
    assert cue in result.cue_ids, (text, result)


@pytest.mark.parametrize(
    ("text", "cue"),
    [
        ("我朋友最近很难过，总说要自杀", "L2_INTENT_ACT"),
        ("我表哥最近很消沉，真希望睡着就不要醒来了", "L2_WISH_NO_WAKE"),
        ("同事这几天很不对劲，干脆去死好了", "L2_INTENT_ACT"),
    ],
)
def test_the_subject_still_carries_over_a_comma(text: str, cue: str) -> None:
    assert cue not in _composed(text), text
    assert SCREEN.assess(text).level < L.L2, text


# --- another sentence's words do not void a plan said whole in its own sentence ---------


@pytest.mark.parametrize(
    "text",
    [
        "室友今天搬走了。我想死，今晚就动手",
        "她今天跟我吵架了。我不想活了，今晚就走",
        "我妈刚打电话来了。我真的想自杀，周末就去做",
        "同事都下班了！我要自杀，时间定在周六晚上",
    ],
)
def test_a_plan_said_whole_in_its_sentence_stands(text: str) -> None:
    result = SCREEN.assess(text)
    assert result.level is L.L3 and result.stage == "STAGE1", (text, result)


@pytest.mark.parametrize(
    "text",
    [
        "我弟弟不想活了。我今晚就走",
        "朋友试图自杀。我现在就去",
        "我妈说她不想活了。我今晚就回去",
    ],
)
def test_a_death_named_only_with_someone_else_still_voids(text: str) -> None:
    assert SCREEN.assess(text).level < L.L3, text


# --- whitespace ends a clause for the clause-bound checks ------------------------------


@pytest.mark.parametrize(
    ("text", "cue"),
    [
        # trailing: the words after the space are a clause of their own.
        ("我想过死 好几次了", "L2_THOUGHT_OF_DYING"),
        ("我有时候会想到死 每天都是", "L2_THOUGHT_OF_DYING"),
        ("说实话我宁愿死 活着太累了", "L2_RATHER_DIE"),
        # a clause-bound unless: an everyday word before the space is another clause's.
        ("公司又裁员了 哪天突然死了，我也觉得没什么不好", "L2_DEATH_ACCEPTED"),
        ("手机又摔坏了 死掉对我来说不是一件坏事", "L2_DEATH_ACCEPTED"),
        # the subject: the listener of the clause before the space is not carried over.
        ("谢谢你陪了这么久 准备去死了", "L2_INTENT_ACT"),
        ("谢谢你一直都在 不如自杀算了", "L2_INTENT_ACT"),
    ],
)
def test_whitespace_ends_a_clause(text: str, cue: str) -> None:
    result = SCREEN.assess(text)
    assert result.level >= L.L2 and cue in result.cue_ids, (text, result)
    # The same sentence typed with a comma reads the same.
    comma = text.replace(" ", "，", 1)
    assert cue in _ids(comma), comma


def test_the_compositions_are_kept_apart_by_their_whitespace() -> None:
    # Two texts that fold to the same string but were typed with and without a space: the
    # remembered compositions of one are never the other's.
    for _ in range(2):
        assert SCREEN.assess("我想过死 不止一次").level is L.L2
        assert SCREEN.assess("我想过死不止一次").level is L.L0


@pytest.mark.parametrize(
    ("text", "level"),
    [
        # Two parts still join across the spaces of one clause typed word by word.
        ("我打算 今晚 去死", L.L3),
        ("遗书 已经写好了", L.L3),
        ("我已经 计划好了 明天去死", L.L3),
        ("我打算 下周 结束这一切", L.L3),
    ],
)
def test_parts_still_join_across_whitespace(text: str, level: L) -> None:
    assert SCREEN.assess(text).level is level, text


@pytest.mark.parametrize("text", ["我没有 想死", "我才不会 去死", "我从来没 想过自杀"])
def test_a_negator_still_reaches_across_whitespace(text: str) -> None:
    assert SCREEN.assess(text).level < L.L2, text


# --- trailing ignores decorations --------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("我有时候会想到死😭", L.L2),
        ("说实话，我宁愿死[哭]", L.L2),
        ("我想死，今晚就动手😮‍💨", L.L3),
        ("我不想活了，就这周五晚上——", L.L3),
        ("我真的想自杀，周末就去做[捂脸][捂脸]", L.L3),
        ("我决定好了，今晚十二点【捂脸】", L.L1),
        ("我已经想好了，就今晚吧🙃", L.L1),
    ],
)
def test_trailing_ignores_emoji_and_emote_codes(text: str, level: L) -> None:
    result = SCREEN.assess(text)
    assert result.level is level, (text, result)
    if level is L.L1:
        assert result.asks_intent, (text, result)


@pytest.mark.parametrize(
    "text",
    [
        "我决定好了，今晚十二点去看电影😭",
        "我已经想好了，就今晚去吃火锅[哭]",
        "我准备好了，就这周五出发去旅行🙃",
    ],
)
def test_trailing_still_refuses_words_after_a_decoration(text: str) -> None:
    result = SCREEN.assess(text)
    assert result.level is L.L0 and not result.asks_intent, (text, result)


# --- a message said twice over ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("我想死，今晚就动手 我想死，今晚就动手", L.L3),
        ("遗书已经写好了 遗书已经写好了", L.L3),
        ("干脆去死好了 干脆去死好了", L.L2),
        ("我有时候会想到死 我有时候会想到死", L.L2),
    ],
)
def test_a_message_said_twice_keeps_its_level(text: str, level: L) -> None:
    assert SCREEN.assess(text).level is level, text


def test_nothing_spans_the_place_where_the_copies_meet() -> None:
    once = "药钱我都攒够了"
    assert SCREEN.assess(once).level is L.L0
    for twice in (f"{once} {once}", f"{once}{once}", f"{once}\n{once}\n{once}"):
        assert SCREEN.assess(twice).level is L.L0, twice


# --- worry about someone else, said over two sentences (§9.4 item 8) --------------------


@pytest.mark.parametrize(
    "text",
    [
        "我朋友最近很难过。她总跟我说不想活了，我该怎么劝她",
        "我弟这几天一直把自己关在房间里。他说活着没意思，我该怎么开口",
        "室友半夜在哭。她跟我说她想死，我明天该怎么跟她聊",
    ],
)
def test_worry_about_someone_else_over_two_sentences(text: str) -> None:
    result = _session().turn(text)
    assert not result.in_crisis, (text, result.reply_kind)
    assert result.crisis_level < L.L2, (text, result.crisis_level)
    assert result.reply_kind in {ReplyKind.RESOURCES, ReplyKind.NORMAL, ReplyKind.CARD}
