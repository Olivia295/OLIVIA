import json
from datetime import UTC, datetime

import pytest

from olivia.core.chang.profile import ProfileCorruptError, ProfileStore
from olivia.core.models import PersonaProfile, UserRegion

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def _p(name="小林"):
    return PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name=name,
        region=UserRegion(country_code="HK", timezone="Asia/Hong_Kong"),
    )


def test_load_returns_none_before_first_save(tmp_path):
    assert ProfileStore(tmp_path).load() is None


def test_save_then_load_round_trip(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p())
    assert store.load() == _p()
    raw = store.path.read_text(encoding="utf-8")
    assert "小林" in raw and json.loads(raw)["schema_version"] == 1


def test_default_base_dir_uses_olivia_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OLIVIA_HOME", str(tmp_path))
    assert ProfileStore().path == tmp_path / "profile.json"


def test_corrupt_profile_recovers_from_snapshot(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p("阿青"))
    store.save(_p("小林"))
    store.path.write_text('{"schema_version": 1, "user_na', encoding="utf-8")
    assert store.load().user_name == "阿青"


def test_corrupt_profile_without_snapshot_raises(tmp_path):
    store = ProfileStore(tmp_path)
    store.path.write_text("not json", encoding="utf-8")
    with pytest.raises(ProfileCorruptError):
        store.load()


def test_semantically_invalid_profile_counts_as_corrupt(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p("阿青"))
    store.save(_p("小林"))  # 此时 "阿青" 进入快照
    data = json.loads(store.path.read_text(encoding="utf-8")) | {"age_confirmed_18_plus": False}
    store.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert store.load() == _p("阿青")  # JSON 合法但违反 18+ 校验，回退到快照


def test_huge_integer_field_counts_as_corrupt_and_recovers(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p("阿青"))
    store.save(_p("小林"))
    data = json.loads(store.path.read_text(encoding="utf-8"))
    huge = 10**400  # float(huge) raises OverflowError, not ValueError
    patched = json.dumps(data | {"directiveness_preference": huge}, ensure_ascii=False)
    assert "1" + "0" * 400 in patched
    store.path.write_text(patched, encoding="utf-8")
    assert store.load() == _p("阿青")


@pytest.mark.parametrize("text", ["[]", "null", "42", '"x"'])
def test_non_object_json_top_level_counts_as_corrupt(tmp_path, text):
    store = ProfileStore(tmp_path)
    store.path.write_text(text, encoding="utf-8")
    with pytest.raises(ProfileCorruptError):
        store.load()
