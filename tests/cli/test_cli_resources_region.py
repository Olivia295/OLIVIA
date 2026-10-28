"""``olivia resources`` and ``olivia region``: snapshot tests over fixed data and dates."""

from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from cli_support import NOW, SHANGHAI, save_profile

from olivia import cli
from olivia.core.chang import onboarding
from olivia.core.chang.profile import PROFILE_FILENAME, ProfileStore
from olivia.core.models import UserRegion
from olivia.core.resources.store import ResourceStore, parse_store


def _line(
    line_id: str, name: str, number: str, kind: str, hours: str, verified: str
) -> dict[str, object]:
    return {
        "id": line_id,
        "name_zh": name,
        "number": number,
        "kind": kind,
        "levels": ["L2", "L3"],
        "hours": hours,
        "scope": "national",
        "adcode": None,
        "minors_only": False,
        "source_url": "https://example.org/",
        "verified_on": verified,
        "notes": "",
    }


def _emergency(number: str, purpose: str, verified: str) -> dict[str, object]:
    return {
        "number": number,
        "purpose": purpose,
        "source_url": "https://example.org/",
        "verified_on": verified,
        "notes": "",
    }


FIXTURE = {
    "version": 1,
    "compiled_on": "2026-01-15",
    "regions": {
        "GB": {
            "emergency": [_emergency("999", "police_fire_ambulance", "2026-01-15")],
            "lines": [
                _line("gb_fixture_text", "测试短信线", "85000", "text_line", "24/7", "2026-01-15"),
                _line(
                    "gb_fixture_call", "测试热线", "116 000", "crisis_hotline", "24/7", "2025-01-01"
                ),
                _line(
                    "gb_fixture_dir",
                    "测试目录",
                    "https://example.org/",
                    "directory_url",
                    "unknown",
                    "2026-01-15",
                ),
            ],
        },
        "ZZ": {
            "emergency": [_emergency("112", "generic_gsm_emergency", "2026-01-15")],
            "lines": [
                _line(
                    "zz_fixture_dir",
                    "全球目录",
                    "https://example.org/zz",
                    "directory_url",
                    "unknown",
                    "2026-01-15",
                ),
            ],
        },
    },
}
FIXED_NOW = datetime(2026, 3, 1, 10, 0, tzinfo=SHANGHAI)


@pytest.fixture
def fixture_store(monkeypatch: pytest.MonkeyPatch) -> list[date]:
    """Serve FIXTURE instead of the packaged data; records the ``today`` it was asked for."""
    seen: list[date] = []

    def load(today: date) -> ResourceStore:
        seen.append(today)
        return parse_store(FIXTURE)

    monkeypatch.setattr(cli, "_load_store", load)
    return seen


# -- resources -------------------------------------------------------------------------------


def test_resources_snapshot_groups_by_kind_and_marks_stale(run_cli, data_home, fixture_store):
    save_profile(data_home, region=UserRegion("GB", "Europe/London"))
    run = run_cli(["resources"], now=FIXED_NOW)
    assert run.code == 0
    assert run.out == (
        "求助资源 · 英国（GB）\n"
        "\n"
        "紧急电话：\n"
        "· 999（报警、消防与急救）\n"
        "\n"
        "心理援助与危机热线：\n"
        "· 测试热线：116 000（信息可能已过期）\n"
        "  服务时间：24/7\n"
        "\n"
        "短信与文字求助：\n"
        "· 测试短信线：85000\n"
        "  服务时间：24/7\n"
        "\n"
        "求助热线目录：\n"
        "· 测试目录：https://example.org/\n"
        "\n"
        "资料整理于 2026-01-15（第 1 版）\n"
        "资料来源：随程序附带\n"
    )
    # "today" comes from the injected clock in the profile's timezone, never the real date.
    assert fixture_store == [date(2026, 3, 1)]


