"""The distilled perception student: pure-NumPy text CNNs (roadmap P6-6a, SDD §9).

The packaged weights live in ``olivia/data/models/perception`` next to ``MANIFEST.json``,
which records each file's SHA-256 and byte size. Loading checks, in order: the manifest,
every file's size and hash, ``student_config.json`` (its ``format_version``, preprocessing
numbers, the architecture, the head layout and the risk thresholds), ``vocab.json``, and
every array of ``student.npz`` (read with ``allow_pickle=False``) against the shape listed
in the config. Any mismatch, or any format or architecture this module does not know,
makes the model *unavailable* with a short machine reason; loading never raises past
:func:`try_load_student`, so a session falls back to the rule screen.

Two config formats load:

* ``format_version`` 1: one CNN. Top-level ``kernels`` and ``student_fingerprint``; the
  arrays are ``embedding``, ``conv{k}_weight`` / ``conv{k}_bias`` per kernel,
  ``dense_*`` and ``heads_*``.
* ``format_version`` 2 with ``architecture.type == "ensemble"``: ``architecture.members``
  CNNs of the same shape (``architecture.member``: ``type`` ``"cnn"``, ``kernels``), their
  arrays named as in version 1 behind the prefix ``m{i}_`` (``architecture.array_prefix``),
  each with its own embedding; ``variant_fingerprint`` names the model. Every member's
  arrays are checked, and the npz holds exactly the members' arrays. Other version-2
  architectures (the experiment notebook's ``cnn``, ``bigru``, ``transformer``) are not
  supported here and leave the model unavailable.

Forward pass (the training notebooks' NumPy reference): ``html.unescape`` -> NBSP to
space -> collapse whitespace -> strip; one id per code point (UNK for unknown); texts
longer than ``max_len`` keep the first ``head_chars`` and the last ``max_len - head_chars``
ids, and short ones are right-padded with PAD to ``min_len``. A CNN runs embedding -> for
each kernel a valid convolution, ReLU and global max pool -> concatenation -> dense + ReLU
-> one linear layer whose slices are the heads. An ensemble runs every member on the same
ids and merges their raw outputs head by head (``architecture.combine``, in float64):
class heads ``log(mean softmax)``, ``tanh`` heads ``atanh(mean tanh)`` and ``sigmoid`` /
``bce`` heads ``logit(mean sigmoid)``, the means clipped 1e-6 inside the open range.
Then, for either format, class heads are ``softmax(z / temperature)``, ``tanh`` heads
``tanh``, and ``sigmoid`` / ``bce`` heads ``sigmoid``; the temperatures and the risk
thresholds were fitted on the merged output.

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

MANIFEST_VERSION: Final = 1
CNN_VERSION: Final = 1
ENSEMBLE_VERSION: Final = 2
MANIFEST: Final = "MANIFEST.json"
WEIGHTS: Final = "student.npz"
VOCAB: Final = "vocab.json"
CONFIG: Final = "student_config.json"
_FILES: Final = (WEIGHTS, VOCAB, CONFIG)
_PACKAGE_DIR: Final = "data/models/perception"
_HEAD_KINDS: Final = frozenset({"class", "tanh", "sigmoid", "bce"})
_RISK_LABELS: Final = ("L0", "L1", "L2", "L3")
_ENSEMBLE_PREFIX: Final = "m{i}_"
_ENSEMBLE_EPS: Final = 1e-6
_COMBINE_KINDS: Final = frozenset({"class", "tanh", "sigmoid"})
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


class _CNN:
    """One text CNN: embedding -> valid conv + ReLU + max pool per kernel -> dense -> heads."""

    def __init__(
        self,
        *,
        embedding: Floats,
        layers: tuple[_Layer, ...],
        dense_weight: Floats,
        dense_bias: Floats,
        heads_weight: Floats,
        heads_bias: Floats,
    ) -> None:
        import numpy as np

        self.embedding = embedding
        self.layers = layers
        self.dense_t = np.ascontiguousarray(dense_weight.T)
        self.dense_bias = dense_bias
        self.heads_t = np.ascontiguousarray(heads_weight.T)
        self.heads_bias = heads_bias

    def raw(self, ids: NDArray[np.intp]) -> Floats:
        import numpy as np

        x = self.embedding[ids]
        pooled = []
        for layer in self.layers:
            windows = np.lib.stride_tricks.sliding_window_view(x, layer.kernel, axis=0)
            flat = windows.reshape(windows.shape[0], -1)
            pooled.append(np.maximum(flat @ layer.weight + layer.bias, 0.0).max(axis=0))
        hidden = np.maximum(np.concatenate(pooled) @ self.dense_t + self.dense_bias, 0.0)
        out: Floats = hidden @ self.heads_t + self.heads_bias
        return out


def preprocess(text: str) -> str:
    """The training preprocessing: unescape, NBSP to space, collapse whitespace, strip."""
    text = html.unescape(text).replace(" ", " ")
    return _WHITESPACE.sub(" ", text).strip()


class StudentModel:
    """The loaded student (one CNN or an ensemble of CNNs); build it with :func:`load_student`."""

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
        members: tuple[_CNN, ...],
        ensemble: bool,
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
        self._members = members
        self._ensemble = ensemble
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

    def raw_outputs(self, text: str) -> NDArray[np.floating[Any]]:
        """The heads layer's raw outputs (before any activation); merged for an ensemble."""
        import numpy as np

        ids = np.asarray(self.encode(text), dtype=np.intp)
        if not self._ensemble:
            return self._members[0].raw(ids)
        return self._combine(np.stack([member.raw(ids) for member in self._members]))

    def _combine(self, raw: Floats) -> NDArray[np.float64]:
        """Merge the members' raw outputs ``(members, width)`` head by head (float64)."""
        import numpy as np

        z = raw.astype(np.float64)
        out = np.empty(z.shape[1])
        for head in self.heads.values():
            s = slice(head.offset, head.offset + head.size)
            v = z[:, s]
            if head.kind == "class":  # log of the mean probability, via each member's log softmax
                log_p = v - v.max(axis=1, keepdims=True)
                log_p = log_p - np.log(np.exp(log_p).sum(axis=1, keepdims=True))
                top = log_p.max(axis=0)
                out[s] = top + np.log(np.exp(log_p - top).mean(axis=0))
            elif head.kind == "tanh":
                mean = np.tanh(v).mean(axis=0)
                out[s] = np.arctanh(np.clip(mean, -1 + _ENSEMBLE_EPS, 1 - _ENSEMBLE_EPS))
            else:  # sigmoid and bce
                mean = (0.5 * (1 + np.tanh(0.5 * v))).mean(axis=0)
                p = np.clip(mean, _ENSEMBLE_EPS, 1 - _ENSEMBLE_EPS)
                out[s] = np.log(p) - np.log1p(-p)
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
    blobs = _verified_files(base)
    config = _json(blobs[CONFIG], "config_invalid")
    version = config.get("format_version")
    if type(version) is not int or version not in (CNN_VERSION, ENSEMBLE_VERSION):
        raise StudentUnavailableError("format_version")
    arrays = _arrays(blobs[WEIGHTS], config)
    if version == CNN_VERSION:
        prefixes = [""]
        kernels = _int_list(config.get("kernels"), "config_invalid")
        fingerprint = config.get("student_fingerprint")
    else:
        prefixes, kernels = _ensemble_layout(config)
        fingerprint = config.get("variant_fingerprint")
        expected = {f"{prefix}{name}" for prefix in prefixes for name in _cnn_array_names(kernels)}
        if set(arrays) != expected:
            raise StudentUnavailableError("array_names")
    for prefix in prefixes:
        _require_core_arrays(arrays, prefix)
    rows = {arrays[f"{prefix}embedding"].shape[0] for prefix in prefixes}
    if len(rows) != 1:
        raise StudentUnavailableError("architecture")
    vocab, unk, pad = _vocab(_json(blobs[VOCAB], "vocab_invalid"), rows.pop())
    max_len = _int(config.get("max_len"), "config_invalid")
    head_chars = _int(config.get("head_chars"), "config_invalid")
    min_len = _int(config.get("min_len"), "config_invalid")
    if not (0 <= head_chars <= max_len and max(kernels) <= min_len <= max_len):
        raise StudentUnavailableError("config_invalid")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise StudentUnavailableError("config_invalid")

    members = tuple(_cnn(arrays, prefix, kernels) for prefix in prefixes)
    widths = {member.heads_bias.shape[0] for member in members}
    if len(widths) != 1:
        raise StudentUnavailableError("architecture")
    heads = _heads(config, widths.pop())
    ge2, l3 = _thresholds(config)
    return StudentModel(
        fingerprint=fingerprint,
        vocab=vocab,
        unk=unk,
        pad=pad,
        max_len=max_len,
        head_chars=head_chars,
        min_len=min_len,
        members=members,
        ensemble=version == ENSEMBLE_VERSION,
        heads=heads,
        threshold_ge2=ge2,
        threshold_l3=l3,
    )


