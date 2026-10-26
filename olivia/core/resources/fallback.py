"""Crisis help that needs no data file (S3), for when the packaged hotline data is damaged.

``bundle.load_hotlines_bytes`` raises :class:`~olivia.core.resources.bundle.BundleIntegrityError`
when ``hotlines.yaml`` or its signature is missing, unreadable or does not verify, and no
number from such a file is ever shown. ``olivia resources`` and ``olivia chat`` then show
:func:`fallback_text` instead: the common emergency numbers, the global helpline directory
and a note that the program files may be damaged.

The text is written here, not loaded, so it survives any damage to the data files.
``tests/resources/test_fallback.py`` locks it and checks every number against the verified
emergency numbers in ``hotlines.yaml`` (the same regions, numbers and order), so the two
cannot drift apart. Wording is a draft pending G-0 (草稿：待 G-0).
"""

from __future__ import annotations

from typing import Final

EMERGENCY: Final[tuple[tuple[str, str, tuple[tuple[str, str | None], ...]], ...]] = (
    ("CN", "中国大陆", (("110", "报警"), ("120", "急救"))),
    ("HK", "中国香港", (("999", None),)),
    ("MO", "中国澳门", (("999", None), ("110", None), ("112", None))),
    ("TW", "中国台湾", (("110", "报警"), ("119", "消防与救护"))),
    ("US", "美国", (("911", None),)),
    ("CA", "加拿大", (("911", None),)),
    ("GB", "英国", (("999", None),)),
    ("AU", "澳大利亚", (("000", None),)),
    (
        "ZZ",
        "其他地方",
        (("112", "多数手机网络可以拨打；当地有自己的紧急号码时，请先拨当地的号码"),),
    ),
)
"""(region code, label, ((number, what it is or None), ...)) in ``hotlines.yaml`` order."""

DIRECTORY_URL: Final = "https://findahelpline.com/"

# 草稿：待 G-0
_LEAD: Final = "如果你现在有危险，或者担心自己的安全，请马上联系当地的紧急服务："
_DIRECTORY: Final = "也可以在 {url} 查找你所在地方的求助热线。"
_DAMAGED: Final = (
    "程序自带的求助电话资料没有通过校验，可能已经损坏，所以这次没有显示其中的热线。"
    "建议重新安装 OLIVIA。"
)


def fallback_text() -> str:
    """The fixed crisis help: emergency numbers first, then the directory, then why."""
    rows = [_LEAD]
    for _code, label, numbers in EMERGENCY:
        shown = "、".join(f"{n}（{what}）" if what else n for n, what in numbers)
        rows.append(f"· {label}：{shown}")
    rows.append(_DIRECTORY.format(url=DIRECTORY_URL))
    rows.append(_DAMAGED)
    return "\n".join(rows)
