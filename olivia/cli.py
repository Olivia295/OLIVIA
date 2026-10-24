"""The ``olivia`` command line (roadmap P2-4, P4-4).

``olivia chat [--inspect] [--rules]``
    First visit runs onboarding (``chang/onboarding.py``); then each line goes to
    ``Session.turn`` and the reply is printed exactly as returned, crisis cards included.
    By default (owner decision 2026-10-24, F7) the crisis screen also consults the
    packaged perception student, which can only raise the rule level and is capped at L2
    (its L3 is not plan evidence: the L2 card then leads with the emergency numbers), and
    takes valence, emotion, intent, stance, readiness and (without a spectrum cue) the
    spectrum from its other heads; arousal is the higher of the rule and model values
    (roadmap C1). A student that is missing or fails verification falls back to the rules
    alone, and ``--inspect`` shows which one ran (``风险模型 rules-only（reason）``).
    ``--rules`` screens with the rules alone. The old ``--model`` is still accepted (it is
    the default now, so it is hidden from the help), and giving it with ``--rules`` is a
    command-line error (exit 2). ``Session.open`` keeps ``student=False`` as its default:
    the product default is the CLI's.
    ``/exit``, end of input or Ctrl-C end the conversation with one goodbye line. The
    feedback commands (``/done``, ``/not-now``, ``/unhelpful``) are ordinary input here,
    as are natural-language replies to a card ("今天先不做了"): the session's perception
    reads them.
``olivia resources``
    The crisis-resource card for the saved region in BROWSING mode.
``olivia region [CODE [--timezone TZ] | --clear]``
    Show, set or clear the saved country/region (country level only, SDD §8.3). CODE is a
    supported code or a common name (``china``, ``中国``, ``香港``, ``usa`` ...); anything
    else is refused with the supported list, never saved as ZZ. ZZ (and ``--clear``) takes
    ``--timezone`` or this computer's zone, never the previous country's.
``olivia health``
    Show and change the recorded health information (clinical-history codes and the
    D2 disclosures), interactively with numbered choices (``chang/health.py``); it is
    always saved encrypted.
``olivia persona [CHOICE]``
    Show the four companion personas with the saved one marked, or switch to CHOICE (a
    number, short name, alias such as ``树洞`` or enum value; PRD JTBD 4, ONB-03). The next
    ``olivia chat`` uses it.
``olivia safety-plan``
    The personal safety plan (``chang/safety_plan.py``, B10): fill it in, or show the saved
    one and edit a section or clear it, interactively with numbered choices; every section
    can be skipped. It is always saved encrypted, and not at all without a keychain. A
    crisis reply in ``chat`` shows its coping, distraction and people sections.
``olivia journal``
    The weekly journal (``chang/journal.py``, B6): a read-only summary of the last seven
    days built from the ledger, then one optional "was it helpful" question.
``olivia memory``
    What this device remembers, on screen only (``memory/forget.py``, B5): the ledger
    entries oldest first and numbered (templated summaries, notes verbatim), then the
    other data by name only; never health details or the plan.
``olivia forget [--entry N | --ledger | --kit | --safety-plan | --all] [--yes]``
    Forget one entry, every chat record, the kit and method preferences, the safety plan,
    or everything (crypto-shredding; ``--all`` also deletes the keychain item, so the
    next ``chat`` starts onboarding afresh). Without a flag, a numbered menu; every
    deletion asks for a typed confirmation unless ``--yes``.
``olivia privacy``
    A short privacy notice (``chang/privacy.py``, B8): what is stored where, always
    offline, what is encrypted, how to see and delete it. Reads and writes nothing.
``olivia settings``
    A numbered menu of switches (``notify/settings.py``, B9); for now the system
    reminders, off by default (decision D5). Turning them on says what will be installed
    and asks once more, then installs one scheduled job (``notify/jobs.py``: a LaunchAgent,
    a Task Scheduler task, or a systemd user timer / crontab line); turning them off, or
    ``forget --all``, removes it. The job runs the hidden ``olivia notify-check``
    (``notify/check.py``), which sends at most one content-free notification and nothing
    while the keychain is locked; all it writes is ``notify.json`` (the dates of the last
    two reminders, no user data).
``olivia --version``
    The installed version, read from the package metadata.

Help and argparse errors are in Chinese (``_Parser``), with full-width colons after the
headings; help goes to ``main``'s ``stdout`` and argparse errors to its ``stderr``, and
neither lists the hidden ``notify-check``. Exit status, the same for every command
(README "退出码"): 0 when the command did what was asked (showing counts); 1 when nothing
could be done (no profile yet, an under-18 refusal record, unreadable or locked data;
``chat`` that ends before a profile exists); 2 for a wrong command line (argparse, or an
unknown region, timezone or persona). Ctrl-C exits like end of input at the same point:
0 once a chat has started (it ends the conversation like ``/exit``) and in the other
commands, 1 during onboarding. ``resources``, ``privacy`` and ``forget --all`` work
without a profile.

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
card shelved last time. ``chat`` reads the saved safety plan for its crisis replies and
never writes it; when there is none, the first S_closing reply mentions
``olivia safety-plan`` once per device (an empty marker file, step B10). Conversation text
and perception output are never written anywhere; the ledger keeps only ids, levels and
times, and the session summary is written at every exit (``/exit``, end of input, Ctrl-C)
and whenever the session closes itself (S_closing -> S_ready). ``chat`` also asks one
optional 0-10 self-rating at the opening and at the end, and offers the weekly journal at
the opening when it is due (``chang/journal.py``, B6; not on a care-greeting opening, not
after a crisis or in S_haven); both only go into the ledger. Without a keychain nothing
is remembered or asked, and the user is told so once per device.

The ``--inspect`` panel (SDD §10.2, ruling 27) prints ids, levels and numbers from
``TurnResult.inspect``, and never the user's text, the reply text or anything below
country level. The CLI makes no network calls.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import random
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from importlib import metadata
from typing import Any, Final, NoReturn, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from olivia import __version__
from olivia.core.chang import onboarding
from olivia.core.chang.care import CareRecorder, CareStore
from olivia.core.chang.health import HealthDone, HealthEditor, HealthPrompt
from olivia.core.chang.journal import ChatChecks, load_journal_text
from olivia.core.chang.journal import run_command as run_journal
from olivia.core.chang.onboarding import (
    DEFAULT_TIMEZONES,
    PERSONA_CHOICES,
    SUPPORTED_REGIONS,
    TIMEZONE_CHOICES,
    Completed,
    OnboardingFlow,
    Prompt,
    Refused,
    canonical_timezone,
    load_onboarding_text,
    persona_from_reply,
    region_from_reply,
)
from olivia.core.chang.privacy import privacy_notice
from olivia.core.chang.profile import ProfileCorruptError, ProfileLockedError, ProfileStore
from olivia.core.chang.safety_plan import SafetyPlanStore, load_safety_plan_text, run_command
from olivia.core.language.data import load_language_data
from olivia.core.memory.forget import (
    DataStores,
    Target,
    load_forget_text,
    run_forget,
    run_memory,
)
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
from olivia.core.resources.resolver import resolve
from olivia.core.resources.store import LineKind, ResourceStore, parse_store
from olivia.core.session import Session, TurnResult
from olivia.core.storage import data_dir_location
from olivia.core.taxonomy import Taxonomy, load_taxonomy
from olivia.core.yaml_load import safe_load
from olivia.notify import system as notify_system
from olivia.notify.check import run_check
from olivia.notify.settings import remove_reminders, run_settings
from olivia.notify.text import load_notify_text

Clock = Callable[[], datetime]

# One taxonomy object per process, so repeated commands share the session's loaded data.
_taxonomy = functools.cache(load_taxonomy)

EXIT_COMMAND: Final = "/exit"

# -- user-facing text (short, warm, no diagnosis words; checked against WILLOW in tests) ---

GOODBYE: Final = "好，今天就先聊到这里。想说话的时候，随时回来。"
CHAT_HINT: Final = "想结束的时候，输入 /exit 就好。"
# ``olivia chat -h`` (F9, FSM-15; draft, G-0): how to ask for quiet company and how to
# leave it; the quoted words are perception.yaml ``haven_exit`` phrases.
CHAT_HELP: Final = (
    "很累的时候，在消息开头写上电量，比如 [5%]，我就安安静静地陪着你；"
    "想聊别的了，说一句「我好多了」或「换个话题吧」就好。想结束时输入 /exit。"
)
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
NOT_SET_UP: Final = (
    "还没有完成第一次设置，这台电脑上还没有可以查看或忘掉的内容。先运行 olivia chat 吧。"
)
NO_REGION: Final = "还没有保存地区。"
ADULTS_ONLY: Final = "这里的陪伴只为成年人设计，所以不会保存地区信息。"
REGION_SHOW: Final = "地区：{label}（{code}）\n时区：{timezone}"
REGION_SAVED: Final = "好的，已经保存：{label}（{code}），时区 {timezone}。"
REGION_UNKNOWN: Final = (
    "没有认出「{raw}」这个地区，所以没有做改动。可以用下面的代码或名称：\n"
    "{choices}\n"
    "不在列表里的地方，请选 ZZ，再用 --timezone 告诉我时区，"
    "例如：olivia region ZZ --timezone Asia/Tokyo"
)
REGION_CHOICE: Final = "  {code}  {label}"
REGION_SYSTEM_TIMEZONE: Final = (
    "时区先按这台电脑的设置用 {timezone}；不对的话，可以用 --timezone 修改。"
)
REGION_NEEDS_TIMEZONE: Final = (
    "{label}有好几个时区，请用 --timezone 告诉我是哪一个，例如：{choices}"
)
REGION_BAD_TIMEZONE: Final = (
    "没有认出时区「{timezone}」。可以用「大洲/城市」的格式，例如 Asia/Singapore。"
)
REGION_CLEARED: Final = (
    "已清除保存的地区。求助卡片会显示全球通用的资源；时区按这台电脑的设置用 {timezone}。"
)
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
    CHAT_HELP,
    PROFILE_CORRUPT,
    PROFILE_LOCKED,
    HEALTH_NOT_SAVED,
    NOT_ONBOARDED,
    NOT_SET_UP,
    NO_REGION,
    ADULTS_ONLY,
    REGION_SHOW,
    REGION_SAVED,
    REGION_UNKNOWN,
    REGION_SYSTEM_TIMEZONE,
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
    """``clock`` in the profile's timezone; this computer's when that zone is missing or
    unknown here (UTC when the computer's cannot be read either)."""
    zone = _zone(profile.region.timezone) if profile.region is not None else None
    if zone is None:
        zone = _zone(onboarding.system_timezone())
    if zone is None:  # pragma: no cover - system_timezone only returns known names
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
        + (f" · 意图确认 {_fmt(check)}" if check else "")
        + (" · 安全计划 已展示" if data.get("safety_plan_shown") is True else ""),
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
    student: bool = True,
) -> int:
    tax = _taxonomy()
    store = ProfileStore()
    try:
        profile = _onboard(console, tax, store, clock())
    except KeyboardInterrupt:  # like end of input here: nothing was set up
        console.say()
        console.say(GOODBYE)
        return 1
    except ProfileCorruptError:
        console.say(PROFILE_CORRUPT)
        return 1
    except ProfileLockedError:
        console.say(PROFILE_LOCKED)
        return 1
    if store.dropped_sensitive_data:
        console.say(HEALTH_NOT_SAVED)
    if profile is None:  # declined, under 18, or input ended: nothing was set up
        return 1
    local = _local_clock(clock, profile)
    # The posteriors and the kit from earlier sessions (B3); None starts fresh.
    state_store = StateStore(store.path.parent, store.vault)
    plan_store = SafetyPlanStore(vault=store.vault)
    plan = plan_store.load_quietly()
    session = Session.open(
        tax,
        profile,
        rng=rng if rng is not None else random.Random(),
        now=local,
        student=student,
        carried=state_store.load(),
        safety_plan=plan,
        suggest_safety_plan=plan is None and plan_store.should_suggest(),
    )
    state_recorder = StateRecorder(state_store, session.carried_state())
    titles = _card_titles(tax)
    ledger = Ledger(store.path.parent, store.vault, method_titles=titles)
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
    # Self-ratings and the journal offer (B6); a care-greeting opening stays alone.
    checks = ChatChecks(
        tax, ledger, recorder, lambda: console.ask(ANSWER_PROMPT), console.say, method_titles=titles
    )
    try:
        carry = checks.opening(local()) if marker is None else None
        pending = carry.line if carry is not None else None
        while carry is None or not carry.ended:
            line = pending if pending is not None else console.ask(USER_PROMPT)
            pending = None
            if line is None:
                break
            if line.strip() == EXIT_COMMAND:
                carry = checks.at_exit(session.state)
                if carry.line is None or carry.line.strip() == EXIT_COMMAND:
                    break
                pending = carry.line  # text typed at the rating: the chat goes on
                continue
            if not line.strip():
                continue
            try:
                turned = session.turn(line)
            except Exception:  # SDD §10.1: even a failed screen leaves every number on screen
                today = local().date()
                card = resolve(
                    _load_store(today),
                    profile.region,
                    CrisisLevel.L3,
                    mode=CardMode.BROWSING,
                    today=today,
                )
                numbers = [e.number for e in card.emergency] + [ln.number for ln in card.lines]
                minimal = load_language_data(tax).render.crisis_minimal
                console.say(
                    "\n".join([f"{profile.agent_name}：{minimal}", *(f"· {n}" for n in numbers)])
                )
                console.say()
                continue
            result = recorder.observe(line, turned)
            checks.observe(result)
            # The reply (a crisis card included) is on screen before any keychain access.
            console.say(f"{profile.agent_name}：{result.reply}")
            care_recorder.observe(result, session.snapshot())
            state_recorder.observe(session.carried_state())  # feedback survives a crash
            if session.safety_plan_suggested:
                plan_store.mark_suggested()
            if inspect:
                for panel_line in inspect_panel(result):
                    console.say(panel_line)
            console.say()
            carry = checks.after_turn(session.state)
            pending = carry.line
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
    return parse_store(safe_load(bundle.data))


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


