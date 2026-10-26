#!/usr/bin/env python3
"""Write training/colab/perception_teacher.ipynb, the Colab notebook for the perception model.

The notebook trains the 9-head teacher (hfl/chinese-roberta-wwm-ext) with 5-fold CV on the
project's own data only, calibrates it on the out-of-fold predictions, distils it into a
character-level CNN student, exports the student as float16 NumPy weights, checks a pure
NumPy forward pass against PyTorch, and evaluates each test set once.

Edit the cells here, never the .ipynb by hand, then regenerate:

    python training/colab/build_perception_teacher.py

Local smoke test (tiny random encoder, CPU): extract the code cells to a script and run it
with OLIVIA_SMOKE_TEST=1 and OLIVIA_PERCEPTION_ROOT=<dir holding raw/...>.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "perception_teacher.ipynb"

CELLS: list[tuple[str, str]] = []


def md(text: str) -> None:
    CELLS.append(("markdown", text.strip("\n")))


def code(text: str) -> None:
    CELLS.append(("code", text.strip("\n")))


# --------------------------------------------------------------------------------------
md(r"""
# 感知模型训练：八头教师模型 + 字符 CNN 学生模型（P6）

> **说明**：本 notebook 训练产品用的感知模型，只用项目自产数据（合成标注数据 + 项目安全用例），不使用 SOS-HL-1K 等没有商用许可的数据集。模型输出只是感知信号，不构成任何诊断。

## 做什么

1. **教师模型**：`hfl/chinese-roberta-wwm-ext` + 9 个输出头（SDD §3.1 的 8 个头，加上 `dominant_spectrum` 辅助头）。
   5 折交叉验证得到每条训练数据的 OOF（训练时没见过的）预测；在 OOF 上为每个分类头拟合一个温度，再按可行性实验 v2 的方法定风险阈值；最后用全部训练数据训练最终教师。
2. **学生模型**：字符级 CNN，用 0.5 × 硬标签 + 0.5 × 蒸馏训练（蒸馏目标默认取 6 个教师的平均，难负例在风险头上加权，见“C5 选项”）；训练池留出 15%（按风险等级分层）不参与学生训练，用来拟合学生自己的温度与阈值。
   导出为 float16 的 NumPy 静态权重（SDD §9，开发计划 P6 要求 < 4 MB），并验证纯 NumPy 前向与 PyTorch 一致、测单条推理时延（SDD §10.1：P99 ≤ 45 ms）。
3. **测试**：独立评估集（`fresh`）与 52 句探针（`probe`，模型结果已看过，只作参考）各只测一次；开发集（`dev`，可选）每次运行都重测，可用来比较选择，但不是最终结论。

## 头与损失

| 头 | 输出 | 损失 | 有标签的数据 |
| :--- | :--- | :--- | :--- |
| `valence` | tanh，[-1, 1] | MSE | 合成数据 |
| `emotion` | 16 类 | 交叉熵 | 合成数据 |
| `arousal` | sigmoid，[0, 1] | MSE | 合成数据 |
| `intent` | 6 类 | 交叉熵 | 合成数据 |
| `risk` | L0–L3 | 带类别权重的交叉熵（权重为类别频率倒数的平方根） | 合成数据 + 项目用例 |
| `crisis_confidence` | sigmoid，[0, 1] | 以标注值为软标签的 BCE；risk ≥ L2 的行乘 γ_pos = 15（SDD §3.1） | 合成数据 |
| `stance` | 5 类 | 交叉熵 | 合成数据 |
| `readiness` | sigmoid，[0, 1] | MSE | 合成数据 |
| `dominant_spectrum` | 12 类（`01`–`11`、`none`） | 交叉熵 | 合成数据 |

- 每行只对它有标签的头计算损失：项目用例只有风险等级，其余头对这些行屏蔽。
- 教师各头的权重 λ 由 `LOSS_BALANCE` 决定：`"gradnorm"`（默认，SDD §3.1 的 GradNorm 动态平衡，见下节）或 `"equal"`（都为 1，与第四轮相同）。学生模型各头 λ 始终为 1。

## C5 选项（步骤 C5，2026-10-24）

目标：“诉苦 + 要方法”等重而不危的句子不再被学生抬到 L2（红队非危机句进危机流程 ≤ 5，危机补漏不降）。每项都由配置区的一个常量开关，默认值即正式运行的取值；全部关掉（`"equal"`、`"base"`、`"final"`、`1.0`）就回到第四轮的做法。

| 常量 | 默认 | 含义 |
| :--- | :--- | :--- |
| `LOSS_BALANCE` | `"gradnorm"` | 教师 9 个头的损失平衡。GradNorm（Chen et al. 2018）：每步在**最后一个共享层**（编码器最后一层 FFN 输出的 `dense` 权重）上量出各头加权损失的梯度范数 G_i，让 G_i 向“平均范数 ×（该头相对训练进度）^α”靠拢，用单独的 Adam 更新各头权重，更新后截断到下限并重新归一化使总和 = 头数 9。`"equal"`：各头 λ = 1，代码路径与第四轮相同，结果可复现。 |
| `GRADNORM_ALPHA` | `1.5` | 恢复力 α：越大，越强地把训练进度落后（损失下降慢）的头拉回来；α = 0 时只让各头梯度范数相等。论文多数任务取 0.5–2.0，NYUv2 用 1.5。 |
| `GRADNORM_LR` | `0.025` | 头权重自己的 Adam 学习率（论文取值）。 |
| `GRADNORM_MIN_WEIGHT` | `0.05` | 每步更新后的权重下限，防止某个头被完全关掉。 |
| `STUDENT_WIDTH` | `"wide"` | 学生宽度：`"wide"` = 每种卷积核 160 个、共享层 192 维；`"base"` = 96 / 128（第四轮）。训练前按字表大小算出 `student.npz` 的字节数并断言 < 4 MB；产品端按数组形状加载，不需要改代码。 |
| `KD_SOURCE` | `"ensemble"` | 蒸馏目标：`"ensemble"` = 5 个折教师 + 最终教师各自的软目标取平均（分类头平均概率，连续头平均输出值；各折教师训练完立即对学生训练文本做预测并存进 `fold_*.npz`，不另存折模型）；`"final"` = 只用最终教师（第四轮）。 |
| `HARD_NEGATIVE_WEIGHT` | `2.0` | 学生**风险头硬标签损失**中，难负例行乘的权重；1.0 即关闭。难负例 = 轮次（取自 `source`）与槽位（顶层 `slot`）在 `HARD_NEGATIVE_SLOTS` 里、真实等级为 L0 的合成数据行（第四、六、七、八、九轮的全部 L0 槽位：问药、问诊断、要练习、红线话题、日常反刍、重度诉苦要方法、主动说病史要练习、丧亲与受虐倾诉、诉苦夹问药、口癖与自嘲、危机后报平安、只想被听、日常短句、“应该”式自责、日常的计划/准备/告别/托付、否认与澄清、转述他人的离开、带时间的日常决定、想念类口癖）。只加在硬标签上、不加在蒸馏项上，免得放大教师自己的误报。 |

另外两处改动不是开关：

- **按槽位的误报率**：教师 OOF 报告与学生留出集报告各多一张表，按合成数据的“轮次:配额槽位”（项目用例按类别）列出真实 L0 行被判为 ≥L2 的比例，“阈值前”只取最大概率等级，“阈值后”再加上 ge2 / L3 阈值（产品的判定）。难负例槽位标 ★。
- **排除集**：`olivia_cases.csv` 中 `role=exclude` 的行（红队全部用户输入，及导出时 `--exclude-csv` 给的文件）只用于从训练池剔除近似重复，从不训练、也不评估。

## 风险等级怎么从概率得到

- 取 `risk` 头概率最大的等级；`P(L2)+P(L3)` 过 **ge2 阈值**时至少为 L2（教师的阈值定在 OOF 上 L2+L3 召回 98%，学生的定在留出集上召回 95%）；`P(L3)` 过 **L3 阈值**时为 L3（OOF 上 L3 召回 95%）。
- 与规则合并按 `crisis.py` 现行仲裁：规则 Stage 1 的 L3 保持；否则取规则与模型的较高者，最高 L2。
  所以 L3 阈值只有在产品打开 `model_plan_evidence` 开关后才起作用；表里“L3 开关打开”一栏只作参考，用来判断能否打开开关。

## 数据

| 文件（放在 `DRIVE_ROOT/raw/` 下） | 来源 | 用途 |
| :--- | :--- | :--- |
| `synthetic/round1.jsonl` | `training/data_gen/validate_batches.py` 合并后的合成数据（`label_schema.json` 的字段 + `source` = `synthetic:<批次>`，第三、四、六轮另有顶层 `slot`） | 全部进训练池，9 个头都有标签；`slot`（连同 `source` 里的轮次）用于按槽位的报告与难负例加权；没有 `slot` 的行（第一、二轮）照常训练，只是槽位为空 |
| `olivia/olivia_cases.csv` | 本地运行 `training/colab/export_olivia_data.py` 生成 | `role=train`：进训练池，只有风险标签；`role=probe`：52 句探针（已看过）；`role=dev`：开发集（`--dev-eval`，可反复看、用于选择）；`role=fresh`：独立评估集（最终测试）；`role=exclude`：红队输入等，只用于泄露剔除。probe / dev / fresh / exclude 都参与泄露剔除 |

## 运行

1. 本地仓库根目录：
   - 合并合成数据：`python training/data_gen/validate_batches.py <批次 JSONL 所在目录> --out round1.jsonl --test-csv build/colab_data/olivia_cases.csv --test-csv <独立评估集.csv>`（用法见该脚本说明）；
   - 按标注规范 v0.2 处理第三、四轮：`python training/data_gen/relabel_v02.py <合并文件> --out round1.jsonl [--include-mixed 4:L0_med_self_adjust ...]`（问药问诊断三个槽位都混有决定与知识问题，默认不改，只报告；整槽改须明确指定）；
   - 导出用例：`.venv/bin/python training/colab/export_olivia_data.py [--dev-eval build/eval/interim_fresh.csv] --fresh-eval <独立评估集.csv> --exclude-csv build/eval/redteam_texts.csv`（红队 `tests/redteam/cases.yaml` 与多轮场景 `tests/redteam/multiturn.yaml` 的全部用户输入总会作为 `exclude` 行导出）；
   - 上传到 Drive：`round1.jsonl` → `OLIVIA_perception/raw/synthetic/`，`olivia_cases.csv` → `OLIVIA_perception/raw/olivia/`。
2. Colab：运行时类型选 GPU，“运行时 → 全部运行”。教师 5 折 + 最终模型是主要耗时（数据约 4,000 条时 T4 上约 1 小时），学生模型几分钟。
3. 断开后重新“全部运行”是安全的：已完成的折、最终教师、学生模型在配置与数据未变时直接复用；每个测试集只测一次（除非 `FORCE_RETEST = True`）。

## 产出（`DRIVE_ROOT/` 下）

| 路径 | 内容 |
| :--- | :--- |
| `models/perception_teacher/model.pt`、`train_config.json` | 最终教师模型与配置 |
| `models/cv_folds/fold_*.npz` | 各折对留出部分的原始输出；GradNorm 每轮末的头权重；`KD_SOURCE = "ensemble"` 时还有该折教师对学生训练文本的原始输出 |
| `configs/teacher_calibration.json` | 教师的温度、阈值与 OOF 指标 |
| `reports/oof_predictions.csv`、`teacher_cv_report.md` / `.json` | 每条训练数据的 OOF 预测；按头的交叉验证报告、按槽位的误报率、GradNorm 头权重 |
| `models/perception_student/student.npz`、`vocab.json`、`student_config.json` | **产品用的学生模型**：float16 权重、字表、头顺序 / 标签 / 温度 / 阈值 / 长度 |
| `models/student_checkpoint/student.pt` | 学生模型训练检查点（用于续跑，不进产品） |
| `cache/teacher_targets.npz` | 最终教师对学生训练文本的输出（蒸馏目标） |
| `reports/student_report.md` / `.json` | 学生在留出集上的指标（含按槽位的误报率）、权重大小、NumPy 一致性与时延 |
| `reports/{probe,dev,fresh}_predictions.csv`、`_summary.md`、`_summary.json` | 各测试集逐条结果与汇总（dev 每次运行覆盖） |

## 不要做的事

- 不要按探针或独立评估集的结果回头改阈值、温度或超参再测。要比较、选择，用开发集（`dev`）。
- OOF 指标来自与训练数据同源的句子，会偏乐观；它只用来定温度和阈值，结论以独立评估集为准。
""")

md("## 1. 环境")

code(r"""
# 依赖：直接用 Colab 预装的 torch / transformers / scikit-learn / pandas（不固定版本，实际版本在下一单元打印）
try:
    import google.colab  # noqa: F401
    IN_COLAB = True
except ImportError:
    IN_COLAB = False
