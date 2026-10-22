"""Crisis-card resolution by region and level (GEO-01..07, R8, ONB-05)."""

from datetime import date, timedelta

import pytest

from olivia.core.models import CrisisLevel, UserRegion
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.resolver import STALE_AFTER_DAYS, resolve, resolve_region_code
from olivia.core.resources.store import LineKind, ResourceStore, load_store, parse_store

STORE = load_store()
TODAY = STORE.compiled_on
SUPPORTED = sorted(STORE.regions)
NON_CN = [code for code in SUPPORTED if code != "CN"]
CRISIS_LEVELS = [CrisisLevel.L2, CrisisLevel.L3]


def _region(code: str) -> UserRegion:
    return UserRegion(country_code=code, timezone="UTC")


def _card(
    code: str | None,
    level: CrisisLevel,
    *,
    mode: CardMode = CardMode.CRISIS,
    today: date = TODAY,
    is_minor: bool = False,
) -> ResourceCard:
    region = None if code is None else _region(code)
    return resolve(STORE, region, level, mode=mode, today=today, is_minor=is_minor)


def _numbers(card: ResourceCard) -> list[str]:
    return [e.number for e in card.emergency] + [ln.number for ln in card.lines]


# Expected card contents per region, in priority (file) order.
EXPECTED = {
    "CN": {
        CrisisLevel.L2: ([], ["12356"]),
        CrisisLevel.L3: (["110", "120"], ["12356"]),
    },
    "HK": {
        CrisisLevel.L2: ([], ["18111", "2389 2222", "2382 0000"]),
        CrisisLevel.L3: (["999"], ["18111", "2389 2222", "2382 0000"]),
    },
    "MO": {
        CrisisLevel.L2: ([], ["2852 5222"]),
        CrisisLevel.L3: (["999", "110", "112"], ["2852 5222"]),
    },
    "TW": {
        CrisisLevel.L2: ([], ["1925", "1995", "1980"]),
        CrisisLevel.L3: (["110", "119"], ["1925", "1995"]),
    },
    "US": {
        CrisisLevel.L2: ([], ["988", "741741"]),
        CrisisLevel.L3: (["911"], ["988"]),
    },
    "CA": {
        CrisisLevel.L2: ([], ["988", "686868"]),
        CrisisLevel.L3: (["911"], ["988"]),
    },
    "GB": {
        CrisisLevel.L2: ([], ["116 123", "111", "85258"]),
        CrisisLevel.L3: (["999"], ["116 123", "111"]),
    },
    "AU": {
        CrisisLevel.L2: ([], ["13 11 14", "0477 13 11 14", "1300 22 4636"]),
        CrisisLevel.L3: (["000"], ["13 11 14"]),
    },
    "ZZ": {
        CrisisLevel.L2: (
            [],
            ["https://findahelpline.com/", "https://befrienders.org/find-support-now/"],
        ),
        CrisisLevel.L3: (
            ["112"],
            ["https://findahelpline.com/", "https://befrienders.org/find-support-now/"],
        ),
    },
}


def test_expected_table_covers_every_supported_region() -> None:
    assert set(EXPECTED) == set(SUPPORTED)


@pytest.mark.parametrize("code", SUPPORTED)
@pytest.mark.parametrize("level", CRISIS_LEVELS)
def test_crisis_card_contents(code: str, level: CrisisLevel) -> None:
    card = _card(code, level)
    emergency, lines = EXPECTED[code][level]
    assert card.region_used == code
    assert card.level is level and card.mode is CardMode.CRISIS
    assert [e.number for e in card.emergency] == emergency
    assert [ln.number for ln in card.lines] == lines
    assert all(level in ln.levels for ln in card.lines)
    assert card.compiled_on == STORE.compiled_on
    assert card.directory_version == STORE.version


@pytest.mark.parametrize("code", SUPPORTED)
def test_every_l3_card_has_an_emergency_number(code: str) -> None:
    assert _card(code, CrisisLevel.L3).emergency


@pytest.mark.parametrize("code", NON_CN)
@pytest.mark.parametrize("mode", list(CardMode))
@pytest.mark.parametrize("level", CRISIS_LEVELS)
def test_non_cn_cards_never_show_mainland_entries(
    code: str, mode: CardMode, level: CrisisLevel
) -> None:
    # R8 / GEO-03, checked by region: 110 is a valid local number in MO and TW.
    cn = STORE.region("CN")
    cn_ids = {e.id for e in cn.emergency} | {ln.id for ln in cn.lines}
    for is_minor in (False, True):
        card = _card(code, level, mode=mode, is_minor=is_minor)
        shown = [*card.emergency, *card.lines]
        assert not {e.id for e in shown} & cn_ids
        assert not any(e.id.startswith("cn_") for e in shown)
        assert not set(_numbers(card)) & {"12356", "120", "12355"}