def _region_choices(store: ResourceStore) -> str:
    labels = load_onboarding_text().region_labels
    return "\n".join(
        REGION_CHOICE.format(code=code, label=labels[code])
        for code in SUPPORTED_REGIONS
        if store.has_region(code)
    )


def _set_region(
    console: _Console, profile: PersonaProfile, raw: str, timezone: str | None, now: datetime
) -> int:
    store_data = _load_store(now.date())
    code = region_from_reply(raw, load_onboarding_text(), numbers=False)
    if code is None or not store_data.has_region(code):
        console.say(REGION_UNKNOWN.format(raw=raw.strip(), choices=_region_choices(store_data)))
        return 2
    current = profile.region
    label = _region_label(code)
    note = ""
    if timezone is not None:
        zone = canonical_timezone(timezone)
        if zone is None:
            console.say(REGION_BAD_TIMEZONE.format(timezone=timezone))
            return 2
    elif code in DEFAULT_TIMEZONES:
        zone = DEFAULT_TIMEZONES[code]
    elif (
        code != UNKNOWN_COUNTRY
        and current is not None
        and current.country_code == code
        and current.timezone in TIMEZONE_CHOICES[code]
    ):
        zone = current.timezone  # the same country again: keep the zone chosen for it
    else:
        # Never keep the old country's zone: this computer's, when it fits the region.
        system = onboarding.system_timezone()
        if code != UNKNOWN_COUNTRY and system not in TIMEZONE_CHOICES[code]:
            choices = "、".join(TIMEZONE_CHOICES[code][:3])
            console.say(REGION_NEEDS_TIMEZONE.format(label=label, choices=choices))
            return 2
        zone, note = system, REGION_SYSTEM_TIMEZONE.format(timezone=system)
    region = UserRegion(country_code=code, timezone=zone)
    if not _save_profile(console, replace(profile, region=region, updated_at=now)):
        return 1
    console.say(REGION_SAVED.format(label=label, code=code, timezone=zone))
    if note:
        console.say(note)
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
        return 1
    if profile.is_age_gate_refusal:
        console.say(ADULTS_ONLY)
        return 1
    now = clock()
    if clear:
        zone = onboarding.system_timezone()
        region = UserRegion(country_code=UNKNOWN_COUNTRY, timezone=zone)
        if not _save_profile(console, replace(profile, region=region, updated_at=now)):
            return 1
        console.say(REGION_CLEARED.format(timezone=zone))
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


