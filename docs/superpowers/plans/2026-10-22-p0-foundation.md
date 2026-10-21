# P0 工程地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从零搭起 OLIVIA 的 Python 工程骨架：类型化读取 `taxonomy.yaml`、SDD §2 数据契约、带三版本快照的原子写入，以及画像存储，并让质量门禁全绿。

**Architecture:** 一个 `olivia` 包。`olivia/core/taxonomy.py` 在加载时做结构完整性检查，之后只暴露只读、类型化的访问方法；`olivia/core/models.py` 放全部枚举与数据契约；`olivia/core/storage.py` 负责应用数据目录与影子写入；`olivia/core/chang/profile.py` 用前两者存取 `PersonaProfile`。后续阶段（P1~P5）只通过这些接口读阈值、读写数据。

**Tech Stack:** Python 3.11、PyYAML、platformdirs；开发依赖 pytest、pytest-cov、hypothesis、ruff、mypy、types-PyYAML。

**Spec:** `docs/DEVELOPMENT_PLAN.md`（§5 P0）、`docs/SYSTEM_DESIGN.md`（§2 数据契约、§6.5 原子写入、§11 模块映射）、`docs/PRODUCT_DOCUMENT.md`（ONB-02、CHANG-05、§9.1）、`taxonomy.yaml` v3.2.0。

## Global Constraints

- Python `>=3.11`；虚拟环境用 `/opt/anaconda3/bin/python3.11 -m venv .venv` 创建。
- 运行时依赖只有 `PyYAML>=6.0` 与 `platformdirs>=4.0`。本阶段不引入 NumPy。
- 所有阈值、枚举、白名单、红线只从 `taxonomy.yaml` 读；访问不存在的键必须抛错，不得返回默认值。
- 包内副本 `olivia/data/taxonomy.yaml` 必须与根目录 `taxonomy.yaml` 字节一致。
- 所有文本文件以 UTF-8 读写，JSON 用 `ensure_ascii=False`。
- 用户数据目录权限 `0o700`（POSIX）。
- 时间戳一律带时区（UTC-aware），naive datetime 视为错误。
- 门禁：`ruff check`、`ruff format --check`、`mypy --strict olivia`、`pytest --cov=olivia --cov-fail-under=85`、`python scripts/validate_taxonomy.py` 全部通过。
- 提交信息用 Conventional Commits，不加任何 AI 署名行。

## Review Focus

1. **taxonomy 少了键或类型不对**（例如有人删了 `battery.thresholds.haven_enter`）：加载或访问时立即抛 `TaxonomyError`，信息里带键路径。→ Task 3 `test_threshold_missing_key_raises`。
2. **危机分数正好落在边界**（0.2、0.5、0.8、1.0）或越界、NaN：0.5 → L2、0.8 → L3、1.0 → L3；越界与 NaN 抛 `ValueError`。→ Task 4 `test_crisis_level_boundaries`、`test_crisis_level_rejects_out_of_range`。
3. **动作 ID 写成别名或拼错**：别名归约为正式 ID，未登记 ID 抛 `UnknownActionError`（是 `KeyError` 子类）。→ Task 4 `test_canonical_action_id`。
4. **写入中途崩溃**（`os.replace` 前抛异常）：原文件保持旧内容，残留的 `.tmp` 不影响下一次读取。→ Task 5 `test_crash_before_replace_keeps_old_content`。
5. **画像文件损坏**（被截断、手工改坏）：从最新的有效快照恢复；没有任何有效版本时抛 `ProfileCorruptError`，绝不静默重置为空画像。→ Task 6 `test_corrupt_profile_recovers_from_snapshot`、`test_corrupt_profile_without_snapshot_raises`。

---

## File Structure

| 文件 | 职责 |
| :--- | :--- |
| `pyproject.toml` | 包元数据、依赖、ruff / mypy / pytest 配置 |
| `olivia/__init__.py` | `__version__` |
| `olivia/py.typed` | PEP 561 标记 |
| `olivia/core/__init__.py`、`olivia/core/chang/__init__.py` | 包标记 |
| `olivia/core/models.py` | 枚举与 SDD §2 数据契约 |
| `olivia/core/taxonomy.py` | 加载、完整性检查、类型化访问 |
| `olivia/core/storage.py` | 应用数据目录、原子写入、快照与恢复 |
| `olivia/core/chang/profile.py` | `ProfileStore` |
| `olivia/data/taxonomy.yaml` | 根目录 SSOT 的包内副本 |
| `scripts/check.sh` | 本地一键门禁 |
| `.github/workflows/ci.yml` | 三平台 CI |
| `tests/...` | 与上面一一对应的测试 |

---

### Task 1: 工程骨架与工具链

**Files:**
- Create: `pyproject.toml`、`olivia/__init__.py`、`olivia/py.typed`、`olivia/core/__init__.py`、`olivia/core/chang/__init__.py`、`tests/test_package.py`

**Interfaces:**
- Produces: 可编辑安装的 `olivia` 包；`olivia.__version__: str`

- [ ] **Step 1: 写失败测试** `tests/test_package.py`

```python
import olivia

def test_version_is_semver_string():
    parts = olivia.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)
```

- [ ] **Step 2: 创建虚拟环境并确认测试失败**

Run: `/opt/anaconda3/bin/python3.11 -m venv .venv && .venv/bin/pip install pytest && .venv/bin/pytest tests/test_package.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'olivia'`

