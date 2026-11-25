# 危机筛查三文件的变异测试（2026-11-25）

对象：`olivia/core/safety/compose.py`（524 行）、`tracker.py`（709 行）、`crisis.py`（989 行），基于 main `f2b09c8`。
只加了测试，产品代码一行没改。本报告不含任何评估集内容；新测试里的句子全部是这里新写的，
沿用 `tests/redteam/cases.yaml` 开头的写作规则（不写方法、剂量、地点细节）。

## 工具与环境

- mutmut 3.8.1（libcst 1.9.0），pytest 9.2.0，Python 3.11.0，macOS 26.4 arm64。
- 独立 venv（不在仓库里，也不碰共享的 `.venv`）：`python3.11 -m venv mutvenv`，
  `pip install -e '<worktree>[dev]' mutmut`。
- 变异在仓库的副本目录里跑（rsync，不含 `.git`），`[tool.mutmut]` 配置只写在副本的
  `pyproject.toml` 里，`mutants/` 也只在副本里生成。仓库本身没有任何 mutmut 产物，所以没有改
  `.gitignore`。
- 最多 2 个 worker（`--max-children 2`）。

## 命令与范围

第一轮（副本 A）配置：

```toml
[tool.mutmut]
source_paths = ["olivia/"]
only_mutate = ["olivia/core/safety/compose.py", "olivia/core/safety/tracker.py", "olivia/core/safety/crisis.py"]
pytest_add_cli_args = ["-p", "no:cacheprovider", "--ignore=tests/safety/test_performance.py"]
pytest_add_cli_args_test_selection = ["tests/safety", "tests/redteam"]
```

```sh
mutmut run --max-children 2 "olivia.core.safety.compose.*"
mutmut run --max-children 2 "olivia.core.safety.tracker.*"
mutmut run --max-children 2 "olivia.core.safety.crisis.*"
```

第一轮范围：`tests/safety`（去掉只量时延的 `test_performance.py`）与 `tests/redteam`，共 6352 个测试。

第二轮（副本 B）只跑第一轮的存活变异，测试换成其余“直接 import 这三个文件”的 37 个测试文件
（`grep -rlE "safety\.(compose|tracker|crisis)|from olivia\.core\.safety import" tests`，去掉
`tests/safety`、`tests/redteam` 与名字含 performance 的文件；cli、fsm、language、memory、methods、
perception、session 七个目录，共 2210 个测试）：

```sh
mutmut run --max-children 2 <第一轮存活变异的名字…>
```

新测试是否杀死某个变异，在 `mutants/` 里逐个新进程验证：

```sh
MUTANT_UNDER_TEST=<变异名> python -m pytest -x -q tests_mut/test_mutation_<file>.py
```

每批都带一个已知等价的变异作对照（应当存活），证明这条命令真的在跑变异代码。

### fork 模式的一个坑

mutmut 3 默认从已经跑过一遍测试的主进程 fork 出 worker。测试模块里模块级的
`SCREEN = SafetyScreen(...)`、`compose.shared_set` 的进程级缓存与 `_CueIndex` 的最近 4 条扫描都在主进程
里用原始代码建好，所以构造函数和缓存路径上的变异在 worker 里可能“假存活”。凡是落在构造函数或缓存上的
存活变异，都另在新进程里用相关测试复核（`MUTANT_UNDER_TEST=… pytest tests/safety/test_compositions.py
tests/safety/test_case_suite.py tests/language/test_perf_round7.py` 等）。例如 `shared_set` 的 4 个变异在
worker 里存活，在新进程里都被 `tests/language/test_perf_round7.py` 杀死，所以记为“范围外现有测试已杀死”。

### 中文参数的测试名会被 mutmut 静默跳过

pytest 默认把参数化测试名里的非 ASCII 字符转义（`test_x[\u642c…]`），mutmut 记下的就是转义后的名字；
它对每个变异把这些名字原样传回 pytest，pytest 却匹配不上，于是这些测试**根本没跑**，也不报错（同一次调用里
其他 ASCII 名字的测试照常跑）。本仓库大部分安全测试都是用中文句子参数化的，所以前两轮的“存活”里混有本该
被现有测试杀死的变异。例：`_habit_on_the_cause` 的 20 号变异在第二轮“存活”，在新进程里整文件跑
`tests/session/test_owner_decisions_1101.py` 就被杀死。