# -- safety plan ------------------------------------------------------------------------------


def _safety_plan(console: _Console) -> int:
    """``olivia safety-plan``: the interactive exchange of ``chang/safety_plan.py``."""
    readable, profile = _load_profile(console)
    if not readable:
        return 1
    command = load_safety_plan_text().command
    if profile is None:
        console.say(command["not_onboarded"])
        return 1
    if profile.is_age_gate_refusal:
        console.say(command["adults_only"])
        return 1
    return run_command(lambda: console.ask(ANSWER_PROMPT), console.say, SafetyPlanStore())


# -- journal ----------------------------------------------------------------------------------


def _journal(console: _Console, clock: Clock) -> int:
    """``olivia journal``: the rolling week's journal (``chang/journal.py``, B6)."""
    readable, profile = _load_profile(console)
    if not readable:
        return 1
    replies = load_journal_text().replies
    if profile is None:
        console.say(replies["not_onboarded"])
        return 1
    if profile.is_age_gate_refusal:
        console.say(replies["adults_only"])
        return 1
    store = ProfileStore()
    tax = _taxonomy()
    titles = _card_titles(tax)
    ledger = Ledger(store.path.parent, store.vault, method_titles=titles)
    now = _local_clock(clock, profile)()
    return run_journal(
        lambda: console.ask(ANSWER_PROMPT), console.say, ledger, now, method_titles=titles
    )


