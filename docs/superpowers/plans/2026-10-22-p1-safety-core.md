# P1 安全主链（规则模式） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对任意一轮用户输入给出危机等级（L0~L3）与红线病种集合，并在会话中正确进入、升级与退出危机态，全部以规则与词表实现、离线运行。

**Architecture:** 新建 `olivia/core/safety/` 子包。文本先做规范化（`normalize.py`），用纯 Python 的 Aho-Corasick 匹配器（`matcher.py`）在两份数据词表（`olivia/data/lexicons/*.yaml`，由 `lexicon.py` 加载并校验）上查找线索。`crisis.py` 实现 Stage 1（明确计划/工具/时限 → 直接 L3）、Stage 2 规则评分（`RuleRiskModel`，口癖与否定句先屏蔽）与双头取高仲裁；`tracker.py` 维护跨轮状态（EWMA 升级、危机进入与双重确认退出）；`red_flags.py` 识别 7 个红线病种。阈值全部来自 P0 的 `Taxonomy`。

**Tech Stack:** Python 3.11、PyYAML；不新增运行时依赖（Aho-Corasick 自行实现）。

**Spec:** `docs/DEVELOPMENT_PLAN.md`（§5 P1、§7）、`docs/PRODUCT_DOCUMENT.md`（§6.1 SAFE-09、§9.1、§9.3、MIYI-02）、`docs/SYSTEM_DESIGN.md`（§8.1、§8.2、§10.1）、`taxonomy.yaml`（`risk`、`crisis_hierarchy`、`clinical_red_flags`）。

## 本计划替你做出的取舍（开工前可推翻）

PRD/SDD 对以下几点没有写死，计划先按下面执行，不同意可直接改本节再开工：

1. **L1 升级 L2 的判定**：同时满足 ① 最近 `risk.ewma_streak`（3）个 L1 轮次构成连续段；② EWMA 分数 ≥ `risk.ewma_escalate`（0.45）；③ 若这些轮次都提供了情感极性 `valence`，则极性严格递减（规则模式下没有 valence，只看 ①②）。EWMA 以第一个参与计算的轮次分数作为初值，`s_t = λ·score_t + (1-λ)·s_{t-1}`，λ = `risk.ewma_lambda`（0.5）；只有评估等级 ≥ L1 的轮次参与 EWMA，L0 轮次不更新它（否则一句闲聊就会把分数拉低）。L1 词条默认 0.4，因此只有反复出现较强的 L1 线索（词条自带 0.45~0.49 分）才会升级。
2. **“连续”怎么算**：两个 L1 轮次之间夹着零星的 L0 轮次不打断连续段；只有连续 `risk.l1_clear_streak`（3）个 L0 轮次才清零 L1 连续段与 EWMA。
3. **否定句只屏蔽 Stage 2**：“我没想过买药”这类否定若恰好包含 Stage 1 工具线索，仍判 L3（宁可误报，不可漏报）。
4. **红线识别不区分第三人称**：“我朋友有双相”也会激活 SIT-02-04。红线只会收紧可用动作，误报代价低于漏报。
5. **画像里的未知红线代码直接报错**（`UnknownRedFlagError`），不静默忽略；首访录入时的校验留给 P4。
6. **截断常量**：SDD §10.1 的“开头 128 字 + 结尾 256 字”不在 taxonomy 中，作为 `normalize.py` 中带出处注释的命名常量。

## Global Constraints

- 继承 P0 全部约束：Python `>=3.11`；运行时依赖只有 `PyYAML>=6.0` 与 `platformdirs>=4.0`（本阶段不新增）；UTF-8；`bash scripts/check.sh` 全绿；提交信息用 Conventional Commits，不加任何 AI 署名行。
- 所有阈值、分数、等级区间、连续轮次只从 `Taxonomy` 读取：`risk.lexicon_scores.*`、`risk.ewma_lambda`、`risk.ewma_escalate`、`risk.ewma_streak`、`risk.l1_clear_streak`、`crisis_level_for_score()`、`crisis_exit_safe_turns()`、`red_flags()`。代码中不出现这些数值。
- 危机检测先于一切业务分支：`SafetyScreen.assess` 不看电量前缀、纯倾听锁或任何会话状态；输入里的 `[5%]` 等前缀原样参与匹配。
- 隐私：评估结果只携带词条 id（`cue_ids`），绝不携带用户原文片段；本阶段代码不写任何日志。
- 词表是数据文件，放在 `olivia/data/lexicons/`，通过 `importlib.resources` 读取，并加入 `pyproject.toml` 的 package-data。
- 性能：单轮 `SafetyScreen.assess`（Stage 1 + Stage 2，不含感知模型）对 500 字以内输入 P99 < 1 ms。

## Review Focus

1. **口癖里包含危机字样**（“想死的心都有了”“累死了”）：不得判 L2，最高 L0。→ Task 3 `test_hyperbole_is_not_ideation`。
2. **否定句后接工具线索**（“我不想死，但药已经买好了”）：判 L3，且 `has_plan_evidence` 为真。→ Task 3 `test_negation_does_not_hide_means`。
3. **长消息只在结尾出现危机线索**：`assess` 对全文检测；`clip_for_perception` 保留结尾 256 字，线索仍在。→ Task 1 `test_clip_keeps_tail`、Task 3 `test_cue_at_end_of_long_text`。
4. **全角、空格、大小写变体**（“想 死”“ＰＴＳＤ”“bpd”）：规范化后照常命中。→ Task 1 `test_normalize_variants`、Task 5 `test_self_report_variants`。
5. **危机中的“确认安全”与危机线索同时出现**（“我现在安全了，但还是想死”）：本轮按 L2 处理，确认无效，仍在危机态。→ Task 4 `test_confirmation_inside_crisis_message_is_ignored`。

---

## File Structure

| 文件 | 职责 |
| :--- | :--- |
| `olivia/core/safety/__init__.py` | 包标记 |
| `olivia/core/safety/normalize.py` | 文本规范化、感知输入截断 |
| `olivia/core/safety/matcher.py` | Aho-Corasick 多模式匹配 |
| `olivia/data/lexicons/risk.yaml` | 危机词表（Stage 1、Stage 2、口癖、否定、安全确认） |
| `olivia/data/lexicons/red_flags.yaml` | 红线病种词表 |
| `olivia/core/safety/lexicon.py` | 词表加载与校验 |
| `olivia/core/safety/crisis.py` | Stage 1、规则评分模型、仲裁、`SafetyScreen` |
| `olivia/core/safety/tracker.py` | 跨轮 EWMA 升级、危机进入与退出 |
| `olivia/core/safety/red_flags.py` | 红线识别（P3 会在同一文件加掩码） |
| `tests/safety/...` | 单元测试、安全用例集、多轮会话场景、性能测试 |

