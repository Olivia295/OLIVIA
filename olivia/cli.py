"""The ``olivia`` command line (roadmap P2-4, P4-4).

``olivia chat [--inspect] [--model]``
    First visit runs onboarding (``chang/onboarding.py``); then each line goes to
    ``Session.turn`` and the reply is printed exactly as returned, crisis cards included.
    The crisis screen uses the rules alone; ``--model`` (experimental, off by default
    until a student passes the release gate) also consults the packaged perception
    student, which can only raise the rule level and is capped at L2, and takes valence,
    emotion, intent, stance, readiness and (without a spectrum cue) the spectrum from its
    other heads; arousal is the higher of the rule and model values (roadmap C1).
    ``/exit``, end of input or Ctrl-C end the conversation with one goodbye line. The
    feedback commands (``/done``, ``/not-now``, ``/unhelpful``) are ordinary input here,
    as are natural-language replies to a card ("今天先不做了"): the session's perception
    reads them.
``olivia resources``
    The crisis-resource card for the saved region in BROWSING mode.
``olivia region [CODE [--timezone TZ] | --clear]``
    Show, set or clear the saved country/region (country level only, SDD §8.3).
``olivia health``
    Show and change the recorded health information (clinical-history codes and the
    D2 disclosures), interactively with numbered choices (``chang/health.py``); it is
    always saved encrypted.
``olivia persona [CHOICE]``
    Show the four companion personas with the saved one marked, or switch to CHOICE (a
    number, short name or enum value; PRD JTBD 4, ONB-03). The next ``olivia chat`` uses it.
``olivia --version``
    The installed version, read from the package metadata.

The CLI writes the profile (``chang/profile.py``: region, timezone and the onboarding
answers) through ``storage.atomic_write_text``, the memory ledger (``core/memory``,
decision D1: one templated summary per session plus the notes the user asked to have
remembered, always encrypted) and, once there is something to encrypt, the wrapped data
keys under ``keys/`` (``core/crypto``). Health information is always encrypted, the whole
profile when the user chose that (ONB-06). After a crisis (or a no to the direct question
about intent) ``chat`` also writes the care marker (``chang/care.py``): a time and a level,
always encrypted, never written without a keychain. The next ``chat`` within seven days
opens with a gentle check-in and removes it (PRD §9, step A3). ``chat`` also keeps the
bandit's posteriors and the kit between sessions (``memory/state.py``, step B3: action ids,
numbers and times, always encrypted, saved after each turn that changes them and at every
exit), so the next session's choices follow earlier feedback and "上次存的那个" finds the
card shelved last time. Conversation text and perception output are never written
anywhere; the ledger keeps only ids, levels and times, and the session summary is written
at every exit (``/exit``, end of input, Ctrl-C) and whenever the session closes itself
(S_closing -> S_ready). Without a keychain nothing is remembered, and the user is told so
once per device.

The ``--inspect`` panel (SDD §10.2, ruling 27) prints ids, levels and numbers from
``TurnResult.inspect``, and never the user's text, the reply text or anything below
country level. The CLI makes no network calls.
"""

from __future__ import annotations

import argparse
import functools
import random
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from importlib import metadata
from typing import Final, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from olivia import __version__
from olivia.core.chang.care import CareRecorder, CareStore
from olivia.core.chang.health import HealthDone, HealthEditor, HealthPrompt
from olivia.core.chang.onboarding import (
    DEFAULT_TIMEZONES,
    FALLBACK_TIMEZONE,
    PERSONA_CHOICES,
    TIMEZONE_CHOICES,
    Completed,
    OnboardingFlow,
    Prompt,
    Refused,
    canonical_timezone,
    load_onboarding_text,
    persona_from_reply,
)
from olivia.core.chang.profile import ProfileCorruptError, ProfileLockedError, ProfileStore
from olivia.core.language.data import load_language_data
from olivia.core.memory.ledger import Ledger
from olivia.core.memory.recorder import SessionRecorder
from olivia.core.memory.state import StateRecorder, StateStore
from olivia.core.models import (
    UNKNOWN_COUNTRY,
    CrisisLevel,
    PersonaProfile,
    PersonaSpectrum,
    UserRegion,
)
from olivia.core.resources.bundle import load_hotlines_bytes
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.resolver import resolve, resolve_region_code
from olivia.core.resources.store import LineKind, ResourceStore, parse_store
from olivia.core.session import Session, TurnResult
from olivia.core.taxonomy import Taxonomy, load_taxonomy

