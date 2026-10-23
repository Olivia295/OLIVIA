"""``olivia privacy``: the short privacy notice (next-phase B8; PIPL, gate G-4)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from cli_support import save_profile

from olivia.core.chang.privacy import (
    PrivacyTextError,
    load_privacy_text,
    privacy_notice,
)
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate
from olivia.core.models import HelpStage
from olivia.core.taxonomy import load_taxonomy

ROOT = Path(__file__).resolve().parents[2]
TEXT_FILE = ROOT / "olivia/data/templates/privacy.yaml"
FORBIDDEN = ["应该", "必须", "一定要", "症状", "病", "诊断", "患者", "治疗", "！", "!"]


def test_prints_the_notice_with_the_data_directory(run_cli, data_home):
    run = run_cli(["privacy"])
    assert run.code == 0
    assert run.out == privacy_notice(data_home) + "\n"
    assert str(data_home) in run.out
    for point in ("离线", "不联网", "加密", "系统钥匙串", "olivia memory", "olivia forget"):
        assert point in run.out, point


def test_reads_and_writes_nothing(run_cli, data_home, keychain):
    assert run_cli(["privacy"]).code == 0
    assert not data_home.exists()  # not even the directory is created
    assert keychain.items == {} and keychain.writes == []


def test_works_whatever_the_profile_holds(run_cli, data_home):
    save_profile(data_home)
    (data_home / "profile.json").write_text("{broken", encoding="utf-8")
    run = run_cli(["privacy"])
    assert run.code == 0 and str(data_home) in run.out


def test_listed_in_the_help(run_cli, capsys):
    with pytest.raises(SystemExit):
        run_cli(["--help"])
    assert "privacy" in capsys.readouterr().out


def test_wording_is_a_marked_draft_and_passes_willow_and_the_gate():
    first = TEXT_FILE.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# 草稿：待 G-0") and "G-4 法务" in first
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    notice = load_privacy_text().notice
    assert apply_willow(notice, ContentKind.NORMAL, data.willow) == notice
    assert gate.reasons(notice, kind=ContentKind.NORMAL, stage=HelpStage.S_CLOSING) == ()
    assert not [word for word in FORBIDDEN if word in notice]


def test_loader_rejects_a_bad_file(tmp_path):
    good = yaml.safe_load(TEXT_FILE.read_text(encoding="utf-8"))
    for broken in (
        {**good, "version": 2},
        {"version": 1},
        {**good, "notice": "没有目录"},  # the {data_dir} slot is required
        {**good, "notice": "{data_dir} {city}"},
    ):
        (tmp_path / "privacy.yaml").write_text(yaml.safe_dump(broken), encoding="utf-8")
        with pytest.raises(PrivacyTextError):
            load_privacy_text(tmp_path)