- [ ] **Step 3: 写 `pyproject.toml` 与包文件**

`pyproject.toml` 要点：
- `[build-system]` 用 setuptools>=68；`[project] name = "olivia"`、`version = "0.1.0"`、`requires-python = ">=3.11"`、`dependencies = ["PyYAML>=6.0", "platformdirs>=4.0"]`；
- `[project.optional-dependencies] dev = ["pytest>=8", "pytest-cov>=5", "hypothesis>=6", "ruff>=0.6", "mypy>=1.10", "types-PyYAML"]`；
- `[tool.setuptools.packages.find] include = ["olivia*"]`；`[tool.setuptools.package-data] olivia = ["py.typed", "data/*.yaml"]`；
- `[tool.ruff] line-length = 100, target-version = "py311"`，`[tool.ruff.lint] select = ["E", "F", "I", "B", "UP", "SIM"]`；
- `[tool.mypy] strict = true, python_version = "3.11"`；
- `[tool.pytest.ini_options] testpaths = ["tests"]`。

`olivia/__init__.py` 只含 `__version__ = "0.1.0"`。

- [ ] **Step 4: 安装并验证**

Run: `.venv/bin/pip install -e '.[dev]' && .venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy --strict olivia`
Expected: 1 passed；ruff、mypy 无报错

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml olivia tests/test_package.py
git commit -m "build: scaffold olivia package and toolchain"
```

---

### Task 2: 枚举与数据契约

**Files:**
- Create: `olivia/core/models.py`、`tests/core/test_models.py`

**Interfaces:**
- Produces（全部在 `olivia.core.models`）：
  - `class CrisisLevel(IntEnum)`: `L0=0, L1=1, L2=2, L3=3`
  - `class HelpStage(StrEnum)`: `S_READY="S_ready", S_EXPLORE="S_explore", S_CLARIFY="S_clarify", S_EMPOWER="S_empower", S_HAVEN="S_haven", S_CLOSING="S_closing", S_CRISIS="S_crisis"`
  - `class PersonaSpectrum(StrEnum)`: `GENTLE_HOLDING, ZEN_PHILOSOPHER, RATIONAL_PEER, SILENT_ANCHOR`（值与名相同）
  - `class SafetyGrade(StrEnum)`: `GRADE_A, GRADE_B, GRADE_C`
  - `class ActionType(StrEnum)`: `MICRO_EXERCISE, STABILIZATION, COMPANIONSHIP, PSYCHOEDUCATION, REFERRAL`
  - `UNKNOWN_COUNTRY: Final = "ZZ"`
  - `PROFILE_SCHEMA_VERSION: Final = 1`
  - `@dataclass(frozen=True) class UserRegion`: `country_code: str`, `timezone: str`, `province_code: str | None = None`, `city_code: str | None = None`, `city_display_name: str | None = None`
  - `@dataclass(frozen=True) class PersonaProfile`: `age_confirmed_18_plus: bool`, `created_at: datetime`, `updated_at: datetime`, `user_name: str = "朋友"`, `agent_name: str = "Olivia"`, `persona_spectrum: PersonaSpectrum = GENTLE_HOLDING`, `directiveness_preference: float = 0.5`, `taboo_topics: tuple[str, ...] = ()`, `region: UserRegion | None = None`, `clinical_history: tuple[str, ...] = ()`, `enable_at_rest_encryption: bool = False`；方法 `to_dict() -> dict[str, object]`、`@classmethod from_dict(cls, data: Mapping[str, object]) -> PersonaProfile`
  - `@dataclass class SessionState`: `session_id: UUID`, `current_stage: HelpStage = S_READY`, `global_turn_count: int = 0`, `stage_turn_count: int = 0`, `pure_listening_locked: bool = False`, `social_battery: float = 1.0`, `current_risk_level: CrisisLevel = L0`, `consecutive_l1_count: int = 0`, `user_shelved_actions: list[str] = field(default_factory=list)`
  - `@dataclass(frozen=True) class PerceptionContext`: `valence: float`, `arousal: float`, `fine_grained_emotion: str`, `empathy_intent: str`, `risk_level: CrisisLevel`, `crisis_confidence: float`, `communication_stance: str`, `readiness_to_change: float`, `distress_vector: Mapping[str, float]`, `detected_distortions: tuple[str, ...]`, `detected_schemas: tuple[str, ...]`, `deep_yearning: str`, `somatic_stabilization_eligible: bool`（字段顺序同 SDD §2.3；情绪、姿态、渴望等标签用 `str`，是否属于 taxonomy 枚举由 P1/P6 的感知层负责校验）
  - `@dataclass(frozen=True) class ActionSkeleton`: `method_id: str`, `action_type: ActionType`, `safety_grade: SafetyGrade | None`, `clinical_rationale: str`, `core_action_steps: tuple[str, ...]`, `duration_minutes: int`, `stealth_workplace_compatible: bool`, `contraindications: tuple[str, ...]`（比 SDD §2.4 多了 `action_type`，供 P3 分发使用；`safety_grade` 对红线专用动作为 `None`）
- 所有 frozen 类在 `__post_init__` 中校验，违反时抛 `ValueError`。

- [ ] **Step 1: 写失败测试** `tests/core/test_models.py`

```python
from datetime import UTC, datetime
from uuid import uuid4
import pytest
from olivia.core.models import (
    ActionType, CrisisLevel, HelpStage, PersonaProfile, PersonaSpectrum,
    PerceptionContext, SessionState, UserRegion, UNKNOWN_COUNTRY,
)