Clock = Callable[[], datetime]

# One taxonomy object per process, so repeated commands share the session's loaded data.
_taxonomy = functools.cache(load_taxonomy)

EXIT_COMMAND: Final = "/exit"

# -- user-facing text (short, warm, no diagnosis words; checked against WILLOW in tests) ---

GOODBYE: Final = "好，今天就先聊到这里。想说话的时候，随时回来。"
CHAT_HINT: Final = "想结束的时候，输入 /exit 就好。"
USER_PROMPT: Final = "你："
ANSWER_PROMPT: Final = "> "
PROFILE_CORRUPT: Final = "本地的设置文件读不出来了。为了不弄丢你的信息，我没有改动它。"
PROFILE_LOCKED: Final = (
    "加密保存的信息现在打不开：系统钥匙串没有响应，或者钥匙已经不在这台电脑上了。"
    "你的文件我没有改动。"
)
HEALTH_NOT_SAVED: Final = (
    "这台电脑上没有可用的系统钥匙串，健康信息没办法加密保存，所以之前记下的健康信息已经删除了。"
    "其他的一切都照常。"
)
NOT_ONBOARDED: Final = "还没有完成第一次设置。先运行 olivia chat，之后就可以修改地区了。"
NO_REGION: Final = "还没有保存地区。"
ADULTS_ONLY: Final = "这里的陪伴只为成年人设计，所以不会保存地区信息。"
REGION_SHOW: Final = "地区：{label}（{code}）\n时区：{timezone}"
REGION_SAVED: Final = "好的，已经保存：{label}（{code}），时区 {timezone}。"
REGION_FALLBACK: Final = (
    "暂时没有「{raw}」这个地区的资料，已按其他地区（ZZ）保存，求助卡片会显示全球通用的资源。"
)
REGION_NEEDS_TIMEZONE: Final = (
    "{label}有好几个时区，请用 --timezone 告诉我是哪一个，例如：{choices}"
)
REGION_BAD_TIMEZONE: Final = (
    "没有认出时区「{timezone}」。可以用「大洲/城市」的格式，例如 Asia/Singapore。"
)
REGION_CLEARED: Final = "已清除保存的地区和时区。求助卡片会显示全球通用的资源。"
REGION_CLEAR_WITH_CODE: Final = "--clear 不能和地区代码一起用。"
RESOURCES_TITLE: Final = "求助资源 · {label}（{code}）"
RESOURCES_SET_REGION: Final = "告诉我你所在的国家或地区后，就能显示当地的电话：olivia region <代码>"
RESOURCES_EMERGENCY: Final = "紧急电话："
RESOURCES_HOURS: Final = "服务时间："
RESOURCES_FOOTER: Final = "资料整理于 {compiled_on}（第 {version} 版）"
OTHER_REGION_LABEL: Final = "其他地区"
PERSONA_SHOW: Final = "现在的陪伴方式：{label}"
PERSONA_CHOICES_HEADING: Final = "可以选择的陪伴方式："
PERSONA_CURRENT_MARK: Final = "（当前）"
PERSONA_HOW_TO: Final = "想换的话，输入 olivia persona 加序号或简称，例如：olivia persona 2"
PERSONA_SAVED: Final = "好的，之后我会用「{name}」的方式陪你，下次打开 olivia chat 时生效。"
PERSONA_UNCHANGED: Final = "现在用的就是「{name}」，不用改动。"
PERSONA_UNKNOWN: Final = "没有认出「{raw}」。可以用下面的序号或简称："
PERSONA_NOT_ONBOARDED: Final = (
    "还没有完成第一次设置。先运行 olivia chat，之后就可以更换陪伴方式了。"
)
PERSONA_ADULTS_ONLY: Final = "这里的陪伴只为成年人设计，所以没有可以更换的陪伴方式。"
LINE_KIND_HEADINGS: Final = {
    LineKind.CRISIS_HOTLINE: "心理援助与危机热线：",
    LineKind.TEXT_LINE: "短信与文字求助：",
    LineKind.YOUTH_LINE: "青少年热线：",
    LineKind.DIRECTORY_URL: "求助热线目录：",
}
_UNKNOWN_HOURS: Final = "unknown"

