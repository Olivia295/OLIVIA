"""The distilled perception student: a pure-NumPy text CNN (roadmap P6-6a, SDD §9).

The packaged weights live in ``olivia/data/models/perception`` next to ``MANIFEST.json``,
which records each file's SHA-256 and byte size. Loading checks, in order: the manifest,
every file's size and hash, ``student_config.json`` (``format_version`` 1, preprocessing
numbers, the head layout and the risk thresholds), ``vocab.json``, and every array of
``student.npz`` (read with ``allow_pickle=False``) against the shape listed in the
config. Any mismatch makes the model *unavailable* with a short machine reason; loading
never raises past :func:`try_load_student`, so a session falls back to the rule screen.

Forward pass (the training notebook's reference): ``html.unescape`` -> NBSP to space ->
collapse whitespace -> strip; one id per code point (UNK for unknown); texts longer than
``max_len`` keep the first ``head_chars`` and the last ``max_len - head_chars`` ids, and
short ones are right-padded with PAD to ``min_len``. Then embedding -> for each kernel a
valid convolution, ReLU and global max pool -> concatenation -> dense + ReLU -> one linear
layer whose slices are the heads. Class heads are ``softmax(z / temperature)``, ``tanh``
heads ``tanh``, and ``sigmoid`` / ``bce`` heads ``sigmoid``.

The risk heads feed the crisis screen (:class:`StudentRiskModel`, an injected
``RiskModel`` for ``SafetyScreen``); the other heads feed model-mode perception
(``model_heads.py``, roadmap C1). The risk model keeps the heads of its last forward
pass so the session runs the student once per turn.

NumPy is imported where the student is loaded or run, not with this module: the session
imports :func:`choose_risk_model` in rules mode too, and NumPy alone is about 18 MB of the
SDD §0 50 MB envelope (G-3).
"""

from __future__ import annotations

import functools
import hashlib
import html
import io
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import RiskModel, RiskPrediction

FORMAT_VERSION: Final = 1
MANIFEST: Final = "MANIFEST.json"
WEIGHTS: Final = "student.npz"
VOCAB: Final = "vocab.json"
CONFIG: Final = "student_config.json"
_FILES: Final = (WEIGHTS, VOCAB, CONFIG)
_PACKAGE_DIR: Final = "data/models/perception"
_HEAD_KINDS: Final = frozenset({"class", "tanh", "sigmoid", "bce"})
_RISK_LABELS: Final = ("L0", "L1", "L2", "L3")
_WHITESPACE: Final = re.compile(r"\s+")
RULES_ONLY: Final = "rules-only"
MODEL_FAILURE_LEVEL: Final = "MODEL_FAILURE"

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    Floats = NDArray[np.float32]
HeadValue = float | dict[str, float]