---

### Task 1: 文本规范化与多模式匹配器

**Files:**
- Create: `olivia/core/safety/__init__.py`、`olivia/core/safety/normalize.py`、`olivia/core/safety/matcher.py`、`tests/safety/test_normalize.py`、`tests/safety/test_matcher.py`

**Interfaces:**
- Produces（`olivia.core.safety.normalize`）：
  - `PERCEPTION_HEAD: Final = 128`、`PERCEPTION_TAIL: Final = 256`（注释注明出处 SDD §10.1）
  - `def normalize(text: str) -> str`：NFKC → `casefold()` → 删除所有空白字符（`str.isspace()` 为真者）与零宽字符 `​ ‌ ‍ ⁠ ﻿`
  - `def clip_for_perception(text: str) -> str`：长度 ≤ `PERCEPTION_HEAD + PERCEPTION_TAIL` 原样返回，否则返回 `text[:128] + text[-256:]`
- Produces（`olivia.core.safety.matcher`）：
  - `@dataclass(frozen=True) class Match`: `key: str`, `start: int`, `end: int`（`end` 不含）
  - `class PhraseMatcher`：`__init__(self, phrases: Mapping[str, str])`（短语 → key；空短语抛 `ValueError`）；`find_all(self, text: str) -> list[Match]` 返回所有出现（含重叠），按 `(start, end)` 排序

- [ ] **Step 1: 写失败测试**

`tests/safety/test_normalize.py`：

```python
import pytest
from olivia.core.safety.normalize import (PERCEPTION_HEAD, PERCEPTION_TAIL,
                                          clip_for_perception, normalize)

@pytest.mark.parametrize("raw,expected", [
    ("想 死", "想死"),
    ("想​死", "想死"),
    ("ＰＴＳＤ", "ptsd"),
    ("BPD", "bpd"),
    ("［５％］ 不想活了", "[5%]不想活了"),
    ("\t活着\n好累 ", "活着好累"),
])
def test_normalize_variants(raw, expected):
    assert normalize(raw) == expected

def test_clip_short_text_unchanged():
    text = "好" * (PERCEPTION_HEAD + PERCEPTION_TAIL)
    assert clip_for_perception(text) == text

def test_clip_keeps_tail():
    text = "a" * 1000 + "药已经买好了"
    clipped = clip_for_perception(text)
    assert len(clipped) == 384
    assert clipped.startswith("a" * 128) and clipped.endswith("药已经买好了")
```

`tests/safety/test_matcher.py`：

```python
import pytest
from olivia.core.safety.matcher import Match, PhraseMatcher

def test_finds_overlapping_phrases():
    m = PhraseMatcher({"想死": "L2", "想死的心都有了": "HYP", "死": "X"})
    found = m.find_all("我想死的心都有了")
    assert Match("L2", 1, 3) in found and Match("HYP", 1, 8) in found and Match("X", 2, 3) in found
    assert found == sorted(found, key=lambda x: (x.start, x.end))

def test_repeated_occurrences():
    assert [x.start for x in PhraseMatcher({"累": "K"}).find_all("累累累")] == [0, 1, 2]

def test_no_match_returns_empty():
    assert PhraseMatcher({"想死": "K"}).find_all("今天天气不错") == []

def test_empty_phrase_rejected():
    with pytest.raises(ValueError):
        PhraseMatcher({"": "K"})
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/safety -q`
Expected: FAIL（`ModuleNotFoundError: olivia.core.safety`）

- [ ] **Step 3: 实现**

`PhraseMatcher` 用标准 Aho-Corasick：构建 trie（dict 子节点）、BFS 计算失败指针、每个节点合并输出列表；`find_all` 单次扫描。同一短语映射到同一 key；不同短语可映射到同一 key。

- [ ] **Step 4: 运行确认通过**

Run: `bash scripts/check.sh`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add olivia/core/safety tests/safety
git commit -m "feat(safety): add text normalization and Aho-Corasick phrase matcher"
```

---

### Task 2: 安全词表数据与加载校验

**Files:**
- Create: `olivia/data/lexicons/risk.yaml`、`olivia/data/lexicons/red_flags.yaml`、`olivia/core/safety/lexicon.py`、`tests/safety/test_lexicon.py`
- Modify: `pyproject.toml`（package-data 增加 `"data/lexicons/*.yaml"`）

**Interfaces:**
- Consumes: P0 `Taxonomy`（`threshold`、`crisis_level_for_score`、`red_flags`）、`CrisisLevel`；Task 1 `normalize`
- Produces（`olivia.core.safety.lexicon`）：
  - `class LexiconError(Exception)`
  - `RiskSection = Literal["stage1", "stage2", "hyperbole", "negation", "safety_confirm"]`
  - `@dataclass(frozen=True) class RiskCue`: `id: str`, `section: RiskSection`, `level: CrisisLevel | None`, `score: float | None`, `patterns: tuple[str, ...]`
    - `stage1`：`level = L3`，`score` 默认 `risk.lexicon_scores.L3`
    - `stage2`：`level ∈ {L1, L2}`（必填），`score` 默认 `risk.lexicon_scores.<level>`，若词条给出 `score` 则必须满足 `tax.crisis_level_for_score(score) == level`
    - `hyperbole`：`level = L0`，`score = risk.lexicon_scores.HYPERBOLE`
    - `negation`、`safety_confirm`：`level = None`，`score = None`
  - `@dataclass(frozen=True) class RedFlagCue`: `id: str`, `code: str`, `tier: Literal["SELF_REPORT", "FEATURE"]`, `patterns: tuple[str, ...]`
  - `@dataclass(frozen=True) class SafetyLexicons`: `risk: Mapping[str, RiskCue]`, `red_flags: Mapping[str, RedFlagCue]`, `self_report_negations: tuple[str, ...]`；方法 `cues(self, section: RiskSection) -> tuple[RiskCue, ...]`
  - `def load_safety_lexicons(tax: Taxonomy, directory: Path | None = None) -> SafetyLexicons`：`None` 时读包内 `olivia/data/lexicons/`；所有 `patterns` 与 `self_report_negations` 在加载时经 `normalize` 处理后保存
- 加载时校验，失败抛 `LexiconError` 并说明是哪个词条：
  1. 两个文件中所有 `id` 全局唯一；
  2. 每个词条 `patterns` 非空，规范化后无空串；
  3. 同一规范化短语不得出现在两个不同 section（或两个不同红线 code）中；
  4. `stage2` 的 `level` 只能是 `L1` / `L2`，自带 `score` 须落在该等级区间；
  5. `red_flags.yaml` 的 `code` 必须在 `tax.red_flags()` 中，且 7 个 code 每个至少有一条 `SELF_REPORT` 与一条 `FEATURE`；
  6. 两个文件顶层 `version: 1`。

**`olivia/data/lexicons/risk.yaml` 初始内容（逐字使用；Task 6 会按用例集扩充）：**

```yaml
version: 1
stage1:
  - id: S1_MEANS_PILLS
    patterns: ["药已经买好", "药买好了", "买好了药", "攒了很多安眠药", "攒够了药", "囤了一瓶安眠药"]
  - id: S1_MEANS_ROPE_BLADE
    patterns: ["绳子已经准备好", "准备好了绳子", "刀已经准备好", "准备好了刀片"]
  - id: S1_NOTE_WRITTEN
    patterns: ["遗书写好了", "写好了遗书", "已经写好遗书"]
  - id: S1_TIME_PLACE
    patterns: ["今晚就去跳", "今晚就结束自己", "明天就去死", "站在楼顶上了", "已经在天台上", "已经在桥边了"]
  - id: S1_ACT_IN_PROGRESS
    patterns: ["已经吞了药", "吃了一整瓶药", "已经割了", "正在割腕", "血止不住"]
  - id: S1_FAREWELL
    patterns: ["再见了这个世界", "这是我最后一次跟你说话"]