USER_TEXTS: Final = (
    GOODBYE,
    CHAT_HINT,
    PROFILE_CORRUPT,
    PROFILE_LOCKED,
    HEALTH_NOT_SAVED,
    NOT_ONBOARDED,
    NO_REGION,
    ADULTS_ONLY,
    REGION_SHOW,
    REGION_SAVED,
    REGION_FALLBACK,
    REGION_NEEDS_TIMEZONE,
    REGION_BAD_TIMEZONE,
    REGION_CLEARED,
    REGION_CLEAR_WITH_CODE,
    RESOURCES_TITLE,
    RESOURCES_SET_REGION,
    RESOURCES_EMERGENCY,
    RESOURCES_HOURS,
    RESOURCES_FOOTER,
    OTHER_REGION_LABEL,
    PERSONA_SHOW,
    PERSONA_CHOICES_HEADING,
    PERSONA_CURRENT_MARK,
    PERSONA_HOW_TO,
    PERSONA_SAVED,
    PERSONA_UNCHANGED,
    PERSONA_UNKNOWN,
    PERSONA_NOT_ONBOARDED,
    PERSONA_ADULTS_ONLY,
    *LINE_KIND_HEADINGS.values(),
)
"""Every sentence the CLI itself says, for the WILLOW and gate checks in the tests."""


@dataclass
class _Console:
    stdin: TextIO
    stdout: TextIO

    def say(self, text: str = "") -> None:
        self.stdout.write(f"{text}\n")
        self.stdout.flush()

    def ask(self, prompt: str) -> str | None:
        """One input line without its newline; None at end of input."""
        if self.stdin is sys.stdin and self.stdin.isatty():  # pragma: no cover - terminal only
            try:
                return input(prompt)
            except EOFError:
                return None
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        # Piped input is not echoed, so end the prompt line here (the text is not shown).
        self.stdout.write("\n")
        if not line:
            return None
        return line.rstrip("\r\n")


def _system_clock() -> datetime:
    return datetime.now(UTC)


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _local_clock(clock: Clock, profile: PersonaProfile) -> Clock:
    """``clock`` in the profile's timezone (UTC if the zone is unknown on this machine)."""
    zone = _zone(profile.region.timezone) if profile.region is not None else None
    if zone is None:
        return clock
    return lambda: clock().astimezone(zone)


# -- chat ------------------------------------------------------------------------------------


def _show_prompt(console: _Console, prompt: Prompt) -> None:
    console.say(prompt.text)
    for number, option in enumerate(prompt.options, start=1):
        console.say(f"  {number}. {option}")


def _onboard(
    console: _Console, tax: Taxonomy, store: ProfileStore, now: datetime
) -> PersonaProfile | None:
    """Run (or skip) onboarding; the adult profile, or None when the visit ends here."""
    flow = OnboardingFlow(tax, store, now)
    outcome = flow.outcome
    if outcome is None:
        step: Prompt | Completed | Refused = flow.prompt()
        while isinstance(step, Prompt):
            _show_prompt(console, step)
            answer = console.ask(ANSWER_PROMPT)
            if answer is None:
                console.say(GOODBYE)
                return None
            console.say()
            step = flow.answer(answer)
        outcome = step
    if isinstance(outcome, Refused):
        console.say(outcome.text)
        return None
    if outcome.text:
        console.say(outcome.text)
        console.say()
    return outcome.profile


