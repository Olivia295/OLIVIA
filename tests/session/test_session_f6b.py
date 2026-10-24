"""Fix F6b through the session: a goodbye that fits the user's local hour.

Usage testing: at 08:00 or 14:00 local time, "我先下了" still got "愿你今晚过得轻松一点".
An ``after_close`` line that points at the evening (``EVENING_WORDS``: 今晚, 休息, 辛苦了 …)
is now used only from 18:00 local time through the B7 late-night window (00:00-05:00);
at other hours the goodbye comes from ``after_close_daytime``. The same holds for the
line after the closing ritual.

Also (user decision 2026-10-24): while the user tells something heavy (grief, sadness
with a loss situation active, the bereavement spectrum, arousal above
``exploration_allow``), S_clarify adds no unasked lens; it waits for a calmer turn.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from olivia.core.language.data import EVENING_WORDS
from olivia.core.models import HelpStage, PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
SHANGHAI = UserRegion("CN", "Asia/Shanghai")
# Local Shanghai hours (UTC+8) and whether the evening lines may be used then.
HOURS = {8: False, 14: False, 17: False, 18: True, 21: True, 2: True, 5: False}


def _at(local_hour: int) -> datetime:
    return datetime(2026, 10, 24, 0, 30, tzinfo=UTC) + timedelta(hours=local_hour - 8)


def _open(
    now: datetime, persona: PersonaSpectrum, seed: int, region: UserRegion | None = SHANGHAI
) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=now,
        updated_at=now,
        region=region,
        persona_spectrum=persona,
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: now)


def _evening(text: str) -> bool:
    return any(word in text for word in EVENING_WORDS)


def _goodbye(now: datetime, persona: PersonaSpectrum, seed: int) -> str:
    session = _open(now, persona, seed)
    session.turn("今天上班好累")
    result = session.turn("我去睡了")
    tails = [v.rsplit("}", 1)[-1] for v in session._engine.data.templates.after_close]
    assert any(result.reply.endswith(tail) for tail in tails), result.reply
    return result.reply


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
@pytest.mark.parametrize("hour", sorted(HOURS))
def test_the_goodbye_fits_the_local_hour(persona: PersonaSpectrum, hour: int) -> None:
    replies = {_goodbye(_at(hour), persona, seed) for seed in range(12)}
    if HOURS[hour]:
        # Evening and late night: every line may be used, the evening ones included.
        assert any(_evening(r) for r in replies), (persona, hour, replies)
    else:
        assert not any(_evening(r) for r in replies), (persona, hour, replies)


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
def test_the_line_after_the_ritual_fits_the_local_hour(persona: PersonaSpectrum) -> None:
    rituals = 0
    for seed in range(6):
        session = _open(_at(9), persona, seed)
        session.turn("今天上班好累")
        if session.turn("给我一个方法").action_id is None:
            continue
        rituals += 1
        assert session.turn("/done").stage is HelpStage.S_CLOSING
        replies = [session.turn("谢谢你").reply for _ in range(4)]
        assert not any(_evening(r) for r in replies), (persona, replies)
        # Never the same closing text twice in a row, in the daytime pool too.
        for earlier, later in zip(replies, replies[1:], strict=False):
            assert earlier != later
    assert rituals, persona


def test_without_a_saved_region_the_clock_as_given_is_used() -> None:
    morning = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
    for seed in range(12):
        session = _open(morning, PersonaSpectrum.GENTLE_HOLDING, seed, region=None)
        session.turn("今天上班好累")
        assert not _evening(session.turn("我去睡了").reply)


# F6b (user decision 2026-10-24): no unasked S_clarify lens while the user tells something
# heavy; the lens waits for a calmer turn and its once-per-session use is not spent.
def _lens_session(persona: PersonaSpectrum, seed: int, region: UserRegion) -> Session:
    now = datetime(2026, 10, 22, 13, 40, tzinfo=UTC)
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=now,
        updated_at=now,
        region=region,
        persona_spectrum=persona,
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: now)


@pytest.mark.parametrize("seed", range(4))
def test_no_lens_while_telling_a_loss(seed: int) -> None:
    # Usage test 03, turn 3: a breakup (SIT-06-03), then crying over his cup.
    session = _lens_session(
        PersonaSpectrum.ZEN_PHILOSOPHER, seed, UserRegion("HK", "Asia/Hong_Kong")
    )
    session.turn("我们分手了，在一起五年")
    session.turn("他说他累了，不想再继续。我到现在都不敢相信")
    heavy = session.turn("每天下班回到家，看到他留下的杯子就忍不住哭")
    assert heavy.stage is HelpStage.S_CLARIFY
    assert heavy.inspect["emotion"] == "sadness" and "SIT-06-03" in heavy.inspect["situations"]
    assert heavy.inspect["info"] is None and "叙事疗法" not in heavy.reply
    # A calmer turn later still gets the session's one lens.
    calm = session.turn("我总觉得自己做得不够好")
    assert calm.inspect["info"] is not None, calm.reply


@pytest.mark.parametrize("seed", range(4))
def test_no_lens_on_a_turn_above_the_exploration_line(seed: int) -> None:
    session = _lens_session(PersonaSpectrum.GENTLE_HOLDING, seed, SHANGHAI)
    session.turn("今天上班好累")
    session.turn("领导一直催我")
    aroused = session.turn("当着大家的面出错，好丢人")
    assert aroused.stage is HelpStage.S_CLARIFY
    assert aroused.inspect["arousal"] > TAX.threshold("arousal.thresholds.exploration_allow")
    assert aroused.inspect["info"] is None
    assert session.turn("我总觉得自己做得不够好").inspect["info"] is not None


def test_plain_tiredness_is_not_heavy(monkeypatch: pytest.MonkeyPatch) -> None:
    # "真的好累" reads as sadness, but with no loss on the table it is not heavy.
    seen: list[tuple[str, bool]] = []
    heavy = Session._heavy

    def spy(self: Session, perception: Any) -> bool:
        result = heavy(self, perception)
        seen.append((perception.fine_grained_emotion, result))
        return result

    monkeypatch.setattr(Session, "_heavy", spy)
    session = _lens_session(PersonaSpectrum.GENTLE_HOLDING, 0, SHANGHAI)
    for text in ("今天上班好累", "领导一直催我", "每天加班，真的好累"):
        session.turn(text)
    assert seen == [("sadness", False)]
