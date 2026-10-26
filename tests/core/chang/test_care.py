"""The cross-session care marker (PRD §9, step A3).

A session that entered the crisis flow (L2/L3), or whose D3 question was answered with a
no, leaves an encrypted marker holding only a time and a kind. The next session within
seven days opens with a gentle greeting, exactly once; older markers are dropped. Without
a keychain nothing is stored. Every test uses the in-memory keychain from conftest.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from olivia.core.chang.care import (
    CARE_FILENAME,
    CARE_STORE,
    MAX_AGE,
    CareKind,
    CareMarker,
    CareRecorder,
    CareStore,
    care_kind,
)
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.crypto.vault import Vault
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.spacing import fill
from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, UserRegion
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
L3_SENTENCE = "我写了一封遗书"
L2_SENTENCE = "我已经站在天台上了"
ASK = "有没有最快的办法离开"
DENIAL = "不是，我就是想辞职"
ORDINARY = ["今天上班好累", "最近工作压力好大", "给我一个方法吧", "/done"]


def _profile(**overrides: object) -> PersonaProfile:
    base = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return replace(base, **overrides)


def _open(seed: int = 3, **overrides: object) -> Session:
    return Session.open(TAX, _profile(**overrides), rng=random.Random(seed), now=lambda: NOW)


def _store(tmp_path, keychain) -> CareStore:
    return CareStore(tmp_path, Vault(tmp_path, keychain))


def _run(store: CareStore, texts: list[str], *, at: datetime = NOW) -> Session:
    """One session, recording care markers the way the CLI does."""
    session = _open()
    recorder = CareRecorder(store, lambda: at)
    for text in texts:
        result = session.turn(text)
        recorder.observe(result, session.snapshot())
    return session


# -- what counts -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texts", "kind"),
    [
        ([L3_SENTENCE], CareKind.L3),
        ([L2_SENTENCE], CareKind.L2),
        ([ASK, DENIAL], CareKind.ASK_DENIED),
        ([ASK, "是的"], CareKind.L2),  # a yes to the question enters the crisis flow
        (ORDINARY, None),
    ],
    ids=["l3", "l2", "ask-denied", "ask-affirmed", "ordinary"],
)
def test_care_kind_follows_the_session(texts, kind):
    session = _open()
    seen = []
    for text in texts:
        result = session.turn(text)
        seen.append(care_kind(result, session.snapshot()))
    assert [k for k in seen if k is not None][-1:] == ([kind] if kind is not None else [])


def test_marker_is_written_on_crisis(tmp_path, keychain):
    store = _store(tmp_path, keychain)
    _run(store, ["今天上班好累", L3_SENTENCE, "谢谢你"])
    assert (tmp_path / CARE_FILENAME).is_file()
    assert store.take(NOW) == CareMarker(NOW, CareKind.L3)


def test_marker_is_written_on_an_l2_crisis(tmp_path, keychain):
    store = _store(tmp_path, keychain)
    _run(store, [L2_SENTENCE])
    assert store.take(NOW) == CareMarker(NOW, CareKind.L2)


def test_marker_is_written_on_a_denied_direct_question(tmp_path, keychain):
    store = _store(tmp_path, keychain)
    _run(store, [ASK, DENIAL, "最近工作压力好大"])
    marker = store.take(NOW)
    assert marker == CareMarker(NOW, CareKind.ASK_DENIED) and marker.light


def test_no_marker_for_an_ordinary_session(tmp_path, keychain):
    store = _store(tmp_path, keychain)
    _run(store, ORDINARY)
    assert list(tmp_path.iterdir()) == []  # no marker, no data key
    assert keychain.items == {}
    assert store.take(NOW) is None


def test_a_crisis_after_a_denial_raises_the_marker_and_nothing_lowers_it(tmp_path, keychain):
    store = _store(tmp_path, keychain)
    _run(store, [ASK, DENIAL, L3_SENTENCE, L2_SENTENCE, "谢谢你"])
    assert store.take(NOW) == CareMarker(NOW, CareKind.L3)


def test_marker_is_written_on_the_crisis_turn_itself(tmp_path, keychain):
    """Ctrl-C or a crash right after the crisis turn still leaves the marker."""
    store = _store(tmp_path, keychain)
    session = _open()
    recorder = CareRecorder(store, lambda: NOW)
    result = session.turn(L3_SENTENCE)
    assert not (tmp_path / CARE_FILENAME).exists()
    recorder.observe(result, session.snapshot())
    assert (tmp_path / CARE_FILENAME).is_file()


def test_an_unread_stronger_marker_is_not_lowered(tmp_path, keychain):
    store = _store(tmp_path, keychain)
    store.save(CareMarker(NOW - timedelta(days=1), CareKind.L3))
    store.save(CareMarker(NOW, CareKind.ASK_DENIED))
    assert store.take(NOW) == CareMarker(NOW, CareKind.L3)


# -- at rest ---------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(CareKind))
def test_marker_is_encrypted_at_rest(tmp_path, keychain, kind):
    store = _store(tmp_path, keychain)
    marker = CareMarker(datetime(2026, 10, 22, 15, 4, 5, tzinfo=UTC), kind)
    assert store.save(marker)
    raw = (tmp_path / CARE_FILENAME).read_bytes()
    for plain in (kind.value, f'"{kind.value}"', "2026-10-22", "15:04:05", '"kind"', '"at"'):
        assert plain.encode() not in raw, plain
    assert (tmp_path / "keys" / f"{CARE_STORE}.key").is_file()
    assert not (tmp_path / ".snapshots").exists()  # no older copy survives a take
    assert store.take(marker.at) == marker


def test_no_keychain_means_no_file(tmp_path, keychain):
    keychain.broken = NoKeychainError("none")
    store = _store(tmp_path, keychain)
    _run(store, [L3_SENTENCE, "谢谢你"])
    assert list(tmp_path.iterdir()) == []
    assert store.take(NOW) is None


def test_no_keychain_is_not_retried_every_turn(tmp_path, keychain):
    keychain.broken = NoKeychainError("none")
    store = _store(tmp_path, keychain)
    calls = []
    original = store.save

    def counting(marker: CareMarker) -> bool:
        calls.append(marker.kind)
        return original(marker)

    store.save = counting  # type: ignore[method-assign]
    _run(store, [L3_SENTENCE, L3_SENTENCE, L3_SENTENCE])
    assert calls == [CareKind.L3]


def test_a_locked_keychain_keeps_the_marker_for_later(tmp_path, keychain):
    store = _store(tmp_path, keychain)
    store.save(CareMarker(NOW, CareKind.L2))
    keychain.broken = KeychainUnavailableError("locked")
    assert _store(tmp_path, keychain).take(NOW) is None
    assert (tmp_path / CARE_FILENAME).is_file()
    keychain.broken = None
    assert _store(tmp_path, keychain).take(NOW) == CareMarker(NOW, CareKind.L2)


@pytest.mark.parametrize("damage", ["garbage", "truncated", "flipped"])
def test_a_damaged_marker_is_dropped_silently(tmp_path, keychain, damage):
    store = _store(tmp_path, keychain)
    store.save(CareMarker(NOW, CareKind.L3))
    path = tmp_path / CARE_FILENAME
    raw = bytearray(path.read_bytes())
    if damage == "garbage":
        raw = bytearray(b"not a marker")
    elif damage == "truncated":
        raw = raw[:5]
    else:
        raw[-1] ^= 0x80
    path.write_bytes(bytes(raw))
    assert _store(tmp_path, keychain).take(NOW) is None
    assert not path.exists()


# -- the greeting window ---------------------------------------------------------------------


def test_greeting_marker_is_taken_exactly_once(tmp_path, keychain):
    store = _store(tmp_path, keychain)
    store.save(CareMarker(NOW, CareKind.L3))
    later = NOW + timedelta(days=2)
    assert _store(tmp_path, keychain).take(later) == CareMarker(NOW, CareKind.L3)
    assert not (tmp_path / CARE_FILENAME).exists()
    assert _store(tmp_path, keychain).take(later) is None


@pytest.mark.parametrize(
    ("age", "kept"),
    [
        (timedelta(0), True),
        (MAX_AGE, True),
        (MAX_AGE + timedelta(seconds=1), False),
        (timedelta(days=30), False),
    ],
)
def test_markers_older_than_seven_days_are_discarded_silently(tmp_path, keychain, age, kept):
    assert timedelta(days=7) == MAX_AGE
    store = _store(tmp_path, keychain)
    store.save(CareMarker(NOW, CareKind.L2))
    taken = _store(tmp_path, keychain).take(NOW + age)
    assert (taken is not None) is kept
    assert not (tmp_path / CARE_FILENAME).exists()


def test_shred_makes_the_marker_unreadable_and_spares_other_stores(tmp_path, keychain):
    vault = Vault(tmp_path, keychain)
    other = vault.seal("profile", b"kept")
    store = CareStore(tmp_path, vault)
    store.save(CareMarker(NOW, CareKind.L3))
    blob = (tmp_path / CARE_FILENAME).read_bytes()
    store.shred()
    assert not (tmp_path / CARE_FILENAME).exists()
    assert not vault.has_data_key(CARE_STORE)
    assert Vault(tmp_path, keychain).open("profile", other) == b"kept"
    # A lingering copy of the file can never be opened again.
    (tmp_path / CARE_FILENAME).write_bytes(blob)
    assert _store(tmp_path, keychain).take(NOW) is None


def test_shred_without_a_marker_is_harmless(tmp_path, keychain):
    _store(tmp_path, keychain).shred()
    assert keychain.items == {}


# -- the greeting itself ---------------------------------------------------------------------


def _filled(pool: tuple[str, ...]) -> set[str]:
    willow = load_language_data(TAX).willow
    texts = set()
    for variant in pool:
        # Names are filled the way the session fills them ("我是 Olivia", dogfood P8).
        text = fill(variant, {"user_name": "小林", "agent_name": "Olivia"})
        texts.add(apply_willow(text, ContentKind.NORMAL, willow))
    return texts


@pytest.mark.parametrize("light", [False, True], ids=["crisis", "ask-denied"])
def test_session_greeting_comes_from_the_right_pool_and_shows_in_inspect(light):
    templates = load_language_data(TAX).templates
    pool = templates.returning_after_check if light else templates.returning_after_crisis
    session = _open()
    assert session.snapshot()["care_greeting"] is False
    greeting = session.care_greeting(light=light)
    assert greeting in _filled(pool)
    assert session.snapshot()["care_greeting"] is True
    result = session.turn("今天上班好累")
    assert result.inspect["care_greeting"] is True
    assert _open().turn("今天上班好累").inspect["care_greeting"] is False


def test_session_greeting_respects_taboo_topics():
    templates = load_language_data(TAX).templates
    for seed in range(8):
        greeting = _open(seed, taboo_topics=("欢迎",)).care_greeting()
        assert "欢迎" not in greeting
        assert greeting in _filled(templates.returning_after_crisis)


def test_crisis_on_return_is_unchanged():
    greeted = _open()
    greeted.care_greeting()
    plain = _open()
    for text in ["今天上班好累", L3_SENTENCE, L2_SENTENCE]:
        a, b = greeted.turn(text), plain.turn(text)
        assert (a.reply_kind, a.stage, a.crisis_level, a.in_crisis) == (
            b.reply_kind,
            b.stage,
            b.crisis_level,
            b.in_crisis,
        )
        assert a.resource_card == b.resource_card
        assert {k: v for k, v in a.inspect.items() if k != "care_greeting"} == {
            k: v for k, v in b.inspect.items() if k != "care_greeting"
        }
    assert a.reply_kind is ReplyKind.CRISIS and a.stage is HelpStage.S_CRISIS
    assert a.resource_card is not None and a.resource_card.level is CrisisLevel.L3