def _fmt(value: object) -> str:
    if value is None or value == [] or value == "":
        return "-"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def inspect_panel(result: TurnResult) -> list[str]:
    """The ``--inspect`` lines for one turn: ids, levels and numbers only.

    Only whitelisted keys of ``result.inspect`` are read, plus the reply kind and the
    resource card's country-level region; the reply and the user's text never are.
    """
    data = result.inspect
    card = result.resource_card
    origin = data.get("feedback_source")
    check = data.get("safety_check")
    mirror = data.get("schema_mirror")
    lines = [
        f"┌ inspect · 第 {_fmt(data.get('turn'))} 轮",
        f"│ 风险 {_fmt(data.get('level'))}（本轮筛查 {_fmt(data.get('assessed_level'))}）"
        f" · 危机中 {_fmt(data.get('in_crisis'))} · 线索 {_fmt(data.get('cue_ids'))}"
        f" · 关怀问候 {_fmt(data.get('care_greeting'))}",
        f"│ 状态 {_fmt(data.get('previous_stage'))} → {_fmt(data.get('stage'))}"
        f"（{_fmt(data.get('reason'))}） · 纯倾听锁 {_fmt(data.get('lock'))}",
        f"│ 唤醒 {_fmt(data.get('arousal'))} · 电量 {_fmt(data.get('battery'))}"
        f" · 谱系 {_fmt(data.get('spectrum'))} · 红线 {_fmt(data.get('red_flags'))}",
        f"│ 禁忌 {_fmt(data.get('contraindications'))} · 情境 {_fmt(data.get('situations'))}",
        f"│ 效价 {_fmt(data.get('valence'))} · 情绪 {_fmt(data.get('emotion'))}"
        f" · 意图 {_fmt(data.get('intent'))} · 姿态 {_fmt(data.get('stance'))}"
        f" · 准备度 {_fmt(data.get('readiness'))}",
        f"│ 认知扭曲 {_fmt(data.get('distortions'))} · 图式 {_fmt(data.get('schemas'))}"
        f" · 渴望 {_fmt(data.get('yearning'))}" + (f" · 图式镜像 {_fmt(mirror)}" if mirror else ""),
        f"│ 可用动作 {_fmt(data.get('candidates'))} · 选中 {_fmt(data.get('chosen'))}"
        f" · 反馈 {_fmt(data.get('feedback'))}" + (f"（来源 {_fmt(origin)}）" if origin else ""),
        f"│ 回复 {result.reply_kind.value} · 审查拦截 {_fmt(data.get('gate'))}"
        + (f" · 资源卡 {card.region_used} {card.level.name}" if card is not None else "")
        + (f" · 意图确认 {_fmt(check)}" if check else ""),
    ]
    model_reason = data.get("risk_model_reason")
    lines.append(
        f"│ 风险模型 {_fmt(data.get('risk_model'))}"
        + (f"（{model_reason}）" if model_reason else "")
        + f" · 模型判断 {_fmt(data.get('model_level'))}"
        + f" · 模型分数 {_fmt(data.get('model_score'))}"
    )
    source = _fmt(data.get("hotline_source"))
    reason = data.get("hotline_reason")
    lines.append(f"└ 热线数据 {source}" + (f"（{reason}）" if reason else ""))
    return lines


def _chat(
    console: _Console,
    inspect: bool,
    clock: Clock,
    rng: random.Random | None,
    *,
    student: bool = False,
) -> int:
    tax = _taxonomy()
    store = ProfileStore()
    try:
        profile = _onboard(console, tax, store, clock())
    except ProfileCorruptError:
        console.say(PROFILE_CORRUPT)
        return 1
    except ProfileLockedError:
        console.say(PROFILE_LOCKED)
        return 1
    if store.dropped_sensitive_data:
        console.say(HEALTH_NOT_SAVED)
    if profile is None:
        return 0
    local = _local_clock(clock, profile)
    # The posteriors and the kit from earlier sessions (B3); None starts fresh.
    state_store = StateStore(store.path.parent, store.vault)
    session = Session.open(
        tax,
        profile,
        rng=rng if rng is not None else random.Random(),
        now=local,
        student=student,
        carried=state_store.load(),
    )
    state_recorder = StateRecorder(state_store, session.carried_state())
    ledger = Ledger(store.path.parent, store.vault, method_titles=_card_titles(tax))
    recorder = SessionRecorder(ledger, session.state.session_id, local)
    if not recorder.enabled and ledger.take_unavailable_notice():
        console.say(ledger.text.replies["memory_unavailable"])
    console.say(CHAT_HINT)
    care = CareStore(vault=store.vault)
    marker = care.take(clock())
    if marker is not None:
        console.say(f"{profile.agent_name}：{session.care_greeting(light=marker.light)}")
        console.say()
    care_recorder = CareRecorder(care, clock)
    try:
        while True:
            line = console.ask(USER_PROMPT)
            if line is None or line.strip() == EXIT_COMMAND:
                break
            if not line.strip():
                continue
            result = recorder.observe(line, session.turn(line))
            # The reply (a crisis card included) is on screen before any keychain access.
            console.say(f"{profile.agent_name}：{result.reply}")
            care_recorder.observe(result, session.snapshot())
            state_recorder.observe(session.carried_state())  # feedback survives a crash
            if inspect:
                for panel_line in inspect_panel(result):
                    console.say(panel_line)
            console.say()
    finally:  # Ctrl-C included: main() says goodbye after this
        if not recorder.close():
            console.say(ledger.text.replies["summary_not_saved"])
        state_recorder.observe(session.carried_state())
    console.say(GOODBYE)
    return 0


