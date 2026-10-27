"""The ``olivia`` command line (roadmap P2-4, P4-4).

``olivia chat [--inspect] [--rules]``
    First visit runs onboarding (``chang/onboarding.py``); then each line goes to
    ``Session.turn`` and the reply is printed exactly as returned, crisis cards included.
    Every onboarding reply is crisis-screened first, the way the chat will screen
    (``chang/setup_screen.py``, QA 2026-10-26 #4; so are the replies in ``profile``,
    ``health`` and ``safety-plan``): at L2 or above it is not taken as an answer, the
    hotlines (the region chosen so far, else every supported region's emergency numbers)
    come with one gentle line, and the user chooses to go on or to leave -- at every such
    reply. A list of topic words for the taboo topics ("自杀、死亡、前任") is saved with the
    numbers and asked nothing; the safety plan keeps such a sentence only in sections 1
    and 5 (QA r3).
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
    ``/exit``, end of input or Ctrl-C end the conversation with one goodbye line; inside
    the crisis flow, or with a safety question still unanswered, the goodbye is the
    session's crisis farewell instead (S5: one gentle line, the region's numbers and the
    safety plan's people, no mood rating), and an unanswered question also leaves the
    care marker, as the crisis flow would. The
    feedback commands (``/done``, ``/not-now``, ``/unhelpful``) are ordinary input here,
    as are natural-language replies to a card ("今天先不做了"): the session's perception
    reads them.
``olivia resources [CODE]``
    The crisis-resource card for the saved region in BROWSING mode; with CODE, that
    region's card, shown once and never saved (no profile needed; it is how an under-18
    refusal record, which keeps no region, sees a region's numbers; QA 2026-10-26 #8).
    It never needs the keychain (S1): a profile that cannot be opened still gives its
    plaintext region; when nothing is readable (the whole profile sealed, ONB-06, or
    every copy damaged) it shows the ZZ card, then why and what next. ``chat`` that
    cannot open the profile shows the same card before it says why. Packaged hotline data
    that fails verification is never shown: ``resources/fallback.py``'s fixed text takes
    its place (S3).
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
``olivia profile``
    Both names and the taboo topics (``chang/profile_command.py``, JTBD 4, F11): a numbered
    menu showing the three, then one changed at a time with the onboarding checks; new
    topics replace the old list, ``0`` clears it, Enter changes nothing. The next ``olivia
    chat`` uses them.
``olivia safety-plan``
    The personal safety plan (``chang/safety_plan.py``, B10): fill it in, or show the saved
    one and edit a section or clear it, interactively with numbered choices; every section
    can be skipped. It is always saved encrypted, and not at all without a keychain. A
    crisis reply in ``chat`` shows its coping, distraction and people sections.
``olivia journal``
    The weekly journal (``chang/journal.py``, B6): a read-only summary of the last seven
    days built from the ledger, in the profile persona's voice (Q-6), with a battery
    line when the week's sessions gave a ``[NN%]`` battery (CHANG-04), then one optional
    "was it helpful" question. Spectra and exercises that name a taboo topic are left
    out (ruling 21, F11).
``olivia stats``
    Local usage numbers (``chang/stats.py``, F12; PRD §11.1), computed from the ledger's
    session summaries and printed only: how many sessions (all, last 7 and 30 days), the
    share of late-night sessions, the share of replies with real-world support guidance,
    the mean self-rating change, the share of sessions whose rating rose and the answers
    to the journal's "was it helpful" question. Numbers only: no conversation text,
    names, spectra or exercise titles. Reads the ledger and writes nothing.
``olivia memory [--edit N]``
    What this device remembers, on screen only (``memory/forget.py``, B5): the ledger
    entries oldest first and numbered (templated summaries, notes verbatim), then the
    other data by name only (the taboo topics as a count); never health details or the
    plan. The method preferences are listed one method at a time, by card title, each
    with a plain sentence and never a number (PRD RSK-06). Dates and times show in the
    profile's current timezone (PRD Q-8, F11); what is stored is never rewritten.
    ``--edit N`` changes the words of note N (PRD feature 5): after the typed
    confirmation the ledger is re-keyed, so the old words are crypto-shredded; a summary
    or journal record cannot be edited (exit 2).
``olivia forget [--entry N | --method N | --ledger | --kit | --safety-plan | --all] [--yes]``
    Forget one entry, every chat record, one method's preference (``--method``, the
    number ``olivia memory`` lists it under), the kit and method preferences, the safety
    plan, or everything (crypto-shredding; ``--all`` also deletes the keychain item, so
    the next ``chat`` starts onboarding afresh). Without a flag, a numbered menu; every
    deletion shows what it removes and asks for a typed confirmation (「确认」 or
    「确定」) unless ``--yes``. A number on the command line that names nothing is a wrong
    value (exit 2).
``olivia privacy``
    A short privacy notice (``chang/privacy.py``, B8): what is stored where, always
    offline, what is encrypted, how to see and delete it. Reads and writes nothing.
``olivia settings``
    A numbered menu of switches (``notify/settings.py``, B9, F11). 1: the system
    reminders, off by default (decision D5). Turning them on says what will be installed
    and asks once more, then installs one scheduled job (``notify/jobs.py``: a LaunchAgent,
    a Task Scheduler task, or a systemd user timer / crontab line); turning them off, or
    ``forget --all``, removes it. The job runs the hidden ``olivia notify-check``
    (``notify/check.py``), which sends at most one content-free notification and nothing
    while the keychain is locked; all it writes is ``notify.json`` (the dates of the last
    two reminders, no user data). 2: the onboarding storage choice (ONB-06): only health
    information encrypted, or the whole profile; each way is explained and confirmed, and
    the whole profile cannot be sealed without a keychain.
``olivia doctor``
    A read-only, offline check of this computer's setup (``olivia/doctor.py``), one line
    each marked ✓ / ! / ✗: versions, the data directory (✗ with how to fix it when this
    account cannot read or write it, or a file is in its place; QA r3) and its modes,
    whether a keychain is there (no item is read), whether the first visit is done, whether
    each store would open (judged from its files and key files, never decrypted), the
    packaged model's verification, the built-in hotline data's signature and age (! after
    90 days), the signed update in use, whether every packaged wording, lexicon and taxonomy
    file loads, and the reminder job. No user text, name or stored content is
    printed; the last line says so. Works before the first visit; exit 1 on any ✗.
``olivia --version``
    The installed version, read from the package metadata.

Help and argparse errors are in Chinese (``_Parser``), with full-width colons after the
headings; help goes to ``main``'s ``stdout`` and argparse errors to its ``stderr``, and
neither lists the hidden ``notify-check``. Exit status, the same for every command
(README "退出码"): 0 when the command did what was asked (showing counts); 1 when nothing
could be done (no profile yet, an under-18 refusal record, unreadable or locked data;
``chat`` that ends before a profile exists); 2 for a wrong command line (argparse, or an
unknown region, timezone or persona, or a ``forget --entry``/``--method`` or ``memory
--edit`` number that names nothing there). Ctrl-C exits like end of input at the same point:
0 once a chat has started (it ends the conversation like ``/exit``) and in the other
commands, 1 during onboarding. ``resources``, ``privacy``, ``doctor`` and ``forget --all``
work without a profile.

One writer per data directory (robustness findings D1-D3; ``core/datalock.py``): the
commands that write data -- ``chat``, ``health``, ``safety-plan``, ``settings``,
``profile``, ``journal`` (it records the offer), ``forget``, ``notify-check``, and
``persona`` / ``region`` / ``memory`` when they change something -- take the data
directory's lock first. When another OLIVIA holds it they change nothing, say so with a
pointer to ``olivia resources`` and exit 1 (``notify-check`` skips quietly, exit 0);
``chat`` first shows the saved region's numbers, read without the lock or the keychain
(QA 2026-10-26 #8), as it does when an interrupted ``forget --all`` stops it.
``resources``, ``privacy``, ``doctor``, ``memory``, ``stats``, showing a persona or region,
help and version never wait for it. A ``forget --all`` that was interrupted is named before any
other command runs (exit 1; ``resources`` still shows the numbers first), a profile
recovered from a snapshot is said once (``chang/profile.py``), right after the command's
own load and with the region the recovered version holds (QA 2026-10-26 #12), and an
error nothing else handled ends the command with the emergency numbers written in the
program (``resources/fallback.py``), then one plain sentence and ``olivia doctor``, never a
traceback (exit 1; Ctrl-C keeps its own handling).

The CLI writes the profile (``chang/profile.py``: region, timezone and the onboarding
answers) through ``storage.atomic_write_text``, the memory ledger (``core/memory``,
decision D1: one templated summary per session plus the notes the user asked to have
remembered, always encrypted) and, once there is something to encrypt, the wrapped data
keys under ``keys/`` (``core/crypto``). Health information is always encrypted, the whole
profile when the user chose that (ONB-06). After a crisis (or a no to the D3 question
about intent; not a no to the question a model-only alarm asked, I9) ``chat`` also writes
the care marker (``chang/care.py``): a time and a level,
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
import platform
import random
import re
import shlex
import sys
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Final, NoReturn, Protocol, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from olivia import __version__, doctor
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
from olivia.core.chang.profile import (
    ProfileCorruptError,
    ProfileLockedError,
    ProfileStore,
    ProfileUnreadableError,
)
from olivia.core.chang.profile_command import run_profile
from olivia.core.chang.safety_plan import (
    SafetyPlanStore,
    Screened,
    load_safety_plan_text,
    run_command,
    without_crisis_entries,
)
from olivia.core.chang.setup_screen import SetupScreen, topic_words_only
from olivia.core.chang.stats import load_stats_text
from olivia.core.chang.stats import run_command as run_stats
from olivia.core.crypto.keychain import Probe
from olivia.core.datalock import DataDirBusyError, DataDirLock
from olivia.core.language.data import load_language_data
from olivia.core.memory.forget import (
    DataStores,
    Target,
    forget_all_unfinished,
    load_forget_text,
    run_edit,
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
from olivia.core.resources.bundle import (
    REASON_FUTURE,
    REASON_INCOMPLETE,
    REASON_INVALID,
    REASON_NO_OVERRIDE,
    REASON_NOT_NEWER,
    REASON_SIG_INVALID,
    REASON_SIG_MISSING,
    REASON_UNREADABLE,
    BundleIntegrityError,
    LoadedBundle,
    compiled_on_of,
    load_hotlines_bytes,
    override_dir_location,
)
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.fallback import fallback_text
from olivia.core.resources.resolver import resolve
from olivia.core.resources.store import LineKind, ResourceDataError, ResourceStore, parse_store
from olivia.core.session import Session, TurnResult
from olivia.core.storage import app_data_dir, data_dir_location
from olivia.core.taxonomy import Taxonomy, load_taxonomy
from olivia.core.yaml_load import safe_load
from olivia.doctor import HOTLINE_MAX_AGE_DAYS, StoreState
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
# Why the profile cannot be opened and what to do next (S1; 草稿：待 G-0): only locked or
# unreachable for now, or the keys are gone for good, or the data is damaged.
PROFILE_LOCKED_NOW: Final = (
    "加密保存的信息现在打不开：系统钥匙串锁住了、没有响应，或者这次登录用不了它。"
    "你的文件我没有改动；解锁钥匙串（比如重新登录这台电脑）以后再试一次就好。"
)
PROFILE_KEYS_LOST: Final = (
    "加密保存的信息再也打不开了：解锁它的钥匙已经不在这台电脑的钥匙串里，或者钥匙文件坏了"
    "（可能被删掉了，或者这些文件是从别的电脑拷过来的）。你的文件我没有改动。"
)
PROFILE_START_OVER: Final = (
    "想从头开始的话，可以运行 olivia forget --all 清除这台电脑上的全部记录，"
    "再运行 olivia chat 重新设置；这样之前的记录会全部丢失。"
)
# S1 (草稿：待 G-0): the hotlines come first when the profile cannot be opened.
CHAT_CANNOT_START: Final = "这次没办法开始聊天。需要的话，下面的电话随时可以联系："
RESOURCES_REGION_UNREADABLE: Final = (
    "现在读不出你保存的地区，所以上面是全球通用的资源。"
    "想看当地的电话，可以运行 olivia resources 加地区代码，例如 olivia resources CN；"
    "设置恢复以后，olivia resources 就会直接显示当地的电话。"
)
# S3 (草稿：待 G-0): the packaged hotline data failed verification; fallback_text() is shown.
CHAT_DATA_DAMAGED: Final = (
    "因为没法确认求助电话是否准确，这次先不开始聊天；重新安装以后，再运行 olivia chat 就好。"
)
# E5 (草稿：待 G-0): the packaged perception model was wanted but could not be used.
MODEL_UNAVAILABLE: Final = "这台电脑上的模型文件这次用不了，危机筛查先只用规则，其他都照常。"
HEALTH_NOT_SAVED: Final = (
    "这台电脑上没有可用的系统钥匙串，健康信息没办法加密保存，所以之前记下的健康信息已经删除了。"
    "其他的一切都照常。"
)
# 草稿：待 G-0 -- robustness findings D1-D4, C2 (2026-10-26).
DATA_DIR_BUSY: Final = (
    "另一个 OLIVIA 正在运行，请先关掉它，再来这里。这次我什么都没有改动。"
    "需要求助电话的话，olivia resources 随时都能用。"
)
# 草稿：待 G-0 -- QA 2026-10-26 #8: ``chat`` shows the numbers before it refuses.
CHAT_BUSY: Final = (
    "另一个 OLIVIA 正在运行，请先关掉它，再来这里。这次我什么都没有改动。"
    "需要的话，上面的电话随时可以联系。"
)
# QA 2026-10-26 #12 (草稿：待 G-0): the region decides which numbers a crisis card shows,
# and the version recovered may hold an older one, so it is named every time.
PROFILE_RECOVERED: Final = (
    "设置文件坏了，已经恢复到 {time} 前后保存的版本，在那之后改过的地方可能没有了。"
    "{region}健康信息、称呼和不想谈的话题，请用 olivia health 和 olivia profile 检查一下。"
)
PROFILE_RECOVERED_TIME: Final = "{time}（这台电脑的时区 {zone}）"
PROFILE_RECOVERED_REGION: Final = (
    "恢复后的地区是{label}（{code}），求助电话按这个地区显示，请用 olivia region 核对；"
)
PROFILE_RECOVERED_NO_REGION: Final = (
    "恢复后的版本里没有保存地区，求助电话会显示全球通用的资源，请用 olivia region 设置；"
)
PROFILE_UNREADABLE: Final = (
    "设置文件现在打不开（可能是权限不对，或者被换成了文件夹）。我没有改动它。"
    "可以运行 olivia doctor 看看是哪里不对。"
)
# QA 2026-10-26 #8 (草稿：待 G-0): said after ``fallback_text(damaged=False)``, so the
# numbers are on screen even when ``resources`` would fail the same way.
# QA r3 (草稿：待 G-0): the same, when the data directory cannot be read or written.
DATA_DIR_UNUSABLE: Final = (
    "这台电脑上的数据目录现在读不了或者写不了（可能是权限不对，或者被换成了文件），"
    "这次没能做完，已经停下了。需要的话，上面的电话随时可以联系。"
    "运行 olivia doctor 可以看到是哪里不对、怎么修。"
)
UNEXPECTED_ERROR: Final = (
    "出了点问题，这次没能做完，已经停下了。需要的话，上面的电话随时可以联系。"
    "可以运行 olivia doctor 检查一下这台电脑上的设置和数据文件。"
)
# QA 2026-10-26 #4 (草稿：待 G-0): a crisis sentence typed while setting up (onboarding,
# profile, health, safety-plan) is not taken as an answer; the numbers come first.
SETUP_CRISIS: Final = (
    "你刚才写的这句话，让我有点担心你。设置可以先放一放，你的安全更要紧："
    "如果你现在很难受，或者有伤害自己的念头，请联系下面的电话，或者叫一位身边信任的人过来陪着你。"
)
SETUP_CHOICE: Final = "想继续，还是先退出？"
SETUP_CHOICES: Final = ("继续", "先退出")
SETUP_CHOICE_UNKNOWN: Final = "我没太看懂这个回答，可以选一个序号吗？"
SETUP_RETRY: Final = "好，我们继续。刚才那句我没有记下，可以重新回答下面的问题。"
# QA r3 (草稿：待 G-0): topic words such as "自杀、死亡、前任" are saved as taboo topics; the
# numbers still come, under this line, and nothing is asked.
SETUP_TOPICS: Final = (
    "好，这些话题我不会主动提起。要是它们让你想起很难受的事，下面的电话随时可以联系，"
    "也可以找一位信任的人陪你说说。"
)
SETUP_LEFT: Final = (
    "好，先停在这里，刚才那句没有保存。上面的电话随时可以联系；想回来的时候，再运行一次就好。"
)
_SETUP_GO_ON: Final = frozenset({"1", "继续"})
_SETUP_LEAVE: Final = frozenset({"2", "先退出", "退出", EXIT_COMMAND})
NOT_ONBOARDED: Final = "还没有完成第一次设置。先运行 olivia chat，之后就可以修改地区了。"
NOT_SET_UP: Final = (
    "还没有完成第一次设置，这台电脑上还没有可以查看或忘掉的内容。先运行 olivia chat 吧。"
)
NO_REGION: Final = "还没有保存地区。"
ADULTS_ONLY: Final = "这里的陪伴只为成年人设计，所以不会保存地区信息。"
# QA 2026-10-26 #8 (草稿：待 G-0): a region for one look at its numbers, never saved, so it
# works for an under-18 refusal record too.
RESOURCES_ONE_OFF_HINT: Final = (
    "想看某个地区的求助电话，可以运行 olivia resources 加地区代码，"
    "例如 olivia resources HK（只是查看，不会保存）。"
)
RESOURCES_ONE_OFF: Final = "这次只是查看，没有保存地区。"
RESOURCES_UNKNOWN: Final = (
    "没有认出「{raw}」这个地区，所以上面先列出了全球通用的资源。"
    "想看某个地区的电话，可以用下面的代码或名称：\n{choices}"
)
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
RESOURCES_SET_REGION: Final = (
    "告诉我你所在的国家或地区后，就能显示当地的电话：olivia region <代码>。"
    "只想看一眼的话，也可以运行 olivia resources <代码>，例如 olivia resources HK。"
)
RESOURCES_EMERGENCY: Final = "紧急电话："
RESOURCES_HOURS: Final = "服务时间："
RESOURCES_FOOTER: Final = "资料整理于 {compiled_on}（第 {version} 版）"
# Where the shown data comes from (GEO-08, F14): the built-in data or a signed update in
# the data directory's resources folder.
RESOURCES_SOURCE_BUILTIN: Final = "资料来源：随程序附带"
RESOURCES_SOURCE_UPDATE: Final = "资料来源：更新包（整理于 {compiled_on}，签名已验证）"
RESOURCES_UPDATE_UNUSED: Final = "资料来源：随程序附带（更新包未启用：{reason}）"
RESOURCES_UPDATE_UNREADABLE: Final = "无法读取"
RESOURCES_UPDATE_REASONS: Final = {
    REASON_SIG_MISSING: "缺少签名文件",
    REASON_SIG_INVALID: "签名验证没有通过",
    REASON_UNREADABLE: RESOURCES_UPDATE_UNREADABLE,
    REASON_FUTURE: "整理日期晚于今天",
    REASON_NOT_NEWER: "不比随程序附带的资料新",
    # S2 (草稿：待 G-0): a signed update that is not complete, well-formed hotline data.
    REASON_INVALID: "内容格式不对",
    REASON_INCOMPLETE: "缺少随程序附带资料里的地区或紧急电话",
}
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

# ``olivia doctor`` (``olivia/doctor.py``): one marked line per check. Only states, dates,
# counts and versions go into the slots, never anything the user typed or a store holds.
DOCTOR_OK: Final = "✓"
DOCTOR_WARN: Final = "!"
DOCTOR_FAIL: Final = "✗"
DOCTOR_HEADING: Final = "OLIVIA 自检（只读，不联网，不会改动任何文件）："
DOCTOR_FOOTER: Final = "以上内容不含你的个人信息，可以放心转给我们。"
DOCTOR_VERSION: Final = "OLIVIA {version} · Python {python} · {system}"
DOCTOR_DIR: Final = "数据目录：{location}"
DOCTOR_DIR_ABSENT: Final = "数据目录：还没有（{location}，第一次设置时会建立）"
DOCTOR_DIR_NOT_DIR: Final = (
    "数据目录：{location} 是一个文件，不是文件夹，程序没办法在这里保存。"
    "可以把这个文件改个名字或者挪走（里面有要留的东西就先备份），再运行 olivia chat"
)
# QA r3 (草稿：待 G-0): a data directory this account cannot read or write, and how to fix it.
DOCTOR_DIR_UNREADABLE: Final = (
    "数据目录读不了：{location} 或者里面的文件夹、文件没有读取权限，程序打不开你的设置和记录"
)
DOCTOR_DIR_UNWRITABLE: Final = (
    "数据目录写不了：{location} 或者里面的文件夹没有写入权限，设置和记录都没办法保存"
)
DOCTOR_FIX_POSIX: Final = (
    "怎么修：在终端里运行 chmod -R u+rwX {path}，把读写权限还给自己，再运行一次 olivia doctor"
)
DOCTOR_FIX_WINDOWS: Final = (
    "怎么修：在这个文件夹上点右键，打开「属性」里的「安全」，给自己的账户勾上读取和写入，"
    "再运行一次 olivia doctor"
)
DOCTOR_PERMISSIONS_OK: Final = "数据目录的权限：只有你自己能读写"
DOCTOR_PERMISSIONS_OFF: Final = "数据目录的权限：有 {count} 处和应有的不一样，应当只有你自己能读写"
DOCTOR_PERMISSIONS_WINDOWS: Final = "数据目录的权限：Windows 上不做这项检查"
DOCTOR_KEYCHAIN_READY: Final = "系统钥匙串：可以使用（只确认了它在，没有读取或改动里面的任何条目）"
DOCTOR_KEYCHAIN_NONE: Final = (
    "系统钥匙串：这台电脑上没有。聊天记录、健康信息和安全计划不会保存，其他照常"
)
DOCTOR_KEYCHAIN_UNAVAILABLE: Final = "系统钥匙串：现在打不开，可能被锁住了，或者没有响应"
DOCTOR_KEYCHAIN_UNCHECKED: Final = (
    "系统钥匙串：没有检测，这种钥匙串没办法在不碰里面条目的情况下确认能不能用"
)
DOCTOR_ONBOARDED: Final = "第一次设置：已完成"
DOCTOR_NOT_ONBOARDED: Final = "第一次设置：还没有完成（运行 olivia chat 开始）"
DOCTOR_ONBOARDED_UNKNOWN: Final = "第一次设置：说不准，因为设置文件打不开"
DOCTOR_STORE_NAMES: Final = {
    "profile": "设置文件",
    "ledger": "聊天记录",
    "state": "锦囊与方法偏好",
    "care": "关心提醒",
    "safety_plan": "安全计划",
}
DOCTOR_STORE_STATES: Final = {
    StoreState.ABSENT: (DOCTOR_OK, "{name}：没有"),
    StoreState.READY: (DOCTOR_OK, "{name}：能打开"),
    StoreState.PARTLY: (DOCTOR_FAIL, "{name}：有一部分打不开"),
    StoreState.BROKEN: (DOCTOR_FAIL, "{name}：打不开，文件或钥匙不完整"),
    StoreState.LOCKED: (DOCTOR_FAIL, "{name}：现在打不开，要等系统钥匙串能用"),
    StoreState.UNREADABLE: (DOCTOR_FAIL, "{name}：读不了，没有读取权限"),
}
DOCTOR_STORES_NOTE: Final = "加密的内容都没有解密，只检查了文件和钥匙是否齐全、完好。"
DOCTOR_MODEL_OK: Final = "本机模型：文件齐全，校验通过"
DOCTOR_MODEL_FAILED: Final = "本机模型：校验没有通过（{reason}），聊天时会自动只用规则做危机筛查"
DOCTOR_HOTLINES_OK: Final = "随程序附带的热线资料：签名有效，整理于 {compiled_on}，距今 {days} 天"
DOCTOR_HOTLINES_STALE: Final = "，已经超过 {max_days} 天，可以更新程序：pipx reinstall olivia"
DOCTOR_HOTLINES_BROKEN: Final = (
    "随程序附带的热线资料：签名验证没有通过，程序文件可能不完整，请重新安装"
)
# QA r3 (草稿：待 G-0): every packaged wording, lexicon and taxonomy file is loaded once.
DOCTOR_PACKAGED_OK: Final = "程序自带的文字与词表：{count} 组都能正常读取"
DOCTOR_PACKAGED_BROKEN: Final = (
    "程序自带的文字与词表：{names} 读不出来，程序文件可能不完整，请重新安装：pipx reinstall olivia"
)
DOCTOR_UPDATE_NONE: Final = "热线更新包：没有，用的是随程序附带的资料"
DOCTOR_UPDATE_USED: Final = "热线更新包：在用（整理于 {compiled_on}，距今 {days} 天，签名已验证）"
DOCTOR_UPDATE_STALE: Final = "，已经超过 {max_days} 天，可以换一份新的更新包"
DOCTOR_UPDATE_UNUSED: Final = "热线更新包：没有启用（{reason}），用的是随程序附带的资料"
DOCTOR_UPDATE_UNCHECKED: Final = "热线更新包：没有检查，因为随程序附带的资料没有通过验证"
DOCTOR_REMINDERS_ON: Final = "系统提醒：已安装"
DOCTOR_REMINDERS_OFF: Final = "系统提醒：没有安装"
DOCTOR_REMINDERS_UNKNOWN: Final = "系统提醒：没能确认有没有安装"
DOCTOR_REMINDERS_MISSING: Final = (
    "系统提醒：设置里是打开的，但系统里没有找到它的定时任务。可以在 olivia settings 里关掉再打开"
)
DOCTOR_REMINDERS_LEFTOVER: Final = (
    "系统提醒：设置里是关闭的，系统里却还留着它的定时任务。"
    "在 olivia settings 里打开再关掉，就会把它删掉"
)
# 草稿：待 G-0 -- what the data-integrity markers say (only shown when true).
DOCTOR_BUSY: Final = (
    "另一个 OLIVIA 正在运行：在它关掉之前，会改动数据的命令不会动手"
    "（olivia resources 和自检不受影响）"
)
DOCTOR_FORGET_UNFINISHED: Final = (
    "上一次「全部忘掉」没有做完：请再运行一次 olivia forget --all，把它清理干净"
)
DOCTOR_RECOVERED: Final = (
    "设置文件坏过，已经从自动备份恢复：请用 olivia region、olivia health 和 olivia profile 检查一下"
)
DOCTOR_KEYCHAIN: Final = {
    Probe.READY: (DOCTOR_OK, DOCTOR_KEYCHAIN_READY),
    Probe.NONE: (DOCTOR_WARN, DOCTOR_KEYCHAIN_NONE),
    Probe.UNAVAILABLE: (DOCTOR_FAIL, DOCTOR_KEYCHAIN_UNAVAILABLE),
    Probe.UNCHECKED: (DOCTOR_WARN, DOCTOR_KEYCHAIN_UNCHECKED),
}
DOCTOR_TEXTS: Final = (
    DOCTOR_BUSY,
    DOCTOR_FORGET_UNFINISHED,
    DOCTOR_RECOVERED,
    DOCTOR_HEADING,
    DOCTOR_FOOTER,
    DOCTOR_VERSION,
    DOCTOR_DIR,
    DOCTOR_DIR_ABSENT,
    DOCTOR_DIR_NOT_DIR,
    DOCTOR_DIR_UNREADABLE,
    DOCTOR_DIR_UNWRITABLE,
    DOCTOR_FIX_POSIX,
    DOCTOR_FIX_WINDOWS,
    DOCTOR_PACKAGED_OK,
    DOCTOR_PACKAGED_BROKEN,
    DOCTOR_PERMISSIONS_OK,
    DOCTOR_PERMISSIONS_OFF,
    DOCTOR_PERMISSIONS_WINDOWS,
    *(text for _, text in DOCTOR_KEYCHAIN.values()),
    DOCTOR_ONBOARDED,
    DOCTOR_NOT_ONBOARDED,
    DOCTOR_ONBOARDED_UNKNOWN,
    *DOCTOR_STORE_NAMES.values(),
    *(text for _, text in DOCTOR_STORE_STATES.values()),
    DOCTOR_STORES_NOTE,
    DOCTOR_MODEL_OK,
    DOCTOR_MODEL_FAILED,
    DOCTOR_HOTLINES_OK,
    DOCTOR_HOTLINES_STALE,
    DOCTOR_HOTLINES_BROKEN,
    DOCTOR_UPDATE_NONE,
    DOCTOR_UPDATE_USED,
    DOCTOR_UPDATE_STALE,
    DOCTOR_UPDATE_UNUSED,
    DOCTOR_UPDATE_UNCHECKED,
    DOCTOR_REMINDERS_ON,
    DOCTOR_REMINDERS_OFF,
    DOCTOR_REMINDERS_UNKNOWN,
    DOCTOR_REMINDERS_MISSING,
    DOCTOR_REMINDERS_LEFTOVER,
)

USER_TEXTS: Final = (
    GOODBYE,
    CHAT_HINT,
    CHAT_HELP,
    DATA_DIR_BUSY,
    CHAT_BUSY,
    SETUP_CRISIS,
    SETUP_CHOICE,
    *SETUP_CHOICES,
    SETUP_CHOICE_UNKNOWN,
    SETUP_RETRY,
    SETUP_TOPICS,
    SETUP_LEFT,
    PROFILE_RECOVERED,
    PROFILE_RECOVERED_TIME,
    PROFILE_RECOVERED_REGION,
    PROFILE_RECOVERED_NO_REGION,
    PROFILE_UNREADABLE,
    UNEXPECTED_ERROR,
    DATA_DIR_UNUSABLE,
    PROFILE_CORRUPT,
    PROFILE_LOCKED,
    PROFILE_LOCKED_NOW,
    PROFILE_KEYS_LOST,
    PROFILE_START_OVER,
    CHAT_CANNOT_START,
    RESOURCES_REGION_UNREADABLE,
    CHAT_DATA_DAMAGED,
    MODEL_UNAVAILABLE,
    HEALTH_NOT_SAVED,
    NOT_ONBOARDED,
    NOT_SET_UP,
    NO_REGION,
    ADULTS_ONLY,
    RESOURCES_ONE_OFF_HINT,
    RESOURCES_ONE_OFF,
    RESOURCES_UNKNOWN,
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
    RESOURCES_SOURCE_BUILTIN,
    RESOURCES_SOURCE_UPDATE,
    RESOURCES_UPDATE_UNUSED,
    *RESOURCES_UPDATE_REASONS.values(),
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
    *DOCTOR_TEXTS,
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
            _enable_line_editing()
            try:
                return clean_input(input(prompt))
            except EOFError:
                return None
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        # Piped input is not echoed, so end the prompt line here (the text is not shown).
        self.stdout.write("\n")
        if not line:
            return None
        return clean_input(line.rstrip("\r\n"))


class _Asker(Protocol):
    """What the setup exchanges need from a console: say a block, ask for a line."""

    def say(self, text: str = "") -> None: ...

    def ask(self, prompt: str) -> str | None: ...


@dataclass
class _SetupConsole:
    """A console whose replies pass the crisis screen first (QA 2026-10-26 #4).

    For onboarding, ``olivia profile``, ``olivia health`` and ``olivia safety-plan``. A
    reply that screens at L2 or above is not handed on: ``show_help`` puts the hotlines on
    screen (the region chosen so far; before that, every supported region's emergency
    numbers) under one gentle line,
    and the user chooses to go on or to leave -- at every such reply, however many come in
    one run. Going on asks the same question again (the reply is dropped); leaving ends the
    exchange as end of input does, with nothing of that reply saved, and sets ``left``.

    ``ask(..., topics=True)`` is the taboo-topic question: a list of topic words
    (``setup_screen.topic_words_only``: "自杀、死亡、前任") is taken after the numbers and
    one gentle line, without asking (QA r3); a sentence there is screened as anywhere else.

    The safety plan decides per section what happens to such a reply, so it calls
    :meth:`check` (the numbers and the choice) and keeps or drops the reply itself
    (``safety_plan.Screened``).
    """

    inner: _Console
    screen: SetupScreen
    show_help: Callable[[], object]
    left: bool = False
    _since_ask: list[str] = field(default_factory=list)
    """What was said since the last reply: the question, to show again."""

    def say(self, text: str = "") -> None:
        self._since_ask.append(text)
        self.inner.say(text)

    def ask(self, prompt: str, *, topics: bool = False) -> str | None:
        while True:
            reply = self.inner.ask(prompt)
            question, self._since_ask = self._since_ask, []
            if reply is None or not self.screen.alarms(reply):
                return reply
            if topics and topic_words_only(reply):
                self._help(SETUP_TOPICS)
                self.inner.say()
                return reply
            if not self._go_on():
                self.left = True
                self.inner.say(SETUP_LEFT)
                return None
            self.inner.say(SETUP_RETRY)
            self.inner.say()
            while question and not question[0]:
                question.pop(0)
            for line in question:
                self.say(line)

    def check(self, reply: str) -> Screened:
        """For the safety plan: CLEAR, or the numbers and then GO_ON or LEAVE."""
        if not self.screen.alarms(reply):
            return Screened.CLEAR
        if self._go_on():
            return Screened.GO_ON
        self.left = True
        return Screened.LEAVE

    def _help(self, lead: str = SETUP_CRISIS) -> None:
        self.inner.say()
        self.inner.say(lead)
        self.inner.say()
        self.show_help()

    def _go_on(self) -> bool:
        """The hotlines, then whether to go on (False also at end of input)."""
        self._help()
        while True:
            self.inner.say()
            self.inner.say(SETUP_CHOICE)
            for number, option in enumerate(SETUP_CHOICES, start=1):
                self.inner.say(f"  {number}. {option}")
            answer = self.inner.ask(ANSWER_PROMPT)
            if answer is None:
                return False
            self.inner.say()
            folded = unicodedata.normalize("NFKC", answer).strip().rstrip("。.").casefold()
            if folded in _SETUP_GO_ON:
                return True
            if folded in _SETUP_LEAVE:
                return False
            if self.screen.alarms(answer):
                self._help()
            else:
                self.inner.say(SETUP_CHOICE_UNKNOWN)


@functools.cache
def _enable_line_editing() -> None:  # pragma: no cover - terminal only
    """Let ``input`` edit by character, not by byte.

    Without it a terminal's own line editing (macOS by default) erases one byte per
    backspace, so deleting a Chinese character leaves two bytes of it in the line. The
    history it keeps stays in memory; nothing is written to disk. Windows has no
    ``readline`` and its console already edits by character.

    ``readline`` takes the locale's character set when it loads: under a C or POSIX
    locale (``LC_ALL=C`` over SSH or in a container) it reads each byte of a Chinese
    character as a key of its own and garbles the line ("我不想活了" arrived as "f活了").
    So the character set is switched to UTF-8 first, and without a UTF-8 locale on the
    system ``readline`` stays off (``clean_input`` then mends what the terminal sends).
    """
    name = _utf8_ctype()
    if name is None:
        return
    if name:
        # Python's readline sets the character-set locale from the environment on every
        # line it reads, so the environment has to say UTF-8 as well, for the rest of the
        # run (programs this one starts inherit it, which they read text in anyway).
        import os

        os.environ["LC_ALL"] = os.environ["LC_CTYPE"] = name
    with contextlib.suppress(ImportError):
        import readline

        _keep_terminal_sequences(readline)


_SEQUENCE_BINDINGS: Final = (
    # Insert these keys literally instead of reading them as commands, so a terminal
    # sequence reaches ``strip_controls`` whole: ESC ] would otherwise be eaten as an
    # unbound Meta key and BEL as "abort", leaving the sequence's text ("0;pwned") in the
    # line with nothing to show where it ends (QA r3).
    r'"\e]": "\C-v\e]"',
    r'"\e[": "\C-v\e["',
    r'"\e\\": "\C-v\e\\"',
    r'"\C-g": "\C-v\C-g"',
)


def _keep_terminal_sequences(readline: Any) -> None:  # pragma: no cover - terminal only
    """GNU readline bindings for :data:`_SEQUENCE_BINDINGS`; libedit (another binding
    syntax) is left as it is."""
    if "libedit" in (readline.__doc__ or ""):
        return
    for binding in _SEQUENCE_BINDINGS:
        readline.parse_and_bind(binding)


_UTF8_LOCALES: Final = ("C.UTF-8", "C.utf8", "en_US.UTF-8", "UTF-8")
"""Tried in order when the locale's character set is not UTF-8 (``UTF-8`` is macOS's)."""


def _utf8_ctype() -> str | None:  # pragma: no cover - terminal only
    """Make the character-set locale UTF-8: "" when it already was, the name of the UTF-8
    locale switched to, or None when the system has none."""
    if sys.platform == "win32":  # no readline, and the console reads Unicode
        return None
    import locale

    if locale.nl_langinfo(locale.CODESET).replace("-", "").upper() == "UTF8":
        return ""
    for name in _UTF8_LOCALES:
        try:
            locale.setlocale(locale.LC_CTYPE, name)
        except locale.Error:
            continue
        return name
    return None


_TERMINAL_SEQUENCE: Final = re.compile(
    # CSI (colours, cursor moves), OSC (window titles, links) and two-character escapes,
    # in their 7-bit (ESC) and 8-bit (C1) spellings.
    r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]?"
    r"|(?:\x1b\]|\x9d)[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?"
    r"|\x1b[ -/]*[0-~]?"
)
_CONTROL_CHARACTERS: Final = re.compile(
    # C0 controls but tab and newline, DEL, C1 controls, and the bidirectional marks,
    # embeddings, overrides and isolates (QA 2026-10-26 #14).
    "[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)


def strip_controls(text: str) -> str:
    """``text`` without terminal control sequences, control characters (tab and newline
    are kept) or Unicode direction controls.

    A colour code would be echoed back into a reply and recolour the terminal; an unclosed
    U+202E (RIGHT-TO-LEFT OVERRIDE) reverses every character printed after it. Neither
    carries anything the user meant to say, so they never reach the session or a store.
    """
    return _CONTROL_CHARACTERS.sub("", _TERMINAL_SEQUENCE.sub("", text))


def clean_input(text: str) -> str:
    """``text`` read as UTF-8, or as GB18030 when it is a GBK / GB18030 line, else without
    the bytes of a half-deleted or invalid character; then :func:`strip_controls`."""
    return strip_controls(_decode_input(text))


def _decode_input(text: str) -> str:
    """``text`` read as UTF-8, or as GB18030 when it is a GBK / GB18030 line, else without
    the bytes of a half-deleted or invalid character.

    Undecodable input bytes arrive as lone surrogates (``surrogateescape``); they would
    reach the crisis screen as noise and cannot be encoded for the encrypted stores. A
    terminal in a GBK or GB18030 locale (a zh_CN.GBK shell, a Windows console in code
    page 936) sends Chinese that is not UTF-8 at all, and dropping its bytes would drop the
    whole sentence, a crisis sentence included. So a line that is not UTF-8 is decoded as
    GB18030 (strictly) when most of its non-ASCII bytes are not valid UTF-8; a line that is
    mostly valid UTF-8 with one broken character keeps the UTF-8 reading, because GB18030
    would turn the valid UTF-8 around it into other characters.
    """
    try:
        raw = text.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:  # a lone surrogate that no decoder produced
        raw = text.encode("utf-8", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    kept = raw.decode("utf-8", "ignore")
    valid_multibyte = sum(len(ch.encode("utf-8")) for ch in kept if ord(ch) > 0x7F)
    broken = len(raw) - len(kept.encode("utf-8"))
    if broken > valid_multibyte:
        with contextlib.suppress(UnicodeDecodeError):
            return raw.decode("gb18030")
    return kept


def _system_clock() -> datetime:
    return datetime.now(UTC)


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _profile_zone(profile: PersonaProfile | None) -> ZoneInfo | None:
    """The profile's timezone; this computer's when that zone is missing or unknown here
    (None when the computer's cannot be read either)."""
    zone = (
        _zone(profile.region.timezone)
        if profile is not None and profile.region is not None
        else None
    )
    return zone if zone is not None else _zone(onboarding.system_timezone())


def _local_clock(clock: Clock, profile: PersonaProfile) -> Clock:
    """``clock`` in the profile's timezone (:func:`_profile_zone`)."""
    zone = _profile_zone(profile)
    if zone is None:  # pragma: no cover - system_timezone only returns known names
        return clock
    return lambda: clock().astimezone(zone)


# -- chat ------------------------------------------------------------------------------------


def _show_prompt(console: _Asker, prompt: Prompt) -> None:
    console.say(prompt.text)
    for number, option in enumerate(prompt.options, start=1):
        console.say(f"  {number}. {option}")


def _setup_hotlines(console: _Console, region: UserRegion | None, clock: Clock) -> None:
    """The numbers for a crisis sentence typed during the first visit: the region's card
    once one is chosen; before that the emergency numbers of every supported region
    (``resources/fallback.py``, the same list the fixed help shows), not a lone 112 (QA r3)."""
    if region is None:
        console.say(fallback_text(damaged=False))
        return
    _show_hotlines(console, None, clock, region=region)


def _onboard(
    console: _Console,
    tax: Taxonomy,
    store: ProfileStore,
    now: datetime,
    screen: SetupScreen | None = None,
) -> PersonaProfile | None:
    """Run (or skip) onboarding; the adult profile, or None when the visit ends here.

    With ``screen`` every reply is crisis-screened first (:class:`_SetupConsole`; the
    hotlines for the region chosen so far, the global ones before that)."""
    flow = OnboardingFlow(tax, store, now)
    outcome = flow.outcome
    if outcome is None:
        asker: _Console | _SetupConsole = console
        if screen is not None:
            asker = _SetupConsole(
                console, screen, lambda: _setup_hotlines(console, flow.region, lambda: now)
            )
        step: Prompt | Completed | Refused = flow.prompt()
        while isinstance(step, Prompt):
            _show_prompt(asker, step)
            if isinstance(asker, _SetupConsole):
                answer = asker.ask(ANSWER_PROMPT, topics=step.step is onboarding.Step.TABOO)
            else:
                answer = asker.ask(ANSWER_PROMPT)
            if answer is None:
                if not (isinstance(asker, _SetupConsole) and asker.left):
                    console.say(GOODBYE)
                return None
            asker.say()
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
    # F15: the kind of note question and what the recorder found, ids only (never the note).
    recall = data.get("note_recall")
    recalled = data.get("note_recall_result")
    # F15: a turn the F10 denial cap lowered shows the level before the cap too, since in a
    # crisis that is the level the tracker read ("风险"); display only.
    uncapped = data.get("uncapped_level")
    lines = [
        f"┌ inspect · 第 {_fmt(data.get('turn'))} 轮",
        f"│ 风险 {_fmt(data.get('level'))}（本轮筛查 {_fmt(data.get('assessed_level'))}"
        + (f"，否认封顶前 {_fmt(uncapped)}" if uncapped else "")
        + "）"
        + f" · 危机中 {_fmt(data.get('in_crisis'))} · 线索 {_fmt(data.get('cue_ids'))}"
        + f" · 关怀问候 {_fmt(data.get('care_greeting'))}",
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
        # 2026-10-26: the question a model-only alarm asked, not a rule cue (display only).
        + ("（只有模型报警）" if check and data.get("safety_check_by") == "model" else "")
        + (" · 安全计划 已展示" if data.get("safety_plan_shown") is True else "")
        + (" · 安全计划 一句提醒" if data.get("safety_plan_reminded") is True else "")
        + (" · 联系身边人 已肯定" if data.get("reach_out") is True else "")
        + (f" · 调出笔记 {_fmt(recall)}（{_fmt(recalled)}）" if recall else ""),
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
    screen = SetupScreen(tax, student=student)
    try:
        profile = _onboard(console, tax, store, clock(), screen)
    except KeyboardInterrupt:  # like end of input here: nothing was set up
        console.say()
        console.say(GOODBYE)
        return 1
    except (ProfileCorruptError, ProfileLockedError) as exc:
        # S1: the numbers first (the saved region's if its plaintext part can be read),
        # then why the chat cannot start and what to do next.
        console.say(CHAT_CANNOT_START)
        console.say()
        _hotlines_for_unreadable_profile(console, store, exc, clock)
        return 1
    if store.dropped_sensitive_data:
        console.say(HEALTH_NOT_SAVED)
    if profile is None:  # declined, under 18, or input ended: nothing was set up
        return 1
    _tell_recovery(console, profile)  # before the conversation, not after it
    local = _local_clock(clock, profile)
    # The posteriors and the kit from earlier sessions (B3); None starts fresh.
    state_store = StateStore(store.path.parent, store.vault)
    plan_store = SafetyPlanStore(vault=store.vault)
    # A crisis reply reads sections 2-4 back: an entry saved before the plan command
    # screened them is left out if it is itself a crisis sentence (QA r3). Screened as
    # ``olivia safety-plan`` screens (the student too, even under ``--rules``: leaving an
    # entry out is the cautious side).
    plan_screen = screen if student else SetupScreen(tax)
    plan = without_crisis_entries(plan_store.load_quietly(), plan_screen.alarms)
    try:
        session = Session.open(
            tax,
            profile,
            rng=rng if rng is not None else random.Random(),
            now=local,
            student=student,
            carried=state_store.load(),
            safety_plan=plan,
            suggest_safety_plan=plan is None and plan_store.should_suggest(),
            hotline_updates=override_dir_location(),
        )
    except HOTLINE_DATA_DAMAGED:  # S3: no chat without verified numbers; the fixed help
        console.say(fallback_text())
        console.say()
        console.say(CHAT_DATA_DAMAGED)
        return 1
    if session.risk_model_fallback is not None:  # E5: said once; the reason is for --inspect
        console.say(MODEL_UNAVAILABLE)
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
        tax,
        ledger,
        recorder,
        lambda: console.ask(ANSWER_PROMPT),
        console.say,
        method_titles=titles,
        taboo_topics=profile.taboo_topics,
        persona=profile.persona_spectrum,
    )
    interrupted = False
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
                console.say(_failed_turn_reply(tax, profile, local().date()))
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
    except KeyboardInterrupt:  # Ctrl-C ends the chat like /exit, with the same goodbye
        interrupted = True
    finally:
        if not recorder.close():
            console.say(ledger.text.replies["summary_not_saved"])
        state_recorder.observe(session.carried_state())
    if interrupted:
        console.say()
    # S5: ending in the crisis flow (or with a safety question unanswered) leaves the
    # region's numbers and the plan's people on screen, and asks nothing.
    farewell = session.farewell()
    if farewell is None:
        console.say(GOODBYE)
        return 0
    console.say(f"{profile.agent_name}：{farewell.text}")
    care_recorder.observe_level(farewell.level)
    return 0


def _failed_turn_reply(tax: Taxonomy, profile: PersonaProfile, today: date) -> str:
    """Every number for the region after a failed turn; the fixed help (S3) when the
    hotline data cannot be verified now."""
    minimal = load_language_data(tax).render.crisis_minimal
    try:
        store = _load_store(today)
    except HOTLINE_DATA_DAMAGED:
        return f"{profile.agent_name}：{minimal}\n{fallback_text()}"
    card = resolve(store, profile.region, CrisisLevel.L3, mode=CardMode.BROWSING, today=today)
    numbers = [e.number for e in card.emergency] + [ln.number for ln in card.lines]
    return "\n".join([f"{profile.agent_name}：{minimal}", *(f"· {n}" for n in numbers)])


def _card_titles(tax: Taxonomy) -> dict[str, str]:
    """Action id -> the exercise card title the user saw, for the ledger's summaries."""
    return {aid: card.title for aid, card in load_language_data(tax).cards.cards.items()}


# -- resources and region ---------------------------------------------------------------------


HOTLINE_DATA_DAMAGED: Final = (BundleIntegrityError, ResourceDataError)
"""The packaged hotline data is missing, unreadable, unverified or invalid (S3)."""


def _load_bundle(today: date) -> LoadedBundle:
    """The verified hotline data: a newer signed update in the data directory's
    ``resources`` folder, else the built-in data (GEO-08, F14)."""
    return load_hotlines_bytes(override_dir_location(), today=today)


def _load_store(today: date) -> ResourceStore:
    """The same verified hotline data a session uses."""
    return parse_store(safe_load(_load_bundle(today).data))


def _hotline_source(bundle: LoadedBundle) -> str:
    """Which data ``olivia resources`` shows: the update and its date, or the built-in data
    (with why an update that is there was not used)."""
    if bundle.source == "override":
        return RESOURCES_SOURCE_UPDATE.format(compiled_on=compiled_on_of(bundle.data).isoformat())
    if bundle.reason is None or bundle.reason == REASON_NO_OVERRIDE:
        return RESOURCES_SOURCE_BUILTIN
    reason = RESOURCES_UPDATE_REASONS.get(bundle.reason, RESOURCES_UPDATE_UNREADABLE)
    return RESOURCES_UPDATE_UNUSED.format(reason=reason)


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


def _unreadable_profile(exc: ProfileCorruptError | ProfileLockedError) -> tuple[str, ...]:
    """Why the profile cannot be opened, and what to do next (S1): a keychain that is only
    locked or unreachable (try again later); keys gone for good or damaged (D4: a damaged
    key is ``ProfileLockedError(lost)``, never a rollback) or damaged data (starting over
    with ``olivia forget --all`` loses the records); a file the system will not read (C2:
    ``olivia doctor``, nothing is lost)."""
    if isinstance(exc, ProfileLockedError):
        return (PROFILE_KEYS_LOST, PROFILE_START_OVER) if exc.lost else (PROFILE_LOCKED_NOW,)
    if isinstance(exc, ProfileUnreadableError):
        return (PROFILE_UNREADABLE,)
    return (PROFILE_CORRUPT, PROFILE_START_OVER)


def _load_profile(console: _Console) -> tuple[bool, PersonaProfile | None]:
    """(readable, profile); an unreadable profile is reported and never overwritten."""
    store = ProfileStore()
    try:
        profile = store.load()
    except (ProfileCorruptError, ProfileLockedError) as exc:
        for line in _unreadable_profile(exc):
            console.say(line)
        return False, None
    if store.dropped_sensitive_data:
        console.say(HEALTH_NOT_SAVED)
    _tell_recovery(console, profile)  # before anything the command says (QA #12)
    return True, profile


def _save_profile(console: _Console, profile: PersonaProfile) -> bool:
    """Save, or report (and change nothing) when encrypted data cannot be written now
    (a damaged key included: robustness C3)."""
    try:
        ProfileStore().save(profile)
    except (ProfileCorruptError, ProfileLockedError) as exc:
        for line in _unreadable_profile(exc):
            console.say(line)
        return False
    return True


def _tell_recovery(console: _Console, profile: PersonaProfile | None = None) -> None:
    """Say once that the profile was recovered from a snapshot (robustness D4), with the
    snapshot's time on this computer's clock with the zone named (QA r3) and the region
    the recovered version holds (QA 2026-10-26 #12).

    The version a damaged main file is recovered from is the newest snapshot that opens,
    which is the one before the last save: its region may not be the one last chosen, and
    nothing on disk says what that was, so the region is always named. Called right after
    the command's own load, so it comes before anything else the command says."""
    base = data_dir_location()
    try:
        moment = ProfileStore(base).take_recovery_notice() if base.is_dir() else None
    except OSError:  # a data directory without permissions: ``olivia doctor`` says so
        return
    if moment is None:
        return
    # This computer's clock, named (QA r3): the profile's zone may be the recovered
    # version's, which is not where the user is now.
    zone = _zone(onboarding.system_timezone())
    shown = moment.astimezone(zone) if zone is not None else moment.astimezone(UTC)
    when = PROFILE_RECOVERED_TIME.format(
        time=shown.strftime("%Y-%m-%d %H:%M"), zone=zone.key if zone is not None else "UTC"
    )
    region = profile.region if profile is not None else None
    if region is None:
        named = PROFILE_RECOVERED_NO_REGION
    else:
        code = region.country_code
        named = PROFILE_RECOVERED_REGION.format(label=_region_label(code), code=code)
    console.say(PROFILE_RECOVERED.format(time=when, region=named))
    console.say()


def _show_hotlines(
    console: _Console,
    profile: PersonaProfile | None,
    clock: Clock,
    *,
    region: UserRegion | None = None,
) -> bool:
    """The BROWSING card for ``region`` (by default ``profile``'s; ZZ without one) and its
    data source; the fixed help instead, and False, when the hotline data cannot be
    verified (S3)."""
    if region is None and profile is not None:
        region = profile.region
    minor = profile is not None and profile.is_age_gate_refusal
    today = (_local_clock(clock, profile) if profile is not None else clock)().date()
    try:
        store = _load_store(today)
        source = _hotline_source(_load_bundle(today))
    except HOTLINE_DATA_DAMAGED:
        console.say(fallback_text())
        return False
    card = resolve(
        store, region, CrisisLevel.L3, mode=CardMode.BROWSING, today=today, is_minor=minor
    )
    console.say(render_browsing(card, _taxonomy()))
    console.say(source)
    return True


def _hotlines_for_unreadable_profile(
    console: _Console,
    store: ProfileStore,
    exc: ProfileCorruptError | ProfileLockedError,
    clock: Clock,
) -> None:
    """S1: the hotlines for the plaintext part of a profile that cannot be opened (the
    region is plaintext unless the whole profile is sealed, ONB-06), the global ones when
    nothing is readable; then why and what next."""
    readable = store.load_unsealed()
    _show_hotlines(console, readable, clock)
    console.say()
    if readable is None:
        console.say(RESOURCES_REGION_UNREADABLE)
    for line in _unreadable_profile(exc):
        console.say(line)


def _resources(console: _Console, code: str | None, clock: Clock) -> int:
    """The saved region's card; it never needs the keychain (S1).

    When the profile cannot be opened, its plaintext part still gives the region (exit 0);
    when nothing is readable (the whole profile sealed and locked, or every copy damaged)
    the global resources are shown with why and what next (exit 1, README).

    ``code`` (``olivia resources HK``) shows that region's card once and saves nothing, so
    it needs no profile and works beside an under-18 refusal record too, where ``olivia
    region`` saves nothing (QA 2026-10-26 #8). An unknown code is a wrong value (exit 2).
    """
    if code is not None:
        return _resources_for(console, code, clock)
    store = ProfileStore()
    try:
        profile = store.load()
    except (ProfileCorruptError, ProfileLockedError) as exc:
        profile = store.load_unsealed()
        if profile is None:
            _hotlines_for_unreadable_profile(console, store, exc, clock)
            return 1
    else:
        if store.dropped_sensitive_data:
            console.say(HEALTH_NOT_SAVED)
        _tell_recovery(console, profile)
    if not _show_hotlines(console, profile, clock):
        return 1
    region = profile.region if profile is not None else None
    if profile is not None and profile.is_age_gate_refusal:
        console.say()
        console.say(RESOURCES_ONE_OFF_HINT)
    elif region is None:
        console.say()
        console.say(RESOURCES_SET_REGION)
    elif region.country_code == UNKNOWN_COUNTRY:  # chosen ("其他地区，或不想说"): no nagging
        console.say()
        console.say(RESOURCES_ONE_OFF_HINT)
    return 0


def _resources_for(console: _Console, raw: str, clock: Clock) -> int:
    """``olivia resources CODE``: the card for CODE, shown once and never saved."""
    try:
        store_data = _load_store(clock().date())
    except HOTLINE_DATA_DAMAGED:
        console.say(fallback_text())
        return 1
    code = region_from_reply(raw, load_onboarding_text(), numbers=False)
    if code is None or not store_data.has_region(code):
        # QA r3: someone in Japan typing "JP" still gets numbers first (the global card).
        _show_hotlines(console, None, clock)
        console.say()
        console.say(RESOURCES_UNKNOWN.format(raw=raw.strip(), choices=_region_choices(store_data)))
        return 2
    profile = _profile_for_card()
    zone = DEFAULT_TIMEZONES.get(code, onboarding.system_timezone())
    if not _show_hotlines(console, profile, clock, region=UserRegion(code, zone)):
        return 1
    console.say()
    console.say(RESOURCES_ONE_OFF)
    return 0


def _profile_for_card() -> PersonaProfile | None:
    """The profile, only to know whether the minors' lines belong on a card; None when it
    cannot be read for any reason (QA r3: a data directory without permissions)."""
    store = ProfileStore(data_dir_location())
    try:
        return store.load()
    except Exception:  # noqa: BLE001 - only one flag is wanted here
        with contextlib.suppress(Exception):
            return store.load_unsealed()
        return None


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
        console.say(RESOURCES_ONE_OFF_HINT)
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
    store = ProfileStore()
    try:
        editor = HealthEditor(_taxonomy(), store, clock())
        if store.dropped_sensitive_data:  # robustness E4: say what the migration removed
            console.say(HEALTH_NOT_SAVED)
        _tell_recovery(console, editor.profile)
        outcome = editor.outcome
        if outcome is None:
            asker = _SetupConsole(
                console,
                SetupScreen(_taxonomy()),
                lambda: _show_hotlines(console, editor.profile, clock),
            )
            step: HealthPrompt | HealthDone = editor.prompt()
            while isinstance(step, HealthPrompt):
                asker.say(step.text)
                for number, option in enumerate(step.options, start=1):
                    asker.say(f"  {number}. {option}")
                answer = asker.ask(ANSWER_PROMPT)
                if answer is None:
                    return 0
                asker.say()
                step = editor.answer(answer)
            outcome = step
    except (ProfileCorruptError, ProfileLockedError) as exc:
        for line in _unreadable_profile(exc):
            console.say(line)
        return 1
    console.say(outcome.text)
    return 0 if outcome.ok else 1


# -- safety plan ------------------------------------------------------------------------------


def _safety_plan(console: _Console, clock: Clock) -> int:
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
    # QA #4, r3: every crisis sentence brings the numbers and the choice; the plan keeps
    # it only in sections 1 and 5 (``safety_plan.Screened``).
    screen = _SetupConsole(
        console, SetupScreen(_taxonomy()), lambda: _show_hotlines(console, profile, clock)
    )
    return run_command(
        lambda: console.ask(ANSWER_PROMPT), console.say, SafetyPlanStore(), screen=screen.check
    )


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
    ledger = Ledger(
        store.path.parent, store.vault, method_titles=titles, zone=_profile_zone(profile)
    )
    now = _local_clock(clock, profile)()
    return run_journal(
        lambda: console.ask(ANSWER_PROMPT),
        console.say,
        ledger,
        now,
        method_titles=titles,
        taboo_topics=profile.taboo_topics,
        persona=profile.persona_spectrum,
    )


def _stats(console: _Console, clock: Clock) -> int:
    """``olivia stats``: the local usage numbers (``chang/stats.py``, F12)."""
    readable, profile = _load_profile(console)
    if not readable:
        return 1
    replies = load_stats_text().replies
    if profile is None:
        console.say(replies["not_onboarded"])
        return 1
    if profile.is_age_gate_refusal:
        console.say(replies["adults_only"])
        return 1
    store = ProfileStore()
    ledger = Ledger(store.path.parent, store.vault)
    now = _local_clock(clock, profile)()
    return run_stats(console.say, ledger, now, _taxonomy().late_night_window())


# -- memory and forget ------------------------------------------------------------------------


def _data_stores(profile: PersonaProfile | None) -> DataStores:
    """Every store; the ledger shows times in the profile's current timezone (Q-8)."""
    base = ProfileStore().path.parent
    return DataStores.open(
        base,
        method_titles=_card_titles(_taxonomy()),
        on_forget_all=(lambda: remove_reminders(notify_system.current_host(), base),),
        zone=_profile_zone(profile),
        taxonomy=_taxonomy(),
    )


def _profile_quietly(console: _Console) -> tuple[bool, PersonaProfile | None]:
    """(readable, profile) without saying why it cannot be read (the commands report errors
    themselves); a recovery from a snapshot is said first (QA #12)."""
    try:
        profile = ProfileStore().load()
    except (ProfileCorruptError, ProfileLockedError):
        return False, None
    _tell_recovery(console, profile)
    return True, profile


def _memory(console: _Console, edit: int | None, clock: Clock) -> int:
    """``olivia memory``: what is stored on this device, on screen only (B5); with
    ``--edit N``, change the words of note N (PRD feature 5)."""
    readable, profile = _profile_quietly(console)
    if readable and profile is None:
        console.say(NOT_SET_UP)
        return 1
    if profile is not None and profile.is_age_gate_refusal:
        console.say(load_forget_text().memory["adults_only"])
        return 1
    stores = _data_stores(profile)
    if edit is not None:
        return run_edit(lambda: console.ask(ANSWER_PROMPT), console.say, stores, edit)
    return run_memory(console.say, stores, now=clock())


_FORGET_FLAGS: Final = (
    ("ledger", Target.LEDGER),
    ("kit", Target.KIT),
    ("safety_plan", Target.SAFETY_PLAN),
    ("all", Target.ALL),
)


def _forget(console: _Console, args: argparse.Namespace, clock: Clock) -> int:
    """``olivia forget``: the menu, or the target a flag names (B5)."""
    target = next((t for flag, t in _FORGET_FLAGS if getattr(args, flag)), None)
    readable, profile = _profile_quietly(console)
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
        _data_stores(profile),
        target=target,
        entry=args.entry,
        method=args.method,
        assume_yes=args.yes,
        now=clock(),
    )