修正办法是让 pytest 不转义：第三轮（副本 C）的 `pytest_add_cli_args` 加上
`-o disable_test_id_escaping_and_forfeit_all_rights_to_community_support=true`，范围取第一、二轮之和
（tests/safety、tests/redteam 与那 37 个文件），重新收集测试与函数的对应关系，只重跑前两轮都没杀死的变异。
新测试的验证（`MUTANT_UNDER_TEST=… pytest <整个文件>`）不按测试名筛选，不受这个问题影响。

## 结果

“第一轮存活”含 mutmut 报的“无测试”（第一轮范围里没有测试调用到那个函数：tracker 的 `_scoped_clear` 2 个，
crisis 的 `clear_denial` 与 `_DenialIndex.clears` 共 43 个）。“现有测试再杀死”是被第二轮或第三轮的现有测试杀死（`compose.shared_set` 的 4 个
按新进程复核计入）。“新测试另杀死”是现有测试都没杀死、新测试杀死的，在新进程里逐个验证。

| 文件 | 变异总数 | 第一轮检查 | 第一轮杀死 | 第一轮存活 | 现有测试再杀死 | 新测试另杀死 | 加测试后存活 | 其中等价 | 其中不能判定 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| compose.py | 758 | 758 | 712 | 46 | 4 | 8 | 34 | 33 | 1 |
| tracker.py | 520 | 520 | 431 | 89 | 41 | 20 | 28 | 27 | 1 |
| crisis.py | 1058 | 879 | 676 | 203 | 43 | 111 | 49 | 43 | 6 |

按“杀死 /（总数 − 等价）”算的变异得分（加测试前已算上现有测试的再杀死）：compose 716/725 → 724/725，
tracker 472/493 → 492/493，crisis（已检查的 879 个）719/836 → 830/836。

第三轮的复核做到了哪里：compose 的 43 个与 tracker 48 个中的 36 个已用全范围、不转义的测试名重跑，**一个也没被
现有测试杀死**，所以上表 compose 与 tracker 的“新测试另杀死”都是现有测试确实漏掉的。tracker 剩下 12 个（10 个
`__init__`、2 个 `_status`，全是等价变异）没来得及重跑，另在新进程里用 `tests/safety/test_tracker.py` 与
`tests/redteam/test_multiturn.py` 复核为存活。crisis 的 203 个第一轮存活变异没有重跑第三轮，其中一部分新测试
杀死的变异也许已被某个用中文参数化的现有测试杀死（mutmut 当时没跑到它们）：这只影响“现有 / 新测试”之间的归属，
不影响“加测试后存活”。

## 等价变异（行为不变）

按理由归类；名字里的序号是 mutmut 的变异编号（`mutmut show <名字>` 可看 diff）。

### compose.py（33 个）

| 理由类别 | 个数 | 变异 |
| --- | ---: | --- |
| 预筛或剪枝改变，但后面每一步仍逐条复查（只影响速度） | 10 | `Composer.__init__` 45、48，`find` 1、23，`_Text.spans` 2，`_covered` 4，`Composer.__init__` 29、32、33、34（`negation_reach` 短语的排序不影响 `_covered` 的“任意拆分”） |
| 同一来源的两个序列 `zip(strict=…)` 改成非 strict | 6 | `_accept` 98、101、102，`_first_hit` 12、15、16 |
| 二分查找的 `lo=` 省略、上界换成 `None`、`a >= b` 改 `a > b`（多出的区间元素都被后面的 `end <= b` 排除；短语非空） | 8 | `_Spans.any_inside` 1、8、14，`_Spans.inside` 1、7、13，`_Text.last_person` 7、13 |
| 前缀数组的初值、长度多 1、正负号或从不读取的 `clause_start[n]` | 7 | `_Text.__init__` 6、8、12、15、17、27、31 |
| 分句起点为 0 或 1 时，往前承接主语的区间是空的或只有一个标点 | 2 | `_accept` 55、56 |

### tracker.py（27 个）

| 理由类别 | 个数 | 变异 |
| --- | ---: | --- |
| 初值不影响结果：换成同为假的 `None`，或在被读到之前就重设（进入危机时；`_l0_streak` 在计数为 0 时不起作用、第一个 L1 轮清零） | 7 | `__init__` 47、51、52、53、54、55、57 |
| 退出危机时的复位值，下次进入危机时重设；`entry is None` 分支不可达 | 5 | `_observe_safe_candidate` 3、25、26、27、28 |
| 确认短语匹配器的值（从不读取）、空守卫匹配器等同 `None` | 3 | `__init__` 23、25、39 |
| `entry_level` 只在危机中非空；等待确认时 `safe_turns` 恒为 0；L2/L3 轮后的 `l0_streak` 只在计数大于 0 时起作用（计数已清零）；未使用的参数 | 4 | `_status` 3、9，`_update_trend` 26，`observe` 54 |
| 文法决定：承诺分句与限定分句从不以时间词结尾 | 4 | `_guard_clear` 33、40，`_is_explicit_confirmation` 21、28 |
| 词表重叠：确认否决词里唯一的限定词“今晚”同时是 F10 否决词，`_scoped_clear` 照样拒绝 | 2 | `_is_explicit_confirmation` 24、26 |
| `exempted = None` 与 `False` 同为假；就寝片段换成占位符而不是删去，只在删去后两侧恰好拼成“准备好”类词时不同 | 2 | `_is_explicit_confirmation` 13、6 |