def _card_titles(tax: Taxonomy) -> dict[str, str]:
    """Action id -> the exercise card title the user saw, for the ledger's summaries."""
    return {aid: card.title for aid, card in load_language_data(tax).cards.cards.items()}


# -- resources and region ---------------------------------------------------------------------


def _load_store(today: date) -> ResourceStore:
    """The same verified hotline data a session uses."""
    bundle = load_hotlines_bytes(None, today=today)
    return parse_store(yaml.safe_load(bundle.data))


def _region_label(code: str) -> str:
    if code == UNKNOWN_COUNTRY:
        return OTHER_REGION_LABEL
    return load_onboarding_text().region_labels.get(code, OTHER_REGION_LABEL)


def render_browsing(card: ResourceCard, tax: Taxonomy) -> str:
    """BROWSING card text: emergency numbers, then lines grouped by kind, stale marked."""
    if card.mode is not CardMode.BROWSING:
        raise ValueError("render_browsing needs a BROWSING-mode card")
    render = load_language_data(tax).render
    stale = set(card.stale_entries)

    def mark(entry_id: str) -> str:
        return render.crisis_stale_mark if entry_id in stale else ""

    blocks = [RESOURCES_TITLE.format(label=_region_label(card.region_used), code=card.region_used)]
    emergency = [RESOURCES_EMERGENCY]
    for em in card.emergency:
        purpose = render.emergency_purposes[em.purpose]
        emergency.append(f"· {em.number}（{purpose}）{mark(em.id)}")
    blocks.append("\n".join(emergency))
    for kind, group in card.lines_by_kind():
        lines = [LINE_KIND_HEADINGS[kind]]
        for ln in group:
            lines.append(f"· {ln.name_zh}：{ln.number}{mark(ln.id)}")
            if ln.hours != _UNKNOWN_HOURS and kind is not LineKind.DIRECTORY_URL:
                lines.append(f"  {RESOURCES_HOURS}{ln.hours}")
        blocks.append("\n".join(lines))
    blocks.append(
        RESOURCES_FOOTER.format(
            compiled_on=card.compiled_on.isoformat(), version=card.directory_version
        )
    )
    return "\n\n".join(blocks)


def _load_profile(console: _Console) -> tuple[bool, PersonaProfile | None]:
    """(readable, profile); an unreadable profile is reported and never overwritten."""
    store = ProfileStore()
    try:
        profile = store.load()
    except ProfileCorruptError:
        console.say(PROFILE_CORRUPT)
        return False, None
    except ProfileLockedError:
        console.say(PROFILE_LOCKED)
        return False, None
    if store.dropped_sensitive_data:
        console.say(HEALTH_NOT_SAVED)
    return True, profile


def _save_profile(console: _Console, profile: PersonaProfile) -> bool:
    """Save, or report (and change nothing) when encrypted data cannot be written now."""
    try:
        ProfileStore().save(profile)
    except ProfileLockedError:
        console.say(PROFILE_LOCKED)
        return False
    return True


def _resources(console: _Console, clock: Clock) -> int:
    readable, profile = _load_profile(console)
    if not readable:
        return 1
    region = profile.region if profile is not None else None
    minor = profile is not None and profile.is_age_gate_refusal
    today = (_local_clock(clock, profile) if profile is not None else clock)().date()
    store = _load_store(today)
    card = resolve(
        store, region, CrisisLevel.L3, mode=CardMode.BROWSING, today=today, is_minor=minor
    )
    console.say(render_browsing(card, _taxonomy()))
    if region is None:
        console.say()
        console.say(RESOURCES_SET_REGION)
    return 0


