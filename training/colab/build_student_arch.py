#!/usr/bin/env python3
"""Write training/colab/student_arch_experiment.ipynb, the student-architecture comparison (step C5).

The notebook reuses the teacher artifacts that ``perception_teacher.ipynb`` left on Drive
(teacher calibration, the cached distillation targets and the fold teachers' outputs on
the student training texts), rebuilds the identical student train / holdout split, then
trains and compares four student architectures with the same distillation targets and
hard-negative weighting: the current wide char-CNN, a CNN + BiGRU, a small pre-LN
character transformer, and an ensemble of three CNNs. Each gets a pure NumPy reference
forward (the code a later product port copies), a parity and latency check, holdout
calibration at two recall targets, and a score on the development set (``role=dev``)
through today's rules + student arbitration. A selection rule written before any result
picks the winner, and only the winner is exported to Drive. The final test set
(``role=fresh``) is never scored here.

The data, split, fingerprint, loss and metric code is not copied by hand: it is taken
verbatim from ``build_perception_teacher.py`` (whole cells, or top-level statements picked
with ``ast``), so the two notebooks cannot drift apart silently.

Edit the cells here, never the .ipynb by hand, then regenerate:

    python training/colab/build_student_arch.py

Local smoke test (CPU): run perception_teacher.ipynb's code cells with OLIVIA_SMOKE_TEST=1
and OLIVIA_PERCEPTION_ROOT=<dir holding raw/...> first (it writes the tiny teacher
artifacts), then this notebook's code cells with the same two variables.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "student_arch_experiment.ipynb"

_spec = importlib.util.spec_from_file_location("build_perception_teacher", HERE / "build_perception_teacher.py")
assert _spec is not None and _spec.loader is not None
_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_main)
MAIN_CODE = [text for kind, text in _main.CELLS if kind == "code"]

CELLS: list[tuple[str, str]] = []


def md(text: str) -> None:
    CELLS.append(("markdown", text.strip("\n")))


def code(text: str) -> None:
    CELLS.append(("code", text.strip("\n")))


def main_cell(marker: str) -> str:
    """The one code cell of the main notebook that contains ``marker``, verbatim."""
    found = [cell for cell in MAIN_CODE if marker in cell]
    assert len(found) == 1, f"{marker!r} matches {len(found)} cells of build_perception_teacher.py"
    return found[0]


def _defines(stmt: ast.stmt, name: str) -> bool:
    if isinstance(stmt, (ast.FunctionDef, ast.ClassDef)):
        return stmt.name == name
    if isinstance(stmt, ast.Assign):
        return any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets)
    if isinstance(stmt, ast.AnnAssign):
        return isinstance(stmt.target, ast.Name) and stmt.target.id == name
    return False


def main_span(marker: str, first: str, last: str) -> str:
    """Top-level statements of a main-notebook cell, from the one defining ``first`` to the
    one defining ``last`` (inclusive), verbatim with the comments between them."""
    cell = main_cell(marker)
    body = ast.parse(cell).body
    starts = [i for i, stmt in enumerate(body) if _defines(stmt, first)]
    ends = [i for i, stmt in enumerate(body) if _defines(stmt, last)]
    assert len(starts) == 1 and len(ends) == 1 and starts[0] <= ends[0], (marker, first, last)
    head = body[starts[0]]
    start_line = min([head.lineno] + [d.lineno for d in getattr(head, "decorator_list", [])])
    lines = cell.split("\n")
    return "\n".join(lines[start_line - 1:body[ends[0]].end_lineno])


def main_export_string(key: str) -> str:
    """A string value of the main notebook's EXPORT_CONFIG literal (preprocess / truncation text)."""
    for stmt in ast.parse(main_cell("EXPORT_CONFIG = {")).body:
        if _defines(stmt, "EXPORT_CONFIG"):
            assert isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Dict)
            for k, v in zip(stmt.value.keys, stmt.value.values):
                if isinstance(k, ast.Constant) and k.value == key:
                    return ast.literal_eval(v)
    raise AssertionError(f"EXPORT_CONFIG has no {key!r}")


SHARED_TEACHER_FINGERPRINTS = main_span('TRAIN_CONFIG = {', "TRAIN_CONFIG", "FOLD_KD_FINGERPRINT")
SHARED_VOCAB = main_span("char_counts = Counter(", "char_counts", "CHAR_INDEX")
SHARED_TARGETS_FINGERPRINT = main_span("char_counts = Counter(", "TARGETS_FINGERPRINT", "TARGETS_FINGERPRINT")
SHARED_SOFT_TARGETS = main_span("char_counts = Counter(", "soft_targets", "soft_targets")
SHARED_KD_TARGETS = main_span("char_counts = Counter(", "kd_teachers", "kd_targets")
SHARED_STUDENT_CNN = main_span("class CharCNN(", "MIN_CHARS", "distill_loss")
SHARED_ARBITRATION = main_span("def combined_levels(", "combined_levels", "summarize")
PREPROCESS_TEXT = json.dumps(main_export_string("preprocess"), ensure_ascii=False)
TRUNCATION_TEXT = json.dumps(main_export_string("truncation"), ensure_ascii=False)


# --------------------------------------------------------------------------------------
md(r"""
# 学生结构对比实验（步骤 C5）

> **说明**：本 notebook 只比较学生模型的结构，不改教师、不改数据，也不碰产品正在用的 `models/perception_student/`。模型输出只是感知信号，不构成任何诊断。

## 为什么做

在一份 300 句的独立评估集上，规则 + 学生（现行仲裁）的 L2+L3 召回只有约 80%（111–115/140），而教师在类似的集合上约 97%。漏判集中在正在进行的行为、已备好手段、时间地点计划、被动意念、换了说法的方法提问。所以差距在**学生的泛化**，不在标注。本实验在完全相同的蒸馏目标、难负例加权和训练 / 留出划分下，比较四种学生结构：

| 变体 | 结构 |
| :--- | :--- |
| `cnn_wide` | 基线 = 主 notebook 现在的学生：字嵌入 64 → 卷积核 2/3/4/5 各 160 个（ReLU、全局最大池化）→ 共享层 192 → 9 个头 |
| `cnn_bigru` | 字嵌入 64 → 卷积核 3（same 填充）160 通道 + ReLU → 1 层双向 GRU（每个方向 128）→ 最大池化 ⊕ 平均池化 → 共享层 192 → 9 个头 |
| `char_transformer` | 字嵌入 160 + 可学习位置（到 max_len）→ 3 层 pre-LN 编码器（4 头注意力，FFN 2×，GELU）→ 末层 LayerNorm → 平均池化 ⊕ 最大池化 → 共享层 192 → 9 个头 |
| `cnn_ensemble3` | 3 个 `cnn_wide`（不同随机种子；第 1 个就是基线）各自输出概率后取平均 |

每个变体：训练前算出 float16 `student.npz` 的确切字节数并断言 < 4 MB；训练后在留出集上按两个召回目标（0.95、0.97）各定一组温度与阈值；写出纯 NumPy 参考前向（float16 权重 → float32 计算），与 PyTorch 对比概率（最大绝对差 ≤ 2e-3），测单线程时延（P50 / P99，目标 P99 ≤ 45 ms）；再用 NumPy 前向给**开发集**（`role=dev`）打分，按主 notebook 的“规则 + 学生（现行仲裁）”合并。

## 选择规则（在看任何结果之前写定）

候选 = 每个变体 × 每个召回目标（共 8 个）。

1. **前提**（不满足即不参选）：`student.npz` < 4 MB；NumPy 对 PyTorch 概率最大绝对差 ≤ 2e-3；单线程 P99 ≤ 45 ms。
2. **约束**：开发集上 L0 被判为 ≥L2 的比例（规则 + 学生，现行仲裁）≤ **10%**；留出集上 L0 被判为 ≥L2 的比例（学生单独，阈值后）≤ **6%**。
3. **目标**：在满足约束的候选中，取开发集上 **L2+L3 判为 ≥L2 的条数**（规则 + 学生，现行仲裁）最多的。
4. **平局**：`student.npz` 更小者胜；再平，单线程 P99 更低者胜。
5. 没有候选满足约束时不导出任何模型，只给出报告。

只导出胜出的那一个（变体 + 召回目标）到 `models/perception_student_arch/<变体>/`。独立评估集（`role=fresh`）是最终测试，本 notebook **完全不评分**；开发集用来选择，它的数字因此会偏乐观。

## 前提

- 先用**同一份** `raw/synthetic/round1.jsonl` 与 `raw/olivia/olivia_cases.csv` 跑完 `perception_teacher.ipynb`（至少到第 8 节，教师蒸馏目标已缓存）。本 notebook 用与主 notebook 逐字相同的代码重建训练池、泄露剔除、分折与学生留出划分，并核对三个指纹：教师配置（`config_fingerprint`）、学生训练文本 + 教师（`cache/teacher_targets.npz`）、各折教师的蒸馏输出（`fold_*.npz` 的 `kd_fingerprint`）。任何一个对不上就停下：说明数据或配置变了，要先重跑主 notebook。
- `olivia_cases.csv` 要带开发集：本地 `export_olivia_data.py --dev-eval build/eval/interim_fresh.csv ...`。开发集、独立评估集、探针、排除集都参与泄露剔除，所以开发集换了文件也要先重跑主 notebook。
- Colab 运行时选 GPU，“全部运行”。四个变体共训练 6 个模型（集成的第 1 个成员复用基线），每个都在 Drive 上存检查点，断开后重跑会直接复用。

## 产出（`DRIVE_ROOT/` 下）

| 路径 | 内容 |
| :--- | :--- |
| `models/student_arch_checkpoints/*.pt` | 各模型的训练检查点（续跑用，不进产品） |
| `reports/student_arch_report.md` / `.json` | 各变体 × 召回目标的留出集与开发集指标、按槽位的 L0 误报、参数量与字节数、一致性与时延、选择过程 |
| `models/perception_student_arch/<胜出变体>/student.npz`、`vocab.json`、`student_config.json` | 胜出者，文件布局与现在的学生相同；`student_config.json` 为 `format_version` 2，多一个 `architecture` 字段写明各层与数组形状。产品端要先移植对应结构才能加载 |
""")

md("## 1. 环境（与主 notebook 相同）")

code(main_cell("IN_COLAB = True"))