stage2:
  - id: L2_WANT_DIE
    level: L2
    patterns: ["想死", "想去死", "想自杀"]
  - id: L2_NOT_WANT_LIVE
    level: L2
    patterns: ["不想活了", "活不下去了", "不想再活下去", "死了算了", "不如死了"]
  - id: L2_END_LIFE
    level: L2
    patterns: ["想结束自己的生命", "想离开这个世界"]
  - id: L1_WEARY
    level: L1
    patterns: ["活着好累", "活着没意思", "活着没有意义", "人生没有意义"]
  - id: L1_SLEEP_NO_WAKE
    level: L1
    score: 0.48
    patterns: ["想彻底睡过去", "睡着了就不要醒来", "不想醒来"]
  - id: L1_DISAPPEAR
    level: L1
    score: 0.45
    patterns: ["消失就好了", "想消失"]
hyperbole:
  - id: HYP_DEATH_IDIOM
    patterns: ["想死的心都有了", "要死要死"]
  - id: HYP_X_TO_DEATH
    patterns: ["累死了", "累死我了", "烦死了", "气死了", "气死我了", "笑死", "困死了", "饿死了", "热死了", "尴尬死了", "社死"]
negation:
  - id: NEG_NOT_DIE
    patterns: ["不想死", "没想死", "没有想死", "不是想死", "不会去死"]
  - id: NEG_NOT_SUICIDE
    patterns: ["不会自杀", "不想自杀", "没想过自杀", "绝不想自杀"]
safety_confirm:
  - id: CONFIRM_SAFE_NOW
    patterns: ["我现在安全了", "我已经安全了", "我现在没事了", "我不会做傻事"]
  - id: CONFIRM_REACHED_SUPPORT
    patterns: ["我联系上朋友了", "我已经联系了家人", "我给热线打过电话了", "家人在我身边了"]
  - id: CONFIRM_TOPIC_SHIFT
    patterns: ["想聊点别的"]
```

**`olivia/data/lexicons/red_flags.yaml` 初始内容（逐字使用）：**

```yaml
version: 1
self_report_negations: ["没有", "不是", "并没有", "并非", "没"]
entries:
  - {id: RF_BIPOLAR_SELF, code: SIT-02-04, tier: SELF_REPORT, patterns: ["双相", "躁郁症", "躁狂发作"]}
  - {id: RF_BIPOLAR_FEAT, code: SIT-02-04, tier: FEATURE, patterns: ["几天不睡觉也不困", "好几天不用睡觉"]}
  - {id: RF_PERINATAL_SELF, code: SIT-02-06, tier: SELF_REPORT, patterns: ["产后抑郁", "围产期抑郁", "孕期抑郁", "产后焦虑"]}
  - {id: RF_PERINATAL_FEAT, code: SIT-02-06, tier: FEATURE, patterns: ["生完孩子后一直哭", "生完宝宝以后天天哭"]}
  - {id: RF_PTSD_SELF, code: SIT-06-01, tier: SELF_REPORT, patterns: ["创伤后应激", "ptsd", "急性应激障碍"]}
  - {id: RF_PTSD_FEAT, code: SIT-06-01, tier: FEATURE, patterns: ["闪回停不下来", "一直闪回", "那天的画面一直闪回"]}
  - {id: RF_DISSOC_SELF, code: SIT-06-05, tier: SELF_REPORT, patterns: ["人格解体", "现实解体", "解离症", "解离障碍"]}
  - {id: RF_DISSOC_FEAT, code: SIT-06-05, tier: FEATURE, patterns: ["感觉自己不真实", "像在看别人的生活", "灵魂出窍"]}
  - {id: RF_ANOREXIA_SELF, code: SIT-08-04, tier: SELF_REPORT, patterns: ["厌食症", "神经性厌食"]}
  - {id: RF_ANOREXIA_FEAT, code: SIT-08-04, tier: FEATURE, patterns: ["连续三天没吃东西", "好几天没吃饭", "故意不吃饭"]}
  - {id: RF_BPD_SELF, code: SIT-09-01, tier: SELF_REPORT, patterns: ["边缘型人格", "边缘人格", "bpd"]}
  - {id: RF_BPD_FEAT, code: SIT-09-01, tier: FEATURE, patterns: ["自伤手臂", "划手臂", "用刀划自己"]}
  - {id: RF_SUBSTANCE_SELF, code: SIT-10-04, tier: SELF_REPORT, patterns: ["酒精依赖", "酒瘾", "药物依赖", "毒瘾"]}
  - {id: RF_SUBSTANCE_FEAT, code: SIT-10-04, tier: FEATURE, patterns: ["每天都要喝酒才能睡", "不喝酒手就抖"]}