@pytest.mark.parametrize("code", [None, "ZZ", "UK", "FR", "JP"])
def test_unknown_or_unsupported_region_falls_back_to_zz(code: str | None) -> None:
    region = None if code is None else _region(code)
    assert resolve_region_code(STORE, region) == "ZZ"
    assert _card(code, CrisisLevel.L3).region_used == "ZZ"


def test_supported_codes_resolve_to_themselves() -> None:
    for code in SUPPORTED:
        assert resolve_region_code(STORE, _region(code)) == code


def test_minor_sees_12355_at_cn_l2_only() -> None:
    l2 = _card("CN", CrisisLevel.L2, is_minor=True)
    assert [ln.number for ln in l2.lines] == ["12356", "12355"]
    assert l2.lines[1].kind is LineKind.YOUTH_LINE
    # 12355 is not a 24h crisis line, so it never joins the L3 card.
    assert "12355" not in _numbers(_card("CN", CrisisLevel.L3, is_minor=True))


@pytest.mark.parametrize("mode", list(CardMode))
@pytest.mark.parametrize("level", CRISIS_LEVELS)
def test_adults_never_see_minors_only_lines(mode: CardMode, level: CrisisLevel) -> None:
    for code in SUPPORTED:
        card = _card(code, level, mode=mode)
        assert not any(ln.minors_only for ln in card.lines)


@pytest.mark.parametrize("mode", list(CardMode))
def test_canada_never_shows_741741(mode: CardMode) -> None:
    for level in CRISIS_LEVELS:
        for is_minor in (False, True):
            card = _card("CA", level, mode=mode, is_minor=is_minor)
            assert "741741" not in _numbers(card)


@pytest.mark.parametrize("level", [CrisisLevel.L0, CrisisLevel.L1])
def test_crisis_mode_rejects_l0_and_l1(level: CrisisLevel) -> None:
    with pytest.raises(ValueError, match="L2 or L3"):
        _card("CN", level)


@pytest.mark.parametrize("code", SUPPORTED)
def test_browsing_shows_everything_grouped_by_kind(code: str) -> None:
    data = STORE.region(code)
    card = _card(code, CrisisLevel.L0, mode=CardMode.BROWSING, is_minor=True)
    assert card.mode is CardMode.BROWSING
    assert card.emergency == data.emergency
    assert set(card.lines) == set(data.lines)
    kind_order = list(LineKind)
    positions = [kind_order.index(ln.kind) for ln in card.lines]
    assert positions == sorted(positions)
    # Within a kind, file order is kept.
    for kind, group in card.lines_by_kind():
        assert list(group) == [ln for ln in data.lines if ln.kind is kind]


def test_browsing_groups_for_gb() -> None:
    card = _card("GB", CrisisLevel.L0, mode=CardMode.BROWSING)
    groups = {kind: [ln.number for ln in group] for kind, group in card.lines_by_kind()}
    assert groups == {
        LineKind.CRISIS_HOTLINE: ["116 123", "111"],
        LineKind.TEXT_LINE: ["85258"],
    }


def test_fresh_data_is_not_stale() -> None:
    card = _card("CN", CrisisLevel.L3, today=TODAY + timedelta(days=STALE_AFTER_DAYS))
    assert card.stale_entries == () and not card.stale


def test_entries_older_than_180_days_are_flagged() -> None:
    card = _card("CN", CrisisLevel.L3, today=TODAY + timedelta(days=STALE_AFTER_DAYS + 1))
    assert card.stale
    assert card.stale_entries == ("cn_emergency_110", "cn_emergency_120", "cn_12356")


def test_stale_flag_only_covers_shown_entries() -> None:
    card = _card("CN", CrisisLevel.L2, today=date(2030, 1, 1))
    assert card.stale_entries == ("cn_12356",)


def test_l2_falls_back_to_emergency_when_region_has_no_l2_line() -> None:
    raw = {
        "version": 1,
        "compiled_on": "2026-10-22",
        "regions": {
            "ZZ": {
                "emergency": [
                    {
                        "number": "112",
                        "purpose": "generic_gsm_emergency",
                        "source_url": "https://example.org/112",
                        "verified_on": "2026-10-22",
                        "notes": "",
                    }
                ],
                "lines": [
                    {
                        "id": "zz_l3_only",
                        "name_zh": "仅 L3",
                        "number": "1",
                        "kind": "crisis_hotline",
                        "levels": ["L3"],
                        "hours": "24/7",
                        "scope": "national",
                        "adcode": None,
                        "minors_only": False,
                        "source_url": "https://example.org/",
                        "verified_on": "2026-10-22",
                        "notes": "",
                    }
                ],
            }
        },
    }
    store: ResourceStore = parse_store(raw)
    card = resolve(store, None, CrisisLevel.L2, mode=CardMode.CRISIS, today=TODAY)
    assert [e.number for e in card.emergency] == ["112"]
    assert card.lines == ()