# -- memory and forget ------------------------------------------------------------------------


def _data_stores() -> DataStores:
    base = ProfileStore().path.parent
    return DataStores.open(
        base,
        method_titles=_card_titles(_taxonomy()),
        on_forget_all=(lambda: remove_reminders(notify_system.current_host(), base),),
    )


def _profile_quietly() -> tuple[bool, PersonaProfile | None]:
    """(readable, profile) without saying anything; the commands report errors themselves."""
    try:
        return True, ProfileStore().load()
    except (ProfileCorruptError, ProfileLockedError):
        return False, None


def _memory(console: _Console) -> int:
    """``olivia memory``: what is stored on this device, on screen only (B5)."""
    readable, profile = _profile_quietly()
    if readable and profile is None:
        console.say(NOT_SET_UP)
        return 1
    code = run_memory(console.say, _data_stores())
    return 1 if profile is not None and profile.is_age_gate_refusal else code


_FORGET_FLAGS: Final = (
    ("ledger", Target.LEDGER),
    ("kit", Target.KIT),
    ("safety_plan", Target.SAFETY_PLAN),
    ("all", Target.ALL),
)


def _forget(console: _Console, args: argparse.Namespace) -> int:
    """``olivia forget``: the menu, or the target a flag names (B5)."""
    target = next((t for flag, t in _FORGET_FLAGS if getattr(args, flag)), None)
    readable, profile = _profile_quietly()
    # ``--all`` always runs: it is also how leftovers without a profile are removed.
    if target is not Target.ALL and readable and profile is None:
        console.say(NOT_SET_UP)
        return 1
    if target is not Target.ALL and profile is not None and profile.is_age_gate_refusal:
        console.say(load_forget_text().forget["adults_only"])
        return 1
    return run_forget(
        lambda: console.ask(ANSWER_PROMPT),
        console.say,
        _data_stores(),
        target=target,
        entry=args.entry,
        assume_yes=args.yes,
    )