""")

code(r"""
# 环境检查、随机种子与挂载 Drive
import contextlib, copy, csv, hashlib, html, json, math, os, platform, random, re, time
from collections import Counter

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
import transformers
from torch import nn

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"torch {torch.__version__} | transformers {transformers.__version__} | numpy {np.__version__} | device {DEVICE}")
if DEVICE.type == "cuda":
    print("GPU:", torch.cuda.get_device_name(0))
elif IN_COLAB:
    print("提示：当前没有 GPU。请在“运行时 → 更改运行时类型”中选择 GPU 后重新运行。")


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


if IN_COLAB:
    from google.colab import drive
    drive.mount("/content/drive", timeout_ms=900_000)  # 15 分钟：授权需要人工完成，默认 2 分钟常来不及
""")

md("## 2. 配置区（所有可变项集中于此）")

code(r"""
SMOKE_TEST = os.environ.get("OLIVIA_SMOKE_TEST") == "1"  # 本地 CPU 冒烟测试用；Colab 上保持关闭
DRIVE_ROOT = os.environ.get("OLIVIA_PERCEPTION_ROOT", "/content/drive/MyDrive/OLIVIA_perception")

# ---- 教师模型 ----
ENCODER = "hfl/chinese-roberta-wwm-ext"
SEED = 42
MAX_LEN = 160         # 含 [CLS]/[SEP] 的 token 上限
HEAD_TOKENS = 48      # 超长时保留开头这么多 token，其余从结尾取（与 SDD §10.1 双端保全同理）
BATCH_SIZE = 32
EPOCHS = 4            # 固定轮数：各折与最终模型相同，不按验证集早停
LR = 3e-5
WEIGHT_DECAY = 0.01
WARMUP_RATIO = 0.1
CV_FOLDS = 5
GAMMA_POS = 15.0      # SDD §3.1：crisis_confidence 头对 risk ≥ L2 的行加权

TARGET_RECALL_GE2 = 0.98  # OOF 上 L2+L3 判为 ≥L2 的召回目标（G-2 危机召回 ≥ 98%）
TARGET_RECALL_L3 = 0.95   # OOF 上 L3 判为 L3 的召回目标（只在产品打开 model_plan_evidence 时使用）
# 学生模型在留出集上的召回目标。学生比教师弱，按 98% 定出的门槛只有约 0.08，日常短句和问药也会被升到 L2；
# 改为 95%（你的决定，2026-10-23），规则底线不变。
STUDENT_TARGET_RECALL_GE2 = 0.95
FP_CATEGORIES = ("HYPERBOLE", "BENIGN", "NEGATION_PURE", "NEGATION_WITH_MEANS", "DOUBLE_NEGATION_OR_METHOD")

# ---- 学生模型（字符级 CNN） ----
STUDENT = {
    "min_char_freq": 2,        # 字表：训练池中出现 ≥ 2 次的字，另加 PAD、UNK
    "embed_dim": 64,
    "kernels": [2, 3, 4, 5],
    "filters": 96,             # 每种卷积核的个数
    "hidden": 128,             # 共享表征维度（SDD §3.1 的 h ∈ R^128）
    "dropout": 0.2,
    "max_len": MAX_LEN,        # 字符数上限，超长时双端保全
    "head_chars": HEAD_TOKENS,
    "holdout_fraction": 0.15,  # 按风险等级分层留出，用来定学生的温度与阈值
    "aug_copies": 2,           # 第 1 份随机删去 10% 的字，第 2 份交换约 10% 的相邻字对
    "aug_rate": 0.10,
    "kd_temperature": 2.0,
    "kd_alpha": 0.5,           # 损失 = (1 - α) × 硬标签 + α × 蒸馏
    "epochs": 15,
    "batch_size": 64,
    "lr": 2e-3,
    "weight_decay": 0.01,
    "warmup_ratio": 0.05,
}
STUDENT_MAX_BYTES = 4 * 1024 * 1024  # 开发计划 P6：NumPy 静态权重 < 4 MB

# ---- C5 选项（每项单独开关；全部取第二个值即回到第四轮的做法，含义见开头“C5 选项”） ----
LOSS_BALANCE = "gradnorm"     # 教师各头损失平衡："gradnorm" | "equal"
GRADNORM_ALPHA = 1.5          # GradNorm 恢复力 α（Chen et al. 2018；NYUv2 取 1.5）
GRADNORM_LR = 0.025           # 头权重的 Adam 学习率（论文取值）
GRADNORM_MIN_WEIGHT = 0.05    # 每步更新后的权重下限；之后重新归一化，使 9 个权重之和 = 9
STUDENT_WIDTH = "wide"        # 学生宽度："wide" | "base"（96 / 128，第四轮）
STUDENT_WIDE = {"filters": 160, "hidden": 192}
KD_SOURCE = "ensemble"        # 蒸馏目标："ensemble"（5 折教师 + 最终教师取平均）| "final"（只用最终教师）
HARD_NEGATIVE_WEIGHT = 2.0    # 学生风险头硬标签损失中难负例行的权重；1.0 = 关闭
HARD_NEGATIVE_SLOTS = {        # 难负例槽位 {轮次: 槽位}（轮次取自 source = synthetic:r<轮>b..；只取真实等级为 L0 的行）
    4: ("L0_med_self_adjust", "L0_diagnosis_question", "L0_technique_request", "L0_redflag_topic_request",
        "L0_everyday_rumination"),                                                # quota_round4.yaml 的全部 L0 槽位
    6: ("L0_heavy_vent_request", "L0_redflag_history_request", "L0_loss_abuse_family", "L0_med_diag_with_venting",
        "L0_hyperbole_dark_humor"),                                               # quota_round6.yaml 的全部 L0 槽位
    7: ("L0_safety_confirmation", "L0_listen_only_request", "L0_short_everyday_negative",
        "L0_should_self_talk"),                                                   # quota_round7.yaml 的全部 L0 槽位
    8: ("L0_benign_plan_time", "L0_benign_preparation_done", "L0_benign_farewell_ending",
        "L0_benign_arrangements"),                                                # quota_round8.yaml 的全部 L0 槽位
    9: ("L0_denial_clarify", "L0_reported_others", "L0_resolved_plans",
        "L0_idiom_miss_want"),                                                    # quota_round9.yaml 的全部 L0 槽位
}
HARD_NEGATIVE_KEYS = {f"r{r}:{slot}" for r, slots in HARD_NEGATIVE_SLOTS.items() for slot in slots}
assert LOSS_BALANCE in ("gradnorm", "equal") and STUDENT_WIDTH in ("wide", "base") and KD_SOURCE in ("ensemble", "final")
if STUDENT_WIDTH == "wide":
    STUDENT.update(STUDENT_WIDE)

PARITY_TEXTS = 200
PARITY_TOL = 2e-3                    # NumPy 与 PyTorch 学生的概率最大绝对差
LATENCY_RUNS = 1000
LATENCY_TARGET_MS = 45.0             # SDD §10.1：感知推断 P99 ≤ 45 ms（单核 CPU）

FORCE_RETRAIN = False
FORCE_RETEST = False

# ---- 标签（与 training/data_gen/label_schema.json 一致） ----
EMOTIONS = ["anxiety", "sadness", "anger", "shame", "guilt", "loneliness", "hopelessness", "grief",
            "fear", "panic", "overwhelm", "numbness", "envy", "disappointment", "confusion", "calm"]
INTENTS = ["VALIDATION", "EXPLORATION", "REFLECTION", "INFORMATION", "STABILIZATION", "REFERRAL"]
LEVEL_NAMES = ["L0", "L1", "L2", "L3"]
STANCES = ["PLACATING", "BLAMING", "SUPER_REASONABLE", "IRRELEVANT", "CONGRUENT"]
SPECTRA = [f"{i:02d}" for i in range(1, 12)] + ["none"]

# (头名, 类型, 标签)。类型：class = softmax 分类；tanh / sigmoid = MSE 回归；bce = 软标签 BCE
HEADS = [
    ("valence", "tanh", None),
    ("emotion", "class", EMOTIONS),
    ("arousal", "sigmoid", None),
    ("intent", "class", INTENTS),
    ("risk", "class", LEVEL_NAMES),
    ("crisis_confidence", "bce", None),
    ("stance", "class", STANCES),
    ("readiness", "sigmoid", None),
    ("dominant_spectrum", "class", SPECTRA),
]
HEAD_NAMES = [name for name, _, _ in HEADS]
HEAD_KIND = {name: kind for name, kind, _ in HEADS}
HEAD_LABELS = {name: labels for name, _, labels in HEADS}
CLASS_HEADS = [name for name, kind, _ in HEADS if kind == "class"]
HEAD_SLICES, _offset = {}, 0
for _name, _kind, _labels in HEADS:
    _size = len(_labels) if _kind == "class" else 1
    HEAD_SLICES[_name] = slice(_offset, _offset + _size)
    _offset += _size
OUT_DIM = _offset  # 9 个头的输出拼成一个向量，切片见 HEAD_SLICES
LOSS_WEIGHTS = {name: 1.0 for name in HEAD_NAMES}  # 固定的各头 λ：学生模型，以及 LOSS_BALANCE = "equal" 时的教师
LABEL_COLUMNS = [f"y_{name}" for name in HEAD_NAMES]

PROBE_SIZE = 52
TEST_SETS = {
    "probe": "52 句探针（模型结果已于 2026-10-22 看过，不再是独立测试，仅作参考）",
    "dev": "开发集（可反复查看、用于比较选择；不是最终结论）",
    "fresh": "独立评估集（不同作者编写）",
}
DEV_ROLE = "dev"  # 开发集每次运行都重测（不受“只测一次”限制）

PATHS = {
    "synthetic": os.path.join(DRIVE_ROOT, "raw", "synthetic", "round1.jsonl"),
    "cases_csv": os.path.join(DRIVE_ROOT, "raw", "olivia", "olivia_cases.csv"),
    "teacher_dir": os.path.join(DRIVE_ROOT, "models", "perception_teacher"),
    "fold_dir": os.path.join(DRIVE_ROOT, "models", "cv_folds"),
    "student_dir": os.path.join(DRIVE_ROOT, "models", "perception_student"),
    "student_ckpt_dir": os.path.join(DRIVE_ROOT, "models", "student_checkpoint"),
    "cache": os.path.join(DRIVE_ROOT, "cache"),
    "reports": os.path.join(DRIVE_ROOT, "reports"),
    "configs": os.path.join(DRIVE_ROOT, "configs"),
}
PATHS["teacher"] = os.path.join(PATHS["teacher_dir"], "model.pt")
PATHS["teacher_config"] = os.path.join(PATHS["teacher_dir"], "train_config.json")
PATHS["teacher_calibration"] = os.path.join(PATHS["configs"], "teacher_calibration.json")
PATHS["oof"] = os.path.join(PATHS["reports"], "oof_predictions.csv")
PATHS["cv_report"] = os.path.join(PATHS["reports"], "teacher_cv_report")
PATHS["teacher_targets"] = os.path.join(PATHS["cache"], "teacher_targets.npz")
PATHS["student_ckpt"] = os.path.join(PATHS["student_ckpt_dir"], "student.pt")
PATHS["student_npz"] = os.path.join(PATHS["student_dir"], "student.npz")
PATHS["student_vocab"] = os.path.join(PATHS["student_dir"], "vocab.json")
PATHS["student_config"] = os.path.join(PATHS["student_dir"], "student_config.json")
PATHS["student_report"] = os.path.join(PATHS["reports"], "student_report")

SMOKE_POOL_ROWS = 64
if SMOKE_TEST:  # 只验证流程：极小的编码器与学生、2 折、1 轮、64 条训练数据
    EPOCHS, BATCH_SIZE, MAX_LEN, HEAD_TOKENS, CV_FOLDS = 1, 8, 64, 16, 2
    wide = STUDENT_WIDTH == "wide"  # 冒烟测试里“加宽”只按比例放大极小的学生，验证流程
    STUDENT.update(embed_dim=16, filters=12 if wide else 8, hidden=24 if wide else 16, epochs=1, batch_size=16,
                   max_len=MAX_LEN, head_chars=HEAD_TOKENS)
    LATENCY_RUNS = 200

for key in ("teacher_dir", "fold_dir", "student_dir", "student_ckpt_dir", "cache", "reports", "configs"):
    os.makedirs(PATHS[key], exist_ok=True)
set_seed(SEED)
print("DRIVE_ROOT:", DRIVE_ROOT, "| SMOKE_TEST:", SMOKE_TEST, "| 输出维度:", OUT_DIM)
print(f"C5 选项：LOSS_BALANCE={LOSS_BALANCE}（α={GRADNORM_ALPHA}）| STUDENT_WIDTH={STUDENT_WIDTH}"
      f"（filters {STUDENT['filters']}，hidden {STUDENT['hidden']}）| KD_SOURCE={KD_SOURCE} | HARD_NEGATIVE_WEIGHT={HARD_NEGATIVE_WEIGHT}")