# -- privacy ----------------------------------------------------------------------------------


def _privacy(console: _Console) -> int:
    """``olivia privacy``: the privacy notice (B8); nothing is read or written."""
    console.say(privacy_notice(data_dir_location()))
    return 0


# -- doctor -----------------------------------------------------------------------------------

Row = tuple[str, str]
"""(mark, text); an empty mark is an indented note under the line before."""


def _shown_location(path: Path) -> str:
    """``path`` with the home directory as ``~``: the account name stays off the screen."""
    try:
        relative = path.relative_to(Path.home())
    except (ValueError, RuntimeError):  # not under home, or no home directory known
        return str(path)
    return "~" if relative == Path() else f"~/{relative.as_posix()}"


def _age(today: date, then: date) -> int:
    return max(0, (today - then).days)


def _shell_path(path: Path) -> str:
    """``path`` as it can be typed in a POSIX shell, the home directory as ``~``."""
    shown = _shown_location(path)
    if shown == "~":
        return shown
    if shown.startswith("~/"):
        return "~/" + shlex.quote(shown[2:])
    return shlex.quote(shown)


def _doctor_fix(location: Path) -> Row:
    if sys.platform == "win32":
        return "", DOCTOR_FIX_WINDOWS
    return "", DOCTOR_FIX_POSIX.format(path=_shell_path(location))