code(main_cell("# 环境检查、随机种子与挂载 Drive"))

md("## 2. 配置（主 notebook 的配置区原样照搬，下面另加本实验的配置）")

code(main_cell('SMOKE_TEST = os.environ.get("OLIVIA_SMOKE_TEST") == "1"'))

code(r"""
# ---- 本实验的配置 ----
import io, shutil, tempfile
from transformers import get_linear_schedule_with_warmup  # 主 notebook 在教师单元里导入；本实验不加载教师模型

TARGET_RECALLS = (0.95, 0.97)       # 留出集上 L2+L3 判为 ≥L2 的召回目标；每个变体各定两组阈值（L3 阈值仍按 TARGET_RECALL_L3）
# 选择规则（见开头；在看任何结果之前写定）
SELECT_MAX_DEV_L0_FA = 0.10         # 开发集 L0 误报为 ≥L2（规则 + 学生，现行仲裁）的上限
SELECT_MAX_HOLDOUT_L0_FA = 0.06     # 留出集 L0 误报为 ≥L2（学生单独，阈值后）的上限
PARITY_IMPL_TOL = 1e-4              # NumPy 对“权重先取 float16 的 PyTorch”：只剩实现差异，超过即为实现错误，直接停下
FULL_LENGTH_RUNS = 100              # 满长文本（max_len 个字）的单条时延测量次数（GRU 的时延随长度线性增长）
ENSEMBLE_EPS = 1e-6                 # 集成合并连续头时把平均值夹在 (−1, 1) / (0, 1) 内，再取反函数

# 各变体的结构；"train" 里的键覆盖 STUDENT 中的同名训练参数（epochs、batch_size、lr、weight_decay、warmup_ratio）
ARCH_VARIANTS = {
    "cnn_wide": {"type": "cnn", "embed_dim": STUDENT["embed_dim"], "kernels": list(STUDENT["kernels"]),
                 "filters": STUDENT["filters"], "hidden": STUDENT["hidden"], "dropout": STUDENT["dropout"]},
    "cnn_bigru": {"type": "bigru", "embed_dim": 64, "conv_kernel": 3, "conv_channels": 160, "gru_hidden": 128,
                  "hidden": 192, "dropout": 0.2},
    "char_transformer": {"type": "transformer", "d_model": 160, "layers": 3, "heads": 4, "ffn_mult": 2, "hidden": 192,
                         "dropout": 0.1, "layer_norm_eps": 1e-5, "train": {"lr": 1e-3, "warmup_ratio": 0.1}},
    "cnn_ensemble3": {"type": "ensemble", "members": 3, "member": "cnn_wide"},
}
if SMOKE_TEST:  # 冒烟测试：只验证流程，结构按比例缩到极小（cnn_wide 已随主配置区缩小）
    ARCH_VARIANTS["cnn_bigru"].update(embed_dim=16, conv_channels=12, gru_hidden=8, hidden=24)
    ARCH_VARIANTS["char_transformer"].update(d_model=16, layers=2, heads=2, hidden=24)
    FULL_LENGTH_RUNS = 20
    # 极小的随机模型误报必然很高：冒烟测试放宽两条误报约束，只为走通选择与导出；正式运行不受影响
    SELECT_MAX_DEV_L0_FA = SELECT_MAX_HOLDOUT_L0_FA = 1.0
TRAIN_KEYS = ("epochs", "batch_size", "lr", "weight_decay", "warmup_ratio")
# 第 m 个模型（m = 0 是基线）的初始化种子与数据顺序种子；m = 0 与主 notebook 的 train_student 完全相同
MEMBER_SEED_STRIDE = 100

PATHS["arch_ckpt_dir"] = os.path.join(DRIVE_ROOT, "models", "student_arch_checkpoints")
PATHS["arch_export_dir"] = os.path.join(DRIVE_ROOT, "models", "perception_student_arch")
PATHS["arch_report"] = os.path.join(PATHS["reports"], "student_arch_report")
os.makedirs(PATHS["arch_ckpt_dir"], exist_ok=True)
LOCAL_EXPORT_DIR = tempfile.mkdtemp(prefix="student_arch_")  # 各变体的临时导出（本机，不写 Drive），NumPy 前向从这里读
print("本实验：召回目标", TARGET_RECALLS, "| 变体", list(ARCH_VARIANTS), "| 临时导出", LOCAL_EXPORT_DIR)
""")

md(r"""
## 3. 数据与学生划分（主 notebook 第 3 节、3b 节原样照搬）

训练池、泄露剔除、分折、学生留出集与增强副本都与主 notebook 逐字相同；下一节用指纹核对。
""")

code(main_cell("def load_synthetic(path):"))

code(main_cell("def stratified_holdout(frame, fraction, seed):"))

code(r"""
# 最终测试集（role=fresh）只参与上面的泄露剔除，本 notebook 不评分；开发集（role=dev）用于选择
FRESH_ROWS = len(tests.pop("fresh"))
dev = tests["dev"]
if dev.empty:
    raise ValueError("olivia_cases.csv 里没有 role=dev 的行：本地用 export_olivia_data.py --dev-eval <开发集.csv> 重新导出、"
                     "上传，并先重跑 perception_teacher.ipynb")
print(f"开发集 {len(dev)} 条：", dev["level"].map(dict(enumerate(LEVEL_NAMES))).value_counts().sort_index().to_dict(),
      f"| 独立评估集 {FRESH_ROWS} 条（本 notebook 不评分）")
""")

md("## 4. 共用部分：损失、校准与指标（主 notebook 第 4 节原样照搬）")

code(main_cell("def risk_class_weights(frame):"))

md(r"""
## 5. 读取教师产物并核对指纹

- 教师配置指纹（`CONFIG_FINGERPRINT`）由训练池与教师配置决定，须与 `models/perception_teacher/train_config.json` 一致。
- 蒸馏目标指纹（`TARGETS_FINGERPRINT`）= 教师配置指纹 + 学生训练文本（含增强副本），须与 `cache/teacher_targets.npz` 一致：这就核对了学生训练 / 留出划分与增强完全相同。
- 集成蒸馏时各折教师的 `kd_fingerprint` 须等于 `FOLD_KD_FINGERPRINT`。
- 蒸馏目标的算法（各教师在“教师温度 × 2”下的软目标取平均）与主 notebook 逐字相同。
""")

code(SHARED_TEACHER_FINGERPRINTS + "\n\n\n" + SHARED_VOCAB + "\n" + SHARED_TARGETS_FINGERPRINT + "\n\n\n" + r"""
def _stale(what):
    raise RuntimeError(f"{what}与当前数据 / 配置对不上：先用同一份 round1.jsonl 与 olivia_cases.csv 重跑 perception_teacher.ipynb"
                       "（至少到第 8 节），再运行本 notebook")


if not (os.path.exists(PATHS["teacher_config"]) and os.path.exists(PATHS["teacher_targets"])):
    _stale("找不到教师产物，")
with open(PATHS["teacher_config"], encoding="utf-8") as f:
    saved_teacher = json.load(f)
if not saved_teacher.get("training_complete") or saved_teacher.get("config_fingerprint") != CONFIG_FINGERPRINT:
    _stale(f"教师配置指纹（Drive 上 {saved_teacher.get('config_fingerprint')}，重建 {CONFIG_FINGERPRINT}）")
with open(PATHS["teacher_calibration"], encoding="utf-8") as f:
    TEACHER_CAL = json.load(f)
if TEACHER_CAL.get("config_fingerprint") != CONFIG_FINGERPRINT:
    _stale("教师校准（teacher_calibration.json）")
with np.load(PATHS["teacher_targets"]) as saved:
    if str(saved["fingerprint"]) != TARGETS_FINGERPRINT:
        _stale(f"蒸馏目标指纹（Drive 上 {saved['fingerprint']}，重建 {TARGETS_FINGERPRINT}；学生训练文本指纹 {STUDENT_TEXTS_HASH}）")
    teacher_train_raw = saved["raw"]
assert teacher_train_raw.shape == (len(student_train), OUT_DIM)

fold_student_raw = []
if KD_SOURCE == "ensemble":
    for k in range(CV_FOLDS):
        fold_path = os.path.join(PATHS["fold_dir"], f"fold_{k}.npz")
        if not os.path.exists(fold_path):
            _stale(f"缺少 fold_{k}.npz，")
        with np.load(fold_path) as saved:
            held = np.flatnonzero(pool["fold"].to_numpy() == k)
            if (str(saved["fingerprint"]) != CONFIG_FINGERPRINT or not np.array_equal(saved["index"], held)
                    or "kd_fingerprint" not in saved.files or str(saved["kd_fingerprint"]) != FOLD_KD_FINGERPRINT):
                _stale(f"第 {k} 折教师的蒸馏输出")
            fold_student_raw.append(saved["kd_raw"])
        assert fold_student_raw[-1].shape == teacher_train_raw.shape
print(f"教师产物指纹一致：教师 {CONFIG_FINGERPRINT}，蒸馏目标 {TARGETS_FINGERPRINT}（学生训练文本 {STUDENT_TEXTS_HASH}），"
      f"折教师 {len(fold_student_raw)} 个（{FOLD_KD_FINGERPRINT}）")


""" + SHARED_SOFT_TARGETS + "\n\n\n" + SHARED_KD_TARGETS + "\n" + r"""
HARD_NEGATIVE_ROWS = hard_negative_mask(student_train)
VOCAB_HASH = hashlib.sha256("".join(VOCAB).encode("utf-8")).hexdigest()[:16]
print(f"字表 {len(VOCAB)} 个；蒸馏目标 = {len(kd_teachers)} 个教师的平均；学生训练集 {len(student_train)} 条，"
      f"留出 {len(student_holdout)} 条，难负例 {int(HARD_NEGATIVE_ROWS.sum())} 行（× {HARD_NEGATIVE_WEIGHT}）")
""")

md(r"""
## 6. 学生结构（PyTorch）

- 字符编码、`CharCNN`、批处理、`student_raw`、蒸馏损失与主 notebook 逐字相同。
- 每个模型都是 `forward(ids, lengths) → (批, OUT_DIM)` 的原始输出，9 个头按 `HEAD_SLICES` 切分。`lengths` 是编码后的长度（含不足 `min_len` 时补的 PAD）；批内补齐的位置在 GRU（`pack_padded_sequence`）、注意力（键掩码）和池化里都被屏蔽，所以与 NumPy 逐条推理完全一致。
- 集成：各成员分别前向，分类头取 `log(平均 softmax)`，连续头取“平均激活值”的反函数（tanh → atanh，sigmoid → logit），这样合并结果仍是“原始输出”，温度与阈值照常拟合。
""")