def _set_region(
    console: _Console, profile: PersonaProfile, raw: str, timezone: str | None, now: datetime
) -> int:
    store_data = _load_store(now.date())
    wanted = raw.strip().upper()
    candidate = wanted if len(wanted) == 2 and wanted.isascii() and wanted.isalpha() else "ZZ"
    code = resolve_region_code(store_data, UserRegion(candidate, FALLBACK_TIMEZONE))
    current = profile.region
    label = _region_label(code)
    if timezone is not None:
        zone = canonical_timezone(timezone)
        if zone is None:
            console.say(REGION_BAD_TIMEZONE.format(timezone=timezone))
            return 1
    elif code in DEFAULT_TIMEZONES:
        zone = DEFAULT_TIMEZONES[code]
    elif current is not None and (
        code == UNKNOWN_COUNTRY or current.timezone in TIMEZONE_CHOICES.get(code, ())
    ):
        zone = current.timezone
    elif code == UNKNOWN_COUNTRY:
        zone = FALLBACK_TIMEZONE
    else:
        choices = "、".join(TIMEZONE_CHOICES.get(code, ("Asia/Singapore",))[:3])
        console.say(REGION_NEEDS_TIMEZONE.format(label=label, choices=choices))
        return 1
    region = UserRegion(country_code=code, timezone=zone)
    if not _save_profile(console, replace(profile, region=region, updated_at=now)):
        return 1
    if code != wanted:
        console.say(REGION_FALLBACK.format(raw=raw.strip()))
    console.say(REGION_SAVED.format(label=label, code=code, timezone=zone))
    return 0


def _region(
    console: _Console, code: str | None, timezone: str | None, clear: bool, clock: Clock
) -> int:
    if clear and (code is not None or timezone is not None):
        console.say(REGION_CLEAR_WITH_CODE)
        return 2
    readable, profile = _load_profile(console)
    if not readable:
        return 1
    setting = clear or code is not None or timezone is not None
    if profile is None:
        console.say(NOT_ONBOARDED if setting else NO_REGION)
        return 1 if setting else 0
    if profile.is_age_gate_refusal:
        console.say(ADULTS_ONLY)
        return 1 if setting else 0
    now = clock()
    if clear:
        region = UserRegion(country_code=UNKNOWN_COUNTRY, timezone=FALLBACK_TIMEZONE)
        if not _save_profile(console, replace(profile, region=region, updated_at=now)):
            return 1
        console.say(REGION_CLEARED)
        return 0
    if code is None and timezone is not None:
        code = profile.region.country_code if profile.region is not None else UNKNOWN_COUNTRY
    if code is not None:
        return _set_region(console, profile, code, timezone, now)
    if profile.region is None:
        console.say(NO_REGION)
        return 0
    shown = profile.region.country_code
    console.say(
        REGION_SHOW.format(label=_region_label(shown), code=shown, timezone=profile.region.timezone)
    )
    return 0


# -- health -----------------------------------------------------------------------------------


def _health(console: _Console, clock: Clock) -> int:
    """``olivia health``: the interactive exchange of ``chang/health.py``."""
    try:
        editor = HealthEditor(_taxonomy(), ProfileStore(), clock())
        outcome = editor.outcome
        if outcome is None:
            step: HealthPrompt | HealthDone = editor.prompt()
            while isinstance(step, HealthPrompt):
                console.say(step.text)
                for number, option in enumerate(step.options, start=1):
                    console.say(f"  {number}. {option}")
                answer = console.ask(ANSWER_PROMPT)
                if answer is None:
                    return 0
                console.say()
                step = editor.answer(answer)
            outcome = step
    except ProfileCorruptError:
        console.say(PROFILE_CORRUPT)
        return 1
    except ProfileLockedError:
        console.say(PROFILE_LOCKED)
        return 1
    console.say(outcome.text)
    return 0 if outcome.ok else 1


# -- persona ----------------------------------------------------------------------------------