def _doctor_dir_rows(found: doctor.DataDir) -> list[Row]:
    where = _shown_location(found.location)
    if found.kind == "absent":
        return [(DOCTOR_OK, DOCTOR_DIR_ABSENT.format(location=where))]
    if found.kind == "other" or found.access == "file":
        return [(DOCTOR_FAIL, DOCTOR_DIR_NOT_DIR.format(location=where))]
    if found.access == "unreadable":
        return [
            (DOCTOR_FAIL, DOCTOR_DIR_UNREADABLE.format(location=where)),
            _doctor_fix(found.location),
        ]
    rows = [(DOCTOR_OK, DOCTOR_DIR.format(location=where))]
    if found.access == "unwritable":
        rows = [
            (DOCTOR_FAIL, DOCTOR_DIR_UNWRITABLE.format(location=where)),
            _doctor_fix(found.location),
        ]
    if found.mismatched is None:
        rows.append((DOCTOR_OK, DOCTOR_PERMISSIONS_WINDOWS))
    elif found.mismatched:
        rows.append((DOCTOR_WARN, DOCTOR_PERMISSIONS_OFF.format(count=found.mismatched)))
    else:
        rows.append((DOCTOR_OK, DOCTOR_PERMISSIONS_OK))
    return rows


def _doctor_store_rows(report: doctor.Report) -> list[Row]:
    profile = report.profile
    if profile.onboarded is None:
        rows = [(DOCTOR_WARN, DOCTOR_ONBOARDED_UNKNOWN)]
    elif profile.onboarded:
        rows = [(DOCTOR_OK, DOCTOR_ONBOARDED)]
    else:
        rows = [(DOCTOR_WARN, DOCTOR_NOT_ONBOARDED)]
    states = {"profile": profile.state, **report.stores}
    for name, label in DOCTOR_STORE_NAMES.items():
        mark, template = DOCTOR_STORE_STATES[states[name]]
        rows.append((mark, template.format(name=label)))
    rows.append(("", DOCTOR_STORES_NOTE))
    return rows