NOW = datetime(2026, 10, 22, tzinfo=UTC)

def _profile(**kw):
    return PersonaProfile(age_confirmed_18_plus=True, created_at=NOW, updated_at=NOW, **kw)

def test_help_stage_has_seven_states():
    assert [s.value for s in HelpStage] == [
        "S_ready", "S_explore", "S_clarify", "S_empower", "S_haven", "S_closing", "S_crisis"]

def test_crisis_level_is_ordered_for_max_arbitration():
    assert max(CrisisLevel.L1, CrisisLevel.L3, CrisisLevel.L2) is CrisisLevel.L3

def test_action_type_values():
    assert {a.value for a in ActionType} == {
        "MICRO_EXERCISE", "STABILIZATION", "COMPANIONSHIP", "PSYCHOEDUCATION", "REFERRAL"}

def test_profile_defaults():
    p = _profile()
    assert (p.user_name, p.agent_name, p.persona_spectrum) == ("朋友", "Olivia", PersonaSpectrum.GENTLE_HOLDING)
    assert p.directiveness_preference == 0.5 and p.region is None

@pytest.mark.parametrize("name", ["", "一二三四五六七八九十一二三"])  # 0 字与 13 字
def test_profile_rejects_name_length_outside_1_to_12(name):
    with pytest.raises(ValueError):
        _profile(user_name=name)

def test_profile_requires_adult_confirmation():
    with pytest.raises(ValueError):
        PersonaProfile(age_confirmed_18_plus=False, created_at=NOW, updated_at=NOW)

def test_profile_rejects_naive_datetime():
    with pytest.raises(ValueError):
        PersonaProfile(age_confirmed_18_plus=True, created_at=datetime(2026, 1, 1), updated_at=NOW)

@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_profile_rejects_directiveness_out_of_range(value):
    with pytest.raises(ValueError):
        _profile(directiveness_preference=value)

def test_profile_round_trip_with_region_and_chinese_text():
    p = _profile(
        user_name="小林", taboo_topics=("前夫", "体重"), clinical_history=("SIT-08-04",),
        region=UserRegion(country_code="CN", timezone="Asia/Shanghai", city_code="440300", city_display_name="深圳市"),
    )
    data = p.to_dict()
    assert data["schema_version"] == 1
    assert PersonaProfile.from_dict(data) == p

def test_profile_from_dict_rejects_unknown_schema_version():
    data = _profile().to_dict() | {"schema_version": 99}
    with pytest.raises(ValueError):
        PersonaProfile.from_dict(data)

def test_region_validation():
    assert UserRegion(country_code=UNKNOWN_COUNTRY, timezone="UTC").country_code == "ZZ"
    for bad in ("cn", "CHN", ""):
        with pytest.raises(ValueError):
            UserRegion(country_code=bad, timezone="UTC")
    with pytest.raises(ValueError):
        UserRegion(country_code="CN", timezone="")

def test_session_state_defaults():
    s = SessionState(session_id=uuid4())
    assert s.current_stage is HelpStage.S_READY and s.social_battery == 1.0
    assert s.current_risk_level is CrisisLevel.L0 and s.user_shelved_actions == []

def _perception(**kw):
    base = dict(valence=0.0, arousal=0.5, fine_grained_emotion="anxiety", empathy_intent="EXPLORATION",
                risk_level=CrisisLevel.L0, crisis_confidence=0.0, communication_stance="CONGRUENT",
                readiness_to_change=0.5, distress_vector={}, detected_distortions=(), detected_schemas=(),
                deep_yearning="SAFETY", somatic_stabilization_eligible=False)
    return PerceptionContext(**(base | kw))

@pytest.mark.parametrize("field,value", [("valence", -1.1), ("arousal", 1.2), ("crisis_confidence", -0.1),
                                         ("readiness_to_change", 2.0)])
def test_perception_rejects_out_of_range(field, value):
    with pytest.raises(ValueError):
        _perception(**{field: value})

def test_perception_caps_schemas_at_three():
    with pytest.raises(ValueError):
        _perception(detected_schemas=("FAILURE", "DEFECTIVENESS", "PUNITIVENESS", "REST_GUILT"))
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/core/test_models.py -q`
Expected: FAIL，`ModuleNotFoundError: olivia.core.models`

- [ ] **Step 3: 实现 `olivia/core/models.py`**

校验规则（`__post_init__`）：
- `UserRegion`：`country_code` 必须匹配 `^[A-Z]{2}$`；`timezone` 非空（是否为合法 IANA 名留给 P2）。
- `PersonaProfile`：`user_name`、`agent_name` 去首尾空白后长度 1~12；`age_confirmed_18_plus` 必须为 `True`；两个时间戳 `tzinfo is not None`；`0.0 <= directiveness_preference <= 1.0`。
- `PerceptionContext`：`valence ∈ [-1, 1]`；`arousal`、`crisis_confidence`、`readiness_to_change ∈ [0, 1]`；`len(detected_schemas) <= 3`。

`to_dict()`：枚举写 `.value`，datetime 写 `isoformat()`，tuple 写 list，`region` 写嵌套 dict 或 `None`，并加 `"schema_version": PROFILE_SCHEMA_VERSION`。`from_dict()` 先检查 `schema_version == 1`，否则抛 `ValueError`。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/core/test_models.py -q && .venv/bin/mypy --strict olivia`
Expected: 全部 PASS；mypy 无报错