### crisis.py（43 个，只算第一轮检查过的 879 个变异）

| 理由类别 | 个数 | 变异 |
| --- | ---: | --- |
| `max(…, default=…)` 的生成器从不为空（`_CLAUSE_STOPS` 有 10 个字符），默认值不会被用到 | 8 | `_habit_on_the_cause` 4、6、15、16，`_someone_elses_habit` 6、8、17、18 |
| `rfind(c, None, …)` 与 `rfind(c, 0, …)` 相同 | 2 | `_habit_on_the_cause` 8，`_someone_elses_habit` 10 |
| `find(c, hit.end)` 的结果至少是 `hit.end ≥ 1`，`>= 0` 改 `> 0` / `>= 1` 不变 | 4 | `_habit_on_the_cause` 24、25，`_someone_elses_habit` 26、27 |
| 分句重叠判断的 `<=` 改 `<`：口癖框不含分句标点，等号的情形不会出现 | 4 | `_habit_on_the_cause` 33、34，`_someone_elses_habit` 35、36 |
| 调用方（`_FigureIndex.alone`）只把频率词交给它，“不是频率词”分支不可达 | 1 | `_someone_elses_habit` 2 |
| 空的 `PhraseMatcher` 与 `None` 等同，或打包词表里该节总不为空 | 8 | `_CueIndex.__init__` 34，`_DenialIndex.__init__` 3，`_DenialIndex.clears` 3，`_FigureIndex.__init__` 4、8，`_FigureIndex.alone` 18，`_RecallIndex.__init__` 3、7 |
| 传了 `_index` 时 `lexicons` 不再被读 | 3 | `SafetyScreen.__init__` 3、11，`with_model` 3 |
| `Match.key`、异常信息文字不参与任何判断（校验保证必有分数，`_cue_score` 的异常不可达） | 5 | `_has_own_risk` 2，`predict_matches` 78，`_repeated_frames` 10、17，`_cue_score` 2 |
| 布尔累加的初值 `None` 与 `False` 等同 | 4 | `reported_risk` 43、45、47、53 |
| 前置条件使它不可达：规则等级为 L0 而有组合命中时，组合必被遮罩，遮罩短语本身就是线索；规则高于 L0 时必有一个线索短语或配对锚点 | 2 | `rules_found_nothing` 1、2 |
| 没传原文时默认的 `normalized` 换成别的字符串：转述与口癖都读不到，结果相同 | 1 | `predict_matches` 1 |
| 多做一次同样的评估，结果与模型最后看到的读法都不变 | 1 | `assess` 19 |

## 不能判定、没写测试的（8 个）

| 变异 | 改了什么 | 为什么不写测试 |
| --- | --- | --- |
| `compose._Text._subjects` 29 | 同一起点的两个人称词谁先谁后 | 打包词表里没有一个人称词是另一个的前缀，同起点的情形不会出现；文档也没规定这种平手 |
| `tracker._rose` 7 | 极性升幅恰好等于 1e-9 时算不算好转 | 1e-9 只是浮点噪声护栏，文档写的是“高于”，没定义这个边界 |
| `crisis._habit_on_the_cause` 14、`_someone_elses_habit` 16 | 消息第一个字是分句标点时，分句起点差一个字 | 只影响以标点开头的消息，文档没写 |
| `crisis._repeated_frames` 8 | 碰到第一个“非日常动词”的叠词框后不再找后面的叠词框 | 要区分，需要一个非日常动词叠词框的“想死”同时被词表口癖框盖住，文档没定这种组合该怎么读 |
| `crisis.SafetyScreen.assess` 17 | 两种读法等级相同时保留哪一个 | 文档只说“取较高的等级”，没规定平手保留哪种读法 |
| `crisis.SafetyScreen.reported_risk` 10 | 传给 `ReportedSpeech.contents` 的 `cues` 多了请求词等非风险匹配 | `cues` 只用来判断后续分句是否另有风险，非风险匹配该不该算，文档没写 |
| `crisis.SafetyScreen.reported_risk` 21 | 风险线索恰好从转述片段的第一个字开始时算不算“在片段内” | 片段从引述动词起算，打包词表里找不到恰好从片段起点开始的线索，文档也没写这个边界 |