def _doctor_activity_rows(found: doctor.Activity) -> list[Row]:
    """The data directory's markers, one line each, only when they say something."""
    rows: list[Row] = []
    if found.busy:
        rows.append((DOCTOR_WARN, DOCTOR_BUSY))
    if found.forget_unfinished:
        rows.append((DOCTOR_FAIL, DOCTOR_FORGET_UNFINISHED))
    if found.recovered:
        rows.append((DOCTOR_WARN, DOCTOR_RECOVERED))
    return rows


def _doctor_hotline_rows(found: doctor.HotlineFacts, today: date) -> list[Row]:
    if not found.builtin_ok or found.builtin_on is None:
        return [(DOCTOR_FAIL, DOCTOR_HOTLINES_BROKEN), (DOCTOR_WARN, DOCTOR_UPDATE_UNCHECKED)]
    days = _age(today, found.builtin_on)
    text = DOCTOR_HOTLINES_OK.format(compiled_on=found.builtin_on.isoformat(), days=days)
    # Old data only matters while it is the data in use.
    stale = days > HOTLINE_MAX_AGE_DAYS and found.used != "override"
    if stale:
        text += DOCTOR_HOTLINES_STALE.format(max_days=HOTLINE_MAX_AGE_DAYS)
    rows = [(DOCTOR_WARN if stale else DOCTOR_OK, text)]
    if found.used == "override" and found.override_on is not None:
        days = _age(today, found.override_on)
        text = DOCTOR_UPDATE_USED.format(compiled_on=found.override_on.isoformat(), days=days)
        stale = days > HOTLINE_MAX_AGE_DAYS
        if stale:
            text += DOCTOR_UPDATE_STALE.format(max_days=HOTLINE_MAX_AGE_DAYS)
        rows.append((DOCTOR_WARN if stale else DOCTOR_OK, text))
    elif found.reason is None:
        rows.append((DOCTOR_OK, DOCTOR_UPDATE_NONE))
    else:
        reason = RESOURCES_UPDATE_REASONS.get(found.reason, RESOURCES_UPDATE_UNREADABLE)
        rows.append((DOCTOR_WARN, DOCTOR_UPDATE_UNUSED.format(reason=reason)))
    return rows


