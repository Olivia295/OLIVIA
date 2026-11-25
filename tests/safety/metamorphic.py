"""Metamorphic testing of the crisis screen: rewrites that keep a sentence's meaning.

Each :class:`Transform` is a pure function of the text. None of them changes what the
sentence says: its subject stays, and nothing adds a negation, a hypothetical, pinyin or a
homophone. They change only its surface: a filler word before it or a particle after it,
its punctuation, an emoji, the script (Traditional characters), invisible characters,
spaces or decorations on the characters, an unrelated everyday sentence before it (which
may name someone else, as everyday talk does), or saying it twice. So the screen's level
should not move, and :func:`holds` says how far it may (the invariance rule):

* a seed expected at L3 stays L3; one expected at L2 stays at L2 or above;
* a seed expected at L0 stays below L2;
* an L1 seed is only reported, never failed.

A seed whose original sentence already misses its expectation is a known gap of the
screen, not of a rewrite: it is skipped and counted (:func:`skipped`).

Seeds: tests/safety/cases.yaml (``expect``), composition_cases.yaml (``level``),
tuned_probe.yaml (``expect``) and known_false_positives.yaml (``ideal``). Never
tests/redteam/cases.yaml, which stays the independent G-5 gate.

tests/safety/test_metamorphic.py runs every (seed, transform) pair in rules mode, with the
gaps of known_metamorphic_gaps.yaml held strictly; scripts/metamorphic_report.py prints the
invariance rates and rewrites that file (``--write-gaps``).
"""

from __future__ import annotations

import json
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from olivia.core.models import CrisisLevel
from olivia.core.safety._trad2simp import TRAD_TO_SIMP

HERE = Path(__file__).parent
GAPS_FILE = HERE / "known_metamorphic_gaps.yaml"

# --- the transforms ------------------------------------------------------------------

# Sentence-final punctuation a suffix replaces, so "……。" or "。啊" never appears. A
# question mark stays: the particle goes before it, and a question gets no full stop.
_FINAL = "。．.!！~～…"
_QUESTION = "?？"
# Apostrophes and hyphens inside an English word are spelling, not punctuation ("don't").
_WORD_MARKS = frozenset("'’-")


def _strip_final(text: str) -> str:
    return text.rstrip(_FINAL + " ")


def _add_final(text: str, word: str) -> str:
    body = text.rstrip(" ")
    asked = len(body) - len(body.rstrip(_QUESTION))
    if not asked:
        return _strip_final(body) + word
    if word == "。":
        return body
    return _strip_final(body[:-asked]) + word + body[-asked:]


def _is_punct(text: str, i: int) -> bool:
    ch = text[i]
    if not unicodedata.category(ch).startswith("P"):
        return False
    if ch in _WORD_MARKS and 0 < i < len(text) - 1:
        before, after = text[i - 1], text[i + 1]
        if before.isascii() and before.isalpha() and after.isascii() and after.isalpha():
            return False
    return True


def strip_punctuation(text: str) -> str:
    """Every punctuation mark (Unicode category P) dropped."""
    return "".join(ch for i, ch in enumerate(text) if not _is_punct(text, i))


def punctuation_to_space(text: str) -> str:
    """Every punctuation mark replaced by a space."""
    return "".join(" " if _is_punct(text, i) else ch for i, ch in enumerate(text))


_HALF_CJK = {"。": "｡", "「": "｢", "」": "｣", "、": "､", "・": "･"}
_FULL_CJK = {half: full for full, half in _HALF_CJK.items()}


def _swap(ch: str) -> str:
    cp = ord(ch)
    if 0x21 <= cp <= 0x7E:
        return chr(cp + 0xFEE0)
    if 0xFF01 <= cp <= 0xFF5E:
        return chr(cp - 0xFEE0)
    if ch == " ":
        return "\u3000"
    if ch == "\u3000":
        return " "
    return _HALF_CJK.get(ch) or _FULL_CJK.get(ch, ch)


def swap_width(text: str) -> str:
    """Full-width and half-width forms swapped: ASCII <-> U+FF01-FF5E, space <-> U+3000,
    。「」、・ <-> their half-width forms."""
    return "".join(_swap(ch) for ch in text)


_ASCII_PUNCT = str.maketrans(
    {
        "。": ".",
        "，": ",",
        "、": ",",
        "！": "!",
        "？": "?",
        "：": ":",
        "；": ";",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "（": "(",
        "）": ")",
        "…": "...",
        "～": "~",
        "—": "-",
    }
)