def _persona_list(console: _Console, current: PersonaSpectrum | None) -> None:
    labels = load_onboarding_text().persona_labels
    console.say(PERSONA_CHOICES_HEADING)
    for number, persona in enumerate(PERSONA_CHOICES, start=1):
        mark = PERSONA_CURRENT_MARK if persona is current else ""
        console.say(f"  {number}. {labels[persona]}{mark}")


def _persona(console: _Console, choice: str | None, clock: Clock) -> int:
    """``olivia persona [CHOICE]``: show the saved persona, or switch it (JTBD 4)."""
    readable, profile = _load_profile(console)
    if not readable:
        return 1
    setting = choice is not None
    if profile is None:
        console.say(PERSONA_NOT_ONBOARDED)
        return 1 if setting else 0
    if profile.is_age_gate_refusal:
        console.say(PERSONA_ADULTS_ONLY)
        return 1 if setting else 0
    labels = load_onboarding_text().persona_labels
    current = profile.persona_spectrum
    if choice is None:
        console.say(PERSONA_SHOW.format(label=labels[current]))
        console.say()
        _persona_list(console, current)
        console.say()
        console.say(PERSONA_HOW_TO)
        return 0
    chosen = persona_from_reply(choice, labels)
    if chosen is None:
        console.say(PERSONA_UNKNOWN.format(raw=choice.strip()))
        _persona_list(console, current)
        return 1
    name = labels[chosen].split("：", 1)[0]
    if chosen is current:
        console.say(PERSONA_UNCHANGED.format(name=name))
        return 0
    if not _save_profile(console, replace(profile, persona_spectrum=chosen, updated_at=clock())):
        return 1
    console.say(PERSONA_SAVED.format(name=name))
    return 0


# -- entry point ------------------------------------------------------------------------------


def package_version() -> str:
    """The installed distribution's version; the source tree's when it is not installed."""
    try:
        return metadata.version("olivia")
    except metadata.PackageNotFoundError:
        return __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="olivia", description="OLIVIA 离线陪伴（命令行）")
    parser.add_argument(
        "--version", action="version", version=f"olivia {package_version()}", help="显示版本号"
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="命令")
    chat = commands.add_parser("chat", help="开始聊天（第一次会先完成设置）")
    chat.add_argument("--inspect", action="store_true", help="每轮显示内部状态面板（不含原文）")
    chat.add_argument(
        "--model", action="store_true", help="试验：危机筛查同时参考感知模型（默认只用规则）"
    )
    commands.add_parser("resources", help="查看所在地区的求助电话")
    region = commands.add_parser("region", help="查看或修改所在的国家/地区")
    region.add_argument("code", nargs="?", help="两位国家/地区代码，例如 CN、HK、US、GB")
    region.add_argument("--timezone", help="IANA 时区，例如 America/New_York")
    region.add_argument("--clear", action="store_true", help="清除保存的地区和时区")
    commands.add_parser("health", help="查看或修改加密记录的健康信息")
    persona = commands.add_parser("persona", help="查看或更换陪伴方式")
    persona.add_argument("choice", nargs="?", help="序号（1–4）或简称，例如 2 或 沉静哲思")
    return parser


def _use_utf8_stdio() -> None:
    """Read and write UTF-8 on the real streams.

    Piped streams otherwise use the locale encoding (cp1252 on many Windows setups),
    which cannot carry Chinese text; a console window is unaffected.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    clock: Clock | None = None,
    rng: random.Random | None = None,
) -> int:
    """Run one command; returns the exit status. ``clock`` must be timezone-aware."""
    if stdin is None and stdout is None:
        _use_utf8_stdio()
    args = build_parser().parse_args(argv)
    console = _Console(stdin or sys.stdin, stdout or sys.stdout)
    now = clock if clock is not None else _system_clock
    try:
        if args.command == "chat":
            return _chat(console, args.inspect, now, rng, student=args.model)
        if args.command == "resources":
            return _resources(console, now)
        if args.command == "health":
            return _health(console, now)
        if args.command == "persona":
            return _persona(console, args.choice, now)
        return _region(console, args.code, args.timezone, args.clear, now)
    except KeyboardInterrupt:
        console.say()
        console.say(GOODBYE)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