code(SHARED_STUDENT_CNN + "\n\n\n" + r"""
class CharBiGRU(nn.Module):
    # 字嵌入 → same 卷积 + ReLU → 1 层双向 GRU → [最大池化; 平均池化]（只在 lengths 内）→ dropout → dense + ReLU → heads
    def __init__(self, vocab_size, cfg):
        super().__init__()
        assert cfg["conv_kernel"] % 2 == 1, "same 卷积要求奇数核宽"
        self.embed = nn.Embedding(vocab_size, cfg["embed_dim"], padding_idx=0)
        self.conv = nn.Conv1d(cfg["embed_dim"], cfg["conv_channels"], cfg["conv_kernel"], padding=cfg["conv_kernel"] // 2)
        self.gru = nn.GRU(cfg["conv_channels"], cfg["gru_hidden"], batch_first=True, bidirectional=True)
        self.dropout = nn.Dropout(cfg["dropout"])
        self.dense = nn.Linear(4 * cfg["gru_hidden"], cfg["hidden"])
        self.heads = nn.Linear(cfg["hidden"], OUT_DIM)

    def forward(self, ids, lengths):
        # 批内补齐位置是 PAD（嵌入恒为 0），所以 same 卷积在文本末尾看到的就是 0，与逐条推理时的零填充相同
        x = torch.relu(self.conv(self.embed(ids).transpose(1, 2))).transpose(1, 2)  # (批, 长度, 通道)
        packed = nn.utils.rnn.pack_padded_sequence(x, lengths.cpu(), batch_first=True, enforce_sorted=False)
        out, _ = self.gru(packed)
        out, _ = nn.utils.rnn.pad_packed_sequence(out, batch_first=True, total_length=ids.shape[1])  # (批, 长度, 2G)
        valid = (torch.arange(ids.shape[1], device=ids.device)[None, :] < lengths[:, None])[:, :, None]
        pooled_max = out.masked_fill(~valid, float("-inf")).max(dim=1).values
        pooled_mean = (out * valid).sum(dim=1) / lengths[:, None].float()
        h = torch.relu(self.dense(self.dropout(torch.cat([pooled_max, pooled_mean], dim=1))))
        return self.heads(h)


class PreLNBlock(nn.Module):
    # x + Attn(LN1(x))；x + FFN(LN2(x))。注意力：qkv 一个线性层，多头缩放点积，键掩码屏蔽补齐位置；FFN：线性 → GELU(tanh 近似) → 线性
    def __init__(self, d_model, heads, ffn_dim, dropout, eps):
        super().__init__()
        assert d_model % heads == 0
        self.n_heads = heads
        self.ln1 = nn.LayerNorm(d_model, eps=eps)
        self.qkv = nn.Linear(d_model, 3 * d_model)
        self.out = nn.Linear(d_model, d_model)
        self.ln2 = nn.LayerNorm(d_model, eps=eps)
        self.ffn1 = nn.Linear(d_model, ffn_dim)
        self.ffn2 = nn.Linear(ffn_dim, d_model)
        self.drop = nn.Dropout(dropout)

    def forward(self, x, key_valid):
        b, length, d = x.shape
        dh = d // self.n_heads
        q, k, v = self.qkv(self.ln1(x)).split(d, dim=2)
        q, k, v = (t.view(b, length, self.n_heads, dh).transpose(1, 2) for t in (q, k, v))  # (批, 头, 长度, dh)
        scores = (q @ k.transpose(-1, -2)) / math.sqrt(dh)
        scores = scores.masked_fill(~key_valid[:, None, None, :], float("-inf"))
        context = (self.drop(torch.softmax(scores, dim=-1)) @ v).transpose(1, 2).reshape(b, length, d)
        x = x + self.drop(self.out(context))
        return x + self.drop(self.ffn2(self.drop(F.gelu(self.ffn1(self.ln2(x)), approximate="tanh"))))


class CharTransformer(nn.Module):
    # 字嵌入 + 可学习位置 → pre-LN 编码器若干层 → 末层 LayerNorm → [平均池化; 最大池化]（只在 lengths 内）→ dropout → dense + ReLU → heads
    def __init__(self, vocab_size, cfg):
        super().__init__()
        d = cfg["d_model"]
        self.embed = nn.Embedding(vocab_size, d, padding_idx=0)
        self.position = nn.Embedding(STUDENT["max_len"], d)
        nn.init.normal_(self.embed.weight, std=0.02)
        nn.init.normal_(self.position.weight, std=0.02)
        with torch.no_grad():
            self.embed.weight[0].zero_()  # PAD 嵌入为 0
        self.blocks = nn.ModuleList(PreLNBlock(d, cfg["heads"], cfg["ffn_mult"] * d, cfg["dropout"], cfg["layer_norm_eps"])
                                    for _ in range(cfg["layers"]))
        self.final_ln = nn.LayerNorm(d, eps=cfg["layer_norm_eps"])
        self.dropout = nn.Dropout(cfg["dropout"])
        self.dense = nn.Linear(2 * d, cfg["hidden"])
        self.heads = nn.Linear(cfg["hidden"], OUT_DIM)

    def forward(self, ids, lengths):
        length = ids.shape[1]
        valid = torch.arange(length, device=ids.device)[None, :] < lengths[:, None]  # (批, 长度)
        x = self.dropout(self.embed(ids) + self.position.weight[:length][None])
        for block in self.blocks:
            x = block(x, valid)
        x = self.final_ln(x)
        mask = valid[:, :, None]
        pooled_mean = (x * mask).sum(dim=1) / lengths[:, None].float()
        pooled_max = x.masked_fill(~mask, float("-inf")).max(dim=1).values
        h = torch.relu(self.dense(self.dropout(torch.cat([pooled_mean, pooled_max], dim=1))))
        return self.heads(h)


def combine_members(raws):
    # 集成：分类头 log(平均 softmax)；tanh 头 atanh(平均 tanh)；sigmoid / bce 头 logit(平均 sigmoid)
    parts = []
    for name, kind, _ in HEADS:
        z = torch.stack([r[:, HEAD_SLICES[name]].float() for r in raws])  # (成员, 批, 宽)
        if kind == "class":
            parts.append(torch.logsumexp(F.log_softmax(z, dim=-1), dim=0) - math.log(len(raws)))
        elif kind == "tanh":
            parts.append(torch.atanh(torch.tanh(z).mean(0).clamp(-1 + ENSEMBLE_EPS, 1 - ENSEMBLE_EPS)))
        else:
            p = torch.sigmoid(z).mean(0).clamp(ENSEMBLE_EPS, 1 - ENSEMBLE_EPS)
            parts.append(torch.log(p) - torch.log1p(-p))
    return torch.cat(parts, dim=1)


class StudentEnsemble(nn.Module):
    def __init__(self, members):
        super().__init__()
        self.members = nn.ModuleList(members)

    def forward(self, ids, lengths):
        return combine_members([m(ids, lengths) for m in self.members])


def build_single(arch):
    return {"cnn": CharCNN, "bigru": CharBiGRU, "transformer": CharTransformer}[arch["type"]](len(VOCAB), arch)


def member_arch(variant):
    arch = ARCH_VARIANTS[variant]
    return ARCH_VARIANTS[arch["member"]] if arch["type"] == "ensemble" else arch


def train_hparams(variant):
    base = ARCH_VARIANTS[variant]["member"] if ARCH_VARIANTS[variant]["type"] == "ensemble" else variant
    return {**{k: STUDENT[k] for k in TRAIN_KEYS}, **ARCH_VARIANTS[base].get("train", {})}


def training_units(variant):
    # 一个变体由哪些需要训练的模型组成：(检查点名, 结构, 成员序号)。集成的第 0 个成员就是基线本身（同名检查点，只训练一次）
    arch = ARCH_VARIANTS[variant]
    if arch["type"] != "ensemble":
        return [(variant, arch, 0)]
    return [(arch["member"] if m == 0 else f"{arch['member']}_seed{m}", member_arch(variant), m) for m in range(arch["members"])]
""")

md(r"""
## 7. 导出格式与大小检查（训练前）

- 每个变体的数组名与形状见下面的 `export_arrays`；`architecture_spec` 写进 `student_config.json` 的 `architecture` 字段，列出各层、所用数组与运算，产品移植照此实现。
- 字节数不是估算：用初始化后的模型按导出格式（float16）写进内存里的 npz 得到确切大小（npz 不压缩，大小与权重取值无关），断言 < 4 MB。
""")