def test_resources_without_a_profile_shows_the_fallback_and_a_hint(run_cli, fixture_store):
    run = run_cli(["resources"], now=FIXED_NOW)
    assert run.code == 0
    assert run.out == (
        "求助资源 · 其他地区（ZZ）\n"
        "\n"
        "紧急电话：\n"
        "· 112（通用紧急求助）\n"
        "\n"
        f"{cli.RESOURCES_EVERYWHERE}\n"  # QA q4 FLT-2: the region is not known
        "· 英国（GB）：999\n"
        "\n"
        "求助热线目录：\n"
        "· 全球目录：https://example.org/zz\n"
        "\n"
        "资料整理于 2026-01-15（第 1 版）\n"
        "资料来源：随程序附带\n"
        "\n"
        f"{cli.RESOURCES_SET_REGION}\n"
    )


def test_resources_for_an_unsupported_saved_region_fall_back_to_zz(
    run_cli, data_home, fixture_store
):
    save_profile(data_home, region=UserRegion("CN", "Asia/Shanghai"))  # not in FIXTURE
    run = run_cli(["resources"], now=FIXED_NOW)
    assert run.out.startswith("求助资源 · 其他地区（ZZ）\n")
    assert cli.RESOURCES_SET_REGION not in run.out
    assert "no override" not in run.out  # the bundle reason belongs to chat --inspect


@pytest.mark.parametrize(
    ("code", "present", "absent"),
    [
        ("CN", ["110", "120", "12356"], ["12355", "999"]),
        ("HK", ["999", "18111"], ["12356", "120（"]),
        ("US", ["911", "988", "741741"], ["12356"]),
        ("ZZ", ["112", "findahelpline.com"], ["12356", "911"]),
    ],
)
def test_resources_with_the_packaged_data(run_cli, data_home, code, present, absent):
    zone = {"CN": "Asia/Shanghai", "HK": "Asia/Hong_Kong", "US": "America/New_York"}
    save_profile(data_home, region=UserRegion(code, zone.get(code, "UTC")))
    run = run_cli(["resources"], now=NOW)
    assert run.code == 0
    assert f"（{code}）" in run.lines[0]
    for text in present:
        assert text in run.out, text
    for text in absent:
        assert text not in run.out, text
    assert "可能已过期" not in run.out


# -- region ----------------------------------------------------------------------------------


def _saved(home) -> UserRegion | None:
    profile = ProfileStore(home).load()
    assert profile is not None
    return profile.region


def test_region_show_snapshot(run_cli, data_home):
    save_profile(
        data_home,
        region=UserRegion("CN", "Asia/Shanghai", city_code="330100", city_display_name="杭州"),
    )
    run = run_cli(["region"])
    assert run.code == 0
    assert run.out == "地区：中国大陆（CN）\n时区：Asia/Shanghai\n"


def test_region_show_without_profile_or_region(run_cli, data_home):
    assert run_cli(["region"]).out == f"{cli.NO_REGION}\n"
    save_profile(data_home, region=None)
    assert run_cli(["region"]).out == f"{cli.NO_REGION}\n"


def test_region_set_single_zone_snapshot(run_cli, data_home, fixture_store):
    save_profile(data_home)
    run = run_cli(["region", "gb"], now=FIXED_NOW)
    assert run.code == 0
    assert run.out == "好的，已经保存：英国（GB），时区 Europe/London。\n"
    assert _saved(data_home) == UserRegion("GB", "Europe/London")
    profile = ProfileStore(data_home).load()
    assert profile is not None and profile.updated_at == FIXED_NOW


@pytest.mark.parametrize(
    ("raw", "code", "zone"),
    [
        ("china", "CN", "Asia/Shanghai"),
        ("中国", "CN", "Asia/Shanghai"),
        ("大陆", "CN", "Asia/Shanghai"),
        ("内地", "CN", "Asia/Shanghai"),
        ("hongkong", "HK", "Asia/Hong_Kong"),
        ("香港", "HK", "Asia/Hong_Kong"),
        ("台湾", "TW", "Asia/Taipei"),
        ("澳门", "MO", "Asia/Macau"),
        ("UK", "GB", "Europe/London"),
    ],
)
def test_region_accepts_common_names(run_cli, data_home, raw, code, zone):
    save_profile(data_home, region=UserRegion("US", "America/Chicago"))
    run = run_cli(["region", raw])
    assert run.code == 0
    assert run.out == f"好的，已经保存：{cli._region_label(code)}（{code}），时区 {zone}。\n"
    assert _saved(data_home) == UserRegion(code, zone)