- [ ] **Step 5: 提交**

```bash
git add olivia/core/models.py tests/core/test_models.py
git commit -m "feat(core): add domain enums and SDD section 2 data contracts"
```

---

### Task 3: taxonomy 加载与基础访问

**Files:**
- Create: `olivia/core/taxonomy.py`、`olivia/data/taxonomy.yaml`（从根目录复制）、`tests/core/test_taxonomy_core.py`、`tests/test_taxonomy_sync.py`
- Modify: `scripts/validate_taxonomy.py:434-438`（删除 `.worktrees/iteration-1/olivia/data/taxonomy.yaml` 一项）

**Interfaces:**
- Produces（`olivia.core.taxonomy`）：
  - `class TaxonomyError(Exception)`
  - `def load_taxonomy(path: Path | None = None) -> Taxonomy`：`None` 时读包内 `olivia/data/taxonomy.yaml`（用 `importlib.resources`）；YAML 语法错误、顶层不是 mapping 时抛 `TaxonomyError`
  - `class Taxonomy`：
    - `version: str`（属性）
    - `def threshold(self, dotted_path: str) -> float`：按点分路径取值；键不存在、值不是 int/float（`bool` 不算数字）时抛 `TaxonomyError`，信息含路径
    - `def values(self, name: str) -> tuple[str, ...]`：`name ∈ {"emotions", "cognitive_distortions", "schemas", "satir_yearnings", "communication_stances", "contraindication_enums", "distress_categories"}`，返回各项 `id`（`distress_categories` 本身是字符串列表）；其他名字抛 `TaxonomyError`
    - `def canonical_label(self, kind: Literal["emotion", "distortion", "schema", "yearning"], label: str) -> str`：正式 id 原样返回，别名映射为正式 id，未知抛 `TaxonomyError`

- [ ] **Step 1: 复制数据并写失败测试**

Run: `mkdir -p olivia/data && cp taxonomy.yaml olivia/data/taxonomy.yaml`

`tests/test_taxonomy_sync.py`：

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_package_copy_matches_root_ssot():
    assert (ROOT / "olivia/data/taxonomy.yaml").read_bytes() == (ROOT / "taxonomy.yaml").read_bytes()
```

`tests/core/test_taxonomy_core.py`：

```python
import pytest
from olivia.core.taxonomy import Taxonomy, TaxonomyError, load_taxonomy

@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load_taxonomy()

def test_version(tax):
    assert tax.version == "3.2.0"

@pytest.mark.parametrize("path,expected", [
    ("arousal.thresholds.somatic_priority", 0.80),
    ("arousal.thresholds.cognitive_block", 0.85),
    ("arousal.thresholds.exploration_allow", 0.60),
    ("battery.thresholds.haven_enter", 0.20),
    ("battery.thresholds.haven_exit", 0.35),
    ("battery.thresholds.empower_min", 0.40),
    ("risk.ewma_lambda", 0.5),
])
def test_threshold_values(tax, path, expected):
    assert tax.threshold(path) == pytest.approx(expected)

def test_threshold_missing_key_raises(tax):
    with pytest.raises(TaxonomyError, match="battery.thresholds.nope"):
        tax.threshold("battery.thresholds.nope")

def test_threshold_non_numeric_raises(tax):
    with pytest.raises(TaxonomyError):
        tax.threshold("version")

def test_values_counts(tax):
    assert len(tax.values("emotions")) == 16
    assert len(tax.values("cognitive_distortions")) == 9
    assert len(tax.values("schemas")) == 20
    assert len(tax.values("satir_yearnings")) == 5
    assert len(tax.values("communication_stances")) == 5
    assert len(tax.values("contraindication_enums")) == 13
    assert tax.values("distress_categories")[0] == "ANXIETY_PANIC"

def test_values_unknown_name_raises(tax):
    with pytest.raises(TaxonomyError):
        tax.values("planets")

def test_canonical_label(tax):
    assert tax.canonical_label("emotion", "anxiety") == "anxiety"
    assert tax.canonical_label("emotion", "irritability") == "anger"
    assert tax.canonical_label("distortion", "LABELING") == "ALL_OR_NOTHING"
    assert tax.canonical_label("schema", "PERFECTIONISM") == "UNRELENTING_STANDARDS"
    assert tax.canonical_label("yearning", "SAFETY_ORDER") == "SAFETY"
    with pytest.raises(TaxonomyError):
        tax.canonical_label("emotion", "joy")

def test_load_rejects_malformed_yaml(tmp_path):
    bad = tmp_path / "t.yaml"
    bad.write_text("version: [unclosed", encoding="utf-8")
    with pytest.raises(TaxonomyError):
        load_taxonomy(bad)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_taxonomy_sync.py tests/core/test_taxonomy_core.py -q`
Expected: sync 测试 PASS；core 测试 FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 `olivia/core/taxonomy.py` 的上述接口**

用 `yaml.safe_load`；`Taxonomy` 内部持有原始 dict，只读访问。

- [ ] **Step 4: 修改校验脚本**

把 `scripts/validate_taxonomy.py` 中 `possible_pkg_paths` 的 `.worktrees/iteration-1/...` 一项删除，保留 `src/olivia/...` 与 `olivia/data/taxonomy.yaml`。

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/pytest -q && .venv/bin/mypy --strict olivia && python3 scripts/validate_taxonomy.py | tail -3`
Expected: 全部 PASS；校验输出含“代码包内 taxonomy 副本与根目录 SSOT 完全一致”