def _doctor_packaged_row(found: doctor.PackagedData) -> Row:
    if found.failed:
        return DOCTOR_FAIL, DOCTOR_PACKAGED_BROKEN.format(names="；".join(found.failed))
    return DOCTOR_OK, DOCTOR_PACKAGED_OK.format(count=found.checked)


def _doctor_reminder_row(installed: bool | None, switched_on: bool | None) -> Row:
    if installed is None:
        return DOCTOR_WARN, DOCTOR_REMINDERS_UNKNOWN
    if switched_on is True and not installed:
        return DOCTOR_WARN, DOCTOR_REMINDERS_MISSING
    if switched_on is False and installed:
        return DOCTOR_WARN, DOCTOR_REMINDERS_LEFTOVER
    return DOCTOR_OK, DOCTOR_REMINDERS_ON if installed else DOCTOR_REMINDERS_OFF


def doctor_rows(report: doctor.Report, today: date) -> list[Row]:
    """Every line of ``olivia doctor`` for ``report``, marked ✓ / ! / ✗."""
    system = " ".join(part for part in (platform.system(), platform.machine()) if part)
    version = DOCTOR_VERSION.format(
        version=package_version(), python=platform.python_version(), system=system or "-"
    )
    reason = report.model_reason
    return [
        (DOCTOR_OK, version),
        *_doctor_dir_rows(report.data_dir),
        DOCTOR_KEYCHAIN[report.keychain],
        *_doctor_store_rows(report),
        *_doctor_activity_rows(report.activity),
        (DOCTOR_OK, DOCTOR_MODEL_OK)
        if reason is None
        else (DOCTOR_FAIL, DOCTOR_MODEL_FAILED.format(reason=reason)),
        *_doctor_hotline_rows(report.hotlines, today),
        _doctor_packaged_row(report.packaged),
        _doctor_reminder_row(report.reminders, report.profile.notifications),
    ]