""")

md("## 3. 数据：读取、校验、泄露检查与分折")

code(r"""
def clean_text(text):
    text = html.unescape(str(text)).replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


EXCLUDE_ROLE = "exclude"  # olivia_cases.csv 中只用于泄露剔除的行（红队输入等）


def source_round(source):
    # synthetic:r4b02 → "r4"；第一轮 synthetic:b01 → "r1"；其余 → ""
    batch = str(source).removeprefix("synthetic:")
    match = re.match(r"r(\d+)b", batch)
    return f"r{match.group(1)}" if match else ("r1" if re.match(r"b\d+", batch) else "")


def slot_keys(frame):
    # 按槽位报告用的分组名：合成数据为“轮次:槽位”（没有槽位时为“轮次:无槽位”），项目用例取类别或来源
    return np.array([(f"{source_round(src)}:{s}" if s else f"{source_round(src) or '合成'}:无槽位") if g == "synthetic"
                     else f"用例:{c or src}"
                     for s, c, src, g in zip(frame["slot"], frame["category"], frame["source"], frame["group"])])


def hard_negative_mask(frame):
    # 难负例：轮次与槽位在 HARD_NEGATIVE_SLOTS 里、真实等级为 L0 的合成数据行
    return ((frame["group"] == "synthetic").to_numpy() & np.isin(slot_keys(frame), list(HARD_NEGATIVE_KEYS))
            & (frame["y_risk"] == 0).to_numpy())


def load_synthetic(path):
    # 每行一条 label_schema.json 记录，外加 source（合并脚本写入）与可选的顶层 slot；未合并的批次文件用 meta.batch / meta.slot 代替
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到 {path}：先在本地用 validate_batches.py 合并合成数据并上传到这里")
    rows = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            missing = [key for key in ("text", *HEAD_NAMES) if key not in record]
            if missing:
                raise ValueError(f"{path}:{line_no} 缺少字段 {missing}")
            meta = record.get("meta") or {}
            source = record.get("source") or "synthetic:" + str(meta.get("batch", "unknown"))
            row = {"id": f"syn_{line_no}", "text": clean_text(record["text"]), "role": "train",
                   "source": source, "group": "synthetic", "category": "", "slot": str(record.get("slot") or meta.get("slot") or ""),
                   "level": -1, "rule_level": -1}
            for name, kind, labels in HEADS:
                value = record[name]
                if kind == "class":
                    if value not in labels:
                        raise ValueError(f"{path}:{line_no} {name}={value!r} 不在标签集里")
                    row[f"y_{name}"] = labels.index(value)
                else:
                    value, low = float(value), (-1.0 if kind == "tanh" else 0.0)
                    if not low <= value <= 1.0:
                        raise ValueError(f"{path}:{line_no} {name}={value} 超出 [{low}, 1]")
                    row[f"y_{name}"] = value
            row["level"] = row["y_risk"]
            rows.append(row)
    if not rows:
        raise ValueError(f"{path} 是空文件")
    return pd.DataFrame(rows)