- [ ] **Step 6: 提交**

```bash
git add olivia/core/taxonomy.py olivia/data/taxonomy.yaml tests/core/test_taxonomy_core.py tests/test_taxonomy_sync.py scripts/validate_taxonomy.py
git commit -m "feat(core): load taxonomy with strict typed threshold and enum access"
```

---

### Task 4: taxonomy 临床视图与加载时完整性检查

**Files:**
- Modify: `olivia/core/taxonomy.py`
- Create: `tests/core/test_taxonomy_clinical.py`

**Interfaces:**
- Consumes: Task 2 的 `CrisisLevel`、`SafetyGrade`、`ActionType`；Task 3 的 `Taxonomy`、`TaxonomyError`
- Produces（`olivia.core.taxonomy`）：
  - `class UnknownActionError(KeyError)`
  - `@dataclass(frozen=True) class MethodEntry`: `id: str`, `name_zh: str`, `name_en: str`, `file: str`, `grade: SafetyGrade`, `evidence_level: str | None`, `duration_minutes: int | None`, `stealth_workplace_compatible: bool | None`, `clinical_rationale: str | None`, `core_action_steps: tuple[str, ...]`, `contraindications: tuple[str, ...]`, `sub_actions: tuple[str, ...]`（B/C 级方法的可选字段为 `None` 或空 tuple）
  - `@dataclass(frozen=True) class RegisteredAction`: `id: str`, `aliases: tuple[str, ...]`, `name_zh: str`, `parent_method_id: str | None`, `action_type: ActionType`, `duration_minutes: int`, `stealth_workplace_compatible: bool`, `clinical_rationale: str`, `core_action_steps: tuple[str, ...]`, `contraindications: tuple[str, ...]`
  - `@dataclass(frozen=True) class RedFlag`: `code: str`, `name_zh: str`, `allowed_actions: tuple[str, ...]`, `banned_methods: tuple[str, ...]`（保留 taxonomy 原文，归约留给 P3）
  - `Taxonomy` 新增方法：
    - `methods(self) -> Mapping[str, MethodEntry]`（75 项，键为两位数 id）
    - `grade_a_ids(self) -> frozenset[str]`
    - `action_registry(self) -> Mapping[str, RegisteredAction]`（键为正式 id）
    - `canonical_action_id(self, action_id: str) -> str`：方法 id 与正式动作 id 原样返回；别名返回正式 id；否则抛 `UnknownActionError`
    - `red_flags(self) -> Mapping[str, RedFlag]`（键为 `SIT-xx-xx`）
    - `banned_tag_methods(self, tag: str) -> tuple[str, ...]`：未知 tag 抛 `TaxonomyError`
    - `is_banned_tag(self, entry: str) -> bool`
    - `stabilization_whitelist(self) -> tuple[str, ...]`
    - `crisis_level_for_score(self, score: float) -> CrisisLevel`
    - `crisis_exit_safe_turns(self, level: CrisisLevel) -> int`：L2、L3 读 `crisis_hierarchy.exit_rule.safe_streak_required`；L0、L1 抛 `ValueError`
- 加载时（`load_taxonomy` 内）做以下检查，失败抛 `TaxonomyError` 并说明是哪一项：
  1. 别名不得与任何正式动作 id、方法 id 或其他别名重复；
  2. 红线 `allowed_actions` 每项都能被 `canonical_action_id` 解析；
  3. 红线 `banned_methods` 每项是方法 id、可解析的动作 id 或已知禁用标签之一；
  4. 稳定化白名单每项是方法 id 或可解析的动作 id；
  5. A 级方法与登记动作的 `contraindications` 都在 `contraindication_enums` 中；
  6. `crisis_hierarchy` 的 L0~L3 区间首尾相接，从 0.0 开始、到 1.0 结束，L0~L2 为 `HALF_OPEN`，L3 为 `CLOSED`。

- [ ] **Step 1: 写失败测试** `tests/core/test_taxonomy_clinical.py`