def _doctor(console: _Console, clock: Clock) -> int:
    """``olivia doctor``: check this computer's setup, read-only and offline.

    Works before the first visit. Exit 1 when any line is ✗, else 0 (warnings included).
    """
    today = clock().date()
    report = doctor.examine(data_dir_location(), today=today, host=notify_system.current_host)
    rows = doctor_rows(report, today)
    console.say(DOCTOR_HEADING)
    for mark, text in rows:
        console.say(f"{mark} {text}" if mark else f"  {text}")
    console.say(DOCTOR_FOOTER)
    return 1 if any(mark == DOCTOR_FAIL for mark, _ in rows) else 0


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


# -- names and taboo topics -------------------------------------------------------------------


def _profile(console: _Console, clock: Clock) -> int:
    """``olivia profile``: both names and the taboo topics (JTBD 4, F11)."""
    readable, profile = _load_profile(console)
    if not readable:
        return 1
    words = load_onboarding_text().profile
    if profile is None:
        console.say(words["not_onboarded"])
        return 1
    if profile.is_age_gate_refusal:
        console.say(words["adults_only"])
        return 1
    asker = _SetupConsole(  # QA #4: a crisis sentence is never taken as a name or topic
        console, SetupScreen(_taxonomy()), lambda: _show_hotlines(console, profile, clock)
    )
    return run_profile(
        lambda: asker.ask(ANSWER_PROMPT),
        asker.say,
        profile,
        save=lambda changed: _save_profile(console, changed),
        now=clock(),
        ask_topics=lambda: asker.ask(ANSWER_PROMPT, topics=True),
    )


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
    resources = commands.add_parser("resources", help="查看所在地区的求助电话")
    resources.add_argument(
        "code",
        nargs="?",
        metavar="地区",
        help="只看这一次的地区（不会保存），例如 HK、US；不写就用保存的地区",
    )
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
    commands.add_parser("stats", help="看看使用数字：聊天次数、深夜占比等（不含聊天内容）")
    persona = commands.add_parser("persona", help="查看或更换陪伴方式")
    persona.add_argument(
        "choice",
        nargs="?",
        metavar="陪伴方式",
        help="序号（1–4）或简称，例如 2、温和、哲思、理性、树洞",
    )
    commands.add_parser("profile", help="查看或修改双方的称呼和不想谈的话题")
    memory = commands.add_parser(
        "memory", help="查看 OLIVIA 在这台电脑上记得什么（只显示在屏幕上）"
    )
    memory.add_argument(
        "--edit", type=int, metavar="序号", help="修改一条你让我记住的话（序号见 olivia memory）"
    )
    forget = commands.add_parser("forget", help="让 OLIVIA 忘掉一条记录、一类数据或全部数据")
    which = forget.add_mutually_exclusive_group()
    which.add_argument(
        "--entry", type=int, metavar="序号", help="忘掉一条记录（序号见 olivia memory）"
    )
    which.add_argument("--ledger", action="store_true", help="忘掉全部聊天记录")
    which.add_argument(
        "--method",
        type=int,
        metavar="序号",
        help="重置一个小练习的方法偏好（序号见 olivia memory 的“方法偏好”）",
    )
    which.add_argument("--kit", action="store_true", help="忘掉锦囊与方法偏好")
    which.add_argument("--safety-plan", action="store_true", help="删掉个人安全计划")
    which.add_argument("--all", action="store_true", help="忘掉全部数据，之后从头开始")
    forget.add_argument("--yes", action="store_true", help="不再询问确认")
    commands.add_parser(
        "privacy", help="看看 OLIVIA 怎么保护你的隐私：存了什么、存在哪里、怎么删除"
    )
    commands.add_parser("settings", help="查看或修改设置：系统提醒（默认关闭）、保存方式")
    commands.add_parser(
        "doctor", help="检查这台电脑上的运行环境（只读；结果不含个人信息，可以转给我们）"
    )
    commands.add_parser("notify-check")  # no help: hidden; the scheduled job runs it (B9)
    return parser