code(r"""
def _take(state, used, key):
    used.add(key)
    return state[key]


def cnn_arrays(state, used, src="", dst="", kernels=None):
    kernels = kernels or ARCH_VARIANTS["cnn_wide"]["kernels"]
    arrays = {f"{dst}embedding": _take(state, used, f"{src}embed.weight")}
    for i, k in enumerate(kernels):
        arrays[f"{dst}conv{k}_weight"] = _take(state, used, f"{src}convs.{i}.weight")  # (卷积核数, 嵌入, k)
        arrays[f"{dst}conv{k}_bias"] = _take(state, used, f"{src}convs.{i}.bias")
    for layer in ("dense", "heads"):
        arrays[f"{dst}{layer}_weight"] = _take(state, used, f"{src}{layer}.weight")
        arrays[f"{dst}{layer}_bias"] = _take(state, used, f"{src}{layer}.bias")
    return arrays


def export_arrays(model, variant):
    # PyTorch state_dict → 导出数组（float32；写盘时转 float16）。断言每个参数都被导出，防止漏掉某一层
    state = {k: v.detach().cpu().float().numpy() for k, v in model.state_dict().items()}
    arch, used = ARCH_VARIANTS[variant], set()
    if arch["type"] == "cnn":
        arrays = cnn_arrays(state, used, kernels=arch["kernels"])
    elif arch["type"] == "ensemble":
        arrays = {}
        for m in range(arch["members"]):
            arrays.update(cnn_arrays(state, used, f"members.{m}.", f"m{m}_", member_arch(variant)["kernels"]))
    elif arch["type"] == "bigru":
        arrays = {"embedding": _take(state, used, "embed.weight"),
                  "conv_weight": _take(state, used, "conv.weight"), "conv_bias": _take(state, used, "conv.bias")}
        for direction, suffix in (("fwd", ""), ("bwd", "_reverse")):
            for ours, theirs in (("w_ih", "weight_ih_l0"), ("w_hh", "weight_hh_l0"), ("b_ih", "bias_ih_l0"), ("b_hh", "bias_hh_l0")):
                arrays[f"gru_{direction}_{ours}"] = _take(state, used, f"gru.{theirs}{suffix}")
        for layer in ("dense", "heads"):
            arrays[f"{layer}_weight"] = _take(state, used, f"{layer}.weight")
            arrays[f"{layer}_bias"] = _take(state, used, f"{layer}.bias")
    else:  # transformer
        arrays = {"embedding": _take(state, used, "embed.weight"), "position": _take(state, used, "position.weight")}
        for l in range(arch["layers"]):
            for part in ("ln1", "qkv", "out", "ln2", "ffn1", "ffn2"):
                for p in ("weight", "bias"):
                    arrays[f"block{l}_{part}_{p}"] = _take(state, used, f"blocks.{l}.{part}.{p}")
        for layer in ("final_ln", "dense", "heads"):
            arrays[f"{layer}_weight"] = _take(state, used, f"{layer}.weight")
            arrays[f"{layer}_bias"] = _take(state, used, f"{layer}.bias")
    missing = set(state) - used
    assert not missing, f"{variant}：这些参数没有导出 {sorted(missing)}"
    return arrays


def npz_bytes(arrays):
    buffer = io.BytesIO()
    np.savez(buffer, **{k: v.astype(np.float16) for k, v in arrays.items()})
    return buffer.getbuffer().nbytes


def cnn_spec(arch, prefix=""):
    return {"type": "cnn", "embed_dim": arch["embed_dim"], "kernels": list(arch["kernels"]), "filters": arch["filters"],
            "hidden": arch["hidden"],
            "layer_list": [{"op": "embedding", "arrays": [f"{prefix}embedding"]}]
                      + [{"op": "conv1d_valid", "kernel": k, "then": "relu → 全局最大池化（时间维）",
                          "arrays": [f"{prefix}conv{k}_weight", f"{prefix}conv{k}_bias"]} for k in arch["kernels"]]
                      + [{"op": "concat", "order": "kernels 顺序"},
                         {"op": "linear", "then": "relu", "arrays": [f"{prefix}dense_weight", f"{prefix}dense_bias"]},
                         {"op": "linear", "then": "按 heads 切片", "arrays": [f"{prefix}heads_weight", f"{prefix}heads_bias"]}],
            "forward": "embedding → 每个 k：conv{k}（valid 卷积）→ ReLU → 全局最大池化；按 kernels 顺序拼接 → dense → ReLU → heads"}


def architecture_spec(variant):
    arch = ARCH_VARIANTS[variant]
    conventions = {"linear": "y = x @ weight.T + bias（weight 为 PyTorch 的 (输出, 输入)）",
                   "conv1d": "weight (输出通道, 输入通道, k)；滑动窗口 (位置, 输入通道, k) 展平后乘 weight.reshape(输出通道, -1).T",
                   "dtype": "数组存为 float16，加载后转 float32 计算"}
    if arch["type"] == "cnn":
        return {**cnn_spec(arch), "conventions": conventions}
    if arch["type"] == "ensemble":
        return {"type": "ensemble", "members": arch["members"], "array_prefix": "m{i}_",
                "member": cnn_spec(member_arch(variant), "m{i}_"),
                "combine": {"class": "log(mean_i softmax(z_i))（之后照常 softmax(z / temperature)）",
                            "tanh": f"atanh(clip(mean_i tanh(z_i), -1 + {ENSEMBLE_EPS}, 1 - {ENSEMBLE_EPS}))",
                            "sigmoid": f"logit(clip(mean_i sigmoid(z_i), {ENSEMBLE_EPS}, 1 - {ENSEMBLE_EPS}))（bce 头同）"},
                "forward": "每个成员按 member 的 CNN 前向得到原始输出 z_i（数组名前缀 m0_、m1_ …），再按 combine 逐头合并成一个原始输出",
                "conventions": conventions}
    if arch["type"] == "bigru":
        g = arch["gru_hidden"]
        return {"type": "bigru", "embed_dim": arch["embed_dim"], "conv_kernel": arch["conv_kernel"],
                "conv_channels": arch["conv_channels"], "gru_hidden": g, "hidden": arch["hidden"],
                "layer_list": [{"op": "embedding", "arrays": ["embedding"]},
                           {"op": "conv1d_same", "kernel": arch["conv_kernel"], "padding": arch["conv_kernel"] // 2,
                            "then": "relu", "arrays": ["conv_weight", "conv_bias"]},
                           {"op": "gru", "direction": "forward", "arrays": ["gru_fwd_w_ih", "gru_fwd_w_hh", "gru_fwd_b_ih", "gru_fwd_b_hh"]},
                           {"op": "gru", "direction": "backward", "arrays": ["gru_bwd_w_ih", "gru_bwd_w_hh", "gru_bwd_b_ih", "gru_bwd_b_hh"]},
                           {"op": "concat_directions", "shape": f"(长度, {2 * g})", "order": "[forward, backward]"},
                           {"op": "pool", "how": "concat(max over time, mean over time)", "shape": f"({4 * g},)"},
                           {"op": "linear", "then": "relu", "arrays": ["dense_weight", "dense_bias"]},
                           {"op": "linear", "then": "按 heads 切片", "arrays": ["heads_weight", "heads_bias"]}],
                "gru": "PyTorch 门顺序 r, z, n（w_ih (3G, 输入)，w_hh (3G, G)）：r = σ(W_ir x + b_ir + W_hr h + b_hr)；"
                       "z = σ(W_iz x + b_iz + W_hz h + b_hz)；n = tanh(W_in x + b_in + r ⊙ (W_hn h + b_hn))；h' = (1 − z) ⊙ n + z ⊙ h；h0 = 0。"
                       "backward 方向从最后一个位置往前走，输出仍按原位置存放",
                "forward": "embedding → same 卷积（两端各补 padding 个零向量）→ ReLU → 双向 GRU → 每个位置拼 [前向, 后向] → "
                           "[时间维最大值; 时间维平均] → dense → ReLU → heads",
                "conventions": conventions}
    d = arch["d_model"]
    return {"type": "transformer", "d_model": d, "layers": arch["layers"], "heads": arch["heads"],
            "head_dim": d // arch["heads"], "ffn_dim": arch["ffn_mult"] * d, "hidden": arch["hidden"],
            "layer_norm_eps": arch["layer_norm_eps"], "max_positions": STUDENT["max_len"],
            "layer_list": [{"op": "embedding", "arrays": ["embedding"]},
                            {"op": "add_position", "arrays": ["position"], "how": "x[t] += position[t]，t 从 0 起"}]
                           + [{"op": "pre_ln_block", "index": l,
                               "arrays": [f"block{l}_{part}_{p}" for part in ("ln1", "qkv", "out", "ln2", "ffn1", "ffn2")
                                          for p in ("weight", "bias")]} for l in range(arch["layers"])]
                           + [{"op": "layer_norm", "arrays": ["final_ln_weight", "final_ln_bias"]},
                              {"op": "pool", "how": "concat(mean over time, max over time)", "shape": f"({2 * d},)"},
                              {"op": "linear", "then": "relu", "arrays": ["dense_weight", "dense_bias"]},
                              {"op": "linear", "then": "按 heads 切片", "arrays": ["heads_weight", "heads_bias"]}],
            "block": "a = LN1(x)；[q, k, v] = split(a @ qkv_weight.T + qkv_bias, 3)；每头 softmax(q_h k_h^T / sqrt(head_dim)) v_h，"
                     "各头按顺序拼回 d_model；x = x + (拼接 @ out_weight.T + out_bias)；"
                     "x = x + ffn2(GELU_tanh(ffn1(LN2(x))))。GELU_tanh(u) = 0.5 u (1 + tanh(√(2/π)(u + 0.044715 u³)))；"
                     "LN(u) = (u − mean) / sqrt(var + eps) × weight + bias（var 为有偏方差）",
            "forward": "embedding + position → pre-LN 编码器 × layers → final LayerNorm → [时间维平均; 时间维最大值] → dense → ReLU → heads；"
                       "逐条推理没有补齐，所有位置（含不足 min_len 时补的 PAD）都参与注意力与池化",
            "conventions": conventions}


VARIANT_SIZES = {}
for variant in ARCH_VARIANTS:
    set_seed(SEED)
    units = training_units(variant)
    probe_model = (StudentEnsemble([build_single(arch) for _, arch, _ in units]) if len(units) > 1
                   else build_single(units[0][1]))
    arrays = export_arrays(probe_model, variant)
    VARIANT_SIZES[variant] = {"params": int(sum(p.numel() for p in probe_model.parameters())),
                              "arrays": len(arrays), "npz_bytes": npz_bytes(arrays)}
    del probe_model
    print(f"{variant:>17s}：{VARIANT_SIZES[variant]['params']:>10,} 个参数，{VARIANT_SIZES[variant]['arrays']:>3d} 个数组，"
          f"student.npz {VARIANT_SIZES[variant]['npz_bytes'] / 1024:8.1f} KB（上限 {STUDENT_MAX_BYTES / 1024:.0f} KB）")
    assert VARIANT_SIZES[variant]["npz_bytes"] < STUDENT_MAX_BYTES, f"{variant} 超过 {STUDENT_MAX_BYTES} 字节"
""")

md(r"""
## 8. 训练（与主 notebook 的学生训练逐行相同，只是模型可换）

损失 = 0.5 × 硬标签（屏蔽损失，风险头难负例 × 2）+ 0.5 × 蒸馏（分类头 T = 2 的 KL × T²，连续头 MSE），AdamW + 线性预热衰减，梯度裁剪 5.0。
基线（成员 0）的初始化种子与数据顺序与主 notebook 的 `train_student` 完全相同；集成的其余成员每个种子加 100。
`char_transformer` 学习率 1e-3、预热 10%（注意力模型在 2e-3 下容易不稳），其余与 STUDENT 相同。
""")