def load_cases(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到 {path}：先在本地运行 export_olivia_data.py 并上传到这里")
    df = pd.read_csv(path, dtype={"id": str, "text": str, "role": str, "source": str, "category": str},
                     keep_default_na=False)
    missing = {"id", "text", "level", "role", "source", "rule_level"} - set(df.columns)
    if missing:
        raise ValueError(f"olivia_cases.csv 缺少列：{sorted(missing)}（请用最新的 export_olivia_data.py 重新导出）")
    if "category" not in df.columns:
        df["category"] = ""
    if not df["role"].isin(["train", *TEST_SETS, EXCLUDE_ROLE]).all():
        raise ValueError("olivia_cases.csv 的 role 取值非法")
    # exclude 行（红队输入等）只用于泄露剔除：不训练、不评估，等级记为 -1
    excluded = df[df["role"] == EXCLUDE_ROLE]
    df = df[df["role"] != EXCLUDE_ROLE].copy()
    if not df["level"].isin([0, 1, 2, 3]).all():
        raise ValueError("olivia_cases.csv 的 level 取值非法")
    if (df["role"] == "probe").sum() != PROBE_SIZE:
        raise ValueError(f"探针应为 {PROBE_SIZE} 条，实际 {(df['role'] == 'probe').sum()} 条")
    df["text"] = df["text"].map(clean_text)
    df["group"] = "cases"
    df["slot"] = ""
    # 项目用例只有风险等级：其余头的标签记为缺失（分类头 -1，连续头 NaN），训练时屏蔽
    for name, kind, _ in HEADS:
        df[f"y_{name}"] = df["level"].astype(int) if name == "risk" else (-1 if kind == "class" else np.nan)
    return df, excluded["text"].map(clean_text)


def tidy(frame):
    frame = frame[["id", "text", "role", "source", "group", "category", "slot", "level", "rule_level",
                   *LABEL_COLUMNS]].copy()
    for name, kind, _ in HEADS:
        column = f"y_{name}"
        frame[column] = frame[column].fillna(-1).astype(int) if kind == "class" else frame[column].astype(float)
    frame[["level", "rule_level"]] = frame[["level", "rule_level"]].astype(int)
    return frame.reset_index(drop=True)


def bigrams(text):
    t = re.sub(r"\s+", "", text)
    return {t[i:i + 2] for i in range(len(t) - 1)} or {t}


def drop_test_leaks(frame, test_texts, threshold=0.8):
    # 训练池中与任何测试句相同或高度相似（字二元组 Jaccard ≥ 0.8）的句子一律剔除
    test_grams = [bigrams(t) for t in test_texts]

    def leaks(text):
        grams = bigrams(text)
        return any(len(grams & g) / len(grams | g) >= threshold for g in test_grams)
    leak = frame["text"].map(leaks)
    for _, row in frame[leak].iterrows():
        print(f"  剔除疑似泄露 [{row['source']}] {row['text'][:60]}")
    return frame[~leak]


def assign_folds(frame, folds, seed):
    # 按 数据来源（合成 / 用例）× 风险等级 分层，每层内打乱后轮流分到各折
    rng = np.random.default_rng(seed)
    fold = np.empty(len(frame), dtype=int)
    for _, idx in frame.groupby(["group", "y_risk"]).indices.items():
        idx = rng.permutation(idx)
        fold[idx] = np.arange(len(idx)) % folds
    return fold


synthetic = load_synthetic(PATHS["synthetic"])
cases, exclude_texts = load_cases(PATHS["cases_csv"])
tests = {role: tidy(cases[cases["role"] == role]) for role in TEST_SETS}
pool = pd.concat([synthetic, cases[cases["role"] == "train"]], ignore_index=True)
if SMOKE_TEST:
    pool = pd.concat([g.sample(min(len(g), SMOKE_POOL_ROWS // 2), random_state=SEED) for _, g in pool.groupby("group")])

print(f"泄露检查（测试集 {sum(len(t) for t in tests.values())} 条 + 排除集 {len(exclude_texts)} 条）：")
pool = tidy(drop_test_leaks(pool, pd.concat([*(t["text"] for t in tests.values()), exclude_texts])))
pool["fold"] = assign_folds(pool, CV_FOLDS, SEED)

print("\n训练池（来源 × 风险等级）：", pool.groupby(["group", "y_risk"]).size().to_dict())
syn_slots = pool.loc[pool["group"] == "synthetic", "slot"]
print(f"合成数据有槽位的行：{int((syn_slots != '').sum())}/{len(syn_slots)}；"
      f"难负例行（轮次与槽位在 HARD_NEGATIVE_SLOTS 且为 L0）：{int(hard_negative_mask(pool).sum())}")
print("各头有标签的行数：", {name: int((pool[f"y_{name}"] >= 0).sum() if HEAD_KIND[name] == "class"
                                    else pool[f"y_{name}"].notna().sum()) for name in HEAD_NAMES})
print("每折条数：", pool["fold"].value_counts().sort_index().to_dict())
for role, frame in tests.items():
    counts = frame["level"].map(dict(enumerate(LEVEL_NAMES))).value_counts().sort_index().to_dict()
    print(f"测试集 {role}：{len(frame)} 条 {counts}")
DATA_FINGERPRINT = hashlib.sha256(pool[["text", *LABEL_COLUMNS, "fold"]].to_csv(index=False).encode("utf-8")).hexdigest()[:16]
""")

md(r"""
### 3b. 学生训练集（在教师训练前确定）

- 训练池按风险等级分层留出 15%，学生训练不使用它们（也不使用它们的增强副本）；它们只用来拟合学生的温度与阈值。
- 学生训练集 = 其余 85% 的原句 + 每句 2 份增强副本（第 1 份随机删去 10% 的字，第 2 份交换约 10% 的相邻字对），增强副本沿用原句的标签与槽位。
- 放在教师训练之前，是因为 `KD_SOURCE = "ensemble"` 时每个折教师训练完就要对这些文本做预测（折模型不保存）。划分只取决于训练池与固定种子，与教师无关。
""")

code(r"""
def stratified_holdout(frame, fraction, seed):
    rng = np.random.default_rng(seed)
    held = np.zeros(len(frame), dtype=bool)
    for _, idx in frame.groupby("y_risk").indices.items():
        idx = rng.permutation(idx)
        held[idx[:int(round(fraction * len(idx)))]] = True
    return held


def char_dropout(text, rng, p):
    kept = "".join(ch for ch in text if rng.random() >= p)
    return kept or text


def adjacent_swap(text, rng, p):
    chars = list(text)
    if len(chars) < 2:
        return text
    for _ in range(max(1, int(round(p * len(chars))))):
        i = int(rng.integers(0, len(chars) - 1))
        chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


held_mask = stratified_holdout(pool, STUDENT["holdout_fraction"], SEED + 1)
student_holdout = pool[held_mask].reset_index(drop=True)
base = pool[~held_mask].reset_index(drop=True)
aug_rng = np.random.default_rng(SEED + 2)
copies = [base.assign(copy=0)]
for c in range(1, STUDENT["aug_copies"] + 1):
    op = char_dropout if c % 2 == 1 else adjacent_swap
    copies.append(base.assign(text=[op(t, aug_rng, STUDENT["aug_rate"]) for t in base["text"]], copy=c))
student_train = pd.concat(copies, ignore_index=True)
# 学生训练文本的指纹：各折教师对这些文本的预测（集成蒸馏目标）按它复用
STUDENT_TEXTS_HASH = hashlib.sha256("\n".join(student_train["text"]).encode("utf-8")).hexdigest()[:16]
print(f"学生训练集 {len(student_train)} 条（原句 {len(base)} × {1 + STUDENT['aug_copies']}），留出 {len(student_holdout)} 条；"
      f"其中难负例 {int(hard_negative_mask(student_train).sum())} 条（含增强副本）")
print("留出集风险等级：", student_holdout["y_risk"].map(dict(enumerate(LEVEL_NAMES))).value_counts().sort_index().to_dict())
""")

md(r"""
## 4. 共用部分：带屏蔽的多头损失、输出换算、校准与指标

- 损失只在有标签的行上计算（分类头标签为 -1、连续头为 NaN 的行跳过）；各头取平均后按 λ 相加（`"equal"` 与学生：λ = 1；`"gradnorm"`：λ 为 GradNorm 每步更新的权重，总损失里视为常数）。
- 学生风险头的难负例加权保持类别加权交叉熵的约简方式：Σ(类别权重 × 行权重 × nll) / Σ(类别权重 × 行权重)，行权重全为 1 时与原来相同。
- 按槽位的误报率只看真实 L0 的行；“阈值前”是最大概率等级，“阈值后”是产品实际的判定（加 ge2 / L3 阈值）。
- 温度只改变分类头概率的“自信程度”，不改变排序；阈值在温度校准后的概率上按召回目标确定。
- 按类别的误报率只在**真实等级为 L0** 的行上计算（v2 可行性实验把非 L0 行也算进了类别误报率，这里已改正）。
""")

code(r"""
from sklearn.metrics import f1_score, roc_auc_score


def risk_class_weights(frame):
    risk = frame.loc[frame["y_risk"] >= 0, "y_risk"].to_numpy()
    counts = np.bincount(risk, minlength=len(LEVEL_NAMES)).astype(float)
    weights = np.sqrt(counts.sum() / (len(LEVEL_NAMES) * np.maximum(counts, 1)))
    return torch.tensor(weights, dtype=torch.float, device=DEVICE)


def label_tensors(rows, device):
    return {name: torch.tensor(rows[f"y_{name}"].to_numpy(), device=device,
                               dtype=torch.long if kind == "class" else torch.float)
            for name, kind, _ in HEADS}


def value_activation(z, kind):
    return torch.tanh(z) if kind == "tanh" else torch.sigmoid(z)


def head_losses(raw, labels, risk_weight, risk_row_weight=None):
    # raw：(批大小, OUT_DIM) 原始输出；labels：每个头一列标签，缺失的行不计。返回 {头名: 该头的平均损失}，没有标签的头不出现
    # risk_row_weight：每行的风险头权重（难负例加权）；None 时与第四轮完全相同
    raw = raw.float()
    parts = {}
    for name, kind, _ in HEADS:
        z, y = raw[:, HEAD_SLICES[name]], labels[name]
        if kind == "class":
            has = y >= 0
            if not has.any():
                continue
            if name == "risk" and risk_row_weight is not None:
                # 与带类别权重的 mean 约简一致：Σ(w_类 × w_行 × nll) / Σ(w_类 × w_行)
                row = risk_row_weight[has]
                nll = F.cross_entropy(z[has], y[has], weight=risk_weight, reduction="none")
                part = (nll * row).sum() / (risk_weight[y[has]] * row).sum()
            else:
                part = F.cross_entropy(z[has], y[has], weight=risk_weight if name == "risk" else None)
        else:
            has = ~torch.isnan(y)
            if not has.any():
                continue
            z, y = z[has, 0], y[has]
            if kind == "bce":
                weight = 1.0 + (GAMMA_POS - 1.0) * (labels["risk"][has] >= 2).float()
                part = (weight * F.binary_cross_entropy_with_logits(z, y, reduction="none")).mean()
            else:
                part = F.mse_loss(value_activation(z, kind), y)
        parts[name] = part
    return parts


def supervised_loss(raw, labels, risk_weight, risk_row_weight=None):
    # 固定权重 LOSS_WEIGHTS 下的总损失（学生，及 LOSS_BALANCE = "equal" 时的教师）
    total = raw.new_zeros((), dtype=torch.float)
    for name, part in head_losses(raw, labels, risk_weight, risk_row_weight).items():
        total = total + LOSS_WEIGHTS[name] * part
    return total


class GradNorm:
    # GradNorm（Chen et al. 2018, ICML）：让各头在最后一个共享层上的加权梯度范数 G_i = w_i‖∇_W L_i‖
    # 向 mean(G) × r_i^α 靠拢，r_i = (L_i / L_i(0)) / 各头该比值的均值（训练进度落后的头 r_i > 1，权重被抬高）。
    # 头权重用单独的 Adam 更新；目标值视为常数；更新后截断到下限并重新归一化，使总和 = 头数。
    # 某批里没有标签的头不参与这一步（项目用例行只有风险标签）。
    def __init__(self, names, alpha=GRADNORM_ALPHA, lr=GRADNORM_LR, min_weight=GRADNORM_MIN_WEIGHT):
        self.names, self.alpha, self.min_weight = list(names), alpha, min_weight
        self.w = torch.ones(len(self.names), device=DEVICE, requires_grad=True)
        self.optimizer = torch.optim.Adam([self.w], lr=lr)
        self.initial = [None] * len(self.names)  # L_i(0)：该头第一次有标签那一步的损失
        self.skipped = 0

    def weights(self):
        return {name: round(float(v), 4) for name, v in zip(self.names, self.w.detach().cpu())}

    def total(self, parts):
        w = self.w.detach().clone()  # 复制：本步稍后会原地更新 self.w
        return sum(w[i] * parts[name] for i, name in enumerate(self.names) if name in parts)

    def step(self, parts, shared, scaler):
        active = [i for i, name in enumerate(self.names) if name in parts]
        if len(active) < 2:
            return
        scale = scaler.get_scale() if scaler.is_enabled() else 1.0  # float16 AMP：在放大后的损失上求梯度，防止下溢
        norms = torch.stack([torch.autograd.grad(parts[self.names[i]] * scale, shared, retain_graph=True)[0].float().norm()
                             for i in active]) / scale
        losses = torch.stack([parts[self.names[i]].detach().float() for i in active])
        if not (torch.isfinite(norms).all() and torch.isfinite(losses).all()):
            self.skipped += 1
            return
        for j, i in enumerate(active):
            if self.initial[i] is None:
                self.initial[i] = max(float(losses[j]), 1e-8)
        ratio = losses / torch.tensor([self.initial[i] for i in active], device=losses.device)
        progress = ratio / ratio.mean()
        g = self.w[active] * norms
        target = (g.mean() * progress ** self.alpha).detach()
        self.optimizer.zero_grad()
        (g - target).abs().sum().backward()
        self.optimizer.step()
        with torch.no_grad():
            self.w.clamp_(min=self.min_weight)
            self.w.mul_(len(self.names) / self.w.sum())


def softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


def outputs_from_raw(raw, temperatures):
    # 原始输出 → 每个头的概率（分类头，除以温度）或数值（连续头）
    out = {}
    for name, kind, _ in HEADS:
        z = raw[:, HEAD_SLICES[name]].astype(np.float64)
        if kind == "class":
            out[name] = softmax(z / temperatures.get(name, 1.0))
        else:
            out[name] = np.tanh(z[:, 0]) if kind == "tanh" else sigmoid(z[:, 0])
    return out


LOG_T_RANGE = (math.log(0.05), math.log(20.0))  # 温度限制在 [0.05, 20]，防止无信息的 logits 把温度推向无穷


def fit_temperature(logits, labels):
    # 在 log 温度上用 LBFGS 最小化交叉熵（负对数似然）
    x = torch.tensor(logits, dtype=torch.float64)
    y = torch.tensor(labels, dtype=torch.long)
    log_t = torch.zeros(1, dtype=torch.float64, requires_grad=True)
    optimizer = torch.optim.LBFGS([log_t], lr=0.1, max_iter=200)

    def closure():
        optimizer.zero_grad()
        value = F.cross_entropy(x / log_t.clamp(*LOG_T_RANGE).exp(), y)
        value.backward()
        return value
    optimizer.step(closure)
    with torch.no_grad():
        t = log_t.clamp(*LOG_T_RANGE).exp()
        before, after = F.cross_entropy(x, y).item(), F.cross_entropy(x / t, y).item()
    return float(t), before, after


def threshold_for_recall(scores, positives, target):
    # 满足“召回 ≥ target”的最大阈值：允许漏掉 floor((1-target)*正例数) 个正例
    pos = np.sort(scores[positives])
    if len(pos) == 0:
        return 0.5
    allowed_misses = int(math.floor((1 - target) * len(pos) + 1e-9))
    return float(pos[allowed_misses])


def calibrate(raw, frame, target_ge2=TARGET_RECALL_GE2):
    # 每个分类头一个温度；风险头再定 ge2 与 L3 两个阈值。raw 必须是模型训练时没见过的行的输出
    temperatures, nll = {}, {}
    for name in CLASS_HEADS:
        y = frame[f"y_{name}"].to_numpy()
        has = y >= 0
        if not has.any():
            temperatures[name], nll[name] = 1.0, None
            continue
        t, before, after = fit_temperature(raw[has][:, HEAD_SLICES[name]], y[has])
        temperatures[name], nll[name] = t, [before, after]
    y = frame["y_risk"].to_numpy()
    has = y >= 0
    p = softmax(raw[has][:, HEAD_SLICES["risk"]] / temperatures["risk"])
    return {
        "temperatures": temperatures, "nll_before_after": nll,
        "threshold_ge2": threshold_for_recall(p[:, 2] + p[:, 3], y[has] >= 2, target_ge2),
        "threshold_l3": threshold_for_recall(p[:, 3], y[has] == 3, TARGET_RECALL_L3),
        "target_recall_ge2": target_ge2, "target_recall_l3": TARGET_RECALL_L3,
        "calibration_rows": int(has.sum()),
    }


def model_levels(p_risk, cal):
    # 最大概率等级；P(L2)+P(L3) 过 ge2 阈值至少 L2；P(L3) 过 L3 阈值为 L3
    level = p_risk.argmax(1)
    level = np.where(p_risk[:, 2] + p_risk[:, 3] >= cal["threshold_ge2"], np.maximum(level, 2), level)
    return np.where(p_risk[:, 3] >= cal["threshold_l3"], 3, level)


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(mask, cond):
    n, k = int(mask.sum()), int((mask & cond).sum())
    return {"hit": k, "n": n, "rate": k / n if n else float("nan"), "ci95": wilson(k, n)}


def fmt_rate(r):
    if not r["n"]:
        return "—"
    return f"{r['hit']}/{r['n']}（{r['ci95'][0]:.0%}–{r['ci95'][1]:.0%}）"


def head_metrics(frame, outputs):
    # 分类头：准确率与 macro-F1（只计该头有标签的行，F1 在真实标签出现过的类别上平均）；连续头：MAE
    result = {}
    for name, kind, _ in HEADS:
        y = frame[f"y_{name}"].to_numpy()
        if kind == "class":
            has = y >= 0
            if not has.any():
                continue
            pred = outputs[name][has].argmax(1)
            result[name] = {"n": int(has.sum()), "accuracy": float((pred == y[has]).mean()),
                            "macro_f1": float(f1_score(y[has], pred, labels=np.unique(y[has]),
                                                       average="macro", zero_division=0))}
        else:
            has = ~np.isnan(y)
            if not has.any():
                continue
            result[name] = {"n": int(has.sum()), "mae": float(np.abs(outputs[name][has] - y[has]).mean())}
    return result


def risk_metrics(frame, p_risk, cal):
    y = frame["y_risk"].to_numpy()
    has = y >= 0
    y, p, category = y[has], p_risk[has], frame["category"].to_numpy()[has]
    level = model_levels(p, cal)
    p_ge2 = p[:, 2] + p[:, 3]
    result = {
        "L2+L3 判为 ≥L2": rate(y >= 2, level >= 2),
        "L3 判为 L3": rate(y == 3, level == 3),
        "L1 判为 L1": rate(y == 1, level == 1),
        "L0 误报为 ≥L2": rate(y == 0, level >= 2),
        "L0 误报为 ≥L1": rate(y == 0, level >= 1),
        "auc_ge2_vs_rest": float(roc_auc_score(y >= 2, p_ge2)) if 0 < (y >= 2).sum() < len(y) else float("nan"),
        # 只在真实等级为 L0 的行上计算（HYPERBOLE 一行是 G-2 口癖误报的粗略估计）
        "按类别的 L0 误报为 ≥L2": {c: rate((y == 0) & (category == c), level >= 2) for c in FP_CATEGORIES},
    }
    return result


def metrics_report(title, frame, outputs, cal, groups):
    # 返回 (markdown 行, json)；groups：{列名: 行掩码}
    per_head = head_metrics(frame, outputs)
    lines = [f"## {title}", "", "### 各头指标", "",
             "| 头 | 有标签行数 | 准确率 | macro-F1 | MAE |", "| :--- | ---: | ---: | ---: | ---: |"]
    for name, kind, _ in HEADS:
        m = per_head.get(name)
        if m is None:
            lines.append(f"| {name} | 0 | — | — | — |")
        elif kind == "class":
            lines.append(f"| {name} | {m['n']} | {m['accuracy']:.3f} | {m['macro_f1']:.3f} | — |")
        else:
            lines.append(f"| {name} | {m['n']} | — | — | {m['mae']:.3f} |")
    risk = {g: risk_metrics(frame[mask].reset_index(drop=True), outputs["risk"][mask], cal) for g, mask in groups.items()}
    lines += ["", f"### 风险指标（ge2 阈值 {cal['threshold_ge2']:.4f}，L3 阈值 {cal['threshold_l3']:.4f}；区间为 Wilson 95%）", "",
              "| 指标 | " + " | ".join(groups) + " |", "| :--- | " + " | ".join(":---:" for _ in groups) + " |"]
    for key in ("L2+L3 判为 ≥L2", "L3 判为 L3", "L1 判为 L1", "L0 误报为 ≥L2", "L0 误报为 ≥L1"):
        lines.append(f"| {key} | " + " | ".join(fmt_rate(risk[g][key]) for g in groups) + " |")
    lines.append("| AUC（≥L2 对其余） | " + " | ".join(f"{risk[g]['auc_ge2_vs_rest']:.3f}" for g in groups) + " |")
    for c in FP_CATEGORIES:
        lines.append(f"| L0 · {c} 误报为 ≥L2 | " + " | ".join(fmt_rate(risk[g]["按类别的 L0 误报为 ≥L2"][c]) for g in groups) + " |")
    return lines, {"per_head": per_head, "risk": risk}


def pool_groups(frame):
    group = frame["group"].to_numpy()
    return {"全部": np.ones(len(frame), dtype=bool), "合成数据": group == "synthetic", "项目用例": group == "cases"}


def slot_false_alarms(title, frame, p_risk, cal):
    # 只在真实等级为 L0 的行上，按槽位统计被判为 ≥L2 的比例。
    # 阈值前：只取最大概率等级；阈值后：再加上 ge2 / L3 阈值（model_levels，产品的判定）。返回 (markdown 行, json)
    y = frame["y_risk"].to_numpy()
    keys = slot_keys(frame)
    before, after = p_risk.argmax(1), model_levels(p_risk, cal)
    result = {}
    for key in sorted(set(keys[y == 0])):
        mask = (y == 0) & (keys == key)
        result[key] = {"before_threshold": rate(mask, before >= 2), "after_threshold": rate(mask, after >= 2),
                       "hard_negative": key in HARD_NEGATIVE_KEYS}
    order = sorted(result, key=lambda k: (-result[k]["after_threshold"]["rate"], k))
    lines = [f"### {title}：按槽位的 L0 误报为 ≥L2（★ = 难负例槽位；区间为 Wilson 95%）", "",
             "| 槽位 | L0 行数 | 阈值前 | 阈值后 |", "| :--- | ---: | :---: | :---: |"]
    for key in order:
        r = result[key]
        lines.append(f"| {key}{' ★' if r['hard_negative'] else ''} | {r['after_threshold']['n']} | "
                     f"{fmt_rate(r['before_threshold'])} | {fmt_rate(r['after_threshold'])} |")
    hard = (y == 0) & np.isin(keys, list(HARD_NEGATIVE_KEYS))
    totals = {"难负例槽位合计": hard, "其余 L0 合计": (y == 0) & ~hard}
    for label, mask in totals.items():
        lines.append(f"| **{label}** | {int(mask.sum())} | {fmt_rate(rate(mask, before >= 2))} | {fmt_rate(rate(mask, after >= 2))} |")
        result[label] = {"before_threshold": rate(mask, before >= 2), "after_threshold": rate(mask, after >= 2)}
    return lines, result
""")

md("## 5. 教师模型：共享编码器 + 9 个头")

code(r"""
from transformers import AutoModel, AutoTokenizer, BertConfig, BertModel, get_linear_schedule_with_warmup

tokenizer = AutoTokenizer.from_pretrained(ENCODER)


class PerceptionTeacher(nn.Module):
    def __init__(self, encoder):
        super().__init__()
        self.encoder = encoder
        self.dropout = nn.Dropout(0.1)
        self.heads = nn.Linear(encoder.config.hidden_size, OUT_DIM)  # 9 个头拼成一个线性层，按 HEAD_SLICES 切分

    def forward(self, input_ids, attention_mask):
        cls = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state[:, 0]
        return self.heads(self.dropout(cls))


def build_teacher():
    if SMOKE_TEST:  # 冒烟测试只验证流程：随机初始化的极小编码器，不下载预训练权重
        cfg = BertConfig(vocab_size=tokenizer.vocab_size, hidden_size=32, num_hidden_layers=1,
                         num_attention_heads=2, intermediate_size=64, max_position_embeddings=MAX_LEN + 2)
        return PerceptionTeacher(BertModel(cfg))
    return PerceptionTeacher(AutoModel.from_pretrained(ENCODER))


def encode(text):
    ids = tokenizer(text, add_special_tokens=False)["input_ids"]
    budget = MAX_LEN - 2
    if len(ids) > budget:
        ids = ids[:HEAD_TOKENS] + ids[len(ids) - (budget - HEAD_TOKENS):]
    return [tokenizer.cls_token_id] + ids + [tokenizer.sep_token_id]


def batches(frame, batch_size, shuffle=False, seed=SEED):
    order = np.arange(len(frame))
    if shuffle:
        np.random.default_rng(seed).shuffle(order)
    for start in range(0, len(order), batch_size):
        rows = frame.iloc[order[start:start + batch_size]]
        encoded = [encode(t) for t in rows["text"]]
        width = max(len(e) for e in encoded)
        ids = torch.full((len(encoded), width), tokenizer.pad_token_id, dtype=torch.long)
        mask = torch.zeros((len(encoded), width), dtype=torch.long)
        for i, e in enumerate(encoded):
            ids[i, :len(e)] = torch.tensor(e)
            mask[i, :len(e)] = 1
        yield ids.to(DEVICE), mask.to(DEVICE), label_tensors(rows, DEVICE)
""")

md("## 6. 教师训练：5 折交叉验证 + 全量最终模型（已完成且配置未变时复用）")

code(r"""
AMP_DTYPE = None
if DEVICE.type == "cuda":
    AMP_DTYPE = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

TRAIN_CONFIG = {
    "encoder": "smoke-tiny-random" if SMOKE_TEST else ENCODER, "seed": SEED, "max_len": MAX_LEN,
    "head_tokens": HEAD_TOKENS, "batch_size": BATCH_SIZE, "epochs": EPOCHS, "lr": LR,
    "weight_decay": WEIGHT_DECAY, "warmup_ratio": WARMUP_RATIO, "cv_folds": CV_FOLDS,
    "gamma_pos": GAMMA_POS, "loss_weights": LOSS_WEIGHTS,
    "heads": [[name, kind, labels] for name, kind, labels in HEADS], "data_fingerprint": DATA_FINGERPRINT,
}
if LOSS_BALANCE == "gradnorm":  # "equal" 不加这一项，配置指纹与第四轮的写法相同
    TRAIN_CONFIG["loss_balance"] = {"method": "gradnorm", "alpha": GRADNORM_ALPHA, "lr": GRADNORM_LR,
                                    "min_weight": GRADNORM_MIN_WEIGHT, "shared_layer": "encoder.layer[-1].output.dense.weight"}
CONFIG_FINGERPRINT = hashlib.sha256(json.dumps(TRAIN_CONFIG, sort_keys=True).encode()).hexdigest()[:16]
# 折教师对学生训练文本的预测（集成蒸馏）按这个指纹复用
FOLD_KD_FINGERPRINT = hashlib.sha256(f"{CONFIG_FINGERPRINT}:{STUDENT_TEXTS_HASH}".encode()).hexdigest()[:16]


def gradnorm_shared_layer(model):
    # GradNorm 的“最后一个共享层”：编码器最后一层 FFN 输出的 dense 权重（各头之前最后一个有参数的共享线性层）
    return model.encoder.encoder.layer[-1].output.dense.weight


def train_teacher(frame, seed, tag):
    # 返回 (模型, GradNorm 每轮末的头权重列表；"equal" 时为空列表)
    set_seed(seed)
    model = build_teacher().to(DEVICE)
    risk_weight = risk_class_weights(frame)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    steps = EPOCHS * math.ceil(len(frame) / BATCH_SIZE)
    scheduler = get_linear_schedule_with_warmup(optimizer, int(WARMUP_RATIO * steps), steps)
    scaler = torch.amp.GradScaler("cuda", enabled=AMP_DTYPE == torch.float16)
    balance = GradNorm(HEAD_NAMES) if LOSS_BALANCE == "gradnorm" else None
    history = []
    for epoch in range(1, EPOCHS + 1):
        model.train()
        started, total = time.time(), 0.0
        for ids, mask, labels in batches(frame, BATCH_SIZE, shuffle=True, seed=seed + epoch):
            with torch.autocast(DEVICE.type, dtype=AMP_DTYPE, enabled=AMP_DTYPE is not None):
                raw = model(ids, mask)
            if balance is None:
                batch_loss = supervised_loss(raw, labels, risk_weight)
                optimizer.zero_grad()
            else:
                parts = head_losses(raw, labels, risk_weight)
                batch_loss = balance.total(parts)  # 用本步更新前的权重
                optimizer.zero_grad()
                balance.step(parts, gradnorm_shared_layer(model), scaler)
            scaler.scale(batch_loss).backward()
            scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            total += batch_loss.item()
        print(f"  [{tag}] epoch {epoch}/{EPOCHS} train_loss {total:.3f} ({time.time() - started:.0f}s)")
        if balance is not None:
            history.append({"epoch": epoch, "weights": balance.weights(), "skipped_steps": balance.skipped})
            print(f"  [{tag}] GradNorm 头权重：" + "，".join(f"{k} {v:.2f}" for k, v in balance.weights().items()))
    return model, history


@torch.no_grad()
def predict_raw(model, frame):
    model.eval()
    out = []
    for ids, mask, _ in batches(frame, BATCH_SIZE * 2):
        with torch.autocast(DEVICE.type, dtype=AMP_DTYPE, enabled=AMP_DTYPE is not None):
            out.append(model(ids, mask).float().cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, OUT_DIM), dtype=np.float32)


def release(model):
    del model
    if DEVICE.type == "cuda":
        torch.cuda.empty_cache()


# ---- 交叉验证：每折训练一个模型，只预测留出的那一折（集成蒸馏时另预测学生训练文本） ----
oof_raw = np.full((len(pool), OUT_DIM), np.nan, dtype=np.float32)
fold_student_raw, GRADNORM_HISTORY = [], {}
for k in range(CV_FOLDS):
    fold_path = os.path.join(PATHS["fold_dir"], f"fold_{k}.npz")
    held = np.flatnonzero(pool["fold"].to_numpy() == k)
    if os.path.exists(fold_path) and not FORCE_RETRAIN:
        saved = np.load(fold_path)
        current = str(saved["fingerprint"]) == CONFIG_FINGERPRINT and np.array_equal(saved["index"], held)
        has_kd = "kd_fingerprint" in saved.files and str(saved["kd_fingerprint"]) == FOLD_KD_FINGERPRINT
        if current and (KD_SOURCE != "ensemble" or has_kd):
            oof_raw[held] = saved["raw"]
            if KD_SOURCE == "ensemble":
                fold_student_raw.append(saved["kd_raw"])
            if "gradnorm" in saved.files:
                GRADNORM_HISTORY[f"fold {k}"] = json.loads(str(saved["gradnorm"]))
            print(f"第 {k} 折已完成，复用。")
            continue
        if current:
            print(f"第 {k} 折缺少集成蒸馏所需的学生训练文本预测（折模型未保存），重新训练。")
    print(f"第 {k} 折：训练 {len(pool) - len(held)} 条，预测 {len(held)} 条")
    model, history = train_teacher(pool.drop(index=held), SEED + 100 * (k + 1), f"fold {k}")
    raw = predict_raw(model, pool.iloc[held])
    extra = {"gradnorm": json.dumps(history)} if history else {}
    if KD_SOURCE == "ensemble":
        kd_raw = predict_raw(model, student_train)
        fold_student_raw.append(kd_raw)
        extra.update(kd_fingerprint=FOLD_KD_FINGERPRINT, kd_raw=kd_raw)
    np.savez(fold_path, fingerprint=CONFIG_FINGERPRINT, index=held, raw=raw, **extra)
    if history:
        GRADNORM_HISTORY[f"fold {k}"] = history
    oof_raw[held] = raw
    release(model)
assert not np.isnan(oof_raw).any()


# ---- 最终教师：全部训练数据，同样的轮数 ----
def teacher_is_current():
    if FORCE_RETRAIN or not (os.path.exists(PATHS["teacher"]) and os.path.exists(PATHS["teacher_config"])):
        return False
    with open(PATHS["teacher_config"], encoding="utf-8") as f:
        saved = json.load(f)
    return saved.get("training_complete") and saved.get("config_fingerprint") == CONFIG_FINGERPRINT


if teacher_is_current():
    print("最终教师已训练完成且配置一致，复用。")
    with open(PATHS["teacher_config"], encoding="utf-8") as f:
        final_history = json.load(f).get("gradnorm_history", [])
else:
    with open(PATHS["teacher_config"], "w", encoding="utf-8") as f:
        json.dump({**TRAIN_CONFIG, "config_fingerprint": CONFIG_FINGERPRINT, "training_complete": False}, f, ensure_ascii=False, indent=2)
    model, final_history = train_teacher(pool, SEED, "final")
    torch.save({"state_dict": model.state_dict(), "config_fingerprint": CONFIG_FINGERPRINT}, PATHS["teacher"])
    release(model)
    extra = {"gradnorm_history": final_history} if final_history else {}
    with open(PATHS["teacher_config"], "w", encoding="utf-8") as f:
        json.dump({**TRAIN_CONFIG, "config_fingerprint": CONFIG_FINGERPRINT, "training_complete": True, **extra},
                  f, ensure_ascii=False, indent=2)
if final_history:
    GRADNORM_HISTORY["final"] = final_history

teacher = build_teacher().to(DEVICE)
teacher.load_state_dict(torch.load(PATHS["teacher"], map_location=DEVICE)["state_dict"])
teacher.eval()
print("已加载最终教师，配置指纹", CONFIG_FINGERPRINT)
""")

md(r"""
## 7. 教师校准与交叉验证报告

温度与阈值只用 OOF 预测确定。最终教师用全部数据训练，它的校准与各折模型相近但不完全相同，这是交叉验证定阈值的通常近似。

报告末尾另有按槽位的 L0 误报表，以及 `LOSS_BALANCE = "gradnorm"` 时各折与最终教师每轮末学到的头权重。
""")

code(r"""
TEACHER_CAL = {"config_fingerprint": CONFIG_FINGERPRINT, **calibrate(oof_raw, pool)}
oof_out = outputs_from_raw(oof_raw, TEACHER_CAL["temperatures"])
cv_lines, cv_json = metrics_report(f"教师 {CV_FOLDS} 折交叉验证（OOF）", pool, oof_out, TEACHER_CAL, pool_groups(pool))
slot_lines, slot_json = slot_false_alarms("教师 OOF", pool, oof_out["risk"], TEACHER_CAL)
cv_lines += [""] + slot_lines
cv_json["slot_false_alarms"] = slot_json
if GRADNORM_HISTORY:
    cv_lines += ["", f"### GradNorm 各头权重（每轮末；α = {GRADNORM_ALPHA}，总和 = {len(HEAD_NAMES)}）", "",
                 "| 模型 | 轮 | " + " | ".join(HEAD_NAMES) + " |", "| :--- | ---: | " + " | ".join("---:" for _ in HEAD_NAMES) + " |"]
    for tag, history in GRADNORM_HISTORY.items():
        for entry in history:
            cv_lines.append(f"| {tag} | {entry['epoch']} | " + " | ".join(f"{entry['weights'][n]:.2f}" for n in HEAD_NAMES) + " |")
    skipped = {tag: h[-1]["skipped_steps"] for tag, h in GRADNORM_HISTORY.items() if h and h[-1]["skipped_steps"]}
    if skipped:
        cv_lines.append(f"\n梯度非有限而跳过的 GradNorm 步数：{skipped}")
    cv_json["gradnorm"] = GRADNORM_HISTORY
else:
    cv_lines += ["", "各头权重 λ 固定为 1（`LOSS_BALANCE = \"equal\"`）。"]
TEACHER_CAL["oof"] = cv_json
with open(PATHS["teacher_calibration"], "w", encoding="utf-8") as f:
    json.dump(TEACHER_CAL, f, ensure_ascii=False, indent=2)

oof_level = model_levels(oof_out["risk"], TEACHER_CAL)
oof_frame = pool.drop(columns=["text"]).assign(
    **{f"p_{name}": oof_out["risk"][:, i].round(4) for i, name in enumerate(LEVEL_NAMES)}, model_level=oof_level,
    **{f"pred_{name}": ([HEAD_LABELS[name][i] for i in oof_out[name].argmax(1)] if HEAD_KIND[name] == "class"
                        else oof_out[name].round(4)) for name in HEAD_NAMES})
oof_frame.to_csv(PATHS["oof"], index=False, encoding="utf-8")

temps = "，".join(f"{name} {t:.2f}" for name, t in TEACHER_CAL["temperatures"].items())
header = [f"# 感知教师模型：交叉验证报告", "",
          f"训练池 {len(pool)} 条（{CV_FOLDS} 折，每折 {EPOCHS} 轮）。配置指纹 `{CONFIG_FINGERPRINT}`。",
          f"温度：{temps}。", "",
          "OOF 指标来自与训练数据同源的句子，会偏乐观；它只用来定温度和阈值。", ""]
with open(PATHS["cv_report"] + ".md", "w", encoding="utf-8") as f:
    f.write("\n".join(header + cv_lines) + "\n")
with open(PATHS["cv_report"] + ".json", "w", encoding="utf-8") as f:
    json.dump(TEACHER_CAL, f, ensure_ascii=False, indent=2)
print("\n".join(header + cv_lines))
""")

md(r"""
## 8. 学生模型：字表、大小检查与蒸馏目标

- 字表：训练池中出现 ≥ 2 次的字，另加 PAD、UNK。训练前按字表大小与学生配置算出 `student.npz` 的字节数（float16，每个数组另加约 260 字节的 npz 头），断言 < 4 MB；导出后再按实际文件大小断言一次。
- 蒸馏目标按学生训练集的**实际文本**（含增强副本）计算：分类头取 `softmax(z / (教师温度 × 2))`，连续头取教师的输出值。
  `KD_SOURCE = "ensemble"` 时对 5 个折教师与最终教师各算一份再取平均（6 个教师权重相同，都用 OOF 上拟合的教师温度）；`"final"` 时只用最终教师。
""")

code(r"""
char_counts = Counter(ch for text in pool["text"] for ch in text)
VOCAB = ["<PAD>", "<UNK>"] + sorted(ch for ch, n in char_counts.items() if n >= STUDENT["min_char_freq"])
CHAR_INDEX = {ch: i for i, ch in enumerate(VOCAB)}


def student_param_count(vocab_size, cfg):
    kernels, e, f, h = cfg["kernels"], cfg["embed_dim"], cfg["filters"], cfg["hidden"]
    return (vocab_size * e + sum(f * e * k + f for k in kernels)
            + len(kernels) * f * h + h + h * OUT_DIM + OUT_DIM)


def student_npz_estimate(vocab_size, cfg):
    # float16 每个参数 2 字节；npz 每个数组另有约 260 字节的 zip 与 .npy 头（第四轮实测 255）（数组数 = 1 + 2 × 卷积核种数 + 4）
    return 2 * student_param_count(vocab_size, cfg) + 260 * (1 + 2 * len(cfg["kernels"]) + 4)


STUDENT_BYTES_ESTIMATE = student_npz_estimate(len(VOCAB), STUDENT)
print(f"字表 {len(VOCAB)} 个（含 PAD、UNK）；学生 {student_param_count(len(VOCAB), STUDENT):,} 个参数，"
      f"student.npz 预计 {STUDENT_BYTES_ESTIMATE / 1024:.1f} KB（上限 {STUDENT_MAX_BYTES / 1024 / 1024:.0f} MB）")
for label, cfg in (("base 96/128", {**STUDENT, "embed_dim": 64, "filters": 96, "hidden": 128}),
                   ("wide 160/192", {**STUDENT, "embed_dim": 64, **STUDENT_WIDE})):
    sizes = "，".join(f"字表 {v}：{student_npz_estimate(v, cfg) / 1024:.0f} KB" for v in (2000, 4000, 8000))
    print(f"  正式配置 {label}（嵌入 64）：{sizes}")
assert STUDENT_BYTES_ESTIMATE < STUDENT_MAX_BYTES, f"学生配置预计 {STUDENT_BYTES_ESTIMATE} 字节，超过 {STUDENT_MAX_BYTES}"

# ---- 最终教师对学生训练文本的输出（配置与文本未变时复用缓存） ----
TARGETS_FINGERPRINT = hashlib.sha256(
    (CONFIG_FINGERPRINT + "\n" + "\n".join(student_train["text"])).encode("utf-8")).hexdigest()[:16]
teacher_train_raw = None
if os.path.exists(PATHS["teacher_targets"]) and not FORCE_RETRAIN:
    saved = np.load(PATHS["teacher_targets"])
    if str(saved["fingerprint"]) == TARGETS_FINGERPRINT:
        teacher_train_raw = saved["raw"]
        print("教师蒸馏目标已计算过，复用。")
if teacher_train_raw is None:
    teacher_train_raw = predict_raw(teacher, student_train)
    np.savez(PATHS["teacher_targets"], fingerprint=TARGETS_FINGERPRINT, raw=teacher_train_raw)


def soft_targets(raw):
    out = np.zeros_like(raw, dtype=np.float32)
    for name, kind, _ in HEADS:
        z = raw[:, HEAD_SLICES[name]].astype(np.float64)
        if kind == "class":
            out[:, HEAD_SLICES[name]] = softmax(z / (TEACHER_CAL["temperatures"][name] * STUDENT["kd_temperature"]))
        else:
            out[:, HEAD_SLICES[name]] = (np.tanh(z) if kind == "tanh" else sigmoid(z))
    return out


kd_teachers = [teacher_train_raw] + (fold_student_raw if KD_SOURCE == "ensemble" else [])
kd_targets = np.mean([soft_targets(raw) for raw in kd_teachers], axis=0).astype(np.float32)
if KD_SOURCE == "ensemble":
    risk = HEAD_SLICES["risk"]
    spread = np.std([soft_targets(raw)[:, risk][:, 2:].sum(1) for raw in kd_teachers], axis=0)
    print(f"集成蒸馏：{len(kd_teachers)} 个教师（最终 + {len(fold_student_raw)} 折）；"
          f"各教师 P(L2)+P(L3)（蒸馏温度下）的标准差：均值 {spread.mean():.3f}，最大 {spread.max():.3f}")
""")

md(r"""
## 9. 学生模型：字符级 CNN 与蒸馏训练

字嵌入 → 卷积核 2/3/4/5 各若干个（ReLU，全局最大池化，只在文本内的窗口上取最大）→ dropout → 共享全连接（ReLU）→ 9 个头。
宽度由 `STUDENT_WIDTH` 决定（`"wide"`：每种卷积核 160 个、共享层 192 维；`"base"`：96 / 128）。
损失 = 0.5 × 硬标签（与教师相同的屏蔽损失，各头 λ = 1）+ 0.5 × 蒸馏（分类头：T = 2 的 KL × T²；连续头：与教师输出的 MSE）。
`HARD_NEGATIVE_WEIGHT ≠ 1` 时，硬标签项中风险头对难负例行（含其增强副本）乘这个权重；蒸馏项不加权。
""")

code(r"""
MIN_CHARS = max(STUDENT["kernels"])


def encode_chars(text, index=None, max_len=None, head=None):
    # 字 → 编号；超长时保留开头 head 个字和结尾其余部分；不足最大卷积核宽度时用 PAD 补齐
    index = CHAR_INDEX if index is None else index
    max_len = STUDENT["max_len"] if max_len is None else max_len
    head = STUDENT["head_chars"] if head is None else head
    ids = [index.get(ch, 1) for ch in text]
    if len(ids) > max_len:
        ids = ids[:head] + ids[len(ids) - (max_len - head):]
    return ids + [0] * (MIN_CHARS - len(ids))


class CharCNN(nn.Module):
    def __init__(self, vocab_size, cfg):
        super().__init__()
        self.kernels = list(cfg["kernels"])
        self.embed = nn.Embedding(vocab_size, cfg["embed_dim"], padding_idx=0)
        self.convs = nn.ModuleList(nn.Conv1d(cfg["embed_dim"], cfg["filters"], k) for k in self.kernels)
        self.dropout = nn.Dropout(cfg["dropout"])
        self.dense = nn.Linear(len(self.kernels) * cfg["filters"], cfg["hidden"])
        self.heads = nn.Linear(cfg["hidden"], OUT_DIM)

    def forward(self, ids, lengths):
        x = self.embed(ids).transpose(1, 2)  # (批, 嵌入, 长度)
        pooled = []
        for k, conv in zip(self.kernels, self.convs):
            h = torch.relu(conv(x))  # (批, 卷积核数, 长度 - k + 1)
            valid = torch.arange(h.shape[2], device=ids.device)[None, :] <= (lengths[:, None] - k)
            pooled.append(h.masked_fill(~valid[:, None, :], 0.0).max(dim=2).values)  # ReLU 输出 ≥ 0，补 0 不改变最大值
        h = torch.relu(self.dense(self.dropout(torch.cat(pooled, dim=1))))
        return self.heads(h)


def char_batch(seqs, device):
    width = max(len(s) for s in seqs)
    ids = torch.zeros((len(seqs), width), dtype=torch.long)
    for i, s in enumerate(seqs):
        ids[i, :len(s)] = torch.tensor(s, dtype=torch.long)
    return ids.to(device), torch.tensor([len(s) for s in seqs], dtype=torch.long, device=device)


@torch.no_grad()
def student_raw(model, texts, device=DEVICE, batch_size=256):
    model.eval()
    encoded = [encode_chars(clean_text(t)) for t in texts]
    out = [model(*char_batch(encoded[i:i + batch_size], device)).float().cpu().numpy()
           for i in range(0, len(encoded), batch_size)]
    return np.concatenate(out) if out else np.zeros((0, OUT_DIM), dtype=np.float32)


def distill_loss(raw, kd):
    t = STUDENT["kd_temperature"]
    total = raw.new_zeros(())
    for name, kind, _ in HEADS:
        z, target = raw[:, HEAD_SLICES[name]], kd[:, HEAD_SLICES[name]]
        if kind == "class":
            part = F.kl_div(F.log_softmax(z / t, dim=1), target, reduction="batchmean") * t * t
        else:
            part = F.mse_loss(value_activation(z[:, 0], kind), target[:, 0])
        total = total + LOSS_WEIGHTS[name] * part
    return total


STUDENT_CONFIG = {**STUDENT, "teacher_fingerprint": CONFIG_FINGERPRINT, "targets_fingerprint": TARGETS_FINGERPRINT,
                  "vocab_hash": hashlib.sha256("".join(VOCAB).encode("utf-8")).hexdigest()[:16],
                  "holdout_hash": hashlib.sha256(student_holdout["id"].str.cat(sep="\n").encode("utf-8")).hexdigest()[:16]}
# C5 选项只在打开时写进指纹（全部关闭时与第四轮的写法相同）
if KD_SOURCE == "ensemble":
    STUDENT_CONFIG["kd_source"] = {"method": "ensemble", "teachers": 1 + len(fold_student_raw),
                                   "fold_kd_fingerprint": FOLD_KD_FINGERPRINT}
HARD_NEGATIVE_ROWS = hard_negative_mask(student_train)
if HARD_NEGATIVE_WEIGHT != 1.0:
    STUDENT_CONFIG["hard_negative"] = {"weight": HARD_NEGATIVE_WEIGHT, "slots": sorted(HARD_NEGATIVE_KEYS),
                                       "rows": int(HARD_NEGATIVE_ROWS.sum())}
STUDENT_FINGERPRINT = hashlib.sha256(json.dumps(STUDENT_CONFIG, sort_keys=True).encode()).hexdigest()[:16]


def train_student():
    set_seed(SEED + 3)
    model = CharCNN(len(VOCAB), STUDENT).to(DEVICE)
    encoded = [encode_chars(t) for t in student_train["text"]]
    targets = torch.tensor(kd_targets, dtype=torch.float)
    risk_weight = risk_class_weights(student_train)
    row_weight = None
    if HARD_NEGATIVE_WEIGHT != 1.0:
        row_weight = torch.tensor(np.where(HARD_NEGATIVE_ROWS, HARD_NEGATIVE_WEIGHT, 1.0), dtype=torch.float)
        print(f"  难负例加权：{int(HARD_NEGATIVE_ROWS.sum())}/{len(student_train)} 行，风险头硬标签损失 × {HARD_NEGATIVE_WEIGHT}")
    optimizer = torch.optim.AdamW(model.parameters(), lr=STUDENT["lr"], weight_decay=STUDENT["weight_decay"])
    steps = STUDENT["epochs"] * math.ceil(len(student_train) / STUDENT["batch_size"])
    scheduler = get_linear_schedule_with_warmup(optimizer, int(STUDENT["warmup_ratio"] * steps), steps)
    alpha = STUDENT["kd_alpha"]
    for epoch in range(1, STUDENT["epochs"] + 1):
        model.train()
        started, total = time.time(), 0.0
        order = np.random.default_rng(SEED + 1000 + epoch).permutation(len(student_train))
        for start in range(0, len(order), STUDENT["batch_size"]):
            chunk = order[start:start + STUDENT["batch_size"]]
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
        print(f"  [student] epoch {epoch}/{STUDENT['epochs']} train_loss {total:.3f} ({time.time() - started:.0f}s)")
    return model


def student_is_current():
    if FORCE_RETRAIN or not os.path.exists(PATHS["student_ckpt"]):
        return False
    saved = torch.load(PATHS["student_ckpt"], map_location="cpu")
    return saved.get("training_complete") and saved.get("fingerprint") == STUDENT_FINGERPRINT


if student_is_current():
    print("学生模型已训练完成且配置一致，复用。")
else:
    trained = train_student()
    torch.save({"state_dict": trained.state_dict(), "fingerprint": STUDENT_FINGERPRINT, "training_complete": True},
               PATHS["student_ckpt"])
    release(trained)

student = CharCNN(len(VOCAB), STUDENT).to(DEVICE)
student.load_state_dict(torch.load(PATHS["student_ckpt"], map_location=DEVICE)["state_dict"])
student.eval()
n_params = sum(p.numel() for p in student.parameters())
print(f"已加载学生模型：{n_params:,} 个参数，指纹 {STUDENT_FINGERPRINT}")
""")

md("## 10. 学生校准（留出集）、导出、NumPy 一致性与时延")

code(r"""
holdout_raw = student_raw(student, student_holdout["text"])
STUDENT_CAL = {"student_fingerprint": STUDENT_FINGERPRINT, **calibrate(holdout_raw, student_holdout, STUDENT_TARGET_RECALL_GE2)}
holdout_out = outputs_from_raw(holdout_raw, STUDENT_CAL["temperatures"])
student_lines, student_json = metrics_report("学生模型：留出集（学生训练时没见过；教师训练时见过）", student_holdout,
                                             holdout_out, STUDENT_CAL, pool_groups(student_holdout))
slot_lines, slot_json = slot_false_alarms("学生留出集", student_holdout, holdout_out["risk"], STUDENT_CAL)
student_lines += [""] + slot_lines
student_json["slot_false_alarms"] = slot_json

# ---- 导出：float16 权重、字表、配置 ----
state = {k: v.detach().cpu().float().numpy() for k, v in student.state_dict().items()}
arrays = {"embedding": state["embed.weight"]}
for i, k in enumerate(STUDENT["kernels"]):
    arrays[f"conv{k}_weight"] = state[f"convs.{i}.weight"]  # (卷积核数, 嵌入, k)
    arrays[f"conv{k}_bias"] = state[f"convs.{i}.bias"]
arrays.update(dense_weight=state["dense.weight"], dense_bias=state["dense.bias"],
              heads_weight=state["heads.weight"], heads_bias=state["heads.bias"])
np.savez(PATHS["student_npz"], **{k: v.astype(np.float16) for k, v in arrays.items()})
npz_bytes = os.path.getsize(PATHS["student_npz"])
assert npz_bytes < STUDENT_MAX_BYTES, f"student.npz {npz_bytes} 字节，超过 {STUDENT_MAX_BYTES}"
print(f"student.npz 实际 {npz_bytes} 字节，训练前预计 {STUDENT_BYTES_ESTIMATE} 字节")

with open(PATHS["student_vocab"], "w", encoding="utf-8") as f:
    json.dump({"chars": VOCAB, "pad": 0, "unk": 1}, f, ensure_ascii=False)
EXPORT_CONFIG = {
    "format_version": 1,
    "student_fingerprint": STUDENT_FINGERPRINT, "teacher_fingerprint": CONFIG_FINGERPRINT,
    "preprocess": "html.unescape → NBSP 换为空格 → 连续空白合并为一个空格 → 去掉首尾空白；按字（Unicode 码位）切分，不在字表中的字记为 UNK",
    "max_len": STUDENT["max_len"], "head_chars": STUDENT["head_chars"], "min_len": MIN_CHARS,
    "truncation": "超过 max_len 时保留开头 head_chars 个字和结尾 max_len - head_chars 个字；不足 min_len 时右侧补 PAD",
    "embed_dim": STUDENT["embed_dim"], "kernels": STUDENT["kernels"], "filters": STUDENT["filters"],
    "hidden": STUDENT["hidden"],
    "forward": "embedding → 每个 k：conv{k}（valid 卷积）→ ReLU → 全局最大池化；按 kernels 顺序拼接 → dense → ReLU → heads",
    "heads": [{"name": name, "kind": kind, "offset": HEAD_SLICES[name].start,
               "size": HEAD_SLICES[name].stop - HEAD_SLICES[name].start, "labels": labels,
               "activation": {"class": "softmax(z / temperature)", "tanh": "tanh", "sigmoid": "sigmoid", "bce": "sigmoid"}[kind]}
              for name, kind, labels in HEADS],
    "temperatures": STUDENT_CAL["temperatures"],
    "risk": {"threshold_ge2": STUDENT_CAL["threshold_ge2"], "threshold_l3": STUDENT_CAL["threshold_l3"],
             "rule": "level = argmax P；P(L2)+P(L3) ≥ threshold_ge2 时至少 L2；P(L3) ≥ threshold_l3 时为 L3",
             "threshold_l3_used_only_with_model_plan_evidence": True,
             "target_recall_ge2": STUDENT_TARGET_RECALL_GE2, "target_recall_l3": TARGET_RECALL_L3},
    "arrays": {k: list(v.shape) for k, v in arrays.items()}, "npz_bytes": npz_bytes,
    # 训练选项只作记录，产品端不读
    "training_options": {"loss_balance": LOSS_BALANCE, "student_width": STUDENT_WIDTH, "kd_source": KD_SOURCE,
                         "hard_negative_weight": HARD_NEGATIVE_WEIGHT},
}
with open(PATHS["student_config"], "w", encoding="utf-8") as f:
    json.dump(EXPORT_CONFIG, f, ensure_ascii=False, indent=2)
print(f"已导出 {PATHS['student_npz']}：{npz_bytes / 1024:.1f} KB（上限 {STUDENT_MAX_BYTES / 1024 / 1024:.0f} MB）")
""")

code(r"""
# ---- 纯 NumPy 参考前向：只读取导出的三个文件，不依赖 PyTorch（产品端照此实现） ----
class NumpyStudent:
    def __init__(self, directory):
        with open(os.path.join(directory, "student_config.json"), encoding="utf-8") as f:
            self.cfg = json.load(f)
        with open(os.path.join(directory, "vocab.json"), encoding="utf-8") as f:
            vocab = json.load(f)
        self.index = {ch: i for i, ch in enumerate(vocab["chars"])}
        self.unk = vocab["unk"]
        with np.load(os.path.join(directory, "student.npz")) as w:
            weights = {k: w[k].astype(np.float32) for k in w.files}
        self.embedding = weights["embedding"]
        # 卷积权重 (卷积核数, 嵌入, k) → (嵌入 × k, 卷积核数)，与滑动窗口 (位置, 嵌入, k) 展平后的顺序一致
        self.convs = [(k, weights[f"conv{k}_weight"].reshape(weights[f"conv{k}_weight"].shape[0], -1).T.copy(),
                       weights[f"conv{k}_bias"]) for k in self.cfg["kernels"]]
        self.dense_w, self.dense_b = weights["dense_weight"].T.copy(), weights["dense_bias"]
        self.heads_w, self.heads_b = weights["heads_weight"].T.copy(), weights["heads_bias"]

    @staticmethod
    def preprocess(text):
        text = html.unescape(str(text)).replace(" ", " ")
        return re.sub(r"\s+", " ", text).strip()

    def encode(self, text):
        cfg = self.cfg
        ids = [self.index.get(ch, self.unk) for ch in self.preprocess(text)]
        if len(ids) > cfg["max_len"]:
            ids = ids[:cfg["head_chars"]] + ids[len(ids) - (cfg["max_len"] - cfg["head_chars"]):]
        return np.array(ids + [0] * (cfg["min_len"] - len(ids)), dtype=np.int64)

    def raw(self, text):
        x = self.embedding[self.encode(text)]  # (长度, 嵌入)
        pooled = []
        for k, w, b in self.convs:
            windows = np.lib.stride_tricks.sliding_window_view(x, k, axis=0)  # (长度 - k + 1, 嵌入, k)
            h = windows.reshape(windows.shape[0], -1) @ w + b
            pooled.append(np.maximum(h, 0.0).max(axis=0))
        h = np.maximum(np.concatenate(pooled) @ self.dense_w + self.dense_b, 0.0)
        return h @ self.heads_w + self.heads_b

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


np_student = NumpyStudent(PATHS["student_dir"])

# ---- 一致性：NumPy（float16 权重）对 PyTorch 学生（float32 权重，CPU） ----
edge_texts = ["", "嗯", "我" * (STUDENT["max_len"] * 3) + "不想活了", "😀🙂 a b c &amp; 测试"]
# 候选：训练池原句、增强副本、倒序原句（保证小数据时也凑满 PARITY_TEXTS 条）；不使用任何测试句
candidates = list(pool["text"]) + list(student_train["text"]) + [t[::-1] for t in pool["text"]]
parity_texts = list(dict.fromkeys(candidates))[:PARITY_TEXTS - len(edge_texts)] + edge_texts
cpu_student = copy.deepcopy(student).cpu().eval()
torch_out = outputs_from_raw(student_raw(cpu_student, parity_texts, device=torch.device("cpu")), STUDENT_CAL["temperatures"])
quantized = copy.deepcopy(cpu_student)
with torch.no_grad():
    for p in quantized.parameters():
        p.copy_(p.half().float())
quant_out = outputs_from_raw(student_raw(quantized, parity_texts, device=torch.device("cpu")), STUDENT_CAL["temperatures"])
np_preds = [np_student.predict(t) for t in parity_texts]
parity, parity_impl = {}, {}
for name, kind, _ in HEADS:
    np_values = np.array([p[name] for p in np_preds])
    parity[name] = float(np.abs(np_values - torch_out[name]).max())
    parity_impl[name] = float(np.abs(np_values - quant_out[name]).max())
parity_max = max(parity.values())
print(f"NumPy 对 PyTorch（{len(parity_texts)} 条）：最大绝对差 {parity_max:.2e}（含 float16 量化；只算实现差异为 {max(parity_impl.values()):.2e}）")
print({k: f"{v:.1e}" for k, v in parity.items()})
assert parity_max < PARITY_TOL, f"NumPy 前向与 PyTorch 不一致：{parity_max:.2e} ≥ {PARITY_TOL}"

# ---- 时延：NumPy 单条推理（限制为单线程，对应 SDD §10.1 的单核 CPU 基线） ----
try:
    from threadpoolctl import threadpool_limits
    single_thread = threadpool_limits(limits=1)
except ImportError:
    single_thread = contextlib.nullcontext()
latency_texts = list(pool["text"]) + edge_texts
with single_thread:
    for t in latency_texts[:20]:
        np_student.predict(t)
    timings = []
    for i in range(LATENCY_RUNS):
        text = latency_texts[i % len(latency_texts)]
        started = time.perf_counter()
        np_student.predict(text)
        timings.append((time.perf_counter() - started) * 1000)
latency = {"runs": LATENCY_RUNS, "p50_ms": float(np.percentile(timings, 50)), "p99_ms": float(np.percentile(timings, 99)),
           "max_ms": float(np.max(timings)), "target_p99_ms": LATENCY_TARGET_MS,
           "cpu": platform.processor() or platform.machine(), "cpu_count": os.cpu_count()}
verdict = "达标" if latency["p99_ms"] <= LATENCY_TARGET_MS else "未达标"
print(f"NumPy 单条时延：P50 {latency['p50_ms']:.2f} ms，P99 {latency['p99_ms']:.2f} ms（目标 ≤ {LATENCY_TARGET_MS:.0f} ms，{verdict}）")

STUDENT_REPORT = {"student_fingerprint": STUDENT_FINGERPRINT, "params": n_params, "npz_bytes": npz_bytes,
                  "training_options": EXPORT_CONFIG["training_options"],
                  "calibration": STUDENT_CAL, "holdout": student_json,
                  "parity": {"texts": len(parity_texts), "max_abs_diff": parity_max, "per_head": parity,
                             "implementation_only": parity_impl, "tolerance": PARITY_TOL},
                  "latency": latency}
temps = "，".join(f"{name} {t:.2f}" for name, t in STUDENT_CAL["temperatures"].items())
header = ["# 感知学生模型（字符级 CNN）", "",
          f"{n_params:,} 个参数；`student.npz` {npz_bytes / 1024:.1f} KB（上限 4 MB）。指纹 `{STUDENT_FINGERPRINT}`，教师 `{CONFIG_FINGERPRINT}`。",
          f"温度（留出集拟合）：{temps}。",
          f"C5 选项：教师 `{LOSS_BALANCE}`，学生 `{STUDENT_WIDTH}`（filters {STUDENT['filters']}，hidden {STUDENT['hidden']}），"
          f"蒸馏 `{KD_SOURCE}`（{len(kd_teachers)} 个教师），难负例权重 {HARD_NEGATIVE_WEIGHT}（{int(HARD_NEGATIVE_ROWS.sum())} 行）。",
          f"NumPy 对 PyTorch 概率最大绝对差 {parity_max:.2e}（{len(parity_texts)} 条，容差 {PARITY_TOL}）。",
          f"NumPy 单条时延（单线程，{latency['cpu']}）：P50 {latency['p50_ms']:.2f} ms，P99 {latency['p99_ms']:.2f} ms（目标 ≤ {LATENCY_TARGET_MS:.0f} ms，{verdict}）。", ""]
with open(PATHS["student_report"] + ".md", "w", encoding="utf-8") as f:
    f.write("\n".join(header + student_lines) + "\n")
with open(PATHS["student_report"] + ".json", "w", encoding="utf-8") as f:
    json.dump(STUDENT_REPORT, f, ensure_ascii=False, indent=2)
print("\n".join(header + student_lines))
""")

md(r"""
## 11. 测试集评估（每个测试集只运行一次）

- 教师、学生各自的等级：最大概率等级；过 ge2 阈值至少 L2；过 L3 阈值为 L3（各用自己的温度与阈值）。学生用导出的 NumPy 权重推理，与产品一致。
- 合并等级按 `crisis.py` 现行仲裁：规则 L3（Stage 1 命中）保持 L3；否则取规则与学生的较高者，最高 L2。
- “L3 开关打开”一栏模拟 `model_plan_evidence = True`：学生判为 L3 时也给 L3。只作参考。
""")

code(r"""
def combined_levels(rule, model_level, l3_switch=False):
    combined = np.where(rule == 3, 3, np.minimum(np.maximum(rule, model_level), 2))
    return np.where(model_level == 3, 3, combined) if l3_switch else combined


def summarize(ideal, predicted):
    def count(mask, cond):
        return int((mask & cond).sum()), int(mask.sum())
    rows = {
        "L3 判为 L3": count(ideal == 3, predicted == 3),
        "L3 判为 ≥L2（弹热线卡）": count(ideal == 3, predicted >= 2),
        "L2 判为 ≥L2": count(ideal == 2, predicted >= 2),
        "L2+L3 判为 ≥L2": count(ideal >= 2, predicted >= 2),
        "L1 判为 L1": count(ideal == 1, predicted == 1),
        "L0 误报为 ≥L2": count(ideal == 0, predicted >= 2),
        "L0 误报为 ≥L1": count(ideal == 0, predicted >= 1),
        "L0–L2 误判为 L3": count(ideal <= 2, predicted == 3),
    }
    return {name: {"hit": k, "n": n, "ci95": wilson(k, n)} for name, (k, n) in rows.items()}


def evaluate(role, frame):
    t_out = outputs_from_raw(predict_raw(teacher, frame), TEACHER_CAL["temperatures"])
    s_out = outputs_from_raw(np.stack([np_student.raw(t) for t in frame["text"]]), STUDENT_CAL["temperatures"])
    ideal, rule = frame["level"].to_numpy(), frame["rule_level"].to_numpy()
    t_level, s_level = model_levels(t_out["risk"], TEACHER_CAL), model_levels(s_out["risk"], STUDENT_CAL)
    combined, combined_l3 = combined_levels(rule, s_level), combined_levels(rule, s_level, l3_switch=True)
    predictions = frame[["id", "text", "level", "rule_level"]].rename(columns={"level": "ideal_level"}).assign(
        **{f"teacher_p_{n}": t_out["risk"][:, i].round(4) for i, n in enumerate(LEVEL_NAMES)}, teacher_level=t_level,
        **{f"student_p_{n}": s_out["risk"][:, i].round(4) for i, n in enumerate(LEVEL_NAMES)},
        student_crisis_confidence=s_out["crisis_confidence"].round(4), student_level=s_level,
        combined_level=combined, combined_level_l3_switch=combined_l3)
    predictions.to_csv(os.path.join(PATHS["reports"], f"{role}_predictions.csv"), index=False, encoding="utf-8")
    summary = {"test_set": TEST_SETS[role], "teacher_fingerprint": CONFIG_FINGERPRINT,
               "student_fingerprint": STUDENT_FINGERPRINT,
               "teacher_calibration": {k: v for k, v in TEACHER_CAL.items() if k != "oof"},
               "student_calibration": STUDENT_CAL,
               "per_head": {"teacher": head_metrics(frame, t_out), "student": head_metrics(frame, s_out)},
               "variants": {
                   "规则（现状）": summarize(ideal, rule),
                   "教师单独": summarize(ideal, t_level),
                   "学生单独": summarize(ideal, s_level),
                   "规则 + 学生（现行仲裁）": summarize(ideal, combined),
                   "规则 + 学生（L3 开关打开，仅参考）": summarize(ideal, combined_l3)}}
    with open(os.path.join(PATHS["reports"], f"{role}_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    names = list(next(iter(summary["variants"].values())))
    lines = [f"# 感知模型测试：{TEST_SETS[role]}", "",
             f"{len(frame)} 条。教师 `{CONFIG_FINGERPRINT}`，学生 `{STUDENT_FINGERPRINT}`；温度与阈值只用 OOF（教师）或留出集（学生）确定。区间为 Wilson 95% 置信区间。", "",
             "| 指标 | " + " | ".join(summary["variants"]) + " |",
             "| :--- | " + " | ".join(":---:" for _ in summary["variants"]) + " |"]
    for name in names:
        cells = [f"{v[name]['hit']}/{v[name]['n']}（{v[name]['ci95'][0]:.0%}–{v[name]['ci95'][1]:.0%}）"
                 for v in summary["variants"].values()]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "## 各头指标（只有带标签的头）", "", "| 模型 | 头 | 行数 | 准确率 | macro-F1 | MAE |",
              "| :--- | :--- | ---: | ---: | ---: | ---: |"]
    for who, metrics in summary["per_head"].items():
        for name, m in metrics.items():
            if "accuracy" in m:
                lines.append(f"| {who} | {name} | {m['n']} | {m['accuracy']:.3f} | {m['macro_f1']:.3f} | — |")
            else:
                lines.append(f"| {who} | {name} | {m['n']} | — | — | {m['mae']:.3f} |")
    sections = [
        ("规则漏判、规则 + 学生补上的句子", lambda r: r.ideal_level >= 2 and r.rule_level < 2 and r.combined_level >= 2),
        ("规则 + 学生仍然漏判（应为 ≥L2，合并 < L2）", lambda r: r.ideal_level >= 2 and r.combined_level < 2),
        ("新增误报（应为 L0，规则 < L2，合并 ≥ L2）", lambda r: r.ideal_level == 0 and r.rule_level < 2 and r.combined_level >= 2),
        ("学生把非 L3 判为 L3（L3 开关打开时会生效）", lambda r: r.ideal_level <= 2 and r.student_level == 3),
    ]
    for title, keep in sections:
        lines += ["", f"## {title}", ""]
        lines += [f"- {r.id}（应为 {LEVEL_NAMES[r.ideal_level]}，规则 {LEVEL_NAMES[r.rule_level]}，学生 {LEVEL_NAMES[r.student_level]}，"
                  f"合并 {LEVEL_NAMES[r.combined_level]}，学生 P(L2)+P(L3)={r.student_p_L2 + r.student_p_L3:.2f}，"
                  f"教师 P(L2)+P(L3)={r.teacher_p_L2 + r.teacher_p_L3:.2f}）{r.text}"
                  for r in predictions.itertuples() if keep(r)]
    with open(os.path.join(PATHS["reports"], f"{role}_summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


fingerprint = (f"{CONFIG_FINGERPRINT}:{STUDENT_FINGERPRINT}:{TEACHER_CAL['threshold_ge2']:.6f}:"
               f"{STUDENT_CAL['threshold_ge2']:.6f}:{STUDENT_CAL['threshold_l3']:.6f}")
for role, frame in tests.items():
    if frame.empty:
        print(f"测试集 {role} 为空，跳过（开发集、独立评估集需要在导出时用 --dev-eval、--fresh-eval 加入）。")
        continue
    marker = os.path.join(PATHS["reports"], f".evaluated_{role}")
    if role == DEV_ROLE:
        evaluate(role, frame)  # 开发集：每次都重测，不写标记
    elif os.path.exists(marker) and not FORCE_RETEST:
        with open(marker, encoding="utf-8") as f:
            previous = f.read().strip()
        print(f"测试集 {role} 已测过（{previous}），不重复测试；下面显示上次的结果。")
        if not previous.startswith(fingerprint + " "):
            print("注意：模型或阈值与上次测试时不同；上次的结果不代表当前模型，按规定也不重测。")
    else:
        evaluate(role, frame)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(f"{fingerprint} @ {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    with open(os.path.join(PATHS["reports"], f"{role}_summary.md"), encoding="utf-8") as f:
        print(f.read())
""")

md(r"""
## 12. 怎么读结果

- 先看第 7 节的教师 OOF 报告：各头的准确率 / macro-F1 / MAE 说明 9 个头是否都学到了东西；`L2+L3 判为 ≥L2` 应接近 98%，`L0 误报` 与 `HYPERBOLE` 一行是代价。它们来自同源句子，偏乐观。
- 再看第 10 节：学生在留出集上与教师差多少、`student.npz` 是否 < 4 MB、NumPy 一致性与时延是否达标。
- 独立评估集（`fresh`）是唯一能下结论的数字：**“L2+L3 判为 ≥L2”** 和 **“L0 误报为 ≥L2”** 两行要一起看，主要看“规则 + 学生（现行仲裁）”一栏，这是产品接入学生模型后的行为。
- 是否打开 `model_plan_evidence`：看“L3 开关打开”一栏的 `L3 判为 L3` 与 `L0–L2 误判为 L3`。开发计划的条件是独立评估集上普通句被判 L3 为 0 且 L3 召回达标。
- 52 句探针（`probe`）的结果只作参考，不能用来证明改进，也不能用来调阈值。
- 开发集（`dev`）可以反复看、用来比较各轮或各种结构（`student_arch_experiment.ipynb` 就按它选学生结构），但正因为用来选择，它的数字会偏乐观；结论仍以独立评估集为准。
""")

code(r"""
# 各产出文件是否存在及大小
outputs = [PATHS["teacher"], PATHS["teacher_config"], PATHS["teacher_calibration"], PATHS["oof"],
           PATHS["cv_report"] + ".md", PATHS["teacher_targets"], PATHS["student_ckpt"], PATHS["student_npz"],
           PATHS["student_vocab"], PATHS["student_config"], PATHS["student_report"] + ".md"]
outputs += [os.path.join(PATHS["fold_dir"], f"fold_{k}.npz") for k in range(CV_FOLDS)]
for role in TEST_SETS:
    outputs += [os.path.join(PATHS["reports"], f"{role}_{suffix}") for suffix in ("predictions.csv", "summary.md", "summary.json")]
for path in outputs:
    size = f"{os.path.getsize(path) / 1024:.1f} KB" if os.path.exists(path) else "缺失"
    print(f"{size:>12s}  {path}")
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