def _use_utf8_stdio() -> None:
    """Read and write UTF-8 on the real streams.

    Piped streams otherwise use the locale encoding (cp1252 on many Windows setups),
    which cannot carry Chinese text; a console window is unaffected. Input that is not
    valid UTF-8 is read through ``surrogateescape`` (``clean_input`` drops it) rather
    than stopping the program.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    reconfigure = getattr(sys.stdin, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="surrogateescape")


_WRITING_COMMANDS: Final = frozenset(
    {"chat", "health", "safety-plan", "settings", "profile", "journal", "forget", "notify-check"}
)
"""Commands that always write data; ``persona``, ``region`` and ``memory`` write only
when asked to change something (:func:`_writes`)."""
_EXEMPT_FROM_UNFINISHED: Final = frozenset({"resources", "privacy", "doctor"})
"""Read-only commands that still run while a ``forget --all`` waits to be finished
(``doctor`` reports it as one of its checks)."""


def _writes(args: argparse.Namespace) -> bool:
    """Whether this command line writes to the data directory (and so takes its lock)."""
    if args.command in _WRITING_COMMANDS:
        return True
    if args.command == "persona":
        return args.choice is not None
    if args.command == "region":
        return bool(args.code is not None or args.timezone is not None or args.clear)
    if args.command == "memory":
        return args.edit is not None
    return False


def _forget_all_unfinished_here() -> bool:
    """:func:`forget_all_unfinished` for the data directory; False when the directory is
    not there or cannot be read (QA r3: a directory without permissions must not stop
    ``doctor``, ``privacy`` or ``resources``; a command that needs it says so itself)."""
    base = data_dir_location()
    try:
        return base.is_dir() and forget_all_unfinished(base)
    except OSError:
        return False


def _forget_all_pending(args: argparse.Namespace) -> bool:
    """An interrupted ``forget --all`` waits to be finished, and this command is not the
    one that finishes it (robustness E2)."""
    if not _forget_all_unfinished_here():
        return False
    if args.command == "forget" and args.all:
        return False
    return args.command not in _EXEMPT_FROM_UNFINISHED


def _dispatch(
    args: argparse.Namespace,
    console: _Console,
    now: Clock,
    rng: random.Random | None,
) -> int:
    if args.command == "chat":
        return _chat(console, args.inspect, now, rng, student=not args.rules)
    if args.command == "resources":
        return _resources(console, args.code, now)
    if args.command == "health":
        return _health(console, now)
    if args.command == "persona":
        return _persona(console, args.choice, now)
    if args.command == "profile":
        return _profile(console, now)
    if args.command == "safety-plan":
        return _safety_plan(console, now)
    if args.command == "journal":
        return _journal(console, now)
    if args.command == "stats":
        return _stats(console, now)
    if args.command == "memory":
        return _memory(console, args.edit, now)
    if args.command == "forget":
        return _forget(console, args, now)
    if args.command == "privacy":
        return _privacy(console)
    if args.command == "settings":
        return _settings(console, now)
    if args.command == "doctor":
        return _doctor(console, now)
    if args.command == "notify-check":
        return _notify_check(now)
    return _region(console, args.code, args.timezone, args.clear, now)


def _hotlines_unlocked(console: _Console, clock: Clock) -> None:
    """The saved region's card without the data directory's lock and without the keychain
    (QA 2026-10-26 #8): the plaintext part of the profile gives the region
    (:meth:`ProfileStore.load_unsealed`, which never writes or decrypts); the global card
    when that cannot be read, the fixed help when the hotline data cannot be verified."""
    profile: PersonaProfile | None
    try:
        profile = ProfileStore(data_dir_location()).load_unsealed()
    except Exception:  # noqa: BLE001 - only the region is wanted here; ZZ without it
        profile = None
    _show_hotlines(console, profile, clock)


def _run(
    args: argparse.Namespace,
    console: _Console,
    now: Clock,
    rng: random.Random | None,
) -> int:
    """One command under the data directory's lock when it writes (D1-D3)."""
    if _forget_all_pending(args):
        if args.command == "chat":  # QA #8: no chat is refused without the numbers
            _hotlines_unlocked(console, now)
            console.say()
        console.say(load_forget_text().forget["unfinished"])
        return 1
    lock: DataDirLock | None = None
    if _writes(args):
        lock = DataDirLock(app_data_dir())
        try:
            lock.acquire()
        except DataDirBusyError:
            if args.command == "chat":  # QA #8: the numbers before the refusal
                _hotlines_unlocked(console, now)
                console.say()
                console.say(CHAT_BUSY)
                return 1
            if args.command != "notify-check":  # the scheduled job stays silent
                console.say(DATA_DIR_BUSY)
                return 1
            return 0
    try:
        code = _dispatch(args, console, now, rng)
        if args.command not in ("notify-check", "doctor"):  # doctor writes nothing at all
            _tell_recovery(console)
        if args.command == "resources" and _forget_all_unfinished_here():
            console.say()
            console.say(load_forget_text().forget["unfinished"])
        return code
    finally:
        if lock is not None:
            lock.release()


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
    for name, value in vars(args).items():  # a region or persona typed on the command line
        if isinstance(value, str):  # is echoed back like a typed line (QA #14)
            setattr(args, name, clean_input(value))
    console = _Console(stdin or sys.stdin, stdout or sys.stdout)
    now = clock if clock is not None else _system_clock
    try:
        return _run(args, console, now, rng)
    except KeyboardInterrupt:
        console.say()
        console.say(GOODBYE)
        return 0
    except Exception:  # noqa: BLE001 - the last resort: never a traceback
        if args.command == "notify-check":
            return 1  # the scheduled job prints nothing
        # QA 2026-10-26 #8: the numbers written in the program first (they need no data
        # file), then what happened; ``resources`` may fail the same way.
        with contextlib.suppress(Exception):
            console.say(fallback_text(damaged=False))
            console.say()
        with contextlib.suppress(Exception):
            unusable = doctor.access_problem(data_dir_location()) is not None
            console.say(DATA_DIR_UNUSABLE if unusable else UNEXPECTED_ERROR)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
