import pytest

from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.red_flags import RedFlagDetector, SessionRedFlags, UnknownRedFlagError
from olivia.core.taxonomy import load_taxonomy


@pytest.fixture(scope="module")
def det():
    tax = load_taxonomy()
    return RedFlagDetector(tax, load_safety_lexicons(tax))


@pytest.mark.parametrize(
    "text,code",
    [
        ("我去年确诊了双相", "SIT-02-04"),
        ("生完孩子后一直哭", "SIT-02-06"),
        ("我有创伤后应激", "SIT-06-01"),
        ("最近总是感觉自己不真实", "SIT-06-05"),
        ("我已经连续三天没吃东西", "SIT-08-04"),
        ("昨晚又用刀划自己", "SIT-09-01"),
        ("不喝酒手就抖", "SIT-10-04"),
    ],
)
def test_detects_each_code(det, text, code):
    assert det.detect(text) == frozenset({code})


@pytest.mark.parametrize(
    "text,code", [("我有ＰＴＳＤ", "SIT-06-01"), ("医生说我是 BPD", "SIT-09-01")]
)
def test_self_report_variants(det, text, code):
    assert code in det.detect(text)


@pytest.mark.parametrize("text", ["我没有双相", "我不是bpd", "我并没有厌食症"])
def test_negated_self_report_is_ignored(det, text):
    assert det.detect(text) == frozenset()


@pytest.mark.parametrize(
    "text,code",
    [
        ("我是不是双相", "SIT-02-04"),
        ("我是不是有厌食症", "SIT-08-04"),
        ("我不是没有双相", "SIT-02-04"),
    ],
)
def test_question_and_double_negation_keep_self_report(det, text, code):
    assert det.detect(text) == frozenset({code})


def test_unrelated_text(det):
    assert det.detect("今天被领导批评了，心里很堵") == frozenset()


def test_profile_flags(det):
    assert det.profile_flags(["SIT-08-04"]) == frozenset({"SIT-08-04"})
    with pytest.raises(UnknownRedFlagError, match="SIT-8-4"):
        det.profile_flags(["SIT-8-4"])


def test_session_accumulates_and_includes_profile(det):
    s = SessionRedFlags(det, clinical_history=["SIT-02-04"])
    assert s.active == frozenset({"SIT-02-04"})
    assert s.observe("我有厌食症") == frozenset({"SIT-02-04", "SIT-08-04"})
    assert s.observe("今天还行") == frozenset({"SIT-02-04", "SIT-08-04"})