```python
import math
from pathlib import Path
import pytest
import yaml
from olivia.core.models import ActionType, CrisisLevel, SafetyGrade
from olivia.core.taxonomy import TaxonomyError, UnknownActionError, load_taxonomy

ROOT = Path(__file__).resolve().parents[2]

@pytest.fixture(scope="module")
def tax():
    return load_taxonomy()

def test_method_counts_by_grade(tax):
    grades = [m.grade for m in tax.methods().values()]
    assert (grades.count(SafetyGrade.GRADE_A), grades.count(SafetyGrade.GRADE_B),
            grades.count(SafetyGrade.GRADE_C)) == (32, 26, 17)
    assert len(tax.grade_a_ids()) == 32 and "12" in tax.grade_a_ids() and "04" not in tax.grade_a_ids()

def test_grade_a_method_fields(tax):
    m = tax.methods()["15"]
    assert m.evidence_level == "Level I" and m.duration_minutes == 4
    assert m.contraindications == ("RED_FLAG_PTSD_FLASHBACK",)
    assert tax.methods()["12"].sub_actions == ("12:tipp_breathing", "12:tipp_cold_water")

def test_action_registry(tax):
    reg = tax.action_registry()
    assert len(reg) == 10
    assert reg["REFERRAL_CARD_PRESENTATION"].action_type is ActionType.REFERRAL
    assert reg["12:tipp_cold_water"].contraindications == (
        "RED_FLAG_ANOREXIA", "RED_FLAG_BPD_NSSI", "CARDIORESPIRATORY_INSTABILITY")
    assert reg["12:tipp_breathing"].parent_method_id == "12"

@pytest.mark.parametrize("raw,canonical", [
    ("DBT_TIPP_MODIFIED_BREATHING", "12:tipp_breathing"),
    ("GROUNDING_54321", "30:grounding"),
    ("GENTLE_PRESENCE", "EMOTIONAL_HOLDING_PRESENCE"),
    ("30:grounding", "30:grounding"),
    ("28", "28"),
])
def test_canonical_action_id(tax, raw, canonical):
    assert tax.canonical_action_id(raw) == canonical

def test_canonical_action_id_unknown_raises_key_error(tax):
    with pytest.raises(UnknownActionError):
        tax.canonical_action_id("REFERRAL_CARD")
    assert issubclass(UnknownActionError, KeyError)

def test_red_flags(tax):
    flags = tax.red_flags()
    assert sorted(flags) == ["SIT-02-04", "SIT-02-06", "SIT-06-01", "SIT-06-05",
                             "SIT-08-04", "SIT-09-01", "SIT-10-04"]
    assert flags["SIT-09-01"].allowed_actions == (
        "EMOTIONAL_HOLDING_PRESENCE", "DBT_TIPP_MODIFIED_BREATHING", "REFERRAL_CARD_PRESENTATION")

def test_banned_tags(tax):
    assert tax.banned_tag_methods("SELF_DETOX_GUIDANCE") == ("10",)
    assert tax.is_banned_tag("TRAUMA_DETAIL_EXPLORATION") and not tax.is_banned_tag("03")
    with pytest.raises(TaxonomyError):
        tax.banned_tag_methods("NOT_A_TAG")

def test_stabilization_whitelist(tax):
    assert tax.stabilization_whitelist() == ("28", "29", "30:grounding", "12:tipp_breathing")

@pytest.mark.parametrize("score,level", [
    (0.0, CrisisLevel.L0), (0.1999, CrisisLevel.L0), (0.2, CrisisLevel.L1), (0.4999, CrisisLevel.L1),
    (0.5, CrisisLevel.L2), (0.7999, CrisisLevel.L2), (0.8, CrisisLevel.L3), (1.0, CrisisLevel.L3),
])
def test_crisis_level_boundaries(tax, score, level):
    assert tax.crisis_level_for_score(score) is level

@pytest.mark.parametrize("score", [-0.01, 1.01, math.nan])
def test_crisis_level_rejects_out_of_range(tax, score):
    with pytest.raises(ValueError):
        tax.crisis_level_for_score(score)

def test_crisis_exit_safe_turns(tax):
    assert tax.crisis_exit_safe_turns(CrisisLevel.L2) == 2
    assert tax.crisis_exit_safe_turns(CrisisLevel.L3) == 3
    with pytest.raises(ValueError):
        tax.crisis_exit_safe_turns(CrisisLevel.L1)

def _mutated(tmp_path, mutate):
    data = yaml.safe_load((ROOT / "taxonomy.yaml").read_text(encoding="utf-8"))
    mutate(data)
    p = tmp_path / "t.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p

def test_integrity_rejects_alias_collision(tmp_path):
    def m(d): d["action_registry"][0]["aliases"].append("30:grounding")
    with pytest.raises(TaxonomyError, match="alias"):
        load_taxonomy(_mutated(tmp_path, m))

def test_integrity_rejects_unresolvable_red_flag_action(tmp_path):
    def m(d): d["clinical_red_flags"]["mandatory_referral_disorders"][0]["allowed_actions"].append("NOPE")
    with pytest.raises(TaxonomyError, match="SIT-02-04"):
        load_taxonomy(_mutated(tmp_path, m))

def test_integrity_rejects_unknown_contraindication(tmp_path):
    def m(d): d["method_safety_tiers"]["grade_A"]["methods"][0]["contraindications"].append("MADE_UP")
    with pytest.raises(TaxonomyError, match="MADE_UP"):
        load_taxonomy(_mutated(tmp_path, m))

def test_integrity_rejects_crisis_gap(tmp_path):
    def m(d): d["crisis_hierarchy"]["L2"]["score_range"] = [0.55, 0.8]
    with pytest.raises(TaxonomyError, match="crisis"):
        load_taxonomy(_mutated(tmp_path, m))
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/core/test_taxonomy_clinical.py -q`
Expected: FAIL（`ImportError: cannot import name 'UnknownActionError'`）

- [ ] **Step 3: 实现上述视图与六项完整性检查**

