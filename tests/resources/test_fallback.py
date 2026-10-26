"""The fixed crisis help shown when the packaged hotline data fails verification (S3).

It is written in the code, so these tests lock it: the text itself, and its emergency
numbers against the verified ones in ``olivia/data/resources/hotlines.yaml`` (any drift
between the two fails here).
"""

from __future__ import annotations

from olivia.core.chang.onboarding import load_onboarding_text
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.resources.fallback import DIRECTORY_URL, EMERGENCY, fallback_text
from olivia.core.resources.store import load_store
from olivia.core.taxonomy import load_taxonomy

EXPECTED = (
    "如果你现在有危险，或者担心自己的安全，请马上联系当地的紧急服务：\n"
    "· 中国大陆：110（报警）、120（急救）\n"
    "· 中国香港：999\n"
    "· 中国澳门：999、110、112\n"
    "· 中国台湾：110（报警）、119（消防与救护）\n"
    "· 美国：911\n"
    "· 加拿大：911\n"
    "· 英国：999\n"
    "· 澳大利亚：000\n"
    "· 其他地方：112（多数手机网络可以拨打；当地有自己的紧急号码时，请先拨当地的号码）\n"
    "也可以在 https://findahelpline.com/ 查找你所在地方的求助热线。\n"
    "程序自带的求助电话资料没有通过校验，可能已经损坏，所以这次没有显示其中的热线。"
    "建议重新安装 OLIVIA。"
)


def test_the_fallback_text_is_locked():
    assert fallback_text() == EXPECTED


def test_without_the_damage_note_only_that_sentence_goes():
    """The CLI's last resort for an unexpected error (QA 2026-10-26 #8): the same numbers,
    without claiming the hotline data is damaged."""
    *kept, damaged = EXPECTED.split("\n")
    assert damaged.startswith("程序自带的求助电话资料没有通过校验")
    assert fallback_text(damaged=False) == "\n".join(kept)


def test_every_region_and_emergency_number_matches_the_verified_data():
    store = load_store()
    assert [code for code, _label, _numbers in EMERGENCY] == list(store.regions)
    for code, _label, numbers in EMERGENCY:
        verified = [e.number for e in store.region(code).emergency]
        assert [number for number, _purpose in numbers] == verified, code


def test_the_directory_is_the_verified_global_directory():
    numbers = [line.number for line in load_store().region("ZZ").lines]
    assert DIRECTORY_URL in numbers


def test_the_fallback_text_passes_willow():
    data = load_language_data(load_taxonomy())
    for text in (fallback_text(), fallback_text(damaged=False)):
        assert apply_willow(text, ContentKind.CRISIS, data.willow) == text
        assert "！" not in text and "!" not in text


def test_region_labels_are_the_programs_own():
    labels = load_onboarding_text().region_labels
    for code, label, _numbers in EMERGENCY:
        if code != "ZZ":
            assert label == labels[code], code
