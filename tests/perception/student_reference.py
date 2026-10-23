"""The training notebook's NumPy reference forward, for parity tests of the product student.

Copied from ``training/colab/build_student_arch.py`` §9 (branch ``train/student-arch``):
``np_relu``, ``np_conv1d``, ``conv_weight_t``, ``NpCNN``, ``NpEnsemble`` and
``NumpyArchStudent``, with the math unchanged. Only the ``cnn`` and ``ensemble``
architectures are kept (the product loads no other), and a format-version-1 config (no
``architecture`` field, top-level ``kernels``) runs as one ``NpCNN``, as the first
notebook's reference did. Deliberately independent of ``olivia.core.perception.student``.
"""

from __future__ import annotations

import html
import json
import os
import re
from typing import Any

import numpy as np

ENSEMBLE_EPS = 1e-6


def np_relu(x: Any) -> Any:
    return np.maximum(x, 0.0)


def np_conv1d(x: Any, weight_t: Any, bias: Any, k: int, padding: int = 0) -> Any:
    # x (length, in channels); weight_t (in channels * k, out channels), i.e. the PyTorch
    # weight (out, in, k) reshaped and transposed
    if padding:
        x = np.pad(x, ((padding, padding), (0, 0)))
    windows = np.lib.stride_tricks.sliding_window_view(x, k, axis=0)  # (len - k + 1, in, k)
    return windows.reshape(windows.shape[0], -1) @ weight_t + bias


def conv_weight_t(weight: Any) -> Any:
    return np.ascontiguousarray(weight.reshape(weight.shape[0], -1).T)


class NpCNN:
    def __init__(self, w: dict[str, Any], arch: dict[str, Any], prefix: str = "") -> None:
        self.embedding = w[f"{prefix}embedding"]
        self.convs = [
            (k, conv_weight_t(w[f"{prefix}conv{k}_weight"]), w[f"{prefix}conv{k}_bias"])
            for k in arch["kernels"]
        ]
        self.dense_t = np.ascontiguousarray(w[f"{prefix}dense_weight"].T)
        self.dense_b = w[f"{prefix}dense_bias"]
        self.heads_t = np.ascontiguousarray(w[f"{prefix}heads_weight"].T)
        self.heads_b = w[f"{prefix}heads_bias"]

    def raw(self, ids: Any) -> Any:
        x = self.embedding[ids]
        pooled = [np_relu(np_conv1d(x, wt, b, k)).max(axis=0) for k, wt, b in self.convs]
        h = np_relu(np.concatenate(pooled) @ self.dense_t + self.dense_b)
        return h @ self.heads_t + self.heads_b


class NpEnsemble:
    def __init__(self, w: dict[str, Any], arch: dict[str, Any], heads: list[Any]) -> None:
        self.members = [NpCNN(w, arch["member"], f"m{i}_") for i in range(arch["members"])]
        self.heads = heads
        self.eps = ENSEMBLE_EPS

    def raw(self, ids: Any) -> Any:
        z = np.stack([m.raw(ids) for m in self.members]).astype(np.float64)  # (members, OUT)
        out = np.empty(z.shape[1])
        for head in self.heads:
            s = slice(head["offset"], head["offset"] + head["size"])
            v = z[:, s]
            if head["kind"] == "class":
                log_p = v - v.max(axis=1, keepdims=True)
                log_p = log_p - np.log(np.exp(log_p).sum(axis=1, keepdims=True))  # log softmax
                top = log_p.max(axis=0)
                out[s] = top + np.log(np.exp(log_p - top).mean(axis=0))  # log(mean prob)
            elif head["kind"] == "tanh":
                out[s] = np.arctanh(np.clip(np.tanh(v).mean(axis=0), -1 + self.eps, 1 - self.eps))
            else:
                p = np.clip((0.5 * (1 + np.tanh(0.5 * v))).mean(axis=0), self.eps, 1 - self.eps)
                out[s] = np.log(p) - np.log1p(-p)
        return out


class NumpyArchStudent:
    def __init__(self, directory: str | os.PathLike[str]) -> None:
        with open(os.path.join(directory, "student_config.json"), encoding="utf-8") as f:
            self.cfg = json.load(f)
        with open(os.path.join(directory, "vocab.json"), encoding="utf-8") as f:
            vocab = json.load(f)
        self.index = {ch: i for i, ch in enumerate(vocab["chars"])}
        self.unk, self.pad = vocab["unk"], vocab["pad"]
        with np.load(os.path.join(directory, "student.npz"), allow_pickle=False) as w:
            weights = {k: w[k].astype(np.float32) for k in w.files}
        for name, shape in self.cfg["arrays"].items():
            assert list(weights[name].shape) == shape, f"{name} {weights[name].shape} != {shape}"
        arch = self.cfg.get("architecture", {"type": "cnn", "kernels": self.cfg.get("kernels")})
        self.net: NpCNN | NpEnsemble
        if arch["type"] == "cnn":
            self.net = NpCNN(weights, arch)
        elif arch["type"] == "ensemble":
            self.net = NpEnsemble(weights, arch, self.cfg["heads"])
        else:
            raise ValueError(f"unknown architecture {arch['type']}")

    @staticmethod
    def preprocess(text: str) -> str:
        text = html.unescape(str(text)).replace(" ", " ")
        return re.sub(r"\s+", " ", text).strip()

    def encode(self, text: str) -> Any:
        cfg = self.cfg
        ids = [self.index.get(ch, self.unk) for ch in self.preprocess(text)]
        if len(ids) > cfg["max_len"]:
            ids = ids[: cfg["head_chars"]] + ids[len(ids) - (cfg["max_len"] - cfg["head_chars"]) :]
        return np.array(ids + [self.pad] * (cfg["min_len"] - len(ids)), dtype=np.int64)

    def raw(self, text: str) -> Any:
        return self.net.raw(self.encode(text))

    def predict(self, text: str) -> dict[str, Any]:
        z = self.raw(text).astype(np.float64)
        out: dict[str, Any] = {}
        for head in self.cfg["heads"]:
            v = z[head["offset"] : head["offset"] + head["size"]]
            if head["kind"] == "class":
                v = v / self.cfg["temperatures"][head["name"]]
                e = np.exp(v - v.max())
                out[head["name"]] = e / e.sum()
            else:
                out[head["name"]] = float(
                    np.tanh(v[0]) if head["kind"] == "tanh" else 1 / (1 + np.exp(-v[0]))
                )
        return out

    def level(self, risk_probs: Any) -> int:
        """The config's risk rule (``risk.rule``) on the risk head's probabilities."""
        r = self.cfg["risk"]
        p = list(risk_probs)
        lv = int(np.argmax(p))
        if p[2] + p[3] >= r["threshold_ge2"]:
            lv = max(lv, 2)
        if p[3] >= r["threshold_l3"]:
            lv = 3
        return lv