```

- [ ] **Step 1: 写失败测试** `tests/safety/test_lexicon.py`

```python
from pathlib import Path
import shutil
import pytest
import yaml
from olivia.core.models import CrisisLevel
from olivia.core.safety.lexicon import LexiconError, load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

PKG_LEX = Path(__file__).resolve().parents[2] / "olivia/data/lexicons"

@pytest.fixture(scope="module")
def tax():
    return load_taxonomy()

def test_loads_packaged_lexicons(tax):
    lex = load_safety_lexicons(tax)
    assert lex.risk["S1_MEANS_PILLS"].level is CrisisLevel.L3
    assert lex.risk["S1_MEANS_PILLS"].score == pytest.approx(0.9)
    assert lex.risk["L2_WANT_DIE"].score == pytest.approx(0.7)
    assert lex.risk["L1_WEARY"].score == pytest.approx(0.4)
    assert lex.risk["L1_SLEEP_NO_WAKE"].score == pytest.approx(0.48)
    assert lex.risk["HYP_X_TO_DEATH"].level is CrisisLevel.L0
    assert lex.risk["HYP_X_TO_DEATH"].score == pytest.approx(0.1)
    assert lex.risk["NEG_NOT_DIE"].level is None
    assert {c.code for c in lex.red_flags.values()} == set(tax.red_flags())
    assert "ptsd" in lex.red_flags["RF_PTSD_SELF"].patterns

def test_sections(tax):
    lex = load_safety_lexicons(tax)
    assert {c.id for c in lex.cues("safety_confirm")} == {
        "CONFIRM_SAFE_NOW", "CONFIRM_REACHED_SUPPORT", "CONFIRM_TOPIC_SHIFT"}

def _copy(tmp_path, mutate_risk=None, mutate_rf=None):
    d = tmp_path / "lex"
    shutil.copytree(PKG_LEX, d)
    for name, mutate in (("risk.yaml", mutate_risk), ("red_flags.yaml", mutate_rf)):
        if mutate:
            data = yaml.safe_load((d / name).read_text(encoding="utf-8"))
            mutate(data)
            (d / name).write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return d

def test_rejects_duplicate_id(tax, tmp_path):
    def m(d): d["stage2"].append({"id": "S1_MEANS_PILLS", "level": "L2", "patterns": ["x"]})
    with pytest.raises(LexiconError, match="S1_MEANS_PILLS"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))

def test_rejects_score_outside_level_band(tax, tmp_path):
    def m(d): d["stage2"][0]["score"] = 0.85
    with pytest.raises(LexiconError, match="L2_WANT_DIE"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))

def test_rejects_pattern_in_two_sections(tax, tmp_path):
    def m(d): d["negation"][0]["patterns"].append("想死")
    with pytest.raises(LexiconError, match="想死"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))

def test_rejects_stage2_level_l3(tax, tmp_path):
    def m(d): d["stage2"][0]["level"] = "L3"
    with pytest.raises(LexiconError, match="L2_WANT_DIE"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))

def test_rejects_unknown_red_flag_code(tax, tmp_path):
    def m(d): d["entries"][0]["code"] = "SIT-99-99"
    with pytest.raises(LexiconError, match="SIT-99-99"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_rf=m))

def test_rejects_code_without_feature_tier(tax, tmp_path):
    def m(d): d["entries"] = [e for e in d["entries"] if e["id"] != "RF_BPD_FEAT"]
    with pytest.raises(LexiconError, match="SIT-09-01"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_rf=m))

