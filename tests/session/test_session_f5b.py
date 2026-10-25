"""Quality fix F5b in whole sessions (rules mode): no second safety question once the user
said they are safe, a hint on how to say it, no information card on a note turn, a short
referral on consecutive turns, and an image used at most once while others are left."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.language.engine import paragraphs
from olivia.core.models import CrisisLevel, PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 13, 0, tzinfo=UTC)
PERSONAS = list(PersonaSpectrum)
SAFETY_QUESTIONS = ("安全吗", "是安全的吗")
CN_LINE = "12356"
RENDER = load_language_data(TAX).render


def _session(
    persona: PersonaSpectrum = PersonaSpectrum.GENTLE_HOLDING,
    *,
    seed: int = 1,
    region: UserRegion | None = None,
    clinical_history: tuple[str, ...] = (),
) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=region if region is not None else UserRegion("CN", "Asia/Shanghai"),
        persona_spectrum=persona,
        clinical_history=clinical_history,
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW)


def _run(session: Session, script: list[str]) -> list[TurnResult]:
    return [session.turn(text) for text in script]


def _asks(reply: str) -> bool:
    return any(q in reply for q in SAFETY_QUESTIONS)


# -- 5: no second safety question after a confirmation -------------------------------------


@pytest.mark.parametrize("persona", PERSONAS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_after_the_user_says_they_are_safe_no_reply_asks_again(
    persona: PersonaSpectrum, seed: int
) -> None:
    session = _session(persona, seed=seed)
    entered, confirmed = _run(session, ["我不想活了", "我现在是安全的"])
    assert entered.in_crisis and _asks(entered.reply)
    assert confirmed.in_crisis and confirmed.reply_kind is ReplyKind.CRISIS
    lead = paragraphs(confirmed.reply)[0]
    assert lead in {
        line.replace("{user_name}", "朋友")
        for line in session._engine.data.templates.safety_confirmed
    }
    assert not _asks(confirmed.reply), confirmed.reply
    assert CN_LINE in confirmed.reply
    waiting = [session.turn(text) for text in ("嗯，我在家", "好")]
    for result in waiting:
        if not result.in_crisis:
            break
        assert result.reply_kind is ReplyKind.CRISIS
        assert not _asks(result.reply), result.reply
        assert CN_LINE in result.reply
    assert not waiting[-1].in_crisis


def test_a_new_crisis_turn_after_a_confirmation_asks_again() -> None:
    session = _session()
    _run(session, ["我不想活了", "我现在是安全的"])
    again = session.turn("我还是不想活了")
    assert again.in_crisis and again.crisis_level >= CrisisLevel.L2
    assert _asks(again.reply)
    assert CN_LINE in again.reply


def test_an_im_fine_that_is_no_confirmation_gets_the_hint_once_per_crisis() -> None:
    session = _session()
    hint = RENDER.crisis_confirm_hint
    entered, fine, better = _run(session, ["我不想活了", "我没事", "我已经好多了"])
    assert hint not in entered.reply
    # "我没事" stays a non-confirmation on purpose: the crisis and its question go on.
    assert fine.in_crisis and _asks(fine.reply) and fine.reply.count(hint) == 1
    assert CN_LINE in fine.reply
    assert better.in_crisis and hint not in better.reply and _asks(better.reply)
    confirmed = session.turn("我现在是安全的")
    assert confirmed.in_crisis and not _asks(confirmed.reply)


def test_the_hint_comes_back_in_a_later_crisis() -> None:
    session = _session()
    hint = RENDER.crisis_confirm_hint
    script = ["我不想活了", "我没事", "我现在是安全的", "嗯", "好", "好"]
    results = _run(session, script)
    assert sum(hint in r.reply for r in results) == 1
    assert not results[-1].in_crisis
    again, fine = _run(session, ["我不想活了", "我没事"])
    assert again.in_crisis and hint not in again.reply
    assert hint in fine.reply


# -- 9: a note turn gets no information card ------------------------------------------------

NOTES = ["最近搬家，事情好多", "记住：周四下午要去见搬家公司的人", "记住：我妈生日是11月3号"]
PLAIN = ["最近搬家，事情好多", "周四下午要去见搬家公司的人", "我妈生日是11月3号"]


def test_a_note_turn_never_carries_an_information_card() -> None:
    # The same turn without the note cue gets the S_clarify lens (the usage-run case).
    control = _run(_session(), PLAIN)
    assert control[2].reply_kind is ReplyKind.INFO and control[2].inspect["info"] is not None
    for seed in range(4):
        for result in _run(_session(seed=seed), NOTES):
            assert result.inspect["info"] is None
            assert result.reply_kind is not ReplyKind.INFO
            assert RENDER.info_lens_intro not in result.reply


# -- 12: no verbatim referral on consecutive turns ------------------------------------------

REQUESTS = [
    "我有双相，最近几天睡得很少但精力特别旺，有点停不下来，能给我一个练习吗",
    "我在吃舍曲林，最近效果不好",
    "褪黑素一次吃多少比较好",
    "你觉得我是不是抑郁症",
]


def test_the_same_referral_on_the_next_turn_is_short_and_keeps_the_place() -> None:
    # Two bounds that leave no card (D-3, F13: SIT-02-04 alone now gets its own cards, and a
    # card waiting for feedback is followed by the feedback prompt, not by the referral).
    session = _session(clinical_history=("SIT-02-04", "SIT-10-04"))
    results = _run(session, REQUESTS)
    with_referral = [r for r in results if "SIT-02-04" in r.referral_flags]
    assert len(with_referral) == len(REQUESTS)
    place = f"· {RENDER.referral_destinations['SIT-02-04']}"
    first, *later = with_referral
    assert RENDER.referral_intro in first.reply and RENDER.referral_closing in first.reply
    intros = []
    for result in later:
        assert place in result.reply
        assert RENDER.referral_closing not in result.reply
        intro = next(line for line in RENDER.referral_again if line in result.reply)
        intros.append(intro)
    assert all(a != b for a, b in zip(intros, intros[1:], strict=False))


# -- 12: one image per session while others are left ---------------------------------------

# The usage run (03): the crisis brings the conversation back to S_explore, whose replies
# carry an image; one image came back four times.
BREAKUP = [
    "我们分手了，在一起五年",
    "他说他累了，不想再继续。我到现在都不敢相信",
    "每天下班回到家，看到他留下的杯子就忍不住哭",
    "上个月外婆也走了，我觉得身边的人一个个都在离开",
    "我不想活了",
    "我不知道",
    "我现在是安全的，只是很难过",
    "嗯，我在家，妈妈在隔壁",
    "今天谢谢你",
    "最近总是睡不着",
    "一个人的时候特别难受",
    "还是很想他",
]


@pytest.mark.parametrize("seed", range(10))
def test_no_image_comes_back_in_one_session(seed: int) -> None:
    session = _session(
        PersonaSpectrum.ZEN_PHILOSOPHER, seed=seed, region=UserRegion("HK", "Asia/Hong_Kong")
    )
    metaphors = session._engine.data.metaphors
    images = {
        *metaphors.fallback,
        *(i for cell in metaphors.by_spectrum_yearning.values() for v in cell.values() for i in v),
        *(i for v in metaphors.by_situation.values() for i in v),
    }
    seen: list[str] = []
    for result in _run(session, BREAKUP):
        seen.extend(image for image in images if image in result.reply)
    assert len(seen) == len(set(seen)), seen