code(r"""
def unit_fingerprint(name, arch, member, hp):
    spec = {"name": name, "arch": arch, "member": member, "train": hp, "teacher": CONFIG_FINGERPRINT,
            "targets": TARGETS_FINGERPRINT, "kd_teachers": len(kd_teachers), "fold_kd": FOLD_KD_FINGERPRINT,
            "kd_temperature": STUDENT["kd_temperature"], "kd_alpha": STUDENT["kd_alpha"], "vocab": VOCAB_HASH,
            "hard_negative": [HARD_NEGATIVE_WEIGHT, int(HARD_NEGATIVE_ROWS.sum())], "seed": SEED}
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


def train_unit(arch, member, hp, tag):
    # 与主 notebook train_student 相同；member = 0 时种子与数据顺序也相同
    set_seed(SEED + 3 + MEMBER_SEED_STRIDE * member)
    model = build_single(arch).to(DEVICE)
    encoded = [encode_chars(t) for t in student_train["text"]]
    targets = torch.tensor(kd_targets, dtype=torch.float)
    risk_weight = risk_class_weights(student_train)
    row_weight = None
    if HARD_NEGATIVE_WEIGHT != 1.0:
        row_weight = torch.tensor(np.where(HARD_NEGATIVE_ROWS, HARD_NEGATIVE_WEIGHT, 1.0), dtype=torch.float)
    optimizer = torch.optim.AdamW(model.parameters(), lr=hp["lr"], weight_decay=hp["weight_decay"])
    steps = hp["epochs"] * math.ceil(len(student_train) / hp["batch_size"])
    scheduler = get_linear_schedule_with_warmup(optimizer, int(hp["warmup_ratio"] * steps), steps)
    alpha = STUDENT["kd_alpha"]
    for epoch in range(1, hp["epochs"] + 1):
        model.train()
        started, total = time.time(), 0.0
        order = np.random.default_rng(SEED + MEMBER_SEED_STRIDE * member + 1000 + epoch).permutation(len(student_train))
        for start in range(0, len(order), hp["batch_size"]):
            chunk = order[start:start + hp["batch_size"]]
            ids, lengths = char_batch([encoded[i] for i in chunk], DEVICE)
            raw = model(ids, lengths)
            labels = label_tensors(student_train.iloc[chunk], DEVICE)
            rows = None if row_weight is None else row_weight[chunk].to(DEVICE)
            loss = ((1 - alpha) * supervised_loss(raw, labels, risk_weight, rows)
                    + alpha * distill_loss(raw, targets[chunk].to(DEVICE)))
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            scheduler.step()
            total += loss.item()
        print(f"  [{tag}] epoch {epoch}/{hp['epochs']} train_loss {total:.3f} ({time.time() - started:.0f}s)")
    return model


def trained_unit(name, arch, member, hp):
    path = os.path.join(PATHS["arch_ckpt_dir"], f"{name}.pt")
    fingerprint = unit_fingerprint(name, arch, member, hp)
    if os.path.exists(path) and not FORCE_RETRAIN:
        saved = torch.load(path, map_location="cpu")
        if saved.get("training_complete") and saved.get("fingerprint") == fingerprint:
            model = build_single(arch)
            model.load_state_dict(saved["state_dict"])
            print(f"{name}：已训练完成且配置一致，复用。")
            return model.to(DEVICE).eval(), fingerprint
    print(f"{name}：训练（{sum(p.numel() for p in build_single(arch).parameters()):,} 个参数）")
    model = train_unit(arch, member, hp, name)
    torch.save({"state_dict": model.state_dict(), "fingerprint": fingerprint, "training_complete": True}, path)
    return model.eval(), fingerprint


UNITS, MODELS, VARIANT_FINGERPRINTS = {}, {}, {}
for variant in ARCH_VARIANTS:
    hp = train_hparams(variant)
    members = []
    for name, arch, member in training_units(variant):
        if name not in UNITS:
            UNITS[name] = trained_unit(name, arch, member, hp)
        members.append(UNITS[name])
    MODELS[variant] = (StudentEnsemble([m for m, _ in members]) if len(members) > 1 else members[0][0]).to(DEVICE).eval()
    VARIANT_FINGERPRINTS[variant] = hashlib.sha256(":".join(f for _, f in members).encode()).hexdigest()[:16]
print("已就绪：", {v: VARIANT_FINGERPRINTS[v] for v in MODELS})

# 基线复现检查（只作参考，不影响选择）：主 notebook 存下的学生检查点与这里的 cnn_wide 在留出集上的原始输出差多少。
# CPU 上应为 0；GPU 上 cuDNN 不完全确定，会有小差异
if os.path.exists(PATHS["student_ckpt"]):
    try:
        reference = CharCNN(len(VOCAB), STUDENT)
        reference.load_state_dict(torch.load(PATHS["student_ckpt"], map_location="cpu")["state_dict"])
        gap = np.abs(student_raw(reference.to(DEVICE), student_holdout["text"])
                     - student_raw(MODELS["cnn_wide"], student_holdout["text"])).max()
        print(f"基线复现：与主 notebook 的学生检查点相比，留出集原始输出最大绝对差 {gap:.2e}")
        del reference
    except RuntimeError as error:  # 形状不同：主 notebook 的检查点来自别的配置
        print("基线复现检查跳过：", str(error).splitlines()[0])
""")

md(r"""
## 9. 纯 NumPy 参考前向（产品移植照此实现）

只读导出的三个文件（`student.npz`、`vocab.json`、`student_config.json`），不依赖 PyTorch；float16 权重加载后转 float32 计算。
预处理、截断、补齐与头的换算与现在的产品学生（`olivia/core/perception/student.py`）相同；按 `architecture.type` 选前向：

- `cnn`：valid 卷积 + ReLU + 时间维最大池化（与现在的产品相同）；
- `bigru`：same 卷积 → 双向 GRU（输入投影一次算完，循环里只做 `h @ W_hh`）→ 最大 ⊕ 平均池化；
- `transformer`：嵌入 + 位置 → pre-LN 块（LayerNorm、多头注意力、GELU tanh 近似）→ 末层 LayerNorm → 平均 ⊕ 最大池化；
- `ensemble`：每个成员一个 `cnn` 前向，再按 `combine` 合并原始输出。
""")