def ascii_punctuation(text: str) -> str:
    """Chinese punctuation as an input method in English-punctuation mode types it."""
    return text.translate(_ASCII_PUNCT)


def repeat_exclamation(text: str) -> str:
    """Every exclamation mark tripled; a sentence without one ends in three."""
    if "！" in text or "!" in text:
        return text.replace("！", "！！！").replace("!", "!!!")
    return text.rstrip("。.") + "！！！"


def repeat_ellipsis(text: str) -> str:
    """Every ellipsis tripled; a sentence without one ends in a long one."""
    if "…" in text:
        return text.replace("…", "………")
    return text.rstrip("。.") + "…………"


def _prefix(word: str) -> Callable[[str], str]:
    def apply(text: str) -> str:
        return word + text

    return apply


def _suffix(word: str) -> Callable[[str], str]:
    def apply(text: str) -> str:
        return _add_final(text, word)

    return apply


def _append(tail: str) -> Callable[[str], str]:
    def apply(text: str) -> str:
        return text + tail

    return apply


def _traditional_views() -> dict[str, str]:
    # The fold table reversed: each Simplified character's first Traditional form.
    views: dict[str, str] = {}
    for trad, simp in TRAD_TO_SIMP.items():
        views.setdefault(simp, trad)
    return views


_TO_TRADITIONAL = str.maketrans(_traditional_views())


def to_traditional(text: str) -> str:
    """Simplified characters written in Traditional (the fold table of
    ``olivia/core/safety/_trad2simp.py`` read backwards)."""
    return text.translate(_TO_TRADITIONAL)


def _between(sep: str | Sequence[str]) -> Callable[[str], str]:
    seps = [sep] if isinstance(sep, str) else list(sep)

    def apply(text: str) -> str:
        out: list[str] = []
        for i, ch in enumerate(text):
            if i:
                out.append(seps[(i - 1) % len(seps)])
            out.append(ch)
        return "".join(out)

    return apply


def repeat_twice(text: str) -> str:
    """The whole sentence said twice, a space apart."""
    return f"{text} {text}"


@dataclass(frozen=True)
class Transform:
    name: str
    family: str
    label: str
    """What it does, in the report's words."""
    apply: Callable[[str], str]

    def __call__(self, text: str) -> str:
        return self.apply(text)


# Families group the transforms in the report and the gap file's header.
FAMILIES: Mapping[str, str] = {
    "prefix": "句首语气词",
    "suffix": "句末语气",
    "punct": "标点形式",
    "emoji": "句末表情",
    "script": "繁体",
    "invisible": "字间空格与零宽字符",
    "decoration": "字上的组合装饰符",
    "context": "句前接日常句",
    "repeat": "整句重复",
}

_INVISIBLE_MIX = ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u00ad")
# Invisible characters that are not format characters (Cf): the combining grapheme joiner,
# the Hangul fillers (U+3164 is the usual "blank" of a chat nickname), the Braille blank,
# a Khmer inherent vowel and a Mongolian variation selector.
_FILLERS = ("\u034f", "\u3164", "\uffa0", "\u2800", "\u115f", "\u1160", "\u17b4", "\u180b")


def underline_each(text: str) -> str:
    """Every character followed by U+0332 COMBINING LOW LINE, as "fancy text" makers
    underline a sentence."""
    return "".join(ch + "\u0332" for ch in text)