def _ensemble_layout(config: Mapping[str, Any]) -> tuple[list[str], list[int]]:
    """The members' array prefixes and their shared kernels (format version 2)."""
    arch = config.get("architecture")
    if not isinstance(arch, dict) or arch.get("type") != "ensemble":
        raise StudentUnavailableError("architecture")
    count = _int(arch.get("members"), "architecture")
    member, combine = arch.get("member"), arch.get("combine")
    if (
        count < 1
        or arch.get("array_prefix") != _ENSEMBLE_PREFIX
        or not isinstance(member, dict)
        or member.get("type") != "cnn"
        or not isinstance(combine, dict)
        or set(combine) != _COMBINE_KINDS
    ):
        raise StudentUnavailableError("architecture")
    kernels = _int_list(member.get("kernels"), "architecture")
    return [_ENSEMBLE_PREFIX.format(i=i) for i in range(count)], kernels


def _cnn_array_names(kernels: list[int]) -> list[str]:
    names = ["embedding", "dense_weight", "dense_bias", "heads_weight", "heads_bias"]
    return names + [f"conv{k}_{part}" for k in kernels for part in ("weight", "bias")]


def _require_core_arrays(arrays: Mapping[str, Floats], prefix: str) -> None:
    for name in ("embedding", "dense_weight", "dense_bias", "heads_weight", "heads_bias"):
        if f"{prefix}{name}" not in arrays:
            raise StudentUnavailableError("array_names")
    if arrays[f"{prefix}embedding"].ndim != 2 or arrays[f"{prefix}heads_weight"].ndim != 2:
        raise StudentUnavailableError("architecture")