# -- privacy ----------------------------------------------------------------------------------


def _privacy(console: _Console) -> int:
    """``olivia privacy``: the privacy notice (B8); nothing is read or written."""
    console.say(privacy_notice(data_dir_location()))
    return 0


# -- settings and reminders -------------------------------------------------------------------


def _settings(console: _Console, clock: Clock) -> int:
    """``olivia settings``: the numbered menu (``notify/settings.py``, B9)."""
    readable, profile = _load_profile(console)
    if not readable:
        return 1
    words = load_notify_text().settings
    if profile is None:
        console.say(words["not_onboarded"])
        return 1
    if profile.is_age_gate_refusal:
        console.say(words["adults_only"])
        return 1
    store = ProfileStore()
    return run_settings(
        lambda: console.ask(ANSWER_PROMPT),
        console.say,
        profile,
        save=lambda changed: _save_profile(console, changed),
        host=notify_system.current_host,
        base=store.path.parent,
        keychain_ok=store.vault.available,
        now=clock(),
    )


def _notify_check(clock: Clock) -> int:
    """``olivia notify-check`` (hidden; the scheduled job): prints nothing."""
    run_check(notify_system.current_host(), ProfileStore().path.parent, clock())
    return 0


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
    if profile is None:
        console.say(PERSONA_NOT_ONBOARDED)
        return 1
    if profile.is_age_gate_refusal:
        console.say(PERSONA_ADULTS_ONLY)
        return 1
    text = load_onboarding_text()
    labels = text.persona_labels
    current = profile.persona_spectrum
    if choice is None:
        console.say(PERSONA_SHOW.format(label=labels[current]))
        console.say()
        _persona_list(console, current)
        console.say()
        console.say(PERSONA_HOW_TO)
        return 0
    chosen = persona_from_reply(choice, labels, text.persona_aliases)
    if chosen is None:
        console.say(PERSONA_UNKNOWN.format(raw=choice.strip()))
        _persona_list(console, current)
        return 2
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


