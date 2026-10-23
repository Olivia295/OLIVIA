"""The wording of ``olivia memory`` / ``olivia forget`` and the store-level helpers (B5).

Every test uses the in-memory keychain from conftest; nothing reaches the OS keychain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from olivia.core.crypto.errors import KeychainUnavailableError
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate, phone_like_runs
from olivia.core.memory.forget import (
    DATA_DIRS,
    DATA_FILES,
    DataStores,
    ForgetTextError,
    forget_all,
    load_forget_text,
)
from olivia.core.models import HelpStage
from olivia.core.taxonomy import load_taxonomy


def test_every_sentence_passes_willow_and_the_gate():
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    for sentence in load_forget_text().all_texts():
        assert apply_willow(sentence, ContentKind.NORMAL, data.willow) == sentence, sentence
        assert gate.reasons(sentence, kind=ContentKind.NORMAL, stage=HelpStage.S_CLOSING) == ()
        assert "！" not in sentence and "!" not in sentence
        assert phone_like_runs(sentence) == (), sentence


def test_text_file_is_validated(tmp_path: Path):
    (tmp_path / "forget.yaml").write_text("version: 1\nmemory: {}\nforget: {}\n", "utf-8")
    with pytest.raises(ForgetTextError):
        load_forget_text(tmp_path)


def test_unknown_slots_and_a_confirm_line_without_the_word_are_rejected(tmp_path: Path):
    packaged = (Path(__file__).parents[2] / "olivia/data/templates/forget.yaml").read_text(
        encoding="utf-8"
    )
    (tmp_path / "forget.yaml").write_text(
        packaged.replace("{count} 张卡", "{name} 张卡"), encoding="utf-8"
    )
    with pytest.raises(ForgetTextError, match="slots"):
        load_forget_text(tmp_path)
    (tmp_path / "forget.yaml").write_text(
        packaged.replace("请输入「确认」", "请输入「好」"), encoding="utf-8"
    )
    with pytest.raises(ForgetTextError, match="confirm_word"):
        load_forget_text(tmp_path)


def test_forget_all_removes_only_what_olivia_owns(tmp_path: Path):
    stores = DataStores.open(tmp_path)
    stores.state.vault.seal("state", b"x")  # creates a key file and the master key
    for name in DATA_FILES:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / f".{DATA_FILES[0]}.abc.tmp").write_bytes(b"x")
    for name in DATA_DIRS:
        (tmp_path / name / "nested").mkdir(parents=True, exist_ok=True)
        (tmp_path / name / "nested" / "f").write_bytes(b"x")
    (tmp_path / "not-ours.txt").write_text("keep", encoding="utf-8")
    assert forget_all(stores) is True
    assert sorted(p.name for p in tmp_path.iterdir()) == ["not-ours.txt"]


def test_forget_all_reports_a_keychain_that_did_not_answer(tmp_path: Path, keychain):
    stores = DataStores.open(tmp_path)
    stores.vault.seal("state", b"x")
    keychain.broken = KeychainUnavailableError("locked")
    assert forget_all(stores) is False
    assert not any(tmp_path.rglob("*.key"))
    assert keychain.items  # the master key is still there