code(r"""
# ---- 基本运算（float32） ----
def np_sigmoid(x):
    return 0.5 * (1.0 + np.tanh(0.5 * x))  # 与 1 / (1 + e^-x) 恒等，大负数也不溢出


def np_relu(x):
    return np.maximum(x, 0.0)


def np_gelu_tanh(x):
    return 0.5 * x * (1.0 + np.tanh(np.float32(0.7978845608028654) * (x + np.float32(0.044715) * x * x * x)))


def np_layer_norm(x, weight, bias, eps):
    mean = x.mean(axis=-1, keepdims=True)
    var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
    return (x - mean) / np.sqrt(var + np.float32(eps)) * weight + bias


def np_softmax(z, axis=-1):
    e = np.exp(z - z.max(axis=axis, keepdims=True))
    return e / e.sum(axis=axis, keepdims=True)


def np_conv1d(x, weight_t, bias, k, padding=0):
    # x (长度, 输入通道)；weight_t (输入通道 × k, 输出通道)，即 PyTorch 权重 (输出, 输入, k) reshape 后转置
    if padding:
        x = np.pad(x, ((padding, padding), (0, 0)))
    windows = np.lib.stride_tricks.sliding_window_view(x, k, axis=0)  # (长度 - k + 1, 输入通道, k)
    return windows.reshape(windows.shape[0], -1) @ weight_t + bias


def conv_weight_t(weight):
    return np.ascontiguousarray(weight.reshape(weight.shape[0], -1).T)


# ---- 各结构的前向：raw(ids) → (OUT_DIM,) 原始输出 ----
class NpCNN:
    def __init__(self, w, arch, prefix=""):
        self.embedding = w[f"{prefix}embedding"]
        self.convs = [(k, conv_weight_t(w[f"{prefix}conv{k}_weight"]), w[f"{prefix}conv{k}_bias"]) for k in arch["kernels"]]
        self.dense_t, self.dense_b = np.ascontiguousarray(w[f"{prefix}dense_weight"].T), w[f"{prefix}dense_bias"]
        self.heads_t, self.heads_b = np.ascontiguousarray(w[f"{prefix}heads_weight"].T), w[f"{prefix}heads_bias"]

    def raw(self, ids):
        x = self.embedding[ids]
        pooled = [np_relu(np_conv1d(x, wt, b, k)).max(axis=0) for k, wt, b in self.convs]
        h = np_relu(np.concatenate(pooled) @ self.dense_t + self.dense_b)
        return h @ self.heads_t + self.heads_b


class NpBiGRU:
    def __init__(self, w, arch):
        self.k = arch["conv_kernel"]
        self.embedding = w["embedding"]
        self.conv_t, self.conv_b = conv_weight_t(w["conv_weight"]), w["conv_bias"]
        self.directions = [(np.ascontiguousarray(w[f"gru_{d}_w_ih"].T), w[f"gru_{d}_b_ih"],
                            np.ascontiguousarray(w[f"gru_{d}_w_hh"].T), w[f"gru_{d}_b_hh"], d == "bwd") for d in ("fwd", "bwd")]
        self.dense_t, self.dense_b = np.ascontiguousarray(w["dense_weight"].T), w["dense_bias"]
        self.heads_t, self.heads_b = np.ascontiguousarray(w["heads_weight"].T), w["heads_bias"]

    @staticmethod
    def gru(x, w_ih_t, b_ih, w_hh_t, b_hh, reverse):
        # PyTorch 门顺序 r, z, n；h0 = 0；反向从最后一个位置走起，输出按原位置存放
        g = w_hh_t.shape[0]
        gi = x @ w_ih_t + b_ih  # (长度, 3G)：输入投影一次算完
        h = np.zeros(g, dtype=np.float32)
        out = np.empty((x.shape[0], g), dtype=np.float32)
        for t in (range(x.shape[0] - 1, -1, -1) if reverse else range(x.shape[0])):
            gh = h @ w_hh_t + b_hh
            r = np_sigmoid(gi[t, :g] + gh[:g])
            z = np_sigmoid(gi[t, g:2 * g] + gh[g:2 * g])
            n = np.tanh(gi[t, 2 * g:] + r * gh[2 * g:])
            h = (1.0 - z) * n + z * h
            out[t] = h
        return out

    def raw(self, ids):
        x = np_relu(np_conv1d(self.embedding[ids], self.conv_t, self.conv_b, self.k, self.k // 2))
        seq = np.concatenate([self.gru(x, *d) for d in self.directions], axis=1)  # (长度, 2G)：[前向, 后向]
        h = np_relu(np.concatenate([seq.max(axis=0), seq.mean(axis=0)]) @ self.dense_t + self.dense_b)
        return h @ self.heads_t + self.heads_b


class NpTransformer:
    def __init__(self, w, arch):
        self.n_heads, self.eps = arch["heads"], arch["layer_norm_eps"]
        self.embedding, self.position = w["embedding"], w["position"]
        t = lambda name: np.ascontiguousarray(w[name].T)
        self.blocks = [{"ln1": (w[f"block{l}_ln1_weight"], w[f"block{l}_ln1_bias"]),
                        "qkv": (t(f"block{l}_qkv_weight"), w[f"block{l}_qkv_bias"]),
                        "out": (t(f"block{l}_out_weight"), w[f"block{l}_out_bias"]),
                        "ln2": (w[f"block{l}_ln2_weight"], w[f"block{l}_ln2_bias"]),
                        "ffn1": (t(f"block{l}_ffn1_weight"), w[f"block{l}_ffn1_bias"]),
                        "ffn2": (t(f"block{l}_ffn2_weight"), w[f"block{l}_ffn2_bias"])} for l in range(arch["layers"])]
        self.final_ln = (w["final_ln_weight"], w["final_ln_bias"])
        self.dense_t, self.dense_b = t("dense_weight"), w["dense_bias"]
        self.heads_t, self.heads_b = t("heads_weight"), w["heads_bias"]

    def attention(self, a, block):
        length, d = a.shape
        dh = d // self.n_heads
        q, k, v = np.split(a @ block["qkv"][0] + block["qkv"][1], 3, axis=1)
        q, k, v = (m.reshape(length, self.n_heads, dh).transpose(1, 0, 2) for m in (q, k, v))  # (头, 长度, dh)
        weights = np_softmax(q @ k.transpose(0, 2, 1) / np.float32(math.sqrt(dh)))
        context = (weights @ v).transpose(1, 0, 2).reshape(length, d)
        return context @ block["out"][0] + block["out"][1]

    def raw(self, ids):
        x = self.embedding[ids] + self.position[:len(ids)]
        for block in self.blocks:
            x = x + self.attention(np_layer_norm(x, *block["ln1"], self.eps), block)
            hidden = np_gelu_tanh(np_layer_norm(x, *block["ln2"], self.eps) @ block["ffn1"][0] + block["ffn1"][1])
            x = x + hidden @ block["ffn2"][0] + block["ffn2"][1]
        x = np_layer_norm(x, *self.final_ln, self.eps)
        h = np_relu(np.concatenate([x.mean(axis=0), x.max(axis=0)]) @ self.dense_t + self.dense_b)
        return h @ self.heads_t + self.heads_b


class NpEnsemble:
    def __init__(self, w, arch, heads):
        self.members = [NpCNN(w, arch["member"], f"m{i}_") for i in range(arch["members"])]
        self.heads = heads
        self.eps = ENSEMBLE_EPS

    def raw(self, ids):
        z = np.stack([m.raw(ids) for m in self.members]).astype(np.float64)  # (成员, OUT_DIM)
        out = np.empty(z.shape[1])
        for head in self.heads:
            s = slice(head["offset"], head["offset"] + head["size"])
            v = z[:, s]
            if head["kind"] == "class":
                log_p = v - v.max(axis=1, keepdims=True)
                log_p = log_p - np.log(np.exp(log_p).sum(axis=1, keepdims=True))      # 每个成员的 log softmax
                top = log_p.max(axis=0)
                out[s] = top + np.log(np.exp(log_p - top).mean(axis=0))                 # log(平均概率)
            elif head["kind"] == "tanh":
                out[s] = np.arctanh(np.clip(np.tanh(v).mean(axis=0), -1 + self.eps, 1 - self.eps))
            else:
                p = np.clip((0.5 * (1 + np.tanh(0.5 * v))).mean(axis=0), self.eps, 1 - self.eps)
                out[s] = np.log(p) - np.log1p(-p)
        return out


class NumpyArchStudent:
    def __init__(self, directory):
        with open(os.path.join(directory, "student_config.json"), encoding="utf-8") as f:
            self.cfg = json.load(f)
        with open(os.path.join(directory, "vocab.json"), encoding="utf-8") as f:
            vocab = json.load(f)
        self.index = {ch: i for i, ch in enumerate(vocab["chars"])}
        self.unk, self.pad = vocab["unk"], vocab["pad"]
        with np.load(os.path.join(directory, "student.npz"), allow_pickle=False) as w:
            weights = {k: w[k].astype(np.float32) for k in w.files}
        for name, shape in self.cfg["arrays"].items():
            assert list(weights[name].shape) == shape, f"{name} 形状 {weights[name].shape} ≠ {shape}"
        arch = self.cfg["architecture"]
        if arch["type"] == "cnn":
            self.net = NpCNN(weights, arch)
        elif arch["type"] == "bigru":
            self.net = NpBiGRU(weights, arch)
        elif arch["type"] == "transformer":
            self.net = NpTransformer(weights, arch)
        elif arch["type"] == "ensemble":
            self.net = NpEnsemble(weights, arch, self.cfg["heads"])
        else:
            raise ValueError(f"未知结构 {arch['type']}")

    @staticmethod
    def preprocess(text):
        text = html.unescape(str(text)).replace("\u00a0", " ")
        return re.sub(r"\s+", " ", text).strip()

    def encode(self, text):
        cfg = self.cfg
        ids = [self.index.get(ch, self.unk) for ch in self.preprocess(text)]
        if len(ids) > cfg["max_len"]:
            ids = ids[:cfg["head_chars"]] + ids[len(ids) - (cfg["max_len"] - cfg["head_chars"]):]
        return np.array(ids + [self.pad] * (cfg["min_len"] - len(ids)), dtype=np.int64)

    def raw(self, text):
        return self.net.raw(self.encode(text))

    def predict(self, text):
        z = self.raw(text).astype(np.float64)
        out = {}
        for head in self.cfg["heads"]:
            v = z[head["offset"]:head["offset"] + head["size"]]
            if head["kind"] == "class":
                v = v / self.cfg["temperatures"][head["name"]]
                e = np.exp(v - v.max())
                out[head["name"]] = e / e.sum()
            else:
                out[head["name"]] = float(np.tanh(v[0]) if head["kind"] == "tanh" else 1 / (1 + np.exp(-v[0])))
        return out
""")

md(r"""
## 10. 每个变体：留出集校准（两个召回目标）、导出、一致性、时延与开发集

- 留出集用 PyTorch 输出（与主 notebook 第 10 节相同）；开发集用导出的 NumPy 前向（与主 notebook 第 11 节相同，即产品的行为）。
- 合并等级与主 notebook 的“规则 + 学生（现行仲裁）”逐字相同：规则 L3 保持；否则取规则与学生的较高者，最高 L2。
- 一致性：NumPy（float16 权重）对 PyTorch（float32 权重）的概率最大绝对差须 ≤ 2e-3；另报“只算实现差异”（对权重先取 float16 的 PyTorch），超过 1e-4 说明 NumPy 实现有错，直接停下。
""")