@pytest.mark.parametrize("raw", ["JP", "japan", "1", "fr", "火星"])
def test_region_unknown_codes_are_refused_with_the_supported_list(run_cli, data_home, raw):
    save_profile(data_home)
    run = run_cli(["region", raw])
    assert run.code == 2
    assert run.out.startswith(f"没有认出「{raw}」这个地区，所以没有做改动。")
    for code in ("CN", "HK", "MO", "TW", "US", "CA", "GB", "AU", "ZZ"):
        assert f"  {code}  " in run.out
    assert "olivia region ZZ --timezone" in run.out
    assert _saved(data_home) == UserRegion("CN", "Asia/Shanghai")


def test_region_zz_never_keeps_the_old_countrys_timezone(run_cli, data_home, monkeypatch):
    """The Japan user: ZZ takes this computer's zone, not the stale Asia/Shanghai."""
    monkeypatch.setattr(onboarding, "system_timezone", lambda: "Asia/Tokyo")
    save_profile(data_home)
    run = run_cli(["region", "ZZ"])
    assert run.code == 0
    assert run.out == (
        "好的，已经保存：其他地区（ZZ），时区 Asia/Tokyo。\n"
        "时区先按这台电脑的设置用 Asia/Tokyo；不对的话，可以用 --timezone 修改。\n"
    )
    assert _saved(data_home) == UserRegion("ZZ", "Asia/Tokyo")
    # And again from ZZ itself: the computer's zone, not the one saved before.
    monkeypatch.setattr(onboarding, "system_timezone", lambda: "Europe/Berlin")
    assert run_cli(["region", "other"]).code == 0
    assert _saved(data_home) == UserRegion("ZZ", "Europe/Berlin")


def test_region_zz_with_a_timezone(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["region", "ZZ", "--timezone", "asia/tokyo"])
    assert run.code == 0
    assert run.out == "好的，已经保存：其他地区（ZZ），时区 Asia/Tokyo。\n"
    assert _saved(data_home) == UserRegion("ZZ", "Asia/Tokyo")