def _cnn(arrays: Mapping[str, Floats], prefix: str, kernels: list[int]) -> _CNN:
    """One CNN from the arrays behind ``prefix``, its shapes checked against each other."""
    import numpy as np

    embedding = arrays[f"{prefix}embedding"]
    embed_dim = embedding.shape[1]
    layers = []
    for k in kernels:
        weight = arrays.get(f"{prefix}conv{k}_weight")
        bias = arrays.get(f"{prefix}conv{k}_bias")
        if (
            weight is None
            or bias is None
            or weight.shape[1:] != (embed_dim, k)
            or bias.shape != weight.shape[:1]
        ):
            raise StudentUnavailableError("architecture")
        flat = np.ascontiguousarray(weight.reshape(weight.shape[0], -1).T)
        layers.append(_Layer(k, flat, bias))
    dense_weight, dense_bias = arrays[f"{prefix}dense_weight"], arrays[f"{prefix}dense_bias"]
    heads_weight, heads_bias = arrays[f"{prefix}heads_weight"], arrays[f"{prefix}heads_bias"]
    if (
        dense_weight.ndim != 2
        or dense_weight.shape[1] != sum(layer.bias.shape[0] for layer in layers)
        or dense_bias.shape != dense_weight.shape[:1]
        or heads_weight.shape[1] != dense_weight.shape[0]
        or heads_bias.shape != heads_weight.shape[:1]
    ):
        raise StudentUnavailableError("architecture")
    return _CNN(
        embedding=embedding,
        layers=tuple(layers),
        dense_weight=dense_weight,
        dense_bias=dense_bias,
        heads_weight=heads_weight,
        heads_bias=heads_bias,
    )


def _read(base: Traversable | Path, name: str) -> bytes:
    try:
        return base.joinpath(name).read_bytes()
    except OSError as exc:
        raise StudentUnavailableError(f"missing_file:{name}") from exc


def _verified_files(base: Traversable | Path) -> dict[str, bytes]:
    manifest = _json(_read(base, MANIFEST), "manifest_invalid")
    entries = manifest.get("files")
    if manifest.get("format_version") != MANIFEST_VERSION or not isinstance(entries, dict):
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

    Rules only is the default (owner decision 2026-10-24) until a student passes the release
    gate (P6-6a). On the 267-case red team the packaged student (the three-CNN ensemble)
    sends 11 of the 169 cases with ``crisis_below`` into S_crisis that the rules keep out
    (round 4: 27) and reaches the crisis level of 11 of the 22 cases the rules miss (round
    4: 13). ``student=True`` asks for the packaged student; one that fails to load falls
    back to rules only, with its reason.
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