`crisis_level_for_score` 的区间判定：先拒绝 NaN 与 `[0, 1]` 之外的值；L0~L2 用 `lo <= score < hi`，L3 用 `lo <= score <= hi`；边界一律取自 taxonomy，不写死数值。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest -q && .venv/bin/mypy --strict olivia`
Expected: 全部 PASS；mypy 无报错

- [ ] **Step 5: 提交**

```bash
git add olivia/core/taxonomy.py tests/core/test_taxonomy_clinical.py
git commit -m "feat(core): add clinical taxonomy views and load-time integrity checks"
```

---

### Task 5: 应用数据目录与原子写入

**Files:**
- Create: `olivia/core/storage.py`、`tests/core/test_storage.py`

**Interfaces:**
- Produces（`olivia.core.storage`）：
  - `SNAPSHOT_KEEP: Final = 3`
  - `class StorageCorruptError(Exception)`
  - `def app_data_dir() -> Path`：环境变量 `OLIVIA_HOME` 存在时用它，否则 `platformdirs.user_data_path("olivia", appauthor=False)`；目录不存在则创建，POSIX 上权限设为 `0o700`
  - `def snapshot_paths(path: Path) -> list[Path]`：`path.parent / ".snapshots"` 下以 `f"{path.name}."` 开头的快照，按新到旧排序
  - `def atomic_write_text(path: Path, text: str) -> None`
  - `def read_text_with_recovery(path: Path, is_valid: Callable[[str], bool]) -> str`：主文件存在且有效则返回；否则按新到旧返回第一个有效快照；全部无效抛 `StorageCorruptError`；主文件与快照都不存在抛 `FileNotFoundError`

- [ ] **Step 1: 写失败测试** `tests/core/test_storage.py`

```python
import os, stat, sys
import pytest
from olivia.core import storage
from olivia.core.storage import (SNAPSHOT_KEEP, StorageCorruptError, app_data_dir,
                                 atomic_write_text, read_text_with_recovery, snapshot_paths)

def test_app_data_dir_respects_env_and_is_private(tmp_path, monkeypatch):
    target = tmp_path / "home"
    monkeypatch.setenv("OLIVIA_HOME", str(target))
    assert app_data_dir() == target and target.is_dir()
    if sys.platform != "win32":
        assert stat.S_IMODE(target.stat().st_mode) == 0o700

def test_write_and_read_chinese_text(tmp_path):
    p = tmp_path / "ledger.md"
    atomic_write_text(p, "今天辛苦了。\n")
    assert read_text_with_recovery(p, lambda s: True) == "今天辛苦了。\n"

def test_keeps_only_three_snapshots(tmp_path):
    p = tmp_path / "ledger.md"
    for i in range(6):
        atomic_write_text(p, f"v{i}")
    snaps = snapshot_paths(p)
    assert len(snaps) == SNAPSHOT_KEEP == 3
    assert [s.read_text(encoding="utf-8") for s in snaps] == ["v4", "v3", "v2"]
    assert p.read_text(encoding="utf-8") == "v5"

def test_crash_before_replace_keeps_old_content(tmp_path, monkeypatch):
    p = tmp_path / "ledger.md"
    atomic_write_text(p, "old")
    def boom(*a, **k): raise OSError("power loss")
    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(p, "new")
    monkeypatch.undo()
    assert read_text_with_recovery(p, lambda s: True) == "old"

def test_corrupt_main_falls_back_to_newest_valid_snapshot(tmp_path):
    p = tmp_path / "data.json"
    atomic_write_text(p, '{"v": 1}')
    atomic_write_text(p, '{"v": 2}')
    p.write_text('{"v": 3', encoding="utf-8")  # 截断
    is_json = lambda s: s.startswith("{") and s.endswith("}")
    assert read_text_with_recovery(p, is_json) == '{"v": 1}'