code(SHARED_ARBITRATION + "\n\n\n" + r"""
try:
    from threadpoolctl import threadpool_limits
except ImportError:
    threadpool_limits = None

EDGE_TEXTS = ["", "嗯", "我" * (STUDENT["max_len"] * 3) + "不想活了", "😀🙂 a b c &amp; 测试"]
# 一致性候选：训练池原句、增强副本、倒序原句，再加边界文本；不使用任何开发集或测试句
_candidates = list(pool["text"]) + list(student_train["text"]) + [t[::-1] for t in pool["text"]]
PARITY_SET = list(dict.fromkeys(_candidates))[:PARITY_TEXTS - len(EDGE_TEXTS)] + EDGE_TEXTS
LATENCY_SET = list(pool["text"]) + EDGE_TEXTS
FULL_LENGTH_TEXT = "我今天很难受" * STUDENT["max_len"]  # 截断后正好 max_len 个字


def single_thread():
    return threadpool_limits(limits=1) if threadpool_limits is not None else contextlib.nullcontext()


def export_variant(model, variant, cal, directory, extra=None):
    os.makedirs(directory, exist_ok=True)
    arrays = export_arrays(model, variant)
    npz_path = os.path.join(directory, "student.npz")
    np.savez(npz_path, **{k: v.astype(np.float16) for k, v in arrays.items()})
    size = os.path.getsize(npz_path)
    assert size < STUDENT_MAX_BYTES, f"{variant}：student.npz {size} 字节，超过 {STUDENT_MAX_BYTES}"
    with open(os.path.join(directory, "vocab.json"), "w", encoding="utf-8") as f:
        json.dump({"chars": VOCAB, "pad": 0, "unk": 1}, f, ensure_ascii=False)
    config = {
        "format_version": 2, "variant": variant, "architecture": architecture_spec(variant),
        "variant_fingerprint": VARIANT_FINGERPRINTS[variant], "teacher_fingerprint": CONFIG_FINGERPRINT,
        "targets_fingerprint": TARGETS_FINGERPRINT,
        "preprocess": __PREPROCESS__,
        "max_len": STUDENT["max_len"], "head_chars": STUDENT["head_chars"], "min_len": MIN_CHARS,
        "truncation": __TRUNCATION__,
        "heads": [{"name": name, "kind": kind, "offset": HEAD_SLICES[name].start,
                   "size": HEAD_SLICES[name].stop - HEAD_SLICES[name].start, "labels": labels,
                   "activation": {"class": "softmax(z / temperature)", "tanh": "tanh", "sigmoid": "sigmoid", "bce": "sigmoid"}[kind]}
                  for name, kind, labels in HEADS],
        "temperatures": cal["temperatures"],
        "risk": {"threshold_ge2": cal["threshold_ge2"], "threshold_l3": cal["threshold_l3"],
                 "rule": "level = argmax P；P(L2)+P(L3) ≥ threshold_ge2 时至少 L2；P(L3) ≥ threshold_l3 时为 L3",
                 "threshold_l3_used_only_with_model_plan_evidence": True,
                 "target_recall_ge2": cal["target_recall_ge2"], "target_recall_l3": cal["target_recall_l3"]},
        "arrays": {k: list(v.shape) for k, v in arrays.items()}, "npz_bytes": size,
        "training_options": {"loss_balance": LOSS_BALANCE, "kd_source": KD_SOURCE, "kd_teachers": len(kd_teachers),
                             "hard_negative_weight": HARD_NEGATIVE_WEIGHT, "train": train_hparams(variant)},
        **(extra or {}),
    }
    with open(os.path.join(directory, "student_config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return size


def parity_check(model, np_model, temperatures):
    cpu_model = copy.deepcopy(model).cpu().eval()
    torch_out = outputs_from_raw(student_raw(cpu_model, PARITY_SET, device=torch.device("cpu")), temperatures)
    with torch.no_grad():
        for p in cpu_model.parameters():
            p.copy_(p.half().float())
    quant_out = outputs_from_raw(student_raw(cpu_model, PARITY_SET, device=torch.device("cpu")), temperatures)
    np_preds = [np_model.predict(t) for t in PARITY_SET]
    per_head, impl = {}, {}
    for name, _, _ in HEADS:
        values = np.array([p[name] for p in np_preds])
        per_head[name] = float(np.abs(values - torch_out[name]).max())
        impl[name] = float(np.abs(values - quant_out[name]).max())
    return {"texts": len(PARITY_SET), "max_abs_diff": max(per_head.values()), "per_head": per_head,
            "implementation_only": max(impl.values()), "tolerance": PARITY_TOL}


def latency_check(np_model):
    with single_thread():
        for t in LATENCY_SET[:20]:
            np_model.predict(t)
        timings = []
        for i in range(LATENCY_RUNS):
            started = time.perf_counter()
            np_model.predict(LATENCY_SET[i % len(LATENCY_SET)])
            timings.append((time.perf_counter() - started) * 1000)
        full = []
        for _ in range(FULL_LENGTH_RUNS):
            started = time.perf_counter()
            np_model.predict(FULL_LENGTH_TEXT)
            full.append((time.perf_counter() - started) * 1000)
    return {"runs": LATENCY_RUNS, "p50_ms": float(np.percentile(timings, 50)), "p99_ms": float(np.percentile(timings, 99)),
            "max_ms": float(np.max(timings)), "full_length_p50_ms": float(np.percentile(full, 50)),
            "full_length_p99_ms": float(np.percentile(full, 99)), "target_p99_ms": LATENCY_TARGET_MS,
            "cpu": platform.processor() or platform.machine(), "cpu_count": os.cpu_count()}


def dev_variants(s_level):
    ideal, rule = dev["level"].to_numpy(), dev["rule_level"].to_numpy()
    combined = combined_levels(rule, s_level)
    result = {"规则 + 学生（现行仲裁）": summarize(ideal, combined), "学生单独": summarize(ideal, s_level),
              "规则 + 学生（L3 开关打开，仅参考）": summarize(ideal, combined_levels(rule, s_level, l3_switch=True))}
    for name, levels in (("规则 + 学生（现行仲裁）", combined), ("学生单独", s_level)):
        k, n = int(((ideal == 1) & (levels >= 2)).sum()), int((ideal == 1).sum())
        result[name]["L1 判为 ≥L2"] = {"hit": k, "n": n, "ci95": wilson(k, n)}
    return result, combined


RULES_ON_DEV = summarize(dev["level"].to_numpy(), dev["rule_level"].to_numpy())
RESULTS = {}
for variant, model in MODELS.items():
    print(f"\n==== {variant} ====")
    holdout_raw = student_raw(model, student_holdout["text"])
    cals = {target: calibrate(holdout_raw, student_holdout, target) for target in TARGET_RECALLS}
    local_dir = os.path.join(LOCAL_EXPORT_DIR, variant)
    size = export_variant(model, variant, cals[TARGET_RECALLS[0]], local_dir)
    np_model = NumpyArchStudent(local_dir)
    parity = parity_check(model, np_model, cals[TARGET_RECALLS[0]]["temperatures"])
    print(f"一致性（{parity['texts']} 条）：最大绝对差 {parity['max_abs_diff']:.2e}（容差 {PARITY_TOL}）；只算实现差异 {parity['implementation_only']:.2e}")
    assert parity["implementation_only"] <= PARITY_IMPL_TOL, f"{variant} 的 NumPy 实现与 PyTorch 不一致：{parity['implementation_only']:.2e}"
    latency = latency_check(np_model)
    print(f"单线程时延：P50 {latency['p50_ms']:.2f} ms，P99 {latency['p99_ms']:.2f} ms；满长 {STUDENT['max_len']} 字 P99 {latency['full_length_p99_ms']:.2f} ms")
    dev_raw = np.stack([np_model.raw(t) for t in dev["text"]]).astype(np.float32)
    per_target = {}
    for target, cal in cals.items():
        hold_out = outputs_from_raw(holdout_raw, cal["temperatures"])
        dev_out = outputs_from_raw(dev_raw, cal["temperatures"])
        s_level = model_levels(dev_out["risk"], cal)
        dev_result, combined = dev_variants(s_level)
        slot_lines, slot_json = slot_false_alarms(f"{variant} @ {target:.2f} 留出集", student_holdout, hold_out["risk"], cal)
        per_target[target] = {
            "calibration": cal,
            "holdout": risk_metrics(student_holdout, hold_out["risk"], cal),
            "holdout_slots": slot_json, "holdout_slot_lines": slot_lines,
            "dev": dev_result,
            "dev_rows": dev[["id", "text", "level", "rule_level"]].assign(
                student_p_ge2=(dev_out["risk"][:, 2] + dev_out["risk"][:, 3]).round(4), student_level=s_level,
                combined_level=combined),
        }
    head_lines, head_json = metrics_report(f"{variant}：留出集（目标 {TARGET_RECALLS[0]:.2f}）", student_holdout,
                                           outputs_from_raw(holdout_raw, cals[TARGET_RECALLS[0]]["temperatures"]),
                                           cals[TARGET_RECALLS[0]], pool_groups(student_holdout))
    RESULTS[variant] = {"params": VARIANT_SIZES[variant]["params"], "npz_bytes": size, "parity": parity,
                        "latency": latency, "per_target": per_target, "holdout_heads": head_json,
                        "holdout_head_lines": head_lines, "fingerprint": VARIANT_FINGERPRINTS[variant]}
""".replace("__PREPROCESS__", PREPROCESS_TEXT).replace("__TRUNCATION__", TRUNCATION_TEXT))

md(r"""
## 11. 对比与选择（按开头写定的规则）
""")

