"""Referral destinations follow the saved region (F4 item 8).

Mainland users get the mainland wording; Hong Kong, Macao and Taiwan their own; everyone
else (and a profile without a region) a generic one that names no mainland-only place.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.language.engine import LanguageEngine
from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LANG = load_language_data(TAX)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
MAINLAND_ONLY = ("妇幼保健院", "综合医院")
ZONES = {"CN": "Asia/Shanghai", "HK": "Asia/Hong_Kong", "US": "America/New_York"}


def _engine() -> LanguageEngine:
    return LanguageEngine(TAX, rng=random.Random(1), data=LANG)


def test_mainland_keeps_its_wording():
    engine = _engine()
    text = engine.render_referral(["SIT-02-06"], "CN")
    assert "妇幼保健院" in text
    assert engine.render_referral(["SIT-02-06"]) == text  # the default stays mainland


@pytest.mark.parametrize("country", ["HK", "MO", "TW", "US", "GB", "AU", "CA", "ZZ", "JP"])
def test_other_regions_name_no_mainland_only_place(country):
    engine = _engine()
    for code in TAX.red_flags():
        text = engine.render_referral([code], country)
        assert engine.last_gate is not None and engine.last_gate.ok, (country, code)
        assert not [w for w in MAINLAND_ONLY if w in text], (country, code, text)
        assert TAX.red_flags()[code].name_zh not in text


@pytest.mark.parametrize("country", ["US", "GB", "ZZ"])
def test_elsewhere_is_generic(country):
    text = _engine().render_referral(list(TAX.red_flags()), country)
    assert "当地的精神科" in text and "家庭医生" in text


@pytest.mark.parametrize("country", ["HK", "MO", "TW"])
def test_hk_mo_tw_have_their_own_wording(country):
    text = _engine().render_referral(["SIT-02-04"], country)
    assert text == _engine().render_referral(["SIT-02-04"], "HK")
    assert "精神科专科门诊" in text


def test_the_withdrawal_warning_is_kept_everywhere():
    for country in ("CN", "HK", "US"):
        # Trial report 2026-10-26 item 13: "请不要自己突然停用" read as "don't quit"; every
        # region's destination now says the doctor helps with stopping.
        text = _engine().render_referral(["SIT-10-04"], country)
        assert "想停或减少时，医生可以陪你一步步来" in text and "医生指导下" in text


@pytest.mark.parametrize(
    ("region", "expected", "absent"),
    [
        (UserRegion("CN", ZONES["CN"]), "妇幼保健院", "当地的"),
        (UserRegion("HK", ZONES["HK"]), "产后检查", "妇幼保健院"),
        (UserRegion("US", ZONES["US"]), "当地的", "妇幼保健院"),
        (None, "当地的", "妇幼保健院"),
    ],
)
def test_the_session_uses_the_profiles_region(region, expected, absent):
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=region,
        clinical_history=("SIT-02-06",),
    )
    session = Session.open(TAX, profile, rng=random.Random(3), now=lambda: NOW)
    # The flag comes up in the conversation (dogfood I5: a profile flag alone waits for a plan).
    result = session.turn("我有产后抑郁，今天有点累")
    assert result.referral_flags == ("SIT-02-06",)
    assert expected in result.reply and absent not in result.reply