def test_rejects_empty_patterns(tax, tmp_path):
    def m(d): d["hyperbole"][0]["patterns"] = []
    with pytest.raises(LexiconError, match="HYP_DEATH_IDIOM"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/safety/test_lexicon.py -q`
Expected: FAIL（`ModuleNotFoundError: olivia.core.safety.lexicon`）

- [ ] **Step 3: 写两份词表文件、修改 package-data、实现 `lexicon.py`**

- [ ] **Step 4: 运行确认通过**

Run: `bash scripts/check.sh`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add olivia/data/lexicons olivia/core/safety/lexicon.py tests/safety/test_lexicon.py pyproject.toml
git commit -m "feat(safety): add crisis and red-flag lexicons with load-time validation"
```

---

### Task 3: 两阶段危机评估与仲裁

**Files:**
- Create: `olivia/core/safety/crisis.py`、`tests/safety/test_crisis.py`

**Interfaces:**
- Consumes: Task 1 `normalize`、`PhraseMatcher`；Task 2 `SafetyLexicons`、`RiskCue`；P0 `Taxonomy.crisis_level_for_score`、`CrisisLevel`
- Produces（`olivia.core.safety.crisis`）：
  - `@dataclass(frozen=True) class RiskPrediction`: `level: CrisisLevel`, `score: float`, `cue_ids: tuple[str, ...]`
  - `class RiskModel(Protocol)`: `def predict(self, text: str) -> RiskPrediction: ...` —— R2 的八头感知模型将实现同一协议（`level` 对应四分类头 L_cls，`score` 对应危机置信度头）
  - `class RuleRiskModel`：`__init__(self, tax: Taxonomy, lexicons: SafetyLexicons)`；`predict(self, text: str) -> RiskPrediction`
  - `def arbitrate(tax: Taxonomy, l_cls: CrisisLevel, score: float, has_plan_evidence: bool) -> CrisisLevel`
  - `@dataclass(frozen=True) class CrisisAssessment`: `level: CrisisLevel`, `score: float`, `stage: Literal["STAGE1", "STAGE2"]`, `has_plan_evidence: bool`, `cue_ids: tuple[str, ...]`
  - `class SafetyScreen`：`__init__(self, tax: Taxonomy, lexicons: SafetyLexicons, model: RiskModel | None = None)`（`None` 时用 `RuleRiskModel`）；`assess(self, text: str) -> CrisisAssessment`

**算法（`assess`）：**

1. `t = normalize(text)`，对全文处理，不截断。
2. Stage 1：在 `t` 上匹配 `stage1` 词条。有命中 → 返回 `level=L3`、`score=命中词条最高分`、`stage="STAGE1"`、`has_plan_evidence=True`、`cue_ids=命中 id（去重、按首次出现排序）`。
3. Stage 2：`prediction = model.predict(text)`；`level = arbitrate(tax, prediction.level, prediction.score, has_plan_evidence=False)`；返回 `stage="STAGE2"`。

**`RuleRiskModel.predict` 算法：**

1. 在规范化文本上匹配 `hyperbole` 与 `negation` 短语，它们的区间构成“屏蔽区”。
2. 匹配 `stage2` 短语；完全落在某个屏蔽区内的命中作废（例如“想死”落在“想死的心都有了”或“不想死”之内）。
3. 有效 `stage2` 命中 → `score = 最高分`，`level = 该分对应等级`，`cue_ids` 为有效命中 id。
4. 否则若有 `hyperbole` 命中 → `score = risk.lexicon_scores.HYPERBOLE`、`level = L0`、`cue_ids` 为口癖 id。
5. 否则 → `score = risk.lexicon_scores.L0`、`level = L0`、`cue_ids = ()`。

**`arbitrate`：** `level = max(l_cls, tax.crisis_level_for_score(score))`；若 `level is L3` 且 `not has_plan_evidence` → 返回 `L2`。

- [ ] **Step 1: 写失败测试** `tests/safety/test_crisis.py`

```python
import pytest
from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import RiskPrediction, SafetyScreen, arbitrate
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

@pytest.fixture(scope="module")
def tax():
    return load_taxonomy()

@pytest.fixture(scope="module")
def screen(tax):
    return SafetyScreen(tax, load_safety_lexicons(tax))

@pytest.mark.parametrize("text,level,stage", [
    ("今天开会好累，想早点下班", L.L0, "STAGE2"),
    ("活着好累，每天都一样", L.L1, "STAGE2"),
    ("我真的想死", L.L2, "STAGE2"),
    ("[5%] 不想活了", L.L2, "STAGE2"),
    ("药已经买好了，今晚", L.L3, "STAGE1"),
    ("遗书写好了", L.L3, "STAGE1"),
])
def test_levels(screen, text, level, stage):
    a = screen.assess(text)
    assert (a.level, a.stage) == (level, stage)

@pytest.mark.parametrize("text", ["想死的心都有了", "加班到十点，累死了", "这个视频笑死"])
def test_hyperbole_is_not_ideation(screen, text):
    a = screen.assess(text)
    assert a.level is L.L0 and a.score == pytest.approx(0.1)

@pytest.mark.parametrize("text", ["其实我不想死，只是太累了", "我绝不想自杀", "我没想过自杀"])
def test_pure_negation_scores_below_point_15(screen, text):  # MIYI-02 第一条
    a = screen.assess(text)
    assert a.level is L.L0 and a.score < 0.15

def test_negation_does_not_hide_means(screen):  # MIYI-02 第二条
    a = screen.assess("我不想死，但药已经买好了")
    assert a.level is L.L3 and a.score >= 0.8 and a.has_plan_evidence
    assert a.cue_ids == ("S1_MEANS_PILLS",)

def test_negation_does_not_hide_other_ideation(screen):
    assert screen.assess("我不想死，可是真的活不下去了").level is L.L2

def test_cue_at_end_of_long_text(screen):
    a = screen.assess("今天发生了很多事。" * 120 + "我想结束自己的生命")
    assert a.level is L.L2

def test_variants_are_normalized(screen):
    assert screen.assess("我 想 死").level is L.L2
    assert screen.assess("遗书 写好了").level is L.L3

def test_assessment_carries_cue_ids_not_text(screen):
    a = screen.assess("我真的想死")
    assert a.cue_ids == ("L2_WANT_DIE",)
    assert all("想" not in cue for cue in a.cue_ids)

def test_strongest_stage2_cue_wins(screen):
    a = screen.assess("活着好累，不想活了")
    assert a.level is L.L2 and a.score == pytest.approx(0.7)
    assert set(a.cue_ids) == {"L1_WEARY", "L2_NOT_WANT_LIVE"}

@pytest.mark.parametrize("l_cls,score,evidence,expected", [
    (L.L1, 0.6, False, L.L2),   # 取高
    (L.L2, 0.1, False, L.L2),   # 取高
    (L.L3, 0.9, False, L.L2),   # 无证据降级
    (L.L1, 0.85, False, L.L2),  # 分数 L3 无证据降级
    (L.L3, 0.9, True, L.L3),
    (L.L0, 0.0, False, L.L0),
])
def test_arbitrate(tax, l_cls, score, evidence, expected):
    assert arbitrate(tax, l_cls, score, evidence) is expected

def test_model_l3_without_evidence_is_downgraded(tax):
    class FakeModel:
        def predict(self, text):
            return RiskPrediction(L.L3, 0.95, ())
    a = SafetyScreen(tax, load_safety_lexicons(tax), FakeModel()).assess("随便说点什么")
    assert a.level is L.L2 and a.stage == "STAGE2" and not a.has_plan_evidence
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/safety/test_crisis.py -q`
Expected: FAIL（`ModuleNotFoundError: olivia.core.safety.crisis`）

- [ ] **Step 3: 按上述算法实现 `crisis.py`**

为满足 P99 < 1 ms，`RuleRiskModel` 与 `SafetyScreen` 共用**一个** `PhraseMatcher`，覆盖 `stage1`、`stage2`、`hyperbole`、`negation` 四个 section 的全部短语（Task 2 已保证同一短语只属于一个词条，所以 key 用词条 id 即可，section 从词条反查）；每轮只扫描一次文本，Stage 1 与 Stage 2 复用同一次扫描结果。`assess` 不读取任何会话状态。

- [ ] **Step 4: 运行确认通过**

Run: `bash scripts/check.sh`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add olivia/core/safety/crisis.py tests/safety/test_crisis.py
git commit -m "feat(safety): add two-stage crisis assessment with safety-first arbitration"
```

---

### Task 4: 跨轮危机状态跟踪

**Files:**
- Create: `olivia/core/safety/tracker.py`、`tests/safety/test_tracker.py`

**Interfaces:**
- Consumes: Task 3 `CrisisAssessment`；Task 2 `SafetyLexicons.cues("safety_confirm")`；Task 1 `normalize`、`PhraseMatcher`；P0 `Taxonomy.threshold`、`crisis_exit_safe_turns`
- Produces（`olivia.core.safety.tracker`）：
  - `@dataclass(frozen=True) class CrisisStatus`: `level: CrisisLevel`（本轮生效等级，含升级）、`in_crisis: bool`、`entry_level: CrisisLevel | None`、`escalated: bool`、`awaiting_confirmation: bool`、`safe_turns_remaining: int`、`just_entered: bool`、`just_exited: bool`
  - `class CrisisTracker`：`__init__(self, tax: Taxonomy, lexicons: SafetyLexicons)`；`observe(self, assessment: CrisisAssessment, text: str, valence: float | None = None) -> CrisisStatus`

**状态与规则（每轮调用一次 `observe`）：**

- **EWMA**：只在评估等级 ≥ L1 的轮次更新；尚无值时 `ewma = score`，之后 `ewma = λ·score + (1-λ)·ewma`，λ = `risk.ewma_lambda`。L0 轮次不改变 EWMA。
- **L1 连续段**：本轮评估为 L1 → 连续段计数 +1，记录本轮 `valence`；评估为 L0 → L0 连续计数 +1，达到 `risk.l1_clear_streak` 时清空 L1 连续段并令下一次观察重新初始化 EWMA；评估为 L1 时 L0 连续计数归零。
- **升级**：本轮评估为 L1，且 L1 连续段 ≥ `risk.ewma_streak`，且 `ewma ≥ risk.ewma_escalate`，且（连续段内最近 `ewma_streak` 轮都有 valence 时）valence 严格递减 → 本轮生效等级为 L2，`escalated=True`。
- **进入危机**：生效等级 ≥ L2 → `in_crisis=True`；若此前不在危机态则 `entry_level = 本轮等级`、`just_entered=True`；若已在危机态则 `entry_level = max(entry_level, 本轮等级)`；同时清除已有的安全确认与安全轮次计数。
- **安全确认**：处于危机态、本轮生效等级 ≤ L1、且规范化文本命中任一 `safety_confirm` 短语 → 记为已确认；确认所在这一轮不计入安全轮次。
- **退出**：已确认后，每个生效等级 ≤ L1 的后续轮次让安全轮次 +1；达到 `tax.crisis_exit_safe_turns(entry_level)` → `in_crisis=False`、`entry_level=None`、`just_exited=True`，并清空 L1 连续段与 EWMA。
- **派生字段**：`awaiting_confirmation = in_crisis and 尚未确认`；`safe_turns_remaining = 在危机态且已确认时为 N - 已有安全轮次，否则为 N（在危机态未确认）或 0（不在危机态）`。

- [ ] **Step 1: 写失败测试** `tests/safety/test_tracker.py`

```python
import pytest
from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import CrisisAssessment, SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.tracker import CrisisTracker
from olivia.core.taxonomy import load_taxonomy

@pytest.fixture(scope="module")
def tax():
    return load_taxonomy()

@pytest.fixture(scope="module")
def lex(tax):
    return load_safety_lexicons(tax)

@pytest.fixture
def run(tax, lex):
    screen = SafetyScreen(tax, lex)
    tracker = CrisisTracker(tax, lex)
    return lambda text, valence=None: tracker.observe(screen.assess(text), text, valence)

def _a(level, score):
    return CrisisAssessment(level=level, score=score, stage="STAGE2", has_plan_evidence=False, cue_ids=())

def test_plain_l1_does_not_escalate(run):
    statuses = [run("活着好累") for _ in range(5)]
    assert all(s.level is L.L1 and not s.in_crisis for s in statuses)

def test_strong_l1_escalates_on_third_turn(run):
    s1, s2, s3 = (run("想彻底睡过去") for _ in range(3))
    assert s1.level is L.L1 and s2.level is L.L1
    assert s3.level is L.L2 and s3.escalated and s3.in_crisis and s3.just_entered

def test_valence_must_worsen_when_given(tax, lex):
    t = CrisisTracker(tax, lex)
    statuses = [t.observe(_a(L.L1, 0.48), "x", v) for v in (-0.5, -0.5, -0.5)]
    assert statuses[-1].level is L.L1  # 极性未恶化，不升级
    t2 = CrisisTracker(tax, lex)
    statuses = [t2.observe(_a(L.L1, 0.48), "x", v) for v in (-0.3, -0.5, -0.7)]
    assert statuses[-1].level is L.L2

def test_isolated_l0_does_not_break_streak(run):
    run("想彻底睡过去"); run("今天吃了面"); run("想彻底睡过去")
    assert run("想彻底睡过去").level is L.L2

def test_three_l0_turns_clear_streak(run):
    run("想彻底睡过去"); run("想彻底睡过去")
    for _ in range(3):
        run("今天吃了面")
    assert run("想彻底睡过去").level is L.L1

def test_l2_exit_needs_confirmation_then_two_safe_turns(run):
    assert run("我想死").in_crisis
    assert run("今天吃了面").awaiting_confirmation   # 没有确认，不计数
    s = run("我现在安全了")
    assert s.in_crisis and not s.awaiting_confirmation and s.safe_turns_remaining == 2
    assert run("今天吃了面").in_crisis
    s = run("今天吃了面")
    assert not s.in_crisis and s.just_exited

def test_l3_exit_needs_three_safe_turns(run):
    run("遗书写好了")
    run("我联系上朋友了")
    assert run("嗯").in_crisis and run("嗯").in_crisis
    assert run("嗯").just_exited

def test_confirmation_inside_crisis_message_is_ignored(run):
    run("我想死")
    s = run("我现在安全了，但还是想死")
    assert s.level is L.L2 and s.in_crisis and s.awaiting_confirmation

def test_relapse_during_exit_resets_and_raises_entry_level(run):
    run("我想死"); run("我现在安全了"); run("嗯")
    s = run("药已经买好了")
    assert s.in_crisis and s.entry_level is L.L3 and s.awaiting_confirmation

def test_battery_prefix_cannot_bypass_crisis(run):
    run("我想死")
    s = run("[5%] 好累")
    assert s.in_crisis and s.awaiting_confirmation
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/safety/test_tracker.py -q`
Expected: FAIL（`ModuleNotFoundError: olivia.core.safety.tracker`）

- [ ] **Step 3: 按上述规则实现 `tracker.py`**

- [ ] **Step 4: 运行确认通过**

Run: `bash scripts/check.sh`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add olivia/core/safety/tracker.py tests/safety/test_tracker.py
git commit -m "feat(safety): track crisis escalation, entry and confirmed exit across turns"
```

---

### Task 5: 红线病种识别

**Files:**
- Create: `olivia/core/safety/red_flags.py`、`tests/safety/test_red_flags.py`

**Interfaces:**
- Consumes: Task 2 `SafetyLexicons.red_flags`、`self_report_negations`；Task 1 `normalize`、`PhraseMatcher`；P0 `Taxonomy.red_flags`
- Produces（`olivia.core.safety.red_flags`）：
  - `class UnknownRedFlagError(ValueError)`
  - `class RedFlagDetector`：`__init__(self, tax: Taxonomy, lexicons: SafetyLexicons)`；`detect(self, text: str) -> frozenset[str]`（返回 `SIT-xx-xx` 代码）；`profile_flags(self, clinical_history: Iterable[str]) -> frozenset[str]`（未知代码抛 `UnknownRedFlagError`，信息含该代码）
  - `class SessionRedFlags`：`__init__(self, detector: RedFlagDetector, clinical_history: Iterable[str] = ())`；`observe(self, text: str) -> frozenset[str]`（返回本会话至今全部激活代码）；属性 `active: frozenset[str]`

**规则：**
- `SELF_REPORT` 命中时，若规范化文本在命中起点之前紧邻（命中前 1~3 个字符构成的后缀）以任一 `self_report_negations` 结尾，则作废（“我没有双相”“我不是bpd”）；`FEATURE` 命中不做否定处理。
- 会话内一旦激活不再撤销（PRD §9.3 三级累积）；画像 `clinical_history` 始终激活。
- 本模块不写回画像：把识别结果写入 `clinical_history` 需要用户明示同意（SDD §2.1），属于 P4。

- [ ] **Step 1: 写失败测试** `tests/safety/test_red_flags.py`

```python
import pytest
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.red_flags import RedFlagDetector, SessionRedFlags, UnknownRedFlagError
from olivia.core.taxonomy import load_taxonomy

@pytest.fixture(scope="module")
def det():
    tax = load_taxonomy()
    return RedFlagDetector(tax, load_safety_lexicons(tax))

@pytest.mark.parametrize("text,code", [
    ("我去年确诊了双相", "SIT-02-04"),
    ("生完孩子后一直哭", "SIT-02-06"),
    ("我有创伤后应激", "SIT-06-01"),
    ("最近总是感觉自己不真实", "SIT-06-05"),
    ("我已经连续三天没吃东西", "SIT-08-04"),
    ("昨晚又用刀划自己", "SIT-09-01"),
    ("不喝酒手就抖", "SIT-10-04"),
])
def test_detects_each_code(det, text, code):
    assert det.detect(text) == frozenset({code})

@pytest.mark.parametrize("text,code", [("我有ＰＴＳＤ", "SIT-06-01"), ("医生说我是 BPD", "SIT-09-01")])
def test_self_report_variants(det, text, code):
    assert code in det.detect(text)

@pytest.mark.parametrize("text", ["我没有双相", "我不是bpd", "我并没有厌食症"])
def test_negated_self_report_is_ignored(det, text):
    assert det.detect(text) == frozenset()

def test_unrelated_text(det):
    assert det.detect("今天被领导批评了，心里很堵") == frozenset()

def test_profile_flags(det):
    assert det.profile_flags(["SIT-08-04"]) == frozenset({"SIT-08-04"})
    with pytest.raises(UnknownRedFlagError, match="SIT-8-4"):
        det.profile_flags(["SIT-8-4"])

def test_session_accumulates_and_includes_profile(det):
    s = SessionRedFlags(det, clinical_history=["SIT-02-04"])
    assert s.active == frozenset({"SIT-02-04"})
    assert s.observe("我有厌食症") == frozenset({"SIT-02-04", "SIT-08-04"})
    assert s.observe("今天还行") == frozenset({"SIT-02-04", "SIT-08-04"})
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/safety/test_red_flags.py -q`
Expected: FAIL（`ModuleNotFoundError: olivia.core.safety.red_flags`）

- [ ] **Step 3: 实现 `red_flags.py`**

- [ ] **Step 4: 运行确认通过**

Run: `bash scripts/check.sh`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add olivia/core/safety/red_flags.py tests/safety/test_red_flags.py
git commit -m "feat(safety): detect red-flag conditions from self-report and feature cues"
```

---

### Task 6: 安全用例集、多轮场景与性能

**Files:**
- Create: `tests/safety/cases.yaml`、`tests/safety/sessions.yaml`、`tests/safety/red_flag_cases.yaml`、`tests/safety/test_case_suite.py`、`tests/safety/test_performance.py`
- Modify: `olivia/data/lexicons/risk.yaml`、`olivia/data/lexicons/red_flags.yaml`（只允许新增词条或短语，用来让用例通过）

**Interfaces:**
- Consumes: Task 3 `SafetyScreen`、Task 4 `CrisisTracker`、Task 5 `RedFlagDetector`

**用例集格式与数量要求：**

`tests/safety/cases.yaml` —— 单轮用例，每条 `{id, text, expect, category}`，`expect ∈ {L0, L1, L2, L3}`。总数 ≥ 300，各类别下限：

| category | 含义 | expect | 下限 |
| :--- | :--- | :---: | :---: |
| `L3_MEANS` | 已准备工具（药、绳、刀、炭等） | L3 | 40 |
| `L3_TIME_PLACE` | 明确时间或地点 | L3 | 25 |
| `L3_ACT_FAREWELL` | 正在实施、告别、遗书 | L3 | 25 |
| `L2_IDEATION` | 明确想死或结束生命，无计划 | L2 | 60 |
| `L1_WEARY` | 厌世、疲惫、想消失，无自杀意念 | L1 | 50 |
| `HYPERBOLE` | 含“死”的中文口癖 | L0 | 50 |
| `NEGATION_PURE` | 纯否定 | L0 | 25 |
| `NEGATION_WITH_MEANS` | 否定句 + 工具/计划线索 | L3 | 15 |
| `BENIGN` | 日常压力、与死亡无关 | L0 | 30 |

`tests/safety/sessions.yaml` —— 多轮场景 ≥ 12 个，每个 `{id, turns: [{text, expect_level, expect_in_crisis}]}`，必须覆盖：强 L1 三轮升级、普通 L1 不升级、零星 L0 不打断、三轮 L0 清零、L2 确认后两轮退出、L3 确认后三轮退出、未确认不退出、确认句中夹带危机线索、退出途中复发并升级为 L3、`[5%]` 前缀在危机中无效、退出后再次进入、长消息结尾线索。

`tests/safety/red_flag_cases.yaml` —— 每个红线代码至少 3 条阳性（含自述与特征），另有至少 10 条阴性（含否定自述与无关文本），每条 `{id, text, expect: [codes]}`。

**编写规则：**
- 用例文本要像真实用户的说法（口语、错别字、标点不全、夹杂英文），不要照抄词表短语；每条用例都不同。
- 用例未通过时只能扩充词表（新增短语或词条），**绝不能**为了通过而降低某条用例的 `expect`；如果认为某条预期本身不对，在报告中列出并保留原预期，交由评审裁定。
- 新增词表短语不得让任何已有用例或 Task 1~5 的测试回退。

- [ ] **Step 1: 写数据驱动测试** `tests/safety/test_case_suite.py`

```python
from pathlib import Path
from collections import Counter
import pytest
import yaml
from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.red_flags import RedFlagDetector
from olivia.core.safety.tracker import CrisisTracker
from olivia.core.taxonomy import load_taxonomy

HERE = Path(__file__).parent
CASES = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
SESSIONS = yaml.safe_load((HERE / "sessions.yaml").read_text(encoding="utf-8"))
RF_CASES = yaml.safe_load((HERE / "red_flag_cases.yaml").read_text(encoding="utf-8"))
MINIMUMS = {"L3_MEANS": 40, "L3_TIME_PLACE": 25, "L3_ACT_FAREWELL": 25, "L2_IDEATION": 60,
            "L1_WEARY": 50, "HYPERBOLE": 50, "NEGATION_PURE": 25, "NEGATION_WITH_MEANS": 15,
            "BENIGN": 30}

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)

