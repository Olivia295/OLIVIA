"""Pronoun-safe mirroring (COLBO-01, SDD §4.1) and utterance kinds (F3)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from olivia.core.language import LanguageEngine, mirror
from olivia.core.language.mirror import FALLBACK_MIRROR, MAX_MIRROR, Utterance, utterance_kind

NON_PRONOUN = ("你死我活", "自我", "忘我", "无我", "唯我", "敌我", "你我")

# The swap table (F3 asks for at least 40 cases, the hands-on examples included).
SWAP_TABLE = [
    # SDD §4.1 / COLBO-01: never "你觉得我不在乎你".
    ("我觉得你根本不在乎我", "你感到对方根本不在乎你"),
    # First-person main clause: flip; a later 我 that the subject does something to
    # (觉得/恨/讨厌 ... 我) becomes 自己.
    ("我觉得我很失败", "你觉得自己很失败"),
    ("我对我自己很失望", "你对你自己很失望"),
    ("我丢了我的工作", "你丢了你的工作"),
    ("我们家总是吵架", "你们家总是吵架"),
    ("我讨厌我这样", "你讨厌自己这样"),
    ("我恨我", "你恨自己"),
    ("我总觉得我做什么都不对", "你总觉得自己做什么都不对"),
    # Third-party conflict: humanistic framing, no mechanical flip.
    ("领导当着大家的面批评我", "你感到领导当着大家的面批评你"),
    ("我觉得他不爱我了", "你感到他不爱你了"),
    ("我老公从来不听我说话", "你老公从来不听你说话"),
    ("你们都不懂我", "你感到他们都不懂你"),
    ("您根本不在乎我的感受", "你感到对方根本不在乎你的感受"),
    ("我觉得你们只是在敷衍我", "你感到他们只是在敷衍你"),
    # F3: a possessed relative is the subject, so the object 我 is 你, never 自己.
    ("我妈今天又打电话骂我", "你妈今天又打电话骂你"),
    ("我爸从来不夸我", "你爸从来不夸你"),
    ("我姐总拿我跟别人比", "你姐总拿你跟别人比"),
    ("外婆以前最疼我", "你感到外婆以前最疼你"),
    ("她从来没夸过我", "你感到她从来没夸过你"),
    ("没人理我", "你感到没人理你"),
    # F3: "V死我了" is an exclamation about the speaker.
    ("气死我了", "你气坏了"),
    ("累死我了", "你累坏了"),
    ("烦死我了", "你烦透了"),
    # F3: a clause addressed to the companion is dropped, the rest is mirrored.
    ("你别给我建议，我只想说说话", "你只想说说话"),
    ("我不需要建议，你听我说就好", "你不需要建议"),
    ("你知道吗，我今天被骂了", "你今天被骂了"),
    ("说出来好受一点了，谢谢", "你感到说出来好受一点了"),
    # Not a pronoun.
    ("我总在自我怀疑", "你总在自我怀疑"),
    ("其他事我都还好", "你感到其他事你都还好"),
    # Sentence and clause choice, battery prefix, fillers.
    ("唉。我真的好累", "你真的好累"),
    ("唉，我真的好累", "你真的好累"),
    ("[5%] 好累", "你感到好累"),
    ("工作好多", "你感到工作好多"),
    ("嗯，好一点了", "你感到好一点了"),
    # F3: a leading time word takes 你 in front instead of 你感到.
    ("今天上班好累", "你今天上班好累"),
    ("最近搬家，事情好多", "你最近搬家，事情好多"),
    ("总是睡不着", "你总是睡不着"),
    ("最近我老是失眠", "你最近老是失眠"),
    ("上个月外婆也走了", "你上个月外婆也走了"),
    ("今天领导又当众批评我", "你感到今天领导又当众批评你"),
    # Trim at a clause boundary.
    ("我最近总是睡不着，一闭眼就想到工作上的事情，越想越心慌", "你最近总是睡不着"),
    ("我很累，也很烦，不想说话", "你很累，也很烦，不想说话"),
    ("我们分手了，在一起五年", "你们分手了，在一起五年"),
    # F3: English words are never cut in the middle.
    ("今天被 manager 骂了，说我的 deck 做得很 sloppy", "你今天被 manager 骂了"),
    ("我的 presentation 被 manager 说得一无是处", "你的 presentation 被"),
]


@pytest.mark.parametrize(("user_text", "expected"), SWAP_TABLE)
def test_mirror_cases(user_text: str, expected: str) -> None:
    assert mirror(user_text) == expected


def test_swap_table_is_large_enough() -> None:
    assert len(SWAP_TABLE) >= 40


@pytest.mark.parametrize(
    "user_text",
    ["我妈今天又打电话骂我", "她骂我", "老板又在群里点我的名", "爸妈不理解我", "朋友都不找我"],
)
def test_object_me_is_never_yourself_when_someone_else_acts(user_text: str) -> None:
    assert "自己" not in mirror(user_text)


def test_conflict_never_flips_into_the_agent() -> None:
    out = mirror("我觉得你根本不在乎我")
    assert "我" not in out
    assert out != "你觉得我根本不在乎你"
    assert "对方" in out


@pytest.mark.parametrize("user_text", ["", "   ", "。。。", "……", "[5%]", "你别给我建议"])
def test_nothing_to_mirror_uses_the_fallback(user_text: str) -> None:
    assert mirror(user_text) == FALLBACK_MIRROR


def test_long_single_clause_is_cut_to_the_limit() -> None:
    out = mirror("我" + "非常" * 20 + "累")
    assert len(out) == MAX_MIRROR
    assert out.startswith("你")


@pytest.mark.parametrize(
    "user_text",
    [
        "I just feel so tired of everything",
        "今天被 manager 骂了说我的 deck 做得很 sloppy 真的很 down",
        "我的 presentation 被 manager 说得一无是处",
        "我想 quit 这份 job 了真的 so tired",
    ],
)
def test_latin_words_are_kept_whole(user_text: str) -> None:
    out = mirror(user_text)
    words = {w.casefold() for w in user_text.split()}
    for token in out.replace("，", " ").split():
        latin = "".join(ch for ch in token if ch.isascii() and ch.isalpha())
        if latin and token.isascii():
            assert latin.casefold() in words, (user_text, out)


@pytest.mark.parametrize(
    ("user_text", "kind"),
    [
        ("今天上班好累", Utterance.STATEMENT),
        ("我妈今天又打电话骂我", Utterance.STATEMENT),
        ("你别给我建议，我只想说说话", Utterance.STATEMENT),
        ("嗯，好一点了", Utterance.STATEMENT),
        ("我都不知道自己在坚持什么", Utterance.STATEMENT),
        ("我不知道该怎么办", Utterance.STATEMENT),
        ("说出来好受一点了，谢谢", Utterance.STATEMENT),
        ("CBT是什么？能教我做一下吗", Utterance.REQUEST),
        ("能带我做一下正念吗", Utterance.REQUEST),
        ("再给我一个别的方法吧", Utterance.REQUEST),
        ("现在可以给我一个方法吗", Utterance.REQUEST),
        ("你别给我建议", Utterance.REQUEST),
        ("有没有什么办法能让我先缓一缓", Utterance.QUESTION),
        ("你觉得我是不是抑郁症", Utterance.QUESTION),
        ("褪黑素一次吃多少比较好？", Utterance.QUESTION),
        ("冥想有用吗", Utterance.QUESTION),
        ("CBT是什么", Utterance.QUESTION),
        ("谢谢你一直在", Utterance.THANKS),
        ("今天谢谢你", Utterance.THANKS),
        ("谢谢你听我说", Utterance.THANKS),
        ("你好", Utterance.GREETING),
        ("在吗", Utterance.GREETING),
        ("记住：周四下午要去见搬家公司的人", Utterance.NOTE),
        ("帮我记一下明天交报告", Utterance.NOTE),
        ("嗯", Utterance.BRIEF),
        ("好", Utterance.BRIEF),
        ("……", Utterance.BRIEF),
        ("😭😭😭", Utterance.BRIEF),
        ("I just feel so tired of everything", Utterance.FOREIGN),
    ],
)
def test_utterance_kinds(user_text: str, kind: Utterance) -> None:
    assert utterance_kind(user_text) is kind


_ALPHABET = st.sampled_from(
    list("我你您们他她的觉得很累想说不在乎老板妈妈自己，。！？ 自我好吗谢死了ab")
)


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet=_ALPHABET, max_size=60))
def test_mirror_invariants(user_text: str) -> None:
    out = mirror(user_text)
    assert 0 < len(out) <= MAX_MIRROR
    assert out.startswith("你")
    plain = out
    for word in NON_PRONOUN:
        plain = plain.replace(word, "")
    assert "我" not in plain, (user_text, out)
    assert "您" not in out


def test_safe_mirror_hides_diagnosis_and_numbers(engine: LanguageEngine) -> None:
    assert engine.safe_mirror("我有抑郁症") == FALLBACK_MIRROR
    assert engine.safe_mirror("我的电话是13800138000") == FALLBACK_MIRROR
    assert engine.safe_mirror("我在学接纳承诺疗法") == FALLBACK_MIRROR
    assert engine.safe_mirror("我觉得我很失败") == "你觉得自己很失败"


@pytest.mark.parametrize(
    "user_text",
    [
        "谢谢你一直在",
        "你好",
        "嗯",
        "CBT是什么",
        "能带我做一下正念吗",
        "记住：我妈生日是11月3号",
        "I just feel so tired of everything",
        "你别给我建议",
    ],
)
def test_non_statements_get_a_short_acknowledgement(engine: LanguageEngine, user_text: str) -> None:
    out = engine.safe_mirror(user_text)
    assert out.startswith("你")
    assert len(out) <= MAX_MIRROR
    assert "感到" not in out
    assert out == engine.safe_mirror(user_text)  # deterministic, no random draw
    assert out in {line for lines in engine.data.utterances.acks.values() for line in lines}