def test_no_valid_version_raises(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("garbage", encoding="utf-8")
    with pytest.raises(StorageCorruptError):
        read_text_with_recovery(p, lambda s: False)

def test_missing_everything_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_text_with_recovery(tmp_path / "absent.json", lambda s: True)
```

注意 `test_corrupt_main_falls_back_to_newest_valid_snapshot`：第二次写入时把 `{"v": 1}` 存为快照，然后主文件被手工截断，所以恢复结果是 `{"v": 1}`。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/core/test_storage.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 `olivia/core/storage.py`**

`atomic_write_text` 的顺序（SDD §6.5）：

1. 若 `path` 已存在，把当前内容复制为 `.snapshots/{name}.{time.time_ns()}`，再删除超出 `SNAPSHOT_KEEP` 的最旧快照；
2. 写入 `path.with_name(path.name + ".tmp")`，`flush()` 后 `os.fsync()`；
3. `os.replace(tmp, path)`；
4. POSIX 上打开父目录并 `os.fsync()`，确保改名落盘。

快照文件名用纳秒时间戳，同一纳秒重复时追加计数后缀，保证排序稳定。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest -q && .venv/bin/mypy --strict olivia`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add olivia/core/storage.py tests/core/test_storage.py
git commit -m "feat(core): add app data dir and atomic shadow write with three snapshots"
```

---

### Task 6: 画像存储 `ProfileStore`

**Files:**
- Create: `olivia/core/chang/profile.py`、`tests/core/chang/test_profile_store.py`

**Interfaces:**
- Consumes: Task 2 `PersonaProfile.to_dict / from_dict`；Task 5 `app_data_dir`、`atomic_write_text`、`read_text_with_recovery`、`StorageCorruptError`
- Produces（`olivia.core.chang.profile`）：
  - `PROFILE_FILENAME: Final = "profile.json"`
  - `class ProfileCorruptError(Exception)`
  - `class ProfileStore`：`__init__(self, base_dir: Path | None = None)`（`None` 时用 `app_data_dir()`）；属性 `path: Path`；`load(self) -> PersonaProfile | None`（从未保存过返回 `None`）；`save(self, profile: PersonaProfile) -> None`

- [ ] **Step 1: 写失败测试** `tests/core/chang/test_profile_store.py`

```python
import json
from datetime import UTC, datetime
import pytest
from olivia.core.chang.profile import ProfileCorruptError, ProfileStore
from olivia.core.models import PersonaProfile, UserRegion

NOW = datetime(2026, 10, 22, tzinfo=UTC)

def _p(name="小林"):
    return PersonaProfile(age_confirmed_18_plus=True, created_at=NOW, updated_at=NOW, user_name=name,
                          region=UserRegion(country_code="HK", timezone="Asia/Hong_Kong"))

def test_load_returns_none_before_first_save(tmp_path):
    assert ProfileStore(tmp_path).load() is None

def test_save_then_load_round_trip(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p())
    assert store.load() == _p()
    raw = store.path.read_text(encoding="utf-8")
    assert "小林" in raw and json.loads(raw)["schema_version"] == 1

def test_default_base_dir_uses_olivia_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OLIVIA_HOME", str(tmp_path))
    assert ProfileStore().path == tmp_path / "profile.json"

def test_corrupt_profile_recovers_from_snapshot(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p("阿青"))
    store.save(_p("小林"))
    store.path.write_text('{"schema_version": 1, "user_na', encoding="utf-8")
    assert store.load().user_name == "阿青"

def test_corrupt_profile_without_snapshot_raises(tmp_path):
    store = ProfileStore(tmp_path)
    store.path.write_text("not json", encoding="utf-8")
    with pytest.raises(ProfileCorruptError):
        store.load()

def test_semantically_invalid_profile_counts_as_corrupt(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p("阿青"))
    store.save(_p("小林"))  # 此时 "阿青" 进入快照
    data = json.loads(store.path.read_text(encoding="utf-8")) | {"age_confirmed_18_plus": False}
    store.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert store.load() == _p("阿青")  # JSON 合法但违反 18+ 校验，回退到快照
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/core/chang/test_profile_store.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 `ProfileStore`**

`load` 的有效性判定 `is_valid(text)`：能 `json.loads`，且 `PersonaProfile.from_dict` 不抛错。主文件与快照都不存在时返回 `None`；`StorageCorruptError` 转为 `ProfileCorruptError`。`save` 用 `json.dumps(..., ensure_ascii=False, indent=2)` 再 `atomic_write_text`。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest -q && .venv/bin/mypy --strict olivia`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add olivia/core/chang/profile.py tests/core/chang/test_profile_store.py
git commit -m "feat(chang): add ProfileStore with snapshot recovery"
```

---

### Task 7: 质量门禁、CI 与文档同步

**Files:**
- Create: `scripts/check.sh`、`.github/workflows/ci.yml`
- Modify: `docs/SYSTEM_DESIGN.md` §11 映射表、`docs/DEVELOPMENT_PLAN.md`（P0 状态）

**Interfaces:**
- Produces: `scripts/check.sh` —— 本地与 CI 共用的唯一门禁入口

- [ ] **Step 1: 写 `scripts/check.sh`**

按顺序执行，任一步失败即退出（`set -euo pipefail`）：

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy --strict olivia
.venv/bin/pytest --cov=olivia --cov-fail-under=85 -q
.venv/bin/python scripts/validate_taxonomy.py
```

在脚本开头允许用环境变量 `PY_BIN_DIR` 覆盖 `.venv/bin`，供 CI 使用。

- [ ] **Step 2: 运行门禁**

Run: `bash scripts/check.sh`
Expected: 全部通过，覆盖率 ≥ 85%。若 `ruff format --check` 报差异，先运行 `.venv/bin/ruff format .` 再重跑。

- [ ] **Step 3: 写 `.github/workflows/ci.yml`**

触发：`push`、`pull_request`。矩阵：`os: [ubuntu-latest, macos-latest, windows-latest]`，`python-version: ["3.11"]`。步骤：checkout → setup-python → `pip install -e '.[dev]'` → `PY_BIN_DIR=$(dirname $(which python)) bash scripts/check.sh`（Windows 用 `shell: bash`）。

- [ ] **Step 4: 同步文档**

- `docs/SYSTEM_DESIGN.md` §11：把“§2 通用领域模型”一行的路径改为 `olivia/core/models.py`（导出 `PersonaProfile`、`SessionState`、`PerceptionContext`、`ActionSkeleton`、`UserRegion`）与 `olivia/core/chang/profile.py`（`ProfileStore`）；`taxonomy.py`、`storage.py`、`chang/profile.py` 三行标“已实现（P0）”；其余旧代码模块（`resources/*` 等）统一标“待实现（P2）”或对应阶段；接口签名改成本计划中的实际签名。
- `docs/DEVELOPMENT_PLAN.md` §4：P0 行加“已完成”及实际用时。

- [ ] **Step 5: 提交**

```bash
git add scripts/check.sh .github/workflows/ci.yml docs/SYSTEM_DESIGN.md docs/DEVELOPMENT_PLAN.md
git commit -m "ci: add unified quality gate and sync design docs for P0"
```

---

## P0 完成判定

- `bash scripts/check.sh` 全绿；
- 上面 Review Focus 的五条都有对应测试且通过；
- `docs/SYSTEM_DESIGN.md` §11 与实际代码一致；
- 工作区干净，7 个提交按任务顺序排列。