def test_japan_user_afternoon_is_not_late_night(run_cli, data_home, monkeypatch):
    """A Japan user at 15:00 must not be on a stale zone where it is night (「深夜」)."""
    monkeypatch.setattr(onboarding, "system_timezone", lambda: "Asia/Tokyo")
    save_profile(data_home, region=UserRegion("US", "America/Los_Angeles"))
    assert run_cli(["region", "ZZ"]).code == 0
    afternoon = datetime(2026, 10, 22, 15, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    profile = ProfileStore(data_home).load()
    assert profile is not None
    assert cli._local_clock(lambda: afternoon, profile)().hour == 15


def test_an_unknown_saved_zone_falls_back_to_the_computers(data_home, monkeypatch):
    monkeypatch.setattr(onboarding, "system_timezone", lambda: "Asia/Tokyo")
    profile = save_profile(data_home, region=UserRegion("ZZ", "Mars/Olympus"))
    noon_utc = datetime(2026, 10, 22, 6, 0, tzinfo=ZoneInfo("UTC"))
    assert cli._local_clock(lambda: noon_utc, profile)().hour == 15


def test_region_multi_zone_uses_the_computers_zone_when_it_fits(run_cli, data_home, monkeypatch):
    monkeypatch.setattr(onboarding, "system_timezone", lambda: "America/Chicago")
    save_profile(data_home)
    run = run_cli(["region", "usa"])
    assert run.code == 0
    assert "America/Chicago" in run.lines[-1]
    assert _saved(data_home) == UserRegion("US", "America/Chicago")


def test_region_multi_zone_needs_a_timezone(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["region", "US"])
    assert run.code == 2
    assert run.out == (
        "美国有好几个时区，请用 --timezone 告诉我是哪一个，"
        "例如：America/New_York、America/Chicago、America/Denver\n"
    )
    assert _saved(data_home) == UserRegion("CN", "Asia/Shanghai")


def test_region_multi_zone_with_timezone_snapshot(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["region", "US", "--timezone", "america/los_angeles"])
    assert run.code == 0
    assert run.out == "好的，已经保存：美国（US），时区 America/Los_Angeles。\n"
    # Same country again: the saved zone is kept.
    assert run_cli(["region", "US"]).code == 0
    assert _saved(data_home) == UserRegion("US", "America/Los_Angeles")


def test_region_timezone_alone_keeps_the_country(run_cli, data_home):
    save_profile(data_home, region=UserRegion("AU", "Australia/Sydney"))
    run = run_cli(["region", "--timezone", "Australia/Perth"])
    assert run.code == 0
    assert _saved(data_home) == UserRegion("AU", "Australia/Perth")


def test_region_bad_timezone_is_refused(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["region", "US", "--timezone", "Mars/Olympus"])
    assert run.code == 2
    assert run.out == (
        "没有认出时区「Mars/Olympus」。可以用「大洲/城市」的格式，例如 Asia/Singapore。\n"
    )
    assert _saved(data_home) == UserRegion("CN", "Asia/Shanghai")


def test_region_zz_without_profile_region_uses_the_computers_zone(run_cli, data_home):
    save_profile(data_home, region=None)
    assert run_cli(["region", "ZZ"]).lines[0] == "好的，已经保存：其他地区（ZZ），时区 UTC。"
    assert _saved(data_home) == UserRegion("ZZ", "UTC")  # the conftest's computer is on UTC


def test_region_clear_snapshot(run_cli, data_home):
    save_profile(
        data_home,
        region=UserRegion("CN", "Asia/Shanghai", city_code="330100", city_display_name="杭州"),
    )
    run = run_cli(["region", "--clear"])
    assert run.code == 0
    assert run.out == (
        "已清除保存的地区。求助卡片会显示全球通用的资源；时区按这台电脑的设置用 UTC。\n"
    )
    assert _saved(data_home) is None  # QA q4 P10: cleared, not "其他地区"
    saved = (data_home / PROFILE_FILENAME).read_text(encoding="utf-8")
    assert "杭州" not in saved and "330100" not in saved
    assert run_cli(["region"]).out == f"{cli.NO_REGION}\n"


def test_region_clear_with_a_code_is_refused(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["region", "HK", "--clear"])
    assert run.code == 2
    assert run.out == f"{cli.REGION_CLEAR_WITH_CODE}\n"
    assert _saved(data_home) == UserRegion("CN", "Asia/Shanghai")


@pytest.mark.parametrize("argv", [["region", "HK"], ["region", "--clear"]])
def test_region_cannot_be_set_before_onboarding(run_cli, data_home, argv):
    run = run_cli(argv)
    assert run.code == 1
    assert run.out == f"{cli.NOT_ONBOARDED}\n"
    assert not (data_home / PROFILE_FILENAME).exists()


def test_region_changes_reach_the_next_chat(run_cli, data_home):
    save_profile(data_home)
    assert run_cli(["region", "HK"]).code == 0
    run = run_cli(["chat", "--rules"], ["我不想活了"])
    (result,) = run.results
    assert result.resource_card is not None and result.resource_card.region_used == "HK"
    assert "12356" not in run.out
    record = json.loads((data_home / PROFILE_FILENAME).read_text(encoding="utf-8"))
    assert record["region"]["country_code"] == "HK"
    assert record["region"]["timezone"] == "Asia/Hong_Kong"


# -- QA 2026-10-26 #8: one look at a region's numbers, never saved -----------------------------


def _under_18(run_cli) -> None:
    assert run_cli(["chat", "--rules"], ["1", "2", "1"]).code == 1  # the refusal record


def test_under_18_resources_point_at_the_one_off_look(run_cli, data_home):
    _under_18(run_cli)
    run = run_cli(["resources"])
    assert run.code == 0
    assert run.lines[-1] == cli.RESOURCES_ONE_OFF_HINT
    assert cli.RESOURCES_SET_REGION not in run.out  # olivia region refuses here


def test_under_18_region_refusal_points_at_the_one_off_look(run_cli, data_home):
    _under_18(run_cli)
    run = run_cli(["region", "HK"])
    assert run.code == 1
    assert run.lines == [cli.ADULTS_ONLY, cli.RESOURCES_ONE_OFF_HINT]


def test_under_18_one_off_look_shows_the_region_and_its_youth_line(run_cli, data_home):
    _under_18(run_cli)
    before = (data_home / PROFILE_FILENAME).read_bytes()
    hk = run_cli(["resources", "HK"])
    assert hk.code == 0
    assert hk.lines[0] == "求助资源 · 中国香港（HK）"
    assert "999" in hk.out and "18111" in hk.out
    assert hk.lines[-1] == cli.RESOURCES_ONE_OFF
    cn = run_cli(["resources", "中国"])
    assert "12356" in cn.out and "12355" in cn.out  # the minors' line, as for this record
    assert (data_home / PROFILE_FILENAME).read_bytes() == before  # nothing saved


def test_an_adults_one_off_look_saves_nothing(run_cli, data_home):
    save_profile(data_home)
    before = (data_home / PROFILE_FILENAME).read_bytes()
    run = run_cli(["resources", "us"])
    assert run.code == 0 and run.lines[0] == "求助资源 · 美国（US）"
    assert "911" in run.out and "988" in run.out and "12356" not in run.out
    assert "12355" not in run_cli(["resources", "CN"]).out  # adults never see it
    assert (data_home / PROFILE_FILENAME).read_bytes() == before
    assert ProfileStore(data_home).load().region == UserRegion("CN", "Asia/Shanghai")


def test_a_one_off_look_works_without_any_profile(run_cli, data_home):
    run = run_cli(["resources", "GB"])
    assert run.code == 0 and "999" in run.out and "116 123" in run.out
    assert not data_home.exists() or not (data_home / PROFILE_FILENAME).exists()


def test_a_one_off_look_at_an_unknown_region_is_a_wrong_value(run_cli, data_home):
    run = run_cli(["resources", "火星"])
    assert run.code == 2
    assert "「火星」" in run.out and "  HK  中国香港" in run.out


@pytest.mark.parametrize("raw", ["JP", "日本", "火星"])
def test_an_unknown_region_still_shows_the_global_card_first(run_cli, data_home, raw):
    """QA r3: someone in Japan typing ``olivia resources JP`` gets numbers before the list."""
    run = run_cli(["resources", raw])
    assert run.code == 2
    assert "求助资源 · 其他地区（ZZ）" in run.out
    assert run.out.index("112") < run.out.index("findahelpline.com") < run.out.index(f"「{raw}」")
    assert "上面先列出了全球通用的资源" in run.out


def test_resources_help_names_the_one_off_region(run_cli, capsys):
    with pytest.raises(SystemExit):
        cli.main(["resources", "-h"])
    assert "不会保存" in capsys.readouterr().out


def test_a_saved_other_region_is_not_asked_for_a_region_again(run_cli, data_home):
    """QA r3: ZZ is a choice ("其他地区，或不想说"); only the one-off look is mentioned."""
    save_profile(data_home, region=UserRegion("ZZ", "UTC"))
    run = run_cli(["resources"])
    assert run.lines[-1] == cli.RESOURCES_ONE_OFF_HINT
    assert cli.RESOURCES_SET_REGION not in run.out
    assert "告诉我你所在的国家或地区" not in run.out


def test_no_saved_region_hints_at_both_ways(run_cli, data_home):
    run = run_cli(["resources"])
    assert run.lines[-1] == cli.RESOURCES_SET_REGION
    assert "olivia resources <代码>" in cli.RESOURCES_SET_REGION


def test_the_zz_crisis_card_lists_112_like_resources(run_cli, data_home):
    """The card says "请先拨打下面的电话": under ZZ there used to be only two links."""
    save_profile(data_home, region=UserRegion("ZZ", "UTC"))
    run = run_cli(["chat", "--rules"], ["", "我不想活了", "/exit", ""])
    (crisis,) = [r for r in run.results if r.resource_card is not None]
    assert [e.number for e in crisis.resource_card.emergency] == ["112"]
    assert "112（通用紧急求助）" in crisis.reply
    assert crisis.reply.index("112") < crisis.reply.index("findahelpline.com")