code(r"""
def pct(entry):
    return entry["hit"] / entry["n"] if entry["n"] else float("nan")


def cell(entry):
    return f"{entry['hit']}/{entry['n']}（{pct(entry):.0%}）" if entry["n"] else "—"


CANDIDATES = []
for variant, r in RESULTS.items():
    for target, t in r["per_target"].items():
        dev_c = t["dev"]["规则 + 学生（现行仲裁）"]
        reasons = []
        if r["npz_bytes"] >= STUDENT_MAX_BYTES:
            reasons.append("超过 4 MB")
        if r["parity"]["max_abs_diff"] > PARITY_TOL:
            reasons.append(f"一致性 {r['parity']['max_abs_diff']:.1e} > {PARITY_TOL}")
        if r["latency"]["p99_ms"] > LATENCY_TARGET_MS:
            reasons.append(f"P99 {r['latency']['p99_ms']:.1f} ms > {LATENCY_TARGET_MS:.0f}")
        if not pct(dev_c["L0 误报为 ≥L2"]) <= SELECT_MAX_DEV_L0_FA:
            reasons.append(f"开发集 L0 误报 {pct(dev_c['L0 误报为 ≥L2']):.1%} > {SELECT_MAX_DEV_L0_FA:.0%}")
        if not t["holdout"]["L0 误报为 ≥L2"]["rate"] <= SELECT_MAX_HOLDOUT_L0_FA:
            reasons.append(f"留出集 L0 误报 {t['holdout']['L0 误报为 ≥L2']['rate']:.1%} > {SELECT_MAX_HOLDOUT_L0_FA:.0%}")
        CANDIDATES.append({"variant": variant, "target": target, "eligible": not reasons, "reasons": reasons,
                           "dev_recall_hits": dev_c["L2+L3 判为 ≥L2"]["hit"], "npz_bytes": r["npz_bytes"],
                           "p99_ms": r["latency"]["p99_ms"]})
eligible = [c for c in CANDIDATES if c["eligible"]]
# 选择规则：开发集 L2+L3 召回条数最多；平局取 student.npz 更小，再平取 P99 更低
WINNER = min(eligible, key=lambda c: (-c["dev_recall_hits"], c["npz_bytes"], c["p99_ms"])) if eligible else None

lines = ["# 学生结构对比（步骤 C5）", "",
         f"教师 `{CONFIG_FINGERPRINT}`，蒸馏目标 `{TARGETS_FINGERPRINT}`（{len(kd_teachers)} 个教师），学生训练 {len(student_train)} 条、"
         f"留出 {len(student_holdout)} 条、开发集 {len(dev)} 条。独立评估集（{FRESH_ROWS} 条）不在本 notebook 评分。"
         "开发集各列为点估计；留出集各列带 Wilson 95% 区间。", "",
         "## 选择规则（运行前写定）", "",
         f"前提：student.npz < 4 MB，NumPy 一致性 ≤ {PARITY_TOL}，单线程 P99 ≤ {LATENCY_TARGET_MS:.0f} ms。"
         f"约束：开发集 L0 误报为 ≥L2（规则 + 学生，现行仲裁）≤ {SELECT_MAX_DEV_L0_FA:.0%}，留出集 L0 误报为 ≥L2（学生单独）≤ {SELECT_MAX_HOLDOUT_L0_FA:.0%}。"
         "目标：开发集 L2+L3 判为 ≥L2（规则 + 学生，现行仲裁）条数最多；平局取更小的 student.npz，再平取更低的 P99。", "",
         "## 结构、大小、一致性与时延", "",
         "| 变体 | 参数 | student.npz | NumPy 一致性 | 只算实现 | P50 | P99 | 满长 P99 |",
         "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
for variant, r in RESULTS.items():
    lat = r["latency"]
    lines.append(f"| {variant} | {r['params']:,} | {r['npz_bytes'] / 1024:.0f} KB | {r['parity']['max_abs_diff']:.1e} | "
                 f"{r['parity']['implementation_only']:.1e} | {lat['p50_ms']:.2f} ms | {lat['p99_ms']:.2f} ms | {lat['full_length_p99_ms']:.2f} ms |")
lines += ["", f"时延为单线程、{RESULTS[next(iter(RESULTS))]['latency']['cpu']}（{os.cpu_count()} 核机器）上的 NumPy 单条推理。", "",
          "## 各变体 × 召回目标", "",
          f"规则单独（现状）在开发集上：L2+L3 判为 ≥L2 {cell(RULES_ON_DEV['L2+L3 判为 ≥L2'])}，L3 判为 L3 {cell(RULES_ON_DEV['L3 判为 L3'])}，"
          f"L1 判为 L1 {cell(RULES_ON_DEV['L1 判为 L1'])}，L0 误报为 ≥L2 {cell(RULES_ON_DEV['L0 误报为 ≥L2'])}。", "",
          "“合并” = 规则 + 学生（现行仲裁）；“学生” = 学生单独（阈值后）。", "",
          "| 变体 | 目标 | ge2 阈值 | 留出 L2+L3 ≥L2 | 留出 L0 → ≥L2 | 开发 合并 L2+L3 ≥L2 | 开发 合并 L3 → ≥L2 | 开发 合并 L3 → L3 | "
          "开发 合并 L0 → ≥L2 | 开发 合并 L1 → L1 | 开发 合并 L1 → ≥L2 | 开发 学生 L2+L3 ≥L2 | 开发 学生 L3 → L3 | 参选 |",
          "| :--- | ---: | ---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |"]
for c in CANDIDATES:
    t = RESULTS[c["variant"]]["per_target"][c["target"]]
    dc, ds = t["dev"]["规则 + 学生（现行仲裁）"], t["dev"]["学生单独"]
    mark = "**胜出**" if c is WINNER else ("是" if c["eligible"] else "否：" + "；".join(c["reasons"]))
    lines.append(f"| {c['variant']} | {c['target']:.2f} | {t['calibration']['threshold_ge2']:.4f} | "
                 f"{fmt_rate(t['holdout']['L2+L3 判为 ≥L2'])} | {fmt_rate(t['holdout']['L0 误报为 ≥L2'])} | "
                 f"{cell(dc['L2+L3 判为 ≥L2'])} | {cell(dc['L3 判为 ≥L2（弹热线卡）'])} | {cell(dc['L3 判为 L3'])} | "
                 f"{cell(dc['L0 误报为 ≥L2'])} | {cell(dc['L1 判为 L1'])} | {cell(dc['L1 判为 ≥L2'])} | "
                 f"{cell(ds['L2+L3 判为 ≥L2'])} | {cell(ds['L3 判为 L3'])} | {mark} |")

# 按槽位的留出集 L0 误报（阈值后），各变体 × 目标并排
columns = [(c["variant"], c["target"]) for c in CANDIDATES]
slot_keys_all = sorted({k for v, t in columns for k in RESULTS[v]["per_target"][t]["holdout_slots"]},
                       key=lambda k: (k.startswith(("难负例", "其余")), k))
lines += ["", "## 留出集按槽位的 L0 误报为 ≥L2（阈值后；★ = 难负例槽位）", "",
          "| 槽位 | " + " | ".join(f"{v} @ {t:.2f}" for v, t in columns) + " |",
          "| :--- | " + " | ".join(":---:" for _ in columns) + " |"]
for key in slot_keys_all:
    cells = []
    for v, t in columns:
        entry = RESULTS[v]["per_target"][t]["holdout_slots"].get(key)
        cells.append(fmt_rate(entry["after_threshold"]) if entry else "—")
    star = " ★" if key in HARD_NEGATIVE_KEYS else ""
    lines.append(f"| {key}{star} | " + " | ".join(cells) + " |")

if WINNER is None:
    lines += ["", "## 结论", "", "**没有候选同时满足两条误报约束，不导出任何模型。**"]
else:
    lines += ["", "## 结论", "",
              f"按规则胜出：**{WINNER['variant']}**，召回目标 {WINNER['target']:.2f}（开发集 L2+L3 判为 ≥L2 {WINNER['dev_recall_hits']} 条）。"]
    base = [c for c in CANDIDATES if c["variant"] == "cnn_wide" and c["target"] == WINNER["target"]][0]
    lines.append(f"同一召回目标下基线 cnn_wide 为 {base['dev_recall_hits']} 条。")
    winner_rows = RESULTS[WINNER["variant"]]["per_target"][WINNER["target"]]["dev_rows"]
    misses = winner_rows[(winner_rows["level"] >= 2) & (winner_rows["combined_level"] < 2)]
    lines += ["", f"### 胜出者在开发集上仍然漏判（应为 ≥L2，合并 < L2）：{len(misses)} 条", ""]
    lines += [f"- {r.id}（应为 {LEVEL_NAMES[r.level]}，规则 {LEVEL_NAMES[r.rule_level]}，学生 {LEVEL_NAMES[r.student_level]}，"
              f"P(L2)+P(L3)={r.student_p_ge2:.2f}）{r.text}" for r in misses.itertuples()]
lines += ["", "## 各变体的留出集明细（目标 0.95 的各头指标；各目标的按槽位表）", ""]
for variant, r in RESULTS.items():
    lines += r["holdout_head_lines"] + [""]
    for target, t in r["per_target"].items():
        lines += t["holdout_slot_lines"] + [""]

REPORT = {"teacher_fingerprint": CONFIG_FINGERPRINT, "targets_fingerprint": TARGETS_FINGERPRINT,
          "student_texts_hash": STUDENT_TEXTS_HASH, "dev_rows": len(dev), "fresh_rows_not_scored": FRESH_ROWS,
          "selection_rule": {"max_dev_l0_false_alarm": SELECT_MAX_DEV_L0_FA, "max_holdout_l0_false_alarm": SELECT_MAX_HOLDOUT_L0_FA,
                             "parity_tolerance": PARITY_TOL, "latency_p99_ms": LATENCY_TARGET_MS, "max_bytes": STUDENT_MAX_BYTES,
                             "objective": "dev L2+L3 → ≥L2 hits (rules + student, current arbitration)",
                             "ties": ["smaller npz_bytes", "lower p99_ms"]},
          "rules_on_dev": RULES_ON_DEV, "candidates": CANDIDATES, "winner": WINNER,
          "variants": {v: {"architecture": architecture_spec(v), "params": r["params"], "npz_bytes": r["npz_bytes"],
                           "parity": r["parity"], "latency": r["latency"], "fingerprint": r["fingerprint"],
                           "holdout_heads": r["holdout_heads"],
                           "per_target": {str(target): {k: t[k] for k in ("calibration", "holdout", "holdout_slots", "dev")}
                                          for target, t in r["per_target"].items()}}
                       for v, r in RESULTS.items()}}
with open(PATHS["arch_report"] + ".md", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
with open(PATHS["arch_report"] + ".json", "w", encoding="utf-8") as f:
    json.dump(REPORT, f, ensure_ascii=False, indent=2)
print("\n".join(lines))
""")

md(r"""
## 12. 导出胜出者

只导出按规则胜出的那一个，用它自己的召回目标的温度与阈值；写到 `models/perception_student_arch/<变体>/`，不碰 `models/perception_student/`。导出后从 Drive 重新加载 NumPy 前向，确认与本地临时导出的输出相同。
""")

code(r"""
if WINNER is None:
    print("没有候选满足选择规则，不导出。")
else:
    variant, target = WINNER["variant"], WINNER["target"]
    out_dir = os.path.join(PATHS["arch_export_dir"], variant)
    assert os.path.realpath(out_dir) != os.path.realpath(PATHS["student_dir"])
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)  # 只清本实验自己的导出目录，避免留下上次别的文件
    chosen = RESULTS[variant]["per_target"][target]
    dev_c = chosen["dev"]["规则 + 学生（现行仲裁）"]
    size = export_variant(MODELS[variant], variant, chosen["calibration"], out_dir, extra={"selection": {
        "rule": REPORT["selection_rule"], "target_recall_ge2": target,
        "dev": {k: dev_c[k] for k in ("L2+L3 判为 ≥L2", "L3 判为 L3", "L0 误报为 ≥L2", "L1 判为 L1", "L1 判为 ≥L2")},
        "holdout_l0_false_alarm": chosen["holdout"]["L0 误报为 ≥L2"], "parity": RESULTS[variant]["parity"]["max_abs_diff"],
        "latency_p99_ms": RESULTS[variant]["latency"]["p99_ms"]}})
    reloaded = NumpyArchStudent(out_dir)
    local = NumpyArchStudent(os.path.join(LOCAL_EXPORT_DIR, variant))
    diff = max(float(np.abs(reloaded.raw(t) - local.raw(t)).max()) for t in PARITY_SET[:50])
    assert diff == 0.0, f"Drive 上的导出与本地临时导出不同：{diff}"
    print(f"已导出胜出者 {variant}（召回目标 {target:.2f}）到 {out_dir}：student.npz {size / 1024:.1f} KB")
    for name in ("student.npz", "vocab.json", "student_config.json"):
        path = os.path.join(out_dir, name)
        print(f"{os.path.getsize(path) / 1024:>10.1f} KB  {path}")
print(f"报告：{PATHS['arch_report']}.md / .json")
""")


def build() -> dict:
    cells = []
    for i, (kind, text) in enumerate(CELLS):
        lines = text.split("\n")
        source = [line + "\n" for line in lines[:-1]] + [lines[-1]]
        cell = {"cell_type": kind, "id": f"cell-{i:02d}", "metadata": {}, "source": source}
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": []},
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }


def main() -> None:
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(CELLS)} cells)")


if __name__ == "__main__":
    main()