HELP_USAGE: Final = "用法："
HELP_POSITIONALS: Final = "参数"
HELP_OPTIONS: Final = "选项"
HELP_COMMANDS: Final = "命令"
HELP_HEADINGS: Final = (HELP_POSITIONALS, HELP_OPTIONS, HELP_COMMANDS)
HELP_HELP: Final = "显示这段说明，然后退出"
HIDDEN_COMMANDS: Final = frozenset({"notify-check"})
"""Commands for the system scheduler (B9): they run, but no help or error lists them."""
_HEADING_LINE: Final = re.compile(rf"^( *)({'|'.join(HELP_HEADINGS)}):$", re.MULTILINE)
HELP_ERROR: Final = "{prog}：命令有误：{message}\n（输入 {prog} -h 可以查看用法）\n"
_ARGPARSE_ERRORS: Final = (
    (re.compile(r"the following arguments are required: (.+)"), "还缺少：{0}"),
    (re.compile(r"unrecognized arguments: (.+)"), "没有认出这些内容：{0}"),
    (
        re.compile(r"argument (.+?): invalid choice: '?(.+?)'? \(choose from (.+)\)"),
        "{0} 不能是「{1}」，可以选：{2}",
    ),
    (re.compile(r"argument (.+?): not allowed with argument (.+)"), "{0} 不能和 {1} 一起用"),
    (re.compile(r"argument (.+?): expected one argument"), "{0} 后面要跟一个值"),
    (re.compile(r"argument (.+?): invalid int value: '?(.+?)'?$"), "{0} 要跟一个整数，「{1}」不是"),
    (
        re.compile(r"argument (.+?): ignored explicit argument '?(.+?)'?$"),
        "{0} 后面不用跟值，「{1}」是多出来的",
    ),
)
_INVALID_CHOICE: Final = _ARGPARSE_ERRORS[2][0]
_CHOICES_GROUP: Final = 2


def _visible_choices(choices: str) -> str:
    """argparse's ``a, b, c`` choice list as ``a、b、c``, without the hidden commands."""
    return "、".join(name for name in choices.split(", ") if name not in HIDDEN_COMMANDS)


def _localise_error(message: str) -> str:
    """argparse's English error in Chinese (the original when no pattern matches)."""
    for pattern, template in _ARGPARSE_ERRORS:
        found = pattern.fullmatch(message)
        if found is not None:
            groups = [group.replace("'", "") for group in found.groups()]
            if pattern is _INVALID_CHOICE:
                groups[_CHOICES_GROUP] = _visible_choices(groups[_CHOICES_GROUP])
            return template.format(*groups)
    return message


class _HelpFormatter(argparse.HelpFormatter):
    """argparse's layout with a Chinese ``usage:`` prefix."""

    def add_usage(
        self,
        usage: str | None,
        actions: Iterable[argparse.Action],
        groups: Iterable[argparse._MutuallyExclusiveGroup],
        prefix: str | None = None,
    ) -> None:
        super().add_usage(usage, actions, groups, HELP_USAGE if prefix is None else prefix)