class StudentUnavailableError(Exception):
    """The packaged student cannot be used; ``reason`` is a short machine string."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Head:
    name: str
    kind: str
    offset: int
    size: int
    labels: tuple[str, ...] | None
    temperature: float | None


@dataclass(frozen=True)
class _Layer:
    kernel: int
    weight: Floats
    """``(E * k, F)``: the conv weight flattened to match the sliding windows."""
    bias: Floats


def preprocess(text: str) -> str:
    """The training preprocessing: unescape, NBSP to space, collapse whitespace, strip."""
    text = html.unescape(text).replace(" ", " ")
    return _WHITESPACE.sub(" ", text).strip()


class StudentModel:
    """The loaded student; build it with :func:`load_student`."""

    def __init__(
        self,
        *,
        fingerprint: str,
        vocab: Mapping[str, int],
        unk: int,
        pad: int,
        max_len: int,
        head_chars: int,
        min_len: int,
        embedding: Floats,
        layers: tuple[_Layer, ...],
        dense_weight: Floats,
        dense_bias: Floats,
        heads_weight: Floats,
        heads_bias: Floats,
        heads: tuple[Head, ...],
        threshold_ge2: float,
        threshold_l3: float,
    ) -> None:
        self.fingerprint = fingerprint
        self._vocab = vocab
        self._unk = unk
        self._pad = pad
        self._max_len = max_len
        self._head_chars = head_chars
        self._min_len = min_len
        self._embedding = embedding
        self._layers = layers
        import numpy as np

        self._dense_t = np.ascontiguousarray(dense_weight.T)
        self._dense_bias = dense_bias
        self._heads_t = np.ascontiguousarray(heads_weight.T)
        self._heads_bias = heads_bias
        self.heads: dict[str, Head] = {head.name: head for head in heads}
        self.threshold_ge2 = threshold_ge2
        self.threshold_l3 = threshold_l3

    def encode(self, text: str) -> list[int]:
        """Token ids after preprocessing, truncation and padding."""
        ids = [self._vocab.get(char, self._unk) for char in preprocess(text)]
        if len(ids) > self._max_len:
            ids = ids[: self._head_chars] + ids[len(ids) - (self._max_len - self._head_chars) :]
        if len(ids) < self._min_len:
            ids += [self._pad] * (self._min_len - len(ids))
        return ids

    def raw_outputs(self, text: str) -> Floats:
        """The heads layer's raw outputs (before any activation)."""
        import numpy as np

        x = self._embedding[np.asarray(self.encode(text), dtype=np.intp)]
        pooled = []
        for layer in self._layers:
            windows = np.lib.stride_tricks.sliding_window_view(x, layer.kernel, axis=0)
            flat = windows.reshape(windows.shape[0], -1)
            pooled.append(np.maximum(flat @ layer.weight + layer.bias, 0.0).max(axis=0))
        hidden = np.maximum(np.concatenate(pooled) @ self._dense_t + self._dense_bias, 0.0)
        out: Floats = hidden @ self._heads_t + self._heads_bias
        return out

    def predict_heads(self, text: str) -> dict[str, HeadValue]:
        """Every head: a float for tanh/sigmoid heads, label probabilities for class heads."""
        import numpy as np

        z = self.raw_outputs(text).astype(np.float64)
        result: dict[str, HeadValue] = {}
        for head in self.heads.values():
            part = z[head.offset : head.offset + head.size]
            if head.kind == "class":
                assert head.labels is not None and head.temperature is not None
                scaled = part / head.temperature
                exp = np.exp(scaled - scaled.max())
                probs = exp / exp.sum()
                result[head.name] = {
                    label: float(p) for label, p in zip(head.labels, probs, strict=True)
                }
            elif head.kind == "tanh":
                result[head.name] = float(np.tanh(part[0]))
            else:
                result[head.name] = float(1.0 / (1.0 + np.exp(-part[0])))
        return result

    def risk(self, text: str) -> tuple[CrisisLevel, float]:
        """The risk level (training rule with the calibrated thresholds) and crisis score."""
        return self.risk_from_heads(self.predict_heads(text))

    def risk_from_heads(self, heads: Mapping[str, HeadValue]) -> tuple[CrisisLevel, float]:
        """:meth:`risk` from heads already computed by :meth:`predict_heads`."""
        probs = heads["risk"]
        score = heads["crisis_confidence"]
        assert isinstance(probs, dict) and isinstance(score, float)
        p = [probs[label] for label in _RISK_LABELS]
        level = max(range(len(p)), key=lambda i: p[i])
        if p[2] + p[3] >= self.threshold_ge2:
            level = max(level, 2)
        if p[3] >= self.threshold_l3:
            level = 3
        return CrisisLevel(level), min(max(score, 0.0), 1.0)


class StudentRiskModel:
    """The student's risk heads as a Stage 2 ``RiskModel`` (no cue ids of its own).

    It keeps every head of its last forward pass (no text) until :meth:`take_heads`, so
    model-mode perception reuses the screen's pass instead of running the student again.
    """

    def __init__(self, student: StudentModel) -> None:
        self.student = student
        self.name = f"student:{student.fingerprint}"
        self._last_heads: dict[str, HeadValue] | None = None

    def predict(self, text: str) -> RiskPrediction:
        self._last_heads = None
        heads = self.student.predict_heads(text)
        self._last_heads = heads
        level, score = self.student.risk_from_heads(heads)
        return RiskPrediction(level, score, ())

    def take_heads(self) -> dict[str, HeadValue] | None:
        """The heads of the last :meth:`predict` not yet taken, then forget them."""
        heads, self._last_heads = self._last_heads, None
        return heads