TRANSFORMS: tuple[Transform, ...] = (
    Transform("prefix_shuoshihua", "prefix", "句首加“说实话，”", _prefix("说实话，")),
    Transform("prefix_qishi", "prefix", "句首加“其实”", _prefix("其实")),
    Transform("prefix_en", "prefix", "句首加“嗯，”", _prefix("嗯，")),
    Transform("prefix_wogennishuo", "prefix", "句首加“我跟你说，”", _prefix("我跟你说，")),
    Transform("suffix_period", "suffix", "句末加“。”", _suffix("。")),
    Transform("suffix_ellipsis", "suffix", "句末加“……”", _suffix("……")),
    Transform("suffix_a", "suffix", "句末加“啊”", _suffix("啊")),
    Transform("punct_strip", "punct", "去掉全部标点", strip_punctuation),
    Transform("punct_to_space", "punct", "标点换成空格", punctuation_to_space),
    Transform("width_swap", "punct", "全角半角互换", swap_width),
    Transform("punct_ascii", "punct", "中文标点换成英文标点", ascii_punctuation),
    Transform("bang_repeat", "punct", "感叹号重复三遍", repeat_exclamation),
    Transform("ellipsis_repeat", "punct", "省略号重复", repeat_ellipsis),
    Transform("emoji_sob", "emoji", "句末加 😭", _append("😭")),
    Transform("emoji_upside_down", "emoji", "句末加 🙃", _append("🙃")),
    Transform(
        "emoji_zwj", "emoji", "句末加零宽连接的组合表情（😮 U+200D 💨）", _append("😮\u200d💨")
    ),
    Transform("emote_code_cry", "emoji", "句末加表情代码 [哭]", _append("[哭]")),
    Transform("traditional", "script", "简体换繁体", to_traditional),
    Transform("spaces_between", "invisible", "字间插空格", _between(" ")),
    Transform("zwsp_between", "invisible", "字间插 U+200B", _between("\u200b")),
    Transform("zwnj_between", "invisible", "字间插 U+200C", _between("\u200c")),
    Transform("bom_between", "invisible", "字间插 U+FEFF", _between("\ufeff")),
    Transform("invisible_mix", "invisible", "字间轮流插六种零宽格式字符", _between(_INVISIBLE_MIX)),
    Transform("invisible_fillers", "invisible", "字间轮流插八种不可见填充字符", _between(_FILLERS)),
    Transform("underline", "decoration", "每个字加组合下划线 U+0332", underline_each),
    Transform("lead_overtime", "context", "句前接“今天加班到九点。”", _prefix("今天加班到九点。")),
    Transform(
        "lead_overtime_space",
        "context",
        "句前接“今天加班到九点”，空格隔开",
        _prefix("今天加班到九点 "),
    ),
    Transform("lead_dinner", "context", "句前接“刚吃完晚饭。”", _prefix("刚吃完晚饭。")),
    Transform("lead_roommate", "context", "句前接“室友今天搬走了。”", _prefix("室友今天搬走了。")),
    Transform("repeat_twice", "repeat", "整句重复两遍", repeat_twice),
)
BY_NAME: Mapping[str, Transform] = {t.name: t for t in TRANSFORMS}

# --- seeds and the invariance rule ---------------------------------------------------


@dataclass(frozen=True)
class Seed:
    id: str
    source: str
    category: str
    expect: CrisisLevel
    text: str


def _load(name: str) -> Any:
    return yaml.safe_load((HERE / name).read_text(encoding="utf-8"))


def load_seeds() -> list[Seed]:
    """Every seed, in file order. Ids are unique across the files."""
    seeds = [
        Seed(c["id"], "cases", c["category"], CrisisLevel[c["expect"]], c["text"])
        for c in _load("cases.yaml")
    ]
    comp = _load("composition_cases.yaml")
    for part in ("positives", "negatives"):
        seeds += [
            Seed(c["id"], "compositions", f"comp:{c['kind']}", CrisisLevel[c["level"]], c["text"])
            for c in comp[part]
        ]
    seeds += [
        Seed(c["id"], "tuned_probe", "tuned_probe", CrisisLevel[c["expect"]], c["text"])
        for c in _load("tuned_probe.yaml")
    ]
    seeds += [
        Seed(c["id"], "known_limits", "known_limits", CrisisLevel[c["ideal"]], c["text"])
        for c in _load("known_false_positives.yaml")
    ]
    ids = [s.id for s in seeds]
    assert len(set(ids)) == len(ids), "seed ids must be unique across the seed files"
    return seeds


def holds(expect: CrisisLevel, level: CrisisLevel) -> bool | None:
    """Whether ``level`` keeps the invariance rule for a seed expected at ``expect``;
    ``None`` for an L1 seed (reported, never failed)."""
    if expect is CrisisLevel.L3:
        return level is CrisisLevel.L3
    if expect is CrisisLevel.L2:
        return level >= CrisisLevel.L2
    if expect is CrisisLevel.L0:
        return level < CrisisLevel.L2
    return None


def skipped(seed: Seed, original: CrisisLevel) -> bool:
    """The original sentence already misses its expectation: a known gap of the screen."""
    return holds(seed.expect, original) is False


@dataclass(frozen=True)
class Outcome:
    seed: Seed
    transform: Transform
    original: CrisisLevel
    level: CrisisLevel

    @property
    def held(self) -> bool | None:
        return holds(self.seed.expect, self.level)

    @property
    def key(self) -> str:
        return gap_key(self.seed.id, self.transform.name)

    @property
    def kind(self) -> str:
        """The gap's kind, as the gap file's reasons and header name it."""
        word = "误报" if self.seed.expect is CrisisLevel.L0 else "掉档"
        return f"{self.seed.expect.name} {word}到 {self.level.name}"


