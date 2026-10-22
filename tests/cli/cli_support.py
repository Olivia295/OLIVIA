"""Constants and helpers shared by the ``olivia`` command-line tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from olivia.core.chang.profile import ProfileStore
from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.session import Session, TurnResult

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 22, 23, 30, tzinfo=SHANGHAI)
PANEL_PREFIXES = ("┌", "│", "└")

# Onboarding answers for a mainland adult: accept, 18+, name, default agent name, the one
# persona, no taboo topics, region 1 (CN, timezone set automatically), skip the consent.
ONBOARD_CN = ["1", "1", "小林", "", "", "", "1", "跳过"]

# An L3 sentence from tests/safety/cases.yaml (rp05, L3_ACT_FAREWELL).
L3_SENTENCE = "我写了一封遗书"


@dataclass
class Run:
    code: int
    out: str
    results: list[TurnResult]
    texts: list[str]
    sessions: list[Session]

    @property
    def lines(self) -> list[str]:
        return self.out.splitlines()

    @property
    def panel(self) -> list[str]:
        return [line for line in self.lines if line.startswith(PANEL_PREFIXES)]


def save_profile(home: Path, **overrides: object) -> PersonaProfile:
    fields: dict[str, object] = {
        "age_confirmed_18_plus": True,
        "created_at": NOW,
        "updated_at": NOW,
        "user_name": "小林",
        "region": UserRegion("CN", "Asia/Shanghai"),
    }
    fields.update(overrides)
    profile = PersonaProfile(**fields)  # type: ignore[arg-type]
    ProfileStore(home).save(profile)
    return profile


def files_under(home: Path) -> list[Path]:
    return sorted(p for p in home.rglob("*") if p.is_file())