def test_case_set_size_and_category_minimums():
    counts = Counter(c["category"] for c in CASES)
    assert len(CASES) >= 300
    for cat, minimum in MINIMUMS.items():
        assert counts[cat] >= minimum, cat
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert len({c["text"] for c in CASES}) == len(CASES)

@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_single_turn_case(case):
    assert SCREEN.assess(case["text"]).level is CrisisLevel[case["expect"]]

def test_session_count():
    assert len(SESSIONS) >= 12

@pytest.mark.parametrize("session", SESSIONS, ids=[s["id"] for s in SESSIONS])
def test_session(session):
    tracker = CrisisTracker(TAX, LEX)
    for i, turn in enumerate(session["turns"]):
        status = tracker.observe(SCREEN.assess(turn["text"]), turn["text"])
        assert status.level is CrisisLevel[turn["expect_level"]], (session["id"], i)
        assert status.in_crisis is turn["expect_in_crisis"], (session["id"], i)

def test_red_flag_case_coverage():
    positives = Counter(code for c in RF_CASES for code in c["expect"])
    assert all(positives[code] >= 3 for code in TAX.red_flags())
    assert sum(1 for c in RF_CASES if not c["expect"]) >= 10

@pytest.mark.parametrize("case", RF_CASES, ids=[c["id"] for c in RF_CASES])
def test_red_flag_case(case):
    detector = RedFlagDetector(TAX, LEX)
    assert detector.detect(case["text"]) == frozenset(case["expect"])
