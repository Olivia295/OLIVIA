"""``olivia profile``: see and change both names and the taboo topics (PRD JTBD 4, F11).

Onboarding asks for the user's name, the companion's name and the topics the user does
not want brought up (ONB-02, ONB-04); this numbered menu shows the three and changes one
at a time, with the onboarding checks (:func:`~olivia.core.chang.onboarding.name_hint`,
:func:`~olivia.core.chang.onboarding.parse_taboo`): a reply that fails them gets the
same hint as onboarding and the question again. An empty reply changes nothing. New
topics replace the old list; ``0``, ``清空`` or a skip word ("没有", "无" ...) clears it.
The persona and the region have their own commands, named once under the menu.
``ask_topics`` reads the reply to the topic question (the CLI's screen treats a list of
topic words such as "自杀、死亡、前任" there as topics, QA r3); ``ask`` by default.

The caller loads the profile (and stops for a missing one or an age-gate refusal record,
with ``not_onboarded`` / ``adults_only``); the change is saved through ``save``, which
is ``ProfileStore.save``: one atomic write, in the file form the storage choice asks for.
All wording is in ``olivia/data/templates/onboarding.yaml`` (``profile_command``).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Final

from olivia.core.chang.onboarding import (
    OnboardingText,
    fill_slots,
    is_skip,
    load_onboarding_text,
    name_hint,
    parse_taboo,
    taboo_hint,
)
from olivia.core.models import NAME_MAX_LEN, PersonaProfile

Ask = Callable[[], str | None]
Say = Callable[[str], None]
Save = Callable[[PersonaProfile], bool]
"""Save the profile; False when it could not be saved (the caller has said why)."""

USER_NAME_ITEM: Final = "1"
AGENT_NAME_ITEM: Final = "2"
TABOO_ITEM: Final = "3"
CLEAR_WORDS: Final = ("0", "清空")
"""Replies (besides the skip words) that clear the taboo topics."""
TOPIC_JOINER: Final = "、"


def _fold(answer: str | None) -> str:
    return unicodedata.normalize("NFKC", answer or "").strip().casefold()


def topics_text(topics: tuple[str, ...], text: OnboardingText) -> str:
    """The topics joined for display, or ``no_topics``."""
    return TOPIC_JOINER.join(topics) if topics else text.profile["no_topics"]


def run_profile(
    ask: Ask,
    say: Say,
    profile: PersonaProfile,
    *,
    save: Save,
    now: datetime,
    text: OnboardingText | None = None,
    ask_topics: Ask | None = None,
) -> int:
    """The menu for an adult's ``profile``; the exit status (0 unless the save failed or
    the choice was not on the menu)."""
    words = load_onboarding_text() if text is None else text
    p = words.profile
    say(p["heading"])
    items = (
        (USER_NAME_ITEM, fill_slots(p["user_name_item"], user_name=profile.user_name)),
        (AGENT_NAME_ITEM, fill_slots(p["agent_name_item"], agent_name=profile.agent_name)),
        (TABOO_ITEM, fill_slots(p["taboo_item"], topics=topics_text(profile.taboo_topics, words))),
    )
    for number, line in items:
        say(f"  {number}. {line}")
    say(p["elsewhere"])
    choice = _fold(ask())
    if not choice:
        return 0
    if choice == USER_NAME_ITEM:
        return _change_name(ask, say, profile, save, now, words, user=True)
    if choice == AGENT_NAME_ITEM:
        return _change_name(ask, say, profile, save, now, words, user=False)
    if choice == TABOO_ITEM:
        return _change_topics(ask_topics or ask, say, profile, save, now, words)
    say(p["unknown_choice"])
    return 1


def _change_name(
    ask: Ask,
    say: Say,
    profile: PersonaProfile,
    save: Save,
    now: datetime,
    words: OnboardingText,
    *,
    user: bool,
) -> int:
    p = words.profile
    key = "user_name" if user else "agent_name"
    current = profile.user_name if user else profile.agent_name
    question = fill_slots(p[key], max_len=str(NAME_MAX_LEN), **{key: current})
    hint = ""
    while True:
        say("")
        say(f"{hint}\n\n{question}" if hint else question)
        answer = ask()
        if answer is None:
            return 0
        name = answer.strip()
        if not name or name == current:
            say(p["unchanged"])
            return 0
        problem = name_hint(words, name)
        if problem is None:
            break
        hint = problem
    changed = replace(profile, user_name=name) if user else replace(profile, agent_name=name)
    if not save(replace(changed, updated_at=now)):
        return 1
    say(fill_slots(p[f"{key}_saved"], **{key: name}))
    return 0


def _change_topics(
    ask: Ask,
    say: Say,
    profile: PersonaProfile,
    save: Save,
    now: datetime,
    words: OnboardingText,
) -> int:
    p = words.profile
    hint = ""
    while True:
        say("")
        say(f"{hint}\n\n{p['taboo']}" if hint else p["taboo"])
        answer = ask()
        if answer is None:
            return 0
        if not answer.strip():
            say(p["unchanged"])
            return 0
        clear = _fold(answer) in CLEAR_WORDS or is_skip(words, answer)
        parsed = () if clear else parse_taboo(answer)
        if parsed is not None:
            topics = parsed
            break
        hint = taboo_hint(words)
    if topics == profile.taboo_topics:
        say(p["unchanged"])
        return 0
    if not save(replace(profile, taboo_topics=topics, updated_at=now)):
        return 1
    if topics:
        say(fill_slots(p["taboo_saved"], topics=topics_text(topics, words)))
    else:
        say(p["taboo_cleared"])
    return 0