# -- loading ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class StudentLoad:
    """A loaded student, or ``None`` and the reason it is unavailable."""

    model: StudentModel | None
    reason: str | None


def try_load_student(directory: Path | None = None) -> StudentLoad:
    """:func:`load_student` that reports failure as a reason instead of raising."""
    try:
        return StudentLoad(load_student(directory), None)
    except StudentUnavailableError as exc:
        return StudentLoad(None, exc.reason)


@functools.cache
def default_student() -> StudentLoad:
    """The packaged student, loaded and verified once per process."""
    return try_load_student()


def load_student(directory: Path | None = None) -> StudentModel:
    """Load and verify the student; ``None`` reads the packaged copy.

    Raises :class:`StudentUnavailableError` (and nothing else) on any problem.
    """
    base: Traversable | Path = (
        resources.files("olivia").joinpath(_PACKAGE_DIR) if directory is None else directory
    )
    try:
        return _load(base)
    except StudentUnavailableError:
        raise
    except Exception as exc:  # any surprise in the files means "unavailable", never a crash
        raise StudentUnavailableError(f"load_error:{type(exc).__name__}") from exc


def _load(base: Traversable | Path) -> StudentModel:
    import numpy as np

    blobs = _verified_files(base)
    config = _json(blobs[CONFIG], "config_invalid")
    if config.get("format_version") != FORMAT_VERSION:
        raise StudentUnavailableError("format_version")
    arrays = _arrays(blobs[WEIGHTS], config)
    vocab, unk, pad = _vocab(_json(blobs[VOCAB], "vocab_invalid"), arrays["embedding"].shape[0])
    kernels = _int_list(config.get("kernels"), "config_invalid")
    max_len = _int(config.get("max_len"), "config_invalid")
    head_chars = _int(config.get("head_chars"), "config_invalid")
    min_len = _int(config.get("min_len"), "config_invalid")
    if not (0 <= head_chars <= max_len and max(kernels) <= min_len <= max_len):
        raise StudentUnavailableError("config_invalid")
    fingerprint = config.get("student_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise StudentUnavailableError("config_invalid")

    embedding = arrays["embedding"]
    embed_dim = embedding.shape[1]
    layers = []
    for k in kernels:
        weight = arrays.get(f"conv{k}_weight")
        bias = arrays.get(f"conv{k}_bias")
        if weight is None or bias is None or weight.shape[1:] != (embed_dim, k):
            raise StudentUnavailableError("architecture")
        flat = np.ascontiguousarray(weight.reshape(weight.shape[0], -1).T)
        layers.append(_Layer(k, flat, bias))
    dense_weight, heads_weight = arrays["dense_weight"], arrays["heads_weight"]
    if dense_weight.shape[1] != sum(layer.bias.shape[0] for layer in layers) or (
        heads_weight.shape[1] != dense_weight.shape[0]
    ):
        raise StudentUnavailableError("architecture")

    heads = _heads(config, heads_weight.shape[0])
    ge2, l3 = _thresholds(config)
    return StudentModel(
        fingerprint=fingerprint,
        vocab=vocab,
        unk=unk,
        pad=pad,
        max_len=max_len,
        head_chars=head_chars,
        min_len=min_len,
        embedding=embedding,
        layers=tuple(layers),
        dense_weight=dense_weight,
        dense_bias=arrays["dense_bias"],
        heads_weight=heads_weight,
        heads_bias=arrays["heads_bias"],
        heads=heads,
        threshold_ge2=ge2,
        threshold_l3=l3,
    )


def _read(base: Traversable | Path, name: str) -> bytes:
    try:
        return base.joinpath(name).read_bytes()
    except OSError as exc:
        raise StudentUnavailableError(f"missing_file:{name}") from exc


def _verified_files(base: Traversable | Path) -> dict[str, bytes]:
    manifest = _json(_read(base, MANIFEST), "manifest_invalid")
    entries = manifest.get("files")
    if manifest.get("format_version") != FORMAT_VERSION or not isinstance(entries, dict):
        raise StudentUnavailableError("manifest_invalid")
    blobs: dict[str, bytes] = {}
    for name in _FILES:
        entry = entries.get(name)
        if not isinstance(entry, dict):
            raise StudentUnavailableError("manifest_invalid")
        data = _read(base, name)
        if len(data) != entry.get("bytes"):
            raise StudentUnavailableError(f"size_mismatch:{name}")
        if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            raise StudentUnavailableError(f"hash_mismatch:{name}")
        blobs[name] = data
    return blobs


def _json(data: bytes, reason: str) -> dict[str, Any]:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise StudentUnavailableError(reason) from exc
    if not isinstance(doc, dict):
        raise StudentUnavailableError(reason)
    return doc


def _int(value: object, reason: str) -> int:
    if type(value) is not int:
        raise StudentUnavailableError(reason)
    return value


def _int_list(value: object, reason: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise StudentUnavailableError(reason)
    items = [_int(item, reason) for item in value]
    if any(item < 1 for item in items) or len(set(items)) != len(items):
        raise StudentUnavailableError(reason)
    return items


def _arrays(data: bytes, config: Mapping[str, Any]) -> dict[str, Floats]:
    import numpy as np

    dtypes = frozenset({np.dtype(np.float16), np.dtype(np.float32)})
    expected = config.get("arrays")
    if not isinstance(expected, dict) or not expected:
        raise StudentUnavailableError("config_invalid")
    try:
        with np.load(io.BytesIO(data), allow_pickle=False) as npz:
            names = list(npz.files)
            raw = {name: npz[name] for name in names}
    except Exception as exc:  # pickled objects, a broken zip or a bad header
        raise StudentUnavailableError("npz_unreadable") from exc
    if set(raw) != set(expected):
        raise StudentUnavailableError("array_names")
    arrays: dict[str, Floats] = {}
    for name, array in raw.items():
        if list(array.shape) != expected[name]:
            raise StudentUnavailableError(f"array_shape:{name}")
        if array.dtype not in dtypes:
            raise StudentUnavailableError(f"array_dtype:{name}")
        values = array.astype(np.float32)
        if not np.isfinite(values).all():
            raise StudentUnavailableError(f"array_nonfinite:{name}")
        arrays[name] = values
    for name in ("embedding", "dense_weight", "dense_bias", "heads_weight", "heads_bias"):
        if name not in arrays:
            raise StudentUnavailableError("array_names")
    if arrays["embedding"].ndim != 2 or arrays["heads_weight"].ndim != 2:
        raise StudentUnavailableError("architecture")
    return arrays


def _vocab(doc: Mapping[str, Any], rows: int) -> tuple[dict[str, int], int, int]:
    chars = doc.get("chars")
    pad, unk = doc.get("pad"), doc.get("unk")
    if (
        not isinstance(chars, list)
        or len(chars) != rows
        or not all(isinstance(c, str) for c in chars)
        or len(set(chars)) != len(chars)
        or type(pad) is not int
        or type(unk) is not int
        or not (0 <= pad < rows and 0 <= unk < rows and pad != unk)
    ):
        raise StudentUnavailableError("vocab_invalid")
    vocab = {char: i for i, char in enumerate(chars) if i not in (pad, unk)}
    return vocab, unk, pad


def _heads(config: Mapping[str, Any], width: int) -> tuple[Head, ...]:
    raw = config.get("heads")
    temperatures = config.get("temperatures")
    if not isinstance(raw, list) or not raw or not isinstance(temperatures, dict):
        raise StudentUnavailableError("head_layout")
    heads: list[Head] = []
    offset = 0
    for item in sorted(raw, key=lambda h: h.get("offset", -1) if isinstance(h, dict) else -1):
        if not isinstance(item, dict):
            raise StudentUnavailableError("head_layout")
        name, kind = item.get("name"), item.get("kind")
        size, labels = item.get("size"), item.get("labels")
        if (
            not isinstance(name, str)
            or kind not in _HEAD_KINDS
            or item.get("offset") != offset
            or type(size) is not int
            or size < 1
        ):
            raise StudentUnavailableError("head_layout")
        temperature: float | None = None
        label_tuple: tuple[str, ...] | None = None
        if kind == "class":
            t = temperatures.get(name)
            if (
                not isinstance(labels, list)
                or len(labels) != size
                or not all(isinstance(label, str) for label in labels)
                or not isinstance(t, int | float)
                or isinstance(t, bool)
                or not (math.isfinite(t) and t > 0)
            ):
                raise StudentUnavailableError("head_layout")
            temperature, label_tuple = float(t), tuple(labels)
        elif size != 1:
            raise StudentUnavailableError("head_layout")
        heads.append(Head(name, str(kind), offset, size, label_tuple, temperature))
        offset += size
    by_name = {head.name: head for head in heads}
    if offset != width or len(by_name) != len(heads):
        raise StudentUnavailableError("head_layout")
    risk, crisis = by_name.get("risk"), by_name.get("crisis_confidence")
    if risk is None or risk.labels != _RISK_LABELS:
        raise StudentUnavailableError("head_layout")
    if crisis is None or crisis.kind not in ("sigmoid", "bce"):
        raise StudentUnavailableError("head_layout")
    return tuple(heads)


def _thresholds(config: Mapping[str, Any]) -> tuple[float, float]:
    risk = config.get("risk")
    if not isinstance(risk, dict):
        raise StudentUnavailableError("risk_thresholds")
    values = []
    for key in ("threshold_ge2", "threshold_l3"):
        value = risk.get(key)
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not (0.0 <= value <= 1.0)
        ):
            raise StudentUnavailableError("risk_thresholds")
        values.append(float(value))
    return values[0], values[1]


# -- the session's choice of risk model ------------------------------------------------------


class _Observed:
    """Wraps the session's injected model and keeps its latest answer for ``inspect``."""

    def __init__(self, inner: RiskModel) -> None:
        self._inner = inner
        self.last: RiskPrediction | str | None = None

    def predict(self, text: str) -> RiskPrediction:
        self.last = MODEL_FAILURE_LEVEL
        prediction = self._inner.predict(text)
        self.last = prediction
        return prediction


@dataclass(frozen=True)
class RiskChoice:
    """Which Stage 2 model a session screens with, for ``SafetyScreen`` and ``inspect``."""

    label: str
    """``student:<fingerprint>``, ``rules-only`` or ``custom:<class name>``."""
    reason: str | None
    """Why the student is not in use when it was wanted (``None`` otherwise)."""
    model: RiskModel | None
    """What to inject into ``SafetyScreen`` (``None``: the rule model alone)."""
    student: StudentRiskModel | None = None
    """The packaged student behind ``model`` when it is in use, for model-mode perception."""

    def take_turn(self) -> tuple[str | None, float | None]:
        """The model's (level name, score) on the last screen, then forget it.

        ``(None, None)`` when no model ran (rules only, or Stage 1 answered first);
        ``("MODEL_FAILURE", None)`` when the model raised or answered out of contract.
        """
        if not isinstance(self.model, _Observed):
            return None, None
        last, self.model.last = self.model.last, None
        if last is None:
            return None, None
        if (
            not isinstance(last, RiskPrediction)
            or not isinstance(last.level, CrisisLevel)
            or not isinstance(last.score, int | float)
            or not (math.isfinite(last.score) and 0.0 <= last.score <= 1.0)
        ):
            return MODEL_FAILURE_LEVEL, None
        return last.level.name, float(last.score)


def choose_risk_model(model: RiskModel | None = None, *, student: bool = False) -> RiskChoice:
    """The session's Stage 2 model: an injected one, the packaged student, or rules only.

    Rules only is the default until a student passes the release gate (P6-6a). The packaged
    round-4 student still sends 11 of 109 non-crisis red-team cases into S_crisis (round 1:
    39) and reaches the crisis level of 16 of the 28 cases the rules miss. ``student=True``
    asks for the packaged student; one that fails to load falls back to rules only, with
    its reason.
    """
    if model is not None and student:
        raise ValueError("an injected risk model and student are mutually exclusive")
    if model is not None:
        return RiskChoice(f"custom:{type(model).__name__}", None, _Observed(model))
    if not student:
        return RiskChoice(RULES_ONLY, None, None)
    loaded = default_student()
    if loaded.model is None:
        return RiskChoice(RULES_ONLY, loaded.reason, None)
    risk_model = StudentRiskModel(loaded.model)
    return RiskChoice(risk_model.name, None, _Observed(risk_model), risk_model)