```

- [ ] **Step 2: 写性能测试** `tests/safety/test_performance.py`

```python
import time
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

def test_assess_p99_under_one_millisecond():
    tax = load_taxonomy()
    screen = SafetyScreen(tax, load_safety_lexicons(tax))
    text = ("今天加班到很晚，领导又催进度，感觉活着好累，" * 20)[:500]
    for _ in range(200):
        screen.assess(text)
    samples = []
    for _ in range(2000):
        t0 = time.perf_counter()
        screen.assess(text)
        samples.append(time.perf_counter() - t0)
    samples.sort()
    assert samples[int(len(samples) * 0.99)] < 0.001
```

- [ ] **Step 3: 编写三份用例文件，运行并扩充词表直到全部通过**

Run: `.venv/bin/pytest tests/safety -q`
Expected: 全部 PASS

- [ ] **Step 4: 运行完整门禁**

Run: `bash scripts/check.sh`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add tests/safety olivia/data/lexicons
git commit -m "test(safety): add 300-case safety suite, session scenarios and latency check"
```

---

### Task 7: 文档同步

**Files:**
- Modify: `docs/SYSTEM_DESIGN.md` §11 映射表、`docs/DEVELOPMENT_PLAN.md` §4

- [ ] **Step 1: 更新 SDD §11**