def gap_key(seed_id: str, transform: str) -> str:
    return f"{seed_id}/{transform}"


def run(
    assess: Callable[[str], CrisisLevel],
    seeds: Iterable[Seed],
    transforms: Sequence[Transform] = TRANSFORMS,
) -> tuple[list[Outcome], list[Seed]]:
    """Every (seed, transform) outcome of the seeds the screen gets right, and the seeds
    skipped because their original sentence misses its expectation."""
    outcomes: list[Outcome] = []
    skips: list[Seed] = []
    for seed in seeds:
        original = assess(seed.text)
        if skipped(seed, original):
            skips.append(seed)
            continue
        for transform in transforms:
            outcomes.append(Outcome(seed, transform, original, assess(transform(seed.text))))
    return outcomes, skips


# --- the gap file ----------------------------------------------------------------------


def load_gaps(path: Path = GAPS_FILE) -> dict[str, str]:
    """``{"<seed id>/<transform>": reason}`` of the gap file."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {entry["id"]: entry["reason"] for entry in doc.get("gaps") or []}


def reason(outcome: Outcome) -> str:
    return f"{outcome.kind}：{outcome.transform.label}（{outcome.seed.category}）"


def summary_lines(failures: Sequence[Outcome]) -> list[str]:
    """The gap file header's counts: by family and kind, by transform, by seed category."""
    by_family: Counter[tuple[str, str]] = Counter((o.transform.family, o.kind) for o in failures)
    lines = ["# 按变换类别与掉档方式："]
    for family, title in FAMILIES.items():
        kinds = sorted((k, n) for (f, k), n in by_family.items() if f == family)
        lines += [f"#   {title} · {k}：{n} 条" for k, n in kinds]
    by_transform = Counter(o.transform.name for o in failures)
    lines.append("# 按变换：")
    lines += [f"#   {t.name}：{by_transform[t.name]}" for t in TRANSFORMS if by_transform[t.name]]
    by_category = Counter(o.seed.category for o in failures)
    lines.append("# 按种子类别：")
    lines += [f"#   {c}：{n}" for c, n in sorted(by_category.items())]
    seeds = len({o.seed.id for o in failures})
    lines.append(f"# 合计：{len(failures)} 条（涉及 {seeds} 个种子）")
    return lines


HEADER = """\
# 危机筛查的变形测试（metamorphic testing）在规则模式下的已知缺口。
# 由 scripts/metamorphic_report.py --write-gaps 生成，从不手挑：它用 test_metamorphic.py
# 的入口（SafetyScreen.assess，规则模式）跑每个 (种子, 变换)，写下全部不满足不变性的组合。
# test_metamorphic.py 对这些条目做严格 xfail：某条开始通过，测试就失败，直到把它从这里删掉
# （重新运行生成脚本）；不在这里的组合一旦失败也是失败。绝不新增条目来掩盖回归。
#
# 不变性：期望 L3 的种子，变体仍是 L3；期望 L2 的，变体 ≥ L2；期望 L0 的，变体 < L2。
# L1 种子只报告。原句本身就没达到期望的种子跳过（规则模式下就是 known_false_positives.yaml
# 里 ideal 不是 L1 的条目：它们的 current 都不等于 ideal）。
# 变换都不改变句子的意思，定义见 tests/safety/metamorphic.py。
#
# 表层形式（零宽与不可见字符、组合装饰符、全角、繁体）的缺口在 normalize.py 与
# _trad2simp.py 里修，不进这个文件；这里只记录词表、组合规则与分句（compose.py、
# crisis.py、risk.yaml）里的缺口，在那里修好后重新生成。
#
"""


def render_gaps(failures: Sequence[Outcome]) -> str:
    """The gap file for ``failures`` (in seed file order, then transform order)."""
    body = ["gaps:"]
    if not failures:
        body = ["gaps: []"]
    for o in failures:
        body.append(f"  - id: {o.key}")
        body.append(f"    reason: {json.dumps(reason(o), ensure_ascii=False)}")
    return HEADER + "\n".join(summary_lines(failures)) + "\n\n" + "\n".join(body) + "\n"


def by_seed(keys: Iterable[str]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for key in keys:
        seed_id, transform = key.rsplit("/", 1)
        grouped[seed_id].add(transform)
    return grouped
