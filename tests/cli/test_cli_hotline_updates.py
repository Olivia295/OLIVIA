"""GEO-08 / F14: a signed hotline update in ``<data dir>/resources/`` reaches the product.

``olivia resources`` and ``olivia chat`` use the update only when its signature verifies
and it is newer than the built-in data, and ``olivia resources`` says which data it shows.
Every test signs with a throwaway key: the public key is monkeypatched and the built-in
data replaced by a fixture signed with the same key. The real signing key is never read.
"""

from __future__ import annotations

import base64
import copy
from pathlib import Path

import pytest
import yaml
from cli_support import save_profile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_cli_resources_region import FIXED_NOW, FIXTURE

from olivia.core.models import UserRegion
from olivia.core.resources import bundle, keys
from olivia.core.storage import data_dir_location

UPDATED_TEXT_LINE = "85258"


def _yaml(compiled_on: str, *, text_line: str = "85000") -> bytes:
    doc = copy.deepcopy(FIXTURE)
    doc["compiled_on"] = compiled_on
    for line in doc["regions"]["GB"]["lines"]:
        if line["id"] == "gb_fixture_text":
            line["number"] = text_line
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False).encode("utf-8")


def _sign(key: Ed25519PrivateKey, data: bytes) -> bytes:
    return base64.b64encode(key.sign(data)) + b"\n"


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> Ed25519PrivateKey:
    """A throwaway key; the built-in data becomes FIXTURE (2026-01-15) signed with it."""
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    monkeypatch.setattr(keys, "HOTLINE_PUBLIC_KEY_B64", base64.b64encode(raw).decode("ascii"))
    builtin = _yaml("2026-01-15")
    monkeypatch.setattr(bundle, "_read_builtin", lambda: (builtin, _sign(private, builtin)))
    return private


def _update(home: Path, data: bytes, signature: bytes | None) -> Path:
    folder = home / bundle.OVERRIDE_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    (folder / bundle.DATA_NAME).write_bytes(data)
    if signature is not None:
        (folder / bundle.SIG_NAME).write_bytes(signature)
    return folder


def test_the_update_folder_is_resources_in_the_data_directory(data_home: Path) -> None:
    assert bundle.override_dir_location() == data_dir_location() / "resources"
    assert bundle.override_dir_location() == data_home / "resources"
    assert not data_home.exists()  # locating it creates nothing


def test_resources_shows_a_valid_update_and_its_date(run_cli, data_home, key) -> None:
    save_profile(data_home, region=UserRegion("GB", "Europe/London"))
    data = _yaml("2026-02-20", text_line=UPDATED_TEXT_LINE)
    _update(data_home, data, _sign(key, data))
    run = run_cli(["resources"], now=FIXED_NOW)
    assert run.code == 0
    assert f"· 测试短信线：{UPDATED_TEXT_LINE}\n" in run.out
    assert "· 测试短信线：85000" not in run.out
    assert run.out.endswith(
        "资料整理于 2026-02-20（第 1 版）\n资料来源：更新包（整理于 2026-02-20，签名已验证）\n"
    )


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda key, data: _sign(key, b"something else"), "签名验证没有通过"),
        (lambda key, data: _sign(Ed25519PrivateKey.generate(), data), "签名验证没有通过"),
        (lambda key, data: None, "缺少签名文件"),
    ],
)
def test_resources_falls_back_to_the_builtin_data_without_a_valid_signature(
    run_cli, data_home, key, make, reason
) -> None:
    save_profile(data_home, region=UserRegion("GB", "Europe/London"))
    data = _yaml("2026-02-20", text_line=UPDATED_TEXT_LINE)
    _update(data_home, data, make(key, data))
    run = run_cli(["resources"], now=FIXED_NOW)
    assert run.code == 0
    assert UPDATED_TEXT_LINE not in run.out
    assert "· 测试短信线：85000" in run.out
    assert run.out.endswith(
        f"资料整理于 2026-01-15（第 1 版）\n资料来源：随程序附带（更新包未启用：{reason}）\n"
    )


@pytest.mark.parametrize(
    ("compiled_on", "reason"),
    [("2026-01-15", "不比随程序附带的资料新"), ("2026-03-02", "整理日期晚于今天")],
)
def test_resources_ignores_an_update_that_is_not_newer_or_from_the_future(
    run_cli, data_home, key, compiled_on, reason
) -> None:
    save_profile(data_home, region=UserRegion("GB", "Europe/London"))
    data = _yaml(compiled_on, text_line=UPDATED_TEXT_LINE)
    _update(data_home, data, _sign(key, data))
    run = run_cli(["resources"], now=FIXED_NOW)  # today is 2026-03-01
    assert UPDATED_TEXT_LINE not in run.out
    assert run.out.endswith(f"资料来源：随程序附带（更新包未启用：{reason}）\n")


def test_resources_without_an_update_says_builtin(run_cli, data_home, key) -> None:
    run = run_cli(["resources"], now=FIXED_NOW)
    assert "资料来源：随程序附带\n" in run.out
    assert "更新包" not in run.out
    assert not (data_home / bundle.OVERRIDE_DIR_NAME).exists()  # looking creates nothing


def test_chat_uses_a_valid_update_for_the_crisis_card(run_cli, data_home, key) -> None:
    save_profile(data_home, region=UserRegion("GB", "Europe/London"))
    data = _yaml("2026-02-20", text_line=UPDATED_TEXT_LINE)
    _update(data_home, data, _sign(key, data))
    run = run_cli(["chat", "--rules", "--inspect"], ["我不想活了", "/exit"])
    assert run.code == 0
    assert run.results[0].inspect["hotline_source"] == "override"
    assert run.results[0].inspect["hotline_reason"] is None
    assert UPDATED_TEXT_LINE in run.results[0].reply
    assert "└ 热线数据 override\n" in run.out


def test_chat_ignores_a_tampered_update(run_cli, data_home, key) -> None:
    save_profile(data_home, region=UserRegion("GB", "Europe/London"))
    data = _yaml("2026-02-20", text_line=UPDATED_TEXT_LINE)
    _update(data_home, data, _sign(key, _yaml("2026-02-20")))
    run = run_cli(["chat", "--rules", "--inspect"], ["我不想活了", "/exit"])
    assert run.results[0].inspect["hotline_source"] == "builtin"
    assert run.results[0].inspect["hotline_reason"] == bundle.REASON_SIG_INVALID
    assert UPDATED_TEXT_LINE not in run.out
    assert "85000" in run.results[0].reply
