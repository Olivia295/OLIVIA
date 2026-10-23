"""The introspector (decision D4, step C2): lexicon, reading, mirror answers and lines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate
from olivia.core.models import CrisisLevel, HelpStage, PerceptionContext
from olivia.core.perception.introspector import (
    MAX_SCHEMAS,
    IntrospectionLexiconError,
    Introspector,
    MirrorAnswer,
    MirrorStatus,
    SchemaMirror,
    load_introspection_lexicon,
    load_mirror_lines,
    read_mirror_answer,
    shame_spiral,
)
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_introspection_lexicon(TAX)
READER = Introspector(LEX)
LINES = load_mirror_lines(TAX)
DATA = Path(__file__).resolve().parents[2] / "olivia" / "data"

# Every id: at least two messages that must show it and two hard negatives that must not
# (shared words, a negation, or the ordinary version of the same topic).
DISTORTIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ALL_OR_NOTHING": (
        ("我总觉得要么完美要么就是失败，没有中间", "考试不是满分就是失败，我一直这么想"),
        ("这次考试拿了满分，好开心", "其实不完美也没关系"),
    ),
    "CATASTROPHIZING": (
        ("报告交晚了，这下全完了", "要是被裁员，我的人生全完了"),
        ("这下全写完了，可以休息了", "天气预报说明天要下雨"),
    ),
    "OVERGENERALIZATION": (
        ("我总是搞砸，连这点小事都办不成", "感觉我什么事都做不好"),
        ("我总是搞不清楚地铁线路", "这件事我做不好，想请教一下"),
    ),
    "MIND_READING": (
        ("开会时说错话，他们肯定在背后笑我", "同事肯定觉得我没用吧"),
        ("他们在背后帮了我很多", "同事觉得我做得不错"),
    ),
    "FORTUNE_TELLING": (
        ("下周的面试肯定过不了", "我这次肯定会失败"),
        ("这次面试过了，挺高兴", "就算失败了也没关系"),
    ),
    "MENTAL_FILTER": (
        ("领导表扬了很多，我却只记得做错的那一点", "别人的夸奖都是客套，我知道"),
        ("领导表扬了我，挺开心的", "这一点我做错了，下次注意"),
    ),
    "EMOTIONAL_REASONING": (
        ("我这么害怕，说明这件事一定很危险", "我心里不安就说明肯定要出问题"),
        ("我有点害怕，想跟你说明一下情况", "这份说明书好难懂"),
    ),
    "SHOULD_STATEMENTS": (
        ("我应该做得更好的", "我不允许自己犯错"),
        ("我做得挺好的", "我在学着允许自己犯错"),
    ),
    "PERSONALIZATION": (
        ("项目延期都是我的错", "要不是因为我，他们也不会吵架"),
        ("这不是我的错，是系统出了问题", "这件事也不全怪我"),
    ),
}
SCHEMAS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "DEFECTIVENESS": (
        ("我总觉得自己不够好", "我一无是处，什么都做不成"),
        ("我不是一无是处的", "这个方案还不够好，再改改"),
    ),
    "UNRELENTING_STANDARDS": (
        ("做什么都必须做到完美", "我对自己要求太高了，差一点都不行"),
        ("这次做得挺完美的", "要求不高，完成就行"),
    ),
    "FEAR_OF_ABANDONMENT": (
        ("我很怕被抛弃", "我总担心他迟早会离开我"),
        ("他下个月要离开北京", "我不怕被抛弃了，现在挺好"),
    ),
    "MISTRUST_ABUSE": (
        ("谁都靠不住，只能靠自己", "别人对我好都是有目的的"),
        ("朋友很靠得住，帮了我很多", "他做这件事很有目的性"),
    ),
    "EMOTIONAL_DEPRIVATION": (
        ("从来没有人真正懂我", "从小到大没人真正关心过我"),
        ("妈妈很关心我的感受", "我的感受挺重要的，我会说出来"),
    ),
    "SOCIAL_ISOLATION": (
        ("在公司跟谁都格格不入", "总觉得自己是局外人"),
        ("这家店的装修有点格格不入", "我在新圈子里交到了朋友"),
    ),
    "DEPENDENCE_INCOMPETENCE": (
        ("离开别人我什么都做不了", "这件事我自己根本搞不定"),
        ("这件事我自己能搞定", "我一个人做了决定，感觉不错"),
    ),
    "VULNERABILITY_TO_HARM": (
        ("总觉得会有不好的事发生", "我肯定得了什么大病"),
        ("今天出门挺顺利的", "最近没什么不好的事发生"),
    ),
    "ENMESHMENT": (
        ("我妈不开心我就不能开心", "我的人生都是父母安排的"),
        ("周末陪我妈去逛街了", "父母安排了一顿家宴"),
    ),
    "SUBJUGATION": (
        ("我的意见不重要，听他们的就好", "我一直不敢拒绝别人"),
        ("我的意见他们都会认真听", "我拒绝了同事的加班请求"),
    ),
    "SELF_SACRIFICE": (
        ("我总是先照顾别人，自己的事往后放", "我习惯了把自己放在最后"),
        ("今天照顾了生病的朋友", "我把自己的事放在第一位"),
    ),
    "APPROVAL_SEEKING": (
        ("我很在意别人怎么看我", "一直在讨好别人，好累"),
        ("我不在意别人怎么看我", "别人怎么看是别人的事"),
    ),
    "NEGATIVITY_PESSIMISM": (
        ("我什么事都会往坏处想", "好事轮不到我"),
        ("最近有好事发生", "我尽量往好处想"),
    ),
    "EMOTIONAL_INHIBITION": (
        ("从小就觉得哭是软弱的表现", "我习惯把情绪都憋在心里"),
        ("看电影的时候哭了一场，舒服多了", "我会把情绪说出来"),
    ),
    "PUNITIVENESS": (
        ("我不配被原谅", "犯了错就该受惩罚"),
        ("他原谅了我，我很感动", "犯了错改过来就好"),
    ),
    "ENTITLEMENT_GRANDIOSITY": (
        ("凭什么要我排队", "规则不适用于我"),
        ("排队排了很久，有点累", "规则我都懂，会遵守"),
    ),
    "INSUFFICIENT_SELF_CONTROL": (
        ("我一点都管不住自己", "又控制不住自己乱花钱了"),
        ("我能管住自己", "这个月花钱很节制"),
    ),
    "CONDITIONAL_WORTH": (
        ("从小就觉得成绩好爸妈才会爱我", "如果不优秀就没人爱我"),
        ("爸妈很爱我", "我成绩一般但挺开心"),
    ),
    "REST_GUILT": (
        ("休息就有负罪感", "放假也不敢休息"),
        ("周末好好休息了一下", "放假去爬山了"),
    ),
    "FAILURE": (
        ("我就是个失败者", "同龄人都比我强"),
        ("失败了也没关系", "同龄人里我混得还行"),
    ),
}
YEARNINGS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "SAFETY": (("最近心里很不踏实", "我一直没有安全感"), ("家里很安全", "这个决定很踏实")),
    "ACCEPTANCE": (
        ("我只是想被接纳", "希望有人接受真实的我"),
        ("他接纳了我的建议", "我接受了这份工作"),
    ),
    "AUTONOMY": (("我想自己做决定", "我只想喘口气"), ("这个决定是大家一起做的", "跑完步喘得厉害")),
    "COMPETENCE": (
        ("我想证明自己可以", "真的很想要成就感"),
        ("这件事证明了数据是对的", "项目成功了"),
    ),
    "CONNECTION": (("其实就是想有人懂我", "我很想被看见"), ("我看见一只猫", "他懂很多东西")),
}


def _context(**overrides: Any) -> PerceptionContext:
    base = PerceptionContext(
        valence=-0.5,
        arousal=0.4,
        fine_grained_emotion="sadness",
        empathy_intent="VALIDATION",
        risk_level=CrisisLevel.L0,
        crisis_confidence=0.0,
        communication_stance="CONGRUENT",
        readiness_to_change=0.5,
        distress_vector={},
        detected_distortions=(),
        detected_schemas=(),
        deep_yearning="SAFETY",
        somatic_stabilization_eligible=False,
    )
    return replace(base, **overrides)


# -- coverage --------------------------------------------------------------------------------


def test_tables_cover_every_taxonomy_id():
    assert list(DISTORTIONS) == list(TAX.values("cognitive_distortions"))
    assert list(SCHEMAS) == list(TAX.values("schemas"))
    assert list(YEARNINGS) == list(TAX.values("satir_yearnings"))
    for table in (DISTORTIONS, SCHEMAS, YEARNINGS):
        for positives, negatives in table.values():
            assert len(positives) >= 2 and len(negatives) >= 2


def test_lexicon_covers_every_id_in_taxonomy_order():
    assert list(LEX.distortions) == list(TAX.values("cognitive_distortions"))
    assert list(LEX.schemas) == list(TAX.values("schemas"))
    assert list(LEX.yearnings) == list(TAX.values("satir_yearnings"))
    assert list(LEX.schema_yearnings) == list(TAX.values("schemas"))
    assert set(LEX.schema_yearnings.values()) <= set(TAX.values("satir_yearnings"))


@pytest.mark.parametrize("label,text", [(k, t) for k, (pos, _) in DISTORTIONS.items() for t in pos])
def test_distortion_positives(label, text):
    assert label in READER.read(text).distortions


@pytest.mark.parametrize("label,text", [(k, t) for k, (_, neg) in DISTORTIONS.items() for t in neg])
def test_distortion_hard_negatives(label, text):
    assert label not in READER.read(text).distortions


@pytest.mark.parametrize("label,text", [(k, t) for k, (pos, _) in SCHEMAS.items() for t in pos])
def test_schema_positives(label, text):
    assert label in READER.read(text).schemas


@pytest.mark.parametrize("label,text", [(k, t) for k, (_, neg) in SCHEMAS.items() for t in neg])
def test_schema_hard_negatives(label, text):
    assert label not in READER.read(text).schemas


@pytest.mark.parametrize("label,text", [(k, t) for k, (pos, _) in YEARNINGS.items() for t in pos])
def test_yearning_positives(label, text):
    assert READER.read(text).yearning == label


@pytest.mark.parametrize("label,text", [(k, t) for k, (_, neg) in YEARNINGS.items() for t in neg])
def test_yearning_hard_negatives(label, text):
    assert READER.read(text).yearning != label


@pytest.mark.parametrize(
    "text",
    [
        "今天上班好累",
        "周末想去公园散散步",
        "最近工作压力很大，有点焦虑，晚上总睡不着",
        "给我一个方法",
    ],
)
def test_ordinary_talk_shows_nothing(text):
    found = READER.read(text)
    assert (found.distortions, found.schemas, found.yearning) == ((), (), None)


# -- reading rules ---------------------------------------------------------------------------


def test_punctuation_does_not_split_a_phrase():
    assert "EMOTIONAL_REASONING" in READER.read("我这么害怕，说明……").distortions
    assert "EMOTIONAL_REASONING" in READER.read("我这么害怕说明").distortions


def test_traditional_script_is_folded():
    assert "DEFECTIVENESS" in READER.read("我覺得自己不夠好").schemas


def test_negation_follows_the_rule_stub():
    assert READER.read("我不是一无是处").schemas == ()
    # The second half of an A-not-A question does not negate.
    assert "DEFECTIVENESS" in READER.read("是不是我太没用了").schemas


def test_ids_keep_the_order_of_first_appearance():
    found = READER.read("同龄人都比我强，我就是个失败者，我一无是处")
    assert found.schemas == ("FAILURE", "DEFECTIVENESS")


def test_schemas_are_capped():
    text = "我一无是处，怕被抛弃，谁都靠不住，休息就有负罪感，好事轮不到我"
    found = READER.read(text)
    assert len(found.schemas) == MAX_SCHEMAS
    assert found.schemas == ("DEFECTIVENESS", "FEAR_OF_ABANDONMENT", "MISTRUST_ABUSE")


def test_yearning_with_most_hits_wins_then_the_earlier_one():
    assert READER.read("想被看见，想自己做决定，想有人懂我").yearning == "CONNECTION"
    assert READER.read("想自己做决定，想有人懂我").yearning == "AUTONOMY"


def test_yearning_falls_back_to_the_first_schema():
    assert READER.read("休息就有负罪感").yearning == "AUTONOMY"
    assert READER.read("我一无是处").yearning == "ACCEPTANCE"
    # A yearning phrase wins over the schema link.
    assert READER.read("我一无是处，好想有人懂我").yearning == "CONNECTION"


def test_apply_fills_the_context_and_keeps_the_default_without_evidence():
    filled = READER.apply("都是我的错，我一无是处", _context())
    assert filled.detected_distortions == ("PERSONALIZATION",)
    assert filled.detected_schemas == ("DEFECTIVENESS",)
    assert filled.deep_yearning == "ACCEPTANCE"
    empty = READER.apply("今天天气不错", _context(deep_yearning="SAFETY"))
    assert (empty.detected_distortions, empty.detected_schemas) == ((), ())
    assert empty.deep_yearning == "SAFETY"


# -- TOXIC_SHAME_SPIRAL ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"detected_schemas": ("DEFECTIVENESS", "PUNITIVENESS")}, True),
        (
            {"detected_schemas": ("DEFECTIVENESS",), "detected_distortions": ("PERSONALIZATION",)},
            True,
        ),
        ({"detected_schemas": ("DEFECTIVENESS",), "fine_grained_emotion": "shame"}, True),
        ({"detected_schemas": ("DEFECTIVENESS",), "fine_grained_emotion": "guilt"}, False),
        ({"detected_schemas": ("DEFECTIVENESS",)}, False),
        ({"detected_schemas": ("PUNITIVENESS",), "fine_grained_emotion": "shame"}, False),
        ({"detected_distortions": ("PERSONALIZATION",), "fine_grained_emotion": "shame"}, False),
    ],
)
def test_shame_spiral_needs_defectiveness_and_self_blame(overrides, expected):
    assert shame_spiral(_context(**overrides)) is expected


def test_shame_spiral_ids_exist_in_the_taxonomy():
    from olivia.core.perception import introspector as mod

    assert mod.SHAME_SCHEMA in TAX.values("schemas")
    assert set(TAX.values("schemas")) >= mod.SELF_BLAME_SCHEMAS
    assert set(TAX.values("cognitive_distortions")) >= mod.SELF_BLAME_DISTORTIONS
    assert set(TAX.emotion_profiles()) >= mod.SELF_BLAME_EMOTIONS


def test_shame_spiral_from_a_message():
    context = READER.apply("都是我的错，我一无是处", _context(fine_grained_emotion="sadness"))
    assert shame_spiral(context)


# -- mirror answers --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "嗯",
        "嗯嗯",
        "是的",
        "对",
        "对啊，一直这样",
        "确实",
        "没错",
        "是这样",
        "嗯，我一直这么觉得",
        "好像是这样",
        "被你说中了",
        "哦，是的",
        "有",
        "你说得对，我一直这样想",
    ],
)
def test_mirror_yes(text):
    assert read_mirror_answer(LEX.answers, text) is MirrorAnswer.CONFIRMED


@pytest.mark.parametrize(
    "text", ["不是", "没有", "不对", "还好吧", "不太是吧", "并不是这样", "倒也不至于", "不会"]
)
def test_mirror_no(text):
    assert read_mirror_answer(LEX.answers, text) is MirrorAnswer.DECLINED


@pytest.mark.parametrize(
    "text",
    [
        "对不起",
        "是不是这样",
        "可能吧",
        "我也说不清",
        "确实不是",
        "哦，",
        "",
        "/done",
        "今天上班好累",
        "对方没回我",
    ],
)
def test_mirror_unclear(text):
    assert read_mirror_answer(LEX.answers, text) is None


# -- the per-session mirror ------------------------------------------------------------------


def _mirror(enabled: bool = True) -> SchemaMirror:
    return SchemaMirror(LEX.answers, LINES, enabled=enabled)


def test_mirror_picks_the_schema_seen_most_then_the_latest():
    mirror = _mirror()
    mirror.observe(["FAILURE"], counts=True)
    mirror.observe(["DEFECTIVENESS"], counts=True)
    assert mirror.choose() == "DEFECTIVENESS"
    mirror.observe(["FAILURE"], counts=True)
    assert mirror.choose() == "FAILURE"


def test_mirror_ignores_evidence_from_unsettled_turns():
    mirror = _mirror()
    mirror.observe(["FAILURE"], counts=False)
    assert mirror.choose() is None


def test_mirror_is_off_in_rules_mode():
    mirror = _mirror(enabled=False)
    mirror.observe(["FAILURE"], counts=True)
    assert mirror.choose() is None


def test_mirror_asks_once_and_reads_exactly_the_next_turn():
    mirror = _mirror()
    mirror.observe(["FAILURE"], counts=True)
    mirror.mark_asked()
    assert mirror.status is MirrorStatus.ASKED and mirror.choose() is None
    assert mirror.answer("是的", readable=True) is MirrorAnswer.CONFIRMED
    assert mirror.status is MirrorStatus.CONFIRMED
    assert mirror.answer("是的", readable=True) is None


def test_an_unreadable_answer_turn_lets_the_question_lapse():
    mirror = _mirror()
    mirror.observe(["FAILURE"], counts=True)
    mirror.mark_asked()
    assert mirror.answer("是的", readable=False) is None
    assert mirror.answer("是的", readable=True) is None
    assert mirror.status is MirrorStatus.ASKED


def test_no_answer_without_a_question():
    assert _mirror().answer("是的", readable=True) is None


# -- mirror lines (draft pending G-0) --------------------------------------------------------


def test_mirror_lines_carry_the_draft_header():
    first = (DATA / "language" / "schema_mirror.yaml").read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# 草稿：待 G-0 两名注册心理师审核")


def test_mirror_lines_cover_every_schema():
    assert list(LINES) == list(TAX.values("schemas"))
    assert all(len(lines) >= 2 for lines in LINES.values())


@pytest.mark.parametrize("schema,line", [(s, ln) for s, lines in LINES.items() for ln in lines])
def test_mirror_lines_are_gentle_questions_that_pass_willow_and_the_gate(schema, line):
    lang = load_language_data(TAX)
    assert len(line) <= lang.templates.paragraph_max
    assert "？" in line
    assert apply_willow(line, ContentKind.NORMAL, lang.willow) == line
    gate = OutputGate(TAX, lang)
    assert gate.reasons(line, kind=ContentKind.NORMAL, stage=HelpStage.S_CLARIFY) == ()
    # No clinical labels: neither the schema's taxonomy name nor the jargon itself.
    names = {
        str(entry["name"])
        for entry in yaml.safe_load((DATA / "taxonomy.yaml").read_text("utf-8"))["schemas"]
    }
    assert not any(name in line for name in names)
    for word in ("图式", "核心信念", "认知扭曲", "缺陷", "障碍", "症"):
        assert word not in line, (schema, word)


# -- loader validation -----------------------------------------------------------------------


def _doc() -> dict[str, Any]:
    loaded = yaml.safe_load((DATA / "lexicons" / "perception.yaml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _load_mutated(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    doc = _doc()
    mutate(doc)
    (tmp_path / "perception.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    load_introspection_lexicon(TAX, tmp_path)


def _section(doc: dict[str, Any]) -> dict[str, Any]:
    section = doc["introspection"]
    assert isinstance(section, dict)
    return section


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda d: _section(d)["schemas"].update({"NOT_A_SCHEMA": ["随便", "什么"]}), "unknown"),
        (lambda d: _section(d)["distortions"].pop("MIND_READING"), "no entry"),
        (lambda d: _section(d)["yearnings"].update({"SAFETY": ["想被看见"]}), "at least 2"),
        (
            lambda d: _section(d)["yearnings"]["SAFETY"].append("想被看见"),
            "listed for both",
        ),
        (
            lambda d: _section(d)["schemas"]["FAILURE"].append("我一无是处"),
            "listed for both",
        ),
        (
            lambda d: _section(d)["schemas"]["FAILURE"].append("我一无是处啊"),
            "lies inside",
        ),
        (lambda d: _section(d)["schema_yearnings"].update({"FAILURE": "NOPE"}), "satir_yearnings"),
        (lambda d: _section(d)["schema_yearnings"].pop("FAILURE"), "satir_yearnings"),
        (
            lambda d: _section(d)["mirror_answers"]["affirm_start"].append("不是"),
            "both a yes and a no",
        ),
        (lambda d: _section(d)["mirror_answers"]["decline_start"].append("没"), "too short"),
        (lambda d: _section(d).update({"extra": {}}), "unknown keys"),
        (lambda d: d.pop("introspection"), "non-empty mapping"),
    ],
)
def test_loader_rejects_bad_lexicons(tmp_path, mutate, match):
    with pytest.raises(IntrospectionLexiconError, match=match):
        _load_mutated(tmp_path, mutate)


def _mirror_doc() -> dict[str, Any]:
    loaded = yaml.safe_load((DATA / "language" / "schema_mirror.yaml").read_text("utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda d: d["by_schema"].pop("FAILURE"), "no entry|non-empty"),
        (lambda d: d["by_schema"]["FAILURE"].append("{user_name}，是这样吗？"), "no slots"),
        (lambda d: d["by_schema"]["FAILURE"].append("我在这里。"), "not a question"),
        (lambda d: d["by_schema"].update({"NOPE": ["是吗？"]}), "unknown keys"),
    ],
)
def test_mirror_loader_rejects_bad_lines(tmp_path, mutate, match):
    doc = _mirror_doc()
    mutate(doc)
    (tmp_path / "schema_mirror.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(IntrospectionLexiconError, match=match):
        load_mirror_lines(TAX, tmp_path)