class _Parser(argparse.ArgumentParser):
    """An ``ArgumentParser`` whose help and errors are in Chinese (subcommands included)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("formatter_class", _HelpFormatter)
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = HELP_POSITIONALS
        self._optionals.title = HELP_OPTIONS
        self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help=HELP_HELP)

    def format_help(self) -> str:
        """argparse's help with a full-width colon after each Chinese heading."""
        return _HEADING_LINE.sub(r"\1\2：", super().format_help())

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(2, HELP_ERROR.format(prog=self.prog, message=_localise_error(message)))


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="olivia", description="OLIVIA 离线陪伴（命令行）")
    parser.add_argument(
        "--version", action="version", version=f"olivia {package_version()}", help="显示版本号"
    )
    commands = parser.add_subparsers(
        dest="command", required=True, metavar="<命令>", title=HELP_COMMANDS
    )
    chat = commands.add_parser("chat", help="开始聊天（第一次会先完成设置）", description=CHAT_HELP)
    chat.add_argument("--inspect", action="store_true", help="每轮显示内部状态面板（不含原文）")
    # Model mode is the default (owner decision 2026-10-24); --model is kept for old scripts
    # and hidden, since a flag that changes nothing would only confuse the help.
    mode = chat.add_mutually_exclusive_group()
    mode.add_argument("--rules", action="store_true", help="只用规则做危机筛查（不参考本机模型）")
    mode.add_argument("--model", action="store_true", help=argparse.SUPPRESS)
    commands.add_parser("resources", help="查看所在地区的求助电话")
    region = commands.add_parser("region", help="查看或修改所在的国家/地区")
    region.add_argument(
        "code",
        nargs="?",
        metavar="地区",
        help="地区代码或名称：CN 中国大陆、HK 香港、MO 澳门、TW 台湾、US、CA、GB、AU，"
        "其他地方用 ZZ",
    )
    region.add_argument("--timezone", metavar="时区", help="IANA 时区，例如 America/New_York")
    region.add_argument("--clear", action="store_true", help="清除保存的地区和时区")
    commands.add_parser("health", help="查看或修改加密记录的健康信息")
    commands.add_parser("safety-plan", help="填写、查看或修改加密保存的个人安全计划")
    commands.add_parser("journal", help="看看这一周的小结")
    persona = commands.add_parser("persona", help="查看或更换陪伴方式")
    persona.add_argument(
        "choice",
        nargs="?",
        metavar="陪伴方式",
        help="序号（1–4）或简称，例如 2、温和、哲思、理性、树洞",
    )
    commands.add_parser("memory", help="查看 OLIVIA 在这台电脑上记得什么（只显示在屏幕上）")
    forget = commands.add_parser("forget", help="让 OLIVIA 忘掉一条记录、一类数据或全部数据")
    which = forget.add_mutually_exclusive_group()
    which.add_argument(
        "--entry", type=int, metavar="序号", help="忘掉一条记录（序号见 olivia memory）"
    )
    which.add_argument("--ledger", action="store_true", help="忘掉全部聊天记录")
    which.add_argument("--kit", action="store_true", help="忘掉锦囊与方法偏好")
    which.add_argument("--safety-plan", action="store_true", help="删掉个人安全计划")
    which.add_argument("--all", action="store_true", help="忘掉全部数据，之后从头开始")
    forget.add_argument("--yes", action="store_true", help="不再询问确认")
    commands.add_parser(
        "privacy", help="看看 OLIVIA 怎么保护你的隐私：存了什么、存在哪里、怎么删除"
    )
    commands.add_parser("settings", help="查看或修改设置（例如系统提醒，默认关闭）")
    commands.add_parser("notify-check")  # no help: hidden; the scheduled job runs it (B9)
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
    stderr: TextIO | None = None,
    clock: Clock | None = None,
    rng: random.Random | None = None,
) -> int:
    """Run one command; returns the exit status. ``clock`` must be timezone-aware.

    ``--help`` and ``--version`` write to ``stdout``, an argparse error to ``stderr`` (the
    real streams when not given); both then raise ``SystemExit`` (0 and 2, as argparse).
    """
    if stdin is None and stdout is None:
        _use_utf8_stdio()
    with (
        contextlib.redirect_stdout(stdout or sys.stdout),
        contextlib.redirect_stderr(stderr or sys.stderr),
    ):
        args = build_parser().parse_args(argv)
    console = _Console(stdin or sys.stdin, stdout or sys.stdout)
    now = clock if clock is not None else _system_clock
    try:
        if args.command == "chat":
            return _chat(console, args.inspect, now, rng, student=not args.rules)
        if args.command == "resources":
            return _resources(console, now)
        if args.command == "health":
            return _health(console, now)
        if args.command == "persona":
            return _persona(console, args.choice, now)
        if args.command == "safety-plan":
            return _safety_plan(console)
        if args.command == "journal":
            return _journal(console, now)
        if args.command == "memory":
            return _memory(console)
        if args.command == "forget":
            return _forget(console, args)
        if args.command == "privacy":
            return _privacy(console)
        if args.command == "settings":
            return _settings(console, now)
        if args.command == "notify-check":
            return _notify_check(now)
        return _region(console, args.code, args.timezone, args.clear, now)
    except KeyboardInterrupt:
        console.say()
        console.say(GOODBYE)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