## 新测试（真实缺口）

只断言文档写明的行为：PRD §9.1、SDD §8.1 / §8.2、next-phase.md §9.4，以及各模块 docstring 里写明的负责人
决定与字段约定。compose 的测试全部用中性占位字（甲、乙、丙……）搭的规则，不依赖 `risk.yaml` 的任何条目；
tracker 与 crisis 的测试用打包词表，但只用文档举过的句式，句子都是新写的。

下面三张表列的是每个测试杀死的变异；其中 tracker 的 `observe` 33、35、82、86–90，`_confirms_scoped` 1，
`_status_kinds` 3、4 与 crisis 的一部分（`clear_denial`、`_DenialIndex.clears`、`_habit_on_the_cause` 的若干个）
也被第二轮的 session 层现有测试杀死，新测试在 `tests/safety` 这一层把它们直接锁住；上表“新测试另杀死”只计现有测试
都没杀死的。

### `tests/safety/test_mutation_compose.py`（8 个测试，杀死 8 个真实缺口变异）

| 测试 | 依据 | 杀死的变异 |
| --- | --- | --- |
| 前面的“忍不住”、正反问不挡住后面真正的否定词 | PRD §9.1 F1（否定词使组合失效；忍不住、要不要不算否定） | `_real_negators` 7、16 |
| 句首的否定词不按正反问读（不拿句尾字去比） | 同上 | `_real_negators` 10 |
| 部分落在两个例外中后一个里也算例外 | `Composition.exceptions` | `_Spans.covers` 10 |
| 被否定的 `unless` 词不再使组合失效；组合自身末尾的否定词不否定它后面的 `unless` 词 | `CompositionRules.unless_negators` / `unless_negation_gap`（“不是为了烧烤”“不用再醒那么早”） | `_Text.denied` 16、17 |
| 部分里含“自己”时，真正的主语仍是它前面的人称词 | PRD §9.1 F1（主语是他人） | `_Text.last_person` 21 |
| 承接上一分句主语时，跳过听话人“你”但不丢掉它前面的主语 | 同上；`listeners` 的约定 | `_Text.last_person` 23 |

### `tests/safety/test_mutation_tracker.py`

| 测试 | 依据 | 杀死的变异 |
| --- | --- | --- |
| 危机中（确认前、确认后）的 L1 轮不升级、不计入连续 L1 | SDD §8.2（确认后 L1 暂停计数），§9.4 第 3 条（#139 起危机中的 L1 不计入） | `observe` 33、35 |
| 回答别的问题（`confirmable=False`）时的“是的”被模型判 L2 仍算复发 | tracker round 6 `confirmable` 约定；F8a ③ 只适用于安全确认 | `observe` 11 |
| 进入危机那一轮的回答里的确认算数（`confirm_on_entry`），只在进入那一轮 | tracker round 6 `confirm_on_entry` | `observe` 82、86–90 |
| 放下念头、两类平静状态算确认；一类状态不算 | §9.4 第 17 条；tracker round 5 / round 6 | `_confirms_scoped` 1，`_status_kinds` 3、4 |
| 承诺 / 限定分句里的时间词是它自己的范围；之外的时间词、“才怪”、规则线索、危险词仍使确认失效；就寝、交出药、已离开高处的片段在守卫读之前删去 | SDD §8.2 F2a（否认词表优先，失败时留在危机），tracker round 3–5、7 | `_is_explicit_confirmation` 19、20、23、30、31、32，`_guard_clear` 12、17、22、29、31、32、35、36、38、42，`_scoped_clear` 1 |
| 告别类线索只在危机中确认之后先问 | §9.4 第 33 条（负责人 2026-11-01 决定） | `asks_after_confirmation` 1 |
| 词表没有 F10 否决词时安全分句照常确认 | S5 与 `DenialRules` “该节缺省时不封顶” | `_guard_clear` 6 |

### `tests/safety/test_mutation_crisis.py`