把“§ 8.4 转介红线过滤网”一行拆成两行：`olivia/core/safety/red_flags.py` 的 `RedFlagDetector`、`SessionRedFlags` 标 `[已实现 / P1]`；`apply_red_flag_mask` 保留为 `[待实现 / P3]`。新增以下行，均标 `[已实现 / P1]`，接口写实际签名：`olivia/core/safety/normalize.py`（`normalize`、`clip_for_perception`）、`matcher.py`（`PhraseMatcher`）、`lexicon.py`（`load_safety_lexicons`）、`crisis.py`（`SafetyScreen.assess`、`RiskModel`、`arbitrate`）、`tracker.py`（`CrisisTracker.observe`）。不改动 SDD 其他内容。

- [ ] **Step 2: 更新 DEVELOPMENT_PLAN §4**

P1 行名称后追加“（本地门禁通过 <完成日期>，实际约 <N> 天）”，不改动其他内容。

- [ ] **Step 3: 运行门禁并提交**

Run: `bash scripts/check.sh`
Expected: 全部通过

```bash
git add docs/SYSTEM_DESIGN.md docs/DEVELOPMENT_PLAN.md
git commit -m "docs: sync module mapping and plan status for P1"
```

---

## P1 完成判定

- `bash scripts/check.sh` 全绿，其中安全用例 ≥ 300 条、多轮场景 ≥ 12 个、红线用例全部通过；
- 性能测试 P99 < 1 ms；
- Review Focus 五条都有对应测试且通过；
- DEVELOPMENT_PLAN §7 中标为 P1 的四条高风险输入都有测试；
- SDD §11 与实际代码一致。
