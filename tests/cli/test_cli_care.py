"""``olivia chat`` across two runs: the gentle check-in after a crisis (PRD §9, step A3)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from cli_support import L3_SENTENCE, NOW, save_profile

from olivia.core.chang.care import CARE_FILENAME, CARE_STORE
from olivia.core.crypto.errors import NoKeychainError
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.spacing import fill
from olivia.core.session import ReplyKind
from olivia.core.taxonomy import load_taxonomy

ASK = "有没有最快的办法离开"
DENIAL = "不是，我就是想辞职"


def _greetings(pool: str) -> set[str]:
    data = load_language_data(load_taxonomy())
    texts = set()
    for variant in getattr(data.templates, pool):
        # Names are filled the way the session fills them ("Olivia 都在", dogfood P8).
        text = fill(variant, {"user_name": "小林", "agent_name": "Olivia"})
        texts.add(f"Olivia：{apply_willow(text, ContentKind.NORMAL, data.willow)}")
    return texts


CRISIS_GREETINGS = _greetings("returning_after_crisis")
LIGHT_GREETINGS = _greetings("returning_after_check")


def _greeting_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line in CRISIS_GREETINGS | LIGHT_GREETINGS]


def test_crisis_then_one_gentle_greeting_then_none(run_cli, data_home):
    save_profile(data_home)
    first = run_cli(["chat", "--rules", "--inspect"], ["今天上班好累", L3_SENTENCE, "/exit"])
    assert first.code == 0 and first.results[-1].reply_kind is ReplyKind.CRISIS
    assert _greeting_lines(first.out) == []
    assert (data_home / CARE_FILENAME).is_file()
    assert (data_home / "keys" / f"{CARE_STORE}.key").is_file()

    second = run_cli(
        ["chat", "--rules", "--inspect"], ["今天上班好累"], now=NOW + timedelta(days=3)
    )
    greeting = _greeting_lines(second.out)
    assert len(greeting) == 1 and greeting[0] in CRISIS_GREETINGS
    # It opens the conversation, before the first reply.
    assert second.out.index(greeting[0]) < second.out.index(f"Olivia：{second.results[0].reply}")
    assert "关怀问候 是" in "\n".join(second.panel)
    assert not (data_home / CARE_FILENAME).exists()

    third = run_cli(["chat", "--rules", "--inspect"], ["今天上班好累"], now=NOW + timedelta(days=4))
    assert _greeting_lines(third.out) == []
    assert "关怀问候 否" in "\n".join(third.panel)


def test_greeting_reveals_nothing_on_screen(run_cli, data_home):
    save_profile(data_home)
    run_cli(["chat", "--rules"], [L3_SENTENCE])
    second = run_cli(["chat", "--rules", "--inspect"], [], now=NOW + timedelta(hours=1))
    (greeting,) = _greeting_lines(second.out)
    for word in ("L2", "L3", "危机", "遗书", "生命", "热线", "12356"):
        assert word not in second.out, word
    assert greeting


def test_a_denied_question_gets_the_lighter_greeting(run_cli, data_home):
    save_profile(data_home)
    first = run_cli(["chat", "--rules"], [ASK, DENIAL, "/exit"])
    assert [r.inspect["safety_check"] for r in first.results] == ["asked", "denied"]
    second = run_cli(["chat", "--rules"], ["今天上班好累"], now=NOW + timedelta(days=1))
    greeting = _greeting_lines(second.out)
    assert len(greeting) == 1 and greeting[0] in LIGHT_GREETINGS


def test_an_ordinary_session_leaves_no_marker(run_cli, data_home):
    save_profile(data_home)
    run_cli(["chat", "--rules"], ["今天上班好累", "给我一个方法吧", "/done"])
    assert not (data_home / CARE_FILENAME).exists()
    # The ledger (B2) has its own key; no care key is made for an ordinary session.
    assert not (data_home / "keys" / "care.key").exists()
    second = run_cli(["chat", "--rules", "--inspect"], ["今天上班好累"])
    assert _greeting_lines(second.out) == []
    assert "关怀问候 否" in "\n".join(second.panel)


def test_a_marker_older_than_seven_days_is_dropped_silently(run_cli, data_home):
    save_profile(data_home)
    run_cli(["chat", "--rules"], [L3_SENTENCE])
    later = run_cli(["chat", "--rules"], ["今天上班好累"], now=NOW + timedelta(days=8))
    assert _greeting_lines(later.out) == []
    assert not (data_home / CARE_FILENAME).exists()


def test_no_keychain_writes_no_marker_and_says_nothing(run_cli, data_home, keychain):
    save_profile(data_home)
    keychain.broken = NoKeychainError("none")
    first = run_cli(["chat", "--rules"], [L3_SENTENCE, "谢谢你"])
    assert first.code == 0 and first.results[0].reply_kind is ReplyKind.CRISIS
    assert not (data_home / CARE_FILENAME).exists()
    # The ledger (B2) has its own key; no care key is made for an ordinary session.
    assert not (data_home / "keys" / "care.key").exists()
    second = run_cli(["chat", "--rules"], ["今天上班好累"])
    assert second.code == 0 and _greeting_lines(second.out) == []


@pytest.mark.parametrize("days", [0, 6])
def test_crisis_on_return_is_handled_as_always(run_cli, data_home, days):
    save_profile(data_home)
    run_cli(["chat", "--rules"], [L3_SENTENCE])
    second = run_cli(["chat", "--rules"], [L3_SENTENCE], now=NOW + timedelta(days=days))
    assert len(_greeting_lines(second.out)) == 1
    (crisis,) = second.results
    assert crisis.reply_kind is ReplyKind.CRISIS and "12356" in crisis.reply
    # The return visit's crisis leaves a fresh marker for the next one.
    third = run_cli(["chat", "--rules"], [], now=NOW + timedelta(days=days + 1))
    assert len(_greeting_lines(third.out)) == 1