| 测试 | 依据 | 杀死的变异 |
| --- | --- | --- |
| `with_model` 的计划证据开关默认关闭、传 `True` 时生效 | SDD §8.2（`model_plan_evidence` 是唯一开关，出厂关闭） | `with_model` 1、10 |
| 紧接在 `raise_with_risk` 线索之后的 Stage 2 短语算“片段之外” | §9.4 第 18 条；`CompositionHit.end` 为开区间 | `_has_own_risk` 15 |
| `rule_clear`：被否定的死亡词、例外里的配对锚点都是线索，单独的请求词不是 | 负责人 2026-10-26 决定（`rules_found_nothing` 的定义），§9.4 第 1 条 | `rules_found_nothing` 7、8、9 |
| 全是口癖的消息带口癖线索 id | F8a；`RiskPrediction.cue_ids` 只放线索 id | `predict_matches` 21 |
| “X得想死”旁有否定短语或配对锚点时仍是 L2 | 负责人 2026-10-28 决定，§9.4 第 4 条 | `_FigureIndex.alone` 8、13、14 |
| 方向控制符：保留的读法最后评估，模型最后一次预测就是它的 | 复测 q4 IN-4（round 5） | `assess` 18、20 |
| 别人的频率词、原因上的频率词先问；用户自己的、无主语的、口癖本句里的、谈痛苦本身的仍是 L2 | §9.4 第 27、32 条（负责人 2026-10-30 追认、2026-11-01 决定 B） | `_someone_elses_habit` 18 个，`_habit_on_the_cause` 13 个，`_FigureIndex.alone` 22、28 |
| 叠词口癖：生存、痛苦类动词仍是 L2，日常动词先问 | crisis round 5（“非日常动词”） | `_repeated_frames` 7 |
| `clear_denial`：Stage 1、配对锚点、组合、被否定的否认、否认之外的 Stage 2、转折与否决词都使它为假 | 负责人 2026-10-26 决定，§9.4 第 6、26 条 | `clear_denial` 21 个，`_DenialIndex.clears` 21 个 |
| `reported_risk` 的各字段（等级、计划、用户无线索、规则风险、锚点、告别强度、用户另说话）、英文转述、转述里的二次转述不再作废 | 问题单第 6 条，§9.4 第 8 条；`ReportedRisk` 字段约定 | `reported_risk` 63 个，`_assess` 50、65、66 |

## 发现的问题（没有改产品代码）

1. **`crisis.py:479–493` `_someone_elses_habit`：谈痛苦本身的频率分句被当成“别人的习惯”。**
   “洗碗洗得想死，难受的是每天都要洗”实际 L1 + D3 先问；按负责人 2026-11-01 决定 B（§9.4 第 32 条：频率词所在分句
   谈的是想死或痛苦本身时仍升 L2）与 round 6 的说明（主语不能只是“感觉 / 心里”这类内心状态），期望 L2。原因：
   “难受的是”不在 `_NO_SUBJECT` 的封闭词表里，被读成了分句自己的主语，于是 `_someone_elses_habit` 返回真，
   `_habit_on_the_cause` 的痛苦检查不再起作用。同句加上“我”（“难受的是我每天都要洗”）就是 L2。新测试只锁了带“我”
   的这一句，没有锁这个实际行为。是在给 `_habit_on_the_cause` 9、11、12、17 写测试时发现的。

顺带看到、不是变异测试得出的一处（交给改规则召回的分支判断）：规则模式下“自杀有什么方法”是 L0。SDD §8.2 R-MS
写配对线索的请求词含“方法、办法”、锚点含“自杀”；词表里 `L2_METHOD_PAIR_MEANS` 有“方法 / 办法”但锚点不含“自杀”，
`L2_METHOD_PAIR_MANNER` 有“自杀”但请求词不含“方法 / 办法”。

## 没覆盖的部分

- **crisis.py 有 179 个变异第一轮没跑到**（总时长到了上限，第一轮在这里停下）：`SafetyScreen._assess` 152 个、
  `_CueIndex.compose` 14 个、`_CueIndex.scan` 13 个、`_remember` 4 个（有重叠计数时以 mutmut 的名字为准）。
  第三轮把它们排在最后用全范围跑，结果见下一节；没跑完的部分就是没覆盖。
- crisis 的 203 个第一轮存活变异没有用第三轮（不转义测试名）重跑，见“结果”一节末尾的说明。
- tracker 的 12 个等价变异没有用第三轮重跑，只在新进程里用 tracker 的测试复核。
- 变异只做在函数体内（mutmut 3 不改模块级常量），所以 `tracker.py` 与 `crisis.py` 顶部的正则与词表常量
  （`_PROMISE`、`_SAFE_CLAUSE`、`_HABIT_WORDS`、`_NO_SUBJECT` 等）完全没有被变异。
- 只量时延的 `tests/safety/test_performance.py` 和名字含 performance 的文件不在范围里（trampoline 会拖慢每次调用）。
