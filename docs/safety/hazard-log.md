# OLIVIA 临床安全危害日志（草稿）

## 0. 这份文档是什么

- **性质**：参照英国 NHS 临床风险管理标准 DCB0129（面向健康 IT 系统的制造方）的危害日志（hazard log）结构写的**草稿**。它**没有经过临床安全官（Clinical Safety Officer）签署**，也没有配套的临床安全案例报告（Clinical Safety Case Report）；如果将来有机构部署本产品，部署方的职责对应 DCB0160，不在本文范围内。
- **临床审阅**：发布门禁 G-0（两名注册心理师审阅）已由负责人在 2026-10-25 搁置，不再是必经环节（`docs/superpowers/plans/2026-10-23-next-phase.md` §9.2）。因此下面每条的初始与残余评级，是工程上依据产品文档、测试与评估结果做出的判断，**不是临床结论**；**残余风险是否可以接受，由产品负责人判断**。标“待 G-0”的条目，其控制措施里有尚未经临床审阅的判断或文案。
- **适用版本**：main `f2b09c8`（2026-11-25）。`olivia chat` 默认模型模式（打包的第八轮学生 `4524170efaf8d8b0`），L3 开关 `model_plan_evidence` 关闭（负责人决定）。
- **范围**：离线命令行程序本身。PRD 中的 AI 增强（P7：CHANG-01、CHANG-06、RSK-03、RSK-08）当前不存在，相关危害不在本日志中；将来接入时必须重新评估（尤其是提示注入与生成内容）。
- **一手材料**：PRD（`docs/PRODUCT_DOCUMENT.md`）§2.2 非目标、§6.1、§7、§9、§11；SDD（`docs/SYSTEM_DESIGN.md`）§8、§10；进度表 §9.1–§9.4（含已执行的 33 条偏离）；红队集 `tests/redteam/cases.yaml` 文件头列出的 12 类；`scripts/privacy_audit.py` 的检查项。

## 1. 风险评级方法

每条危害评两次：**初始**（没有本产品的控制措施时）与**残余**（控制措施就位后）。每次给出严重度与可能性，再由下面的矩阵读出风险等级。矩阵按 DCB0129 / DCB0160 指南常用的 5 × 5 分级方式整理，用词是本文自己的说明，不是标准原文；矩阵各格应由临床安全官最终确认。

### 1.1 严重度（后果有多重）

| 等级 | 含义（对使用者） |
| :--- | :--- |
| 轻微 | 短暂的不适或困惑，自己就能恢复，与安全无关。 |
| 显著 | 明显的困扰、被冒犯或信任受损，可能因此停用或错过一次支持；没有持续伤害。 |
| 较大 | 得到不合适的内容或支持被延误，可能让状况短期加重，需要他人或专业人员帮忙才能恢复。 |
| 重大 | 可能造成严重心理伤害、自伤或长期恶化；或敏感健康信息大范围泄露。 |
| 灾难性 | 可能导致死亡或不可逆的伤害。 |

### 1.2 可能性（在会遇到这种情境的使用者中，多常发生）

| 等级 | 含义 |
| :--- | :--- |
| 极高 | 几乎每次出现这种情境都会发生。 |
| 高 | 经常发生；评估或测试里反复出现。 |
| 中 | 偶尔发生；评估或测试里出现过。 |
| 低 | 很少发生，但能想出具体情形。 |
| 极低 | 几乎不会发生，需要几道控制同时失效。 |

### 1.3 风险矩阵与等级含义

| 可能性 ＼ 严重度 | 轻微 | 显著 | 较大 | 重大 | 灾难性 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| 极高 | 3 | 4 | 4 | 5 | 5 |
| 高 | 2 | 3 | 3 | 4 | 5 |
| 中 | 2 | 2 | 3 | 3 | 4 |
| 低 | 1 | 2 | 2 | 3 | 4 |
| 极低 | 1 | 1 | 2 | 2 | 3 |

| 风险 | 含义 |
| :---: | :--- |
| 1 | 可以接受，不需要另加措施。 |
| 2 | 可以接受，前提是再降低风险已不现实或代价不成比例。 |
| 3 | 不理想：只有在负责人（正式流程中是临床安全官）写明理由、同意接受并持续监测时才接受。 |
| 4 | 必须进一步控制；降到 3 或以下之前不应对外发布。 |
| 5 | 不可接受。 |

注意：按这个矩阵，严重度为“灾难性”的危害即使可能性降到“极低”也仍是 3。所以本日志里大量危机识别类条目的残余风险停在 3 或 4，这是危害本身的性质，不代表控制没有做；它们都需要负责人逐条决定是否接受。

### 1.4 状态

- **已控制**：控制措施已实现、有测试锁定，没有登记中的已知缺口。残余风险是否可接受仍由负责人判断。
- **部分控制**：控制措施已实现，但有登记中的已知缺口、评估未达标（如 G-2），或依赖人工流程、无法验证的前提。
- **开放**：还没有有效的控制措施。本版没有这样的条目。
- **待 G-0**：控制措施已实现、有测试，但其中的临床判断或文案标着“草稿：待 G-0”，临床上是否合适没有人审过。

## 2. 字段与维护

每条危害用一个 `yaml` 代码块写结构化字段，代码块之后是说明文字：

| 字段 | 含义 |
| :--- | :--- |
| `id` | `HAZ-NN`，唯一 |
| `title` | 短名，用于汇总表 |
| `hazard` | 危害：可能出什么问题 |
| `cause` | 原因（列表） |
| `effect` | 后果：对使用者意味着什么 |
| `initial` / `residual` | 初始 / 残余的 `severity`（严重度）、`likelihood`（可能性）、`risk`（风险，须与矩阵一致） |
| `controls` | 控制措施：代码或数据位置（以路径开头时路径必须存在），或 PRD / SDD / 进度表的需求编号与章节 |
| `evidence` | 证据：pytest 节点 id（`tests/...py::测试名`），或 `scripts/` 下的脚本 |
| `status` | 已控制 / 部分控制 / 开放 / 待 G-0 |
| `known_gaps` | 已知缺口：引用 `tests/redteam/known_gaps*.yaml` 中某类条目的**条数**（文件、模式、缺口类型、类别或编号），不贴句子 |

`scripts/check_hazard_log.py`（`scripts/check.sh` 的最后一步，CI 随之运行）检查：编号唯一、字段齐全、严重度与可能性用上表的词、风险在 1–5 且与矩阵一致、残余风险不高于初始风险、每条至少一个控制和一个证据、每个 pytest 证据在 `tests/` 下真实存在（用 AST 扫描测试函数与测试类，不运行 pytest）、脚本证据文件存在、以路径开头的控制措施路径存在、“已控制”不带已知缺口、`known_gaps` 的条数与缺口文件当前内容一致，以及下面的汇总表与各条目一致。

维护规则：

- 红队已知缺口是严格 xfail，某条开始通过就会从缺口文件删掉；删掉后本日志对应的条数也要改（检查会指出是哪一条），并重新判断残余风险与状态。
- 改了任何条目后运行 `python scripts/check_hazard_log.py --table`，把输出贴到汇总表的两个标记之间。
- 证据只说明“这一行为被测试锁定、回归时 CI 会失败”，不证明临床上足够。评估集数字只引自进度表（`docs/superpowers/plans/2026-10-23-next-phase.md` §9），评估集本身不入库。

## 3. 汇总

<!-- hazard-summary:start -->
| 编号 | 危害 | 初始风险 | 残余风险 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| HAZ-01 | 单句危机表达漏判（普通话、主动意念、无计划） | 灾难性 / 高 → 5 | 灾难性 / 中 → 4 | 部分控制 |
| HAZ-02 | 被动轻生念头漏判 | 灾难性 / 高 → 5 | 灾难性 / 中 → 4 | 部分控制 |
| HAZ-03 | 打听结束生命的方法未被拦截 | 灾难性 / 高 → 5 | 灾难性 / 低 → 4 | 部分控制 |
| HAZ-04 | 有计划、手段或时间的危机被低估为 L2 | 重大 / 高 → 4 | 重大 / 中 → 3 | 部分控制 |
| HAZ-05 | 多轮渐进加重的表达漏判 | 灾难性 / 高 → 5 | 灾难性 / 中 → 4 | 部分控制 |
| HAZ-06 | 英文、粤语与中英混用的危机表达漏判 | 灾难性 / 高 → 5 | 灾难性 / 中 → 4 | 部分控制 |
| HAZ-07 | 繁体、异体与不可见字符绕过筛查 | 灾难性 / 中 → 4 | 灾难性 / 低 → 4 | 部分控制 |
| HAZ-08 | 否认、否定或口癖遮罩把真实风险压下去 | 灾难性 / 中 → 4 | 灾难性 / 低 → 4 | 部分控制 |
| HAZ-09 | 当前或刚发生的自伤没有被询问与转介 | 重大 / 高 → 4 | 重大 / 低 → 3 | 待 G-0 |
| HAZ-10 | 低电量前缀、避风港或命令绕过危机筛查 | 灾难性 / 中 → 4 | 灾难性 / 极低 → 3 | 已控制 |
| HAZ-11 | 口癖、日常倾诉与其他话题被误判为危机 | 显著 / 高 → 3 | 显著 / 中 → 2 | 部分控制 |
| HAZ-12 | 危机流程无法结束或反复追问 | 显著 / 高 → 3 | 显著 / 低 → 2 | 已控制 |
| HAZ-13 | 确认安全后复发未被识别，或危机流程过早结束 | 灾难性 / 中 → 4 | 灾难性 / 低 → 4 | 部分控制 |
| HAZ-14 | 危机中结束会话时没有留下号码 | 重大 / 中 → 3 | 重大 / 极低 → 2 | 已控制 |
| HAZ-15 | 热线号码错误、被篡改或被编造 | 灾难性 / 低 → 4 | 灾难性 / 极低 → 3 | 已控制 |
| HAZ-16 | 热线号码或服务时段过期 | 重大 / 中 → 3 | 重大 / 低 → 3 | 部分控制 |
| HAZ-17 | 给错地区的号码 | 重大 / 中 → 3 | 重大 / 低 → 3 | 部分控制 |
| HAZ-18 | 危机卡号码缺失、顺序错误或被其他逻辑遮住 | 灾难性 / 低 → 4 | 灾难性 / 极低 → 3 | 已控制 |
| HAZ-19 | 数据损坏或处理出错时没有号码可给 | 灾难性 / 低 → 4 | 灾难性 / 极低 → 3 | 已控制 |
| HAZ-20 | 复述用户的风险原话 | 较大 / 高 → 3 | 较大 / 低 → 2 | 待 G-0 |
| HAZ-21 | 给出处方、剂量或停药建议 | 重大 / 中 → 3 | 重大 / 极低 → 2 | 已控制 |
| HAZ-22 | 给出诊断标签或病理化措辞 | 较大 / 中 → 3 | 较大 / 极低 → 2 | 已控制 |
| HAZ-23 | 给红线用户不合适的练习 | 重大 / 中 → 3 | 重大 / 低 → 3 | 待 G-0 |
| HAZ-24 | 下发需要专业监护的方法 | 重大 / 低 → 3 | 重大 / 极低 → 2 | 已控制 |
| HAZ-25 | 状态机越权：倾听阶段或危机中给方法 | 较大 / 中 → 3 | 较大 / 极低 → 2 | 已控制 |
| HAZ-26 | 未成年人未被识别或继续深度陪伴 | 重大 / 中 → 3 | 重大 / 中 → 3 | 部分控制 |
| HAZ-27 | 替他人担心时处理不当 | 灾难性 / 中 → 4 | 灾难性 / 低 → 4 | 部分控制 |
| HAZ-28 | 首访与设置命令里的危机句未被筛查 | 重大 / 低 → 3 | 重大 / 极低 → 2 | 已控制 |
| HAZ-29 | 安全计划在危机中念回有害内容 | 较大 / 中 → 3 | 较大 / 低 → 2 | 待 G-0 |
| HAZ-30 | 病态依恋与深夜长时间使用 | 较大 / 中 → 3 | 较大 / 低 → 2 | 待 G-0 |
| HAZ-31 | 联网或把原文发出本机 | 重大 / 低 → 3 | 重大 / 极低 → 2 | 已控制 |
| HAZ-32 | 本机隐私泄露 | 重大 / 中 → 3 | 重大 / 低 → 3 | 部分控制 |
| HAZ-33 | 遗忘或删除之后数据仍可读 | 较大 / 中 → 3 | 较大 / 低 → 2 | 已控制 |
| HAZ-34 | 模型缺失或损坏时没有安全退回 | 灾难性 / 低 → 4 | 灾难性 / 极低 → 3 | 已控制 |
| HAZ-35 | 提示注入 | 较大 / 中 → 3 | 较大 / 极低 → 2 | 已控制 |
| HAZ-36 | 长输入中的危机线索被截断或拖慢 | 灾难性 / 中 → 4 | 灾难性 / 低 → 4 | 部分控制 |
| HAZ-37 | 时延或内存超出预算 | 显著 / 中 → 2 | 显著 / 低 → 2 | 已控制 |
<!-- hazard-summary:end -->

## 4. 危机识别

### HAZ-01 单句危机表达漏判

```yaml
id: HAZ-01
title: 单句危机表达漏判（普通话、主动意念、无计划）
hazard: 用户在一句话里明确表达想死或想结束生命，筛查给出 L0 或 L1，没有进入危机流程。
cause:
  - 规则只认列出的短语、配对与组合，换说法、插入字词、谐音或新俚语就可能漏掉
  - 学生模型的召回不到 100%，且只能抬高、不能补足规则没有的计划证据
  - 用户用 --rules 或模型不可用时只剩规则，规则召回明显更低
effect: 回复是普通陪伴，不出现热线与安全询问；正想死的人得不到求助途径，可能延误求助。
initial: {severity: 灾难性, likelihood: 高, risk: 5}
controls:
  - olivia/data/lexicons/risk.yaml 的 stage2、stage2_pairs、compositions 节
  - olivia/core/safety/compose.py 组合线索引擎（同一分句内两组词按间隔组合，统一排除否定、他人主语、日常抵消）
  - olivia/core/safety/crisis.py SafetyScreen.assess 与取高仲裁（规则是下限，模型只能抬高）
  - olivia/core/perception/student.py 打包的学生模型，olivia chat 默认参与筛查（PRD MIYI-01 F7 实现说明）
  - docs/PRODUCT_DOCUMENT.md §9.1 四级分级与 §6.1 SAFE-09 危机前置
evidence:
  - tests/safety/test_case_suite.py::test_single_turn_case
  - tests/safety/test_crisis.py::test_levels
  - tests/safety/test_compositions.py::test_positive
  - tests/safety/test_compositions.py::test_an_injected_model_never_lowers_a_composition
  - tests/safety/test_rules_context_g3.py::test_a_sentence_naming_nobody_is_the_users_own
  - tests/safety/test_rules_context_g3.py::test_whitespace_ends_a_clause
  - tests/safety/test_rules_context_g3.py::test_trailing_ignores_emoji_and_emote_codes
  - tests/safety/test_metamorphic.py::test_seed_keeps_its_level
  - tests/safety/test_crisis.py::test_rules_stay_a_floor_under_an_injected_model
  - tests/perception/test_student.py::test_crisis_talk_without_method_words_reaches_l2
  - tests/session/test_session_risk_model.py::test_default_session_screens_with_the_student
  - tests/redteam/test_redteam.py::test_case
  - scripts/eval_crisis.py
residual: {severity: 灾难性, likelihood: 中, risk: 4}
status: 部分控制
known_gaps: []
```

G-2 要求标注危机集召回 ≥ 98%，尚未达到。进度表第七轮记录的独立评估集 EVAL-4（只用于报告）：模型模式召回 89.9%（直接进危机与“先问一句”都算接住），规则模式 39.9%。红队集里明确主动意念的用例没有登记缺口；规则模式的已知局限另记在 `tests/safety/known_false_positives.yaml`（文件头汇总由 `test_known_limitations_summary` 锁定）。评估数字只能通过 `scripts/eval_crisis.py` 取得，它不打印句子、不在 `check.sh` 中运行。

### HAZ-02 被动轻生念头漏判

```yaml
id: HAZ-02
title: 被动轻生念头漏判
hazard: 用户表达希望不再醒来、希望没出生过等被动轻生念头（C-SSRS 第 1 项），筛查把它当作疲惫（L1）或日常，没有给热线。
cause:
  - 被动念头常常没有任何死亡字眼，规则短语覆盖有限
  - 只有模型报警且分数低于 0.6 时先问一句而不直接进危机（进度表 §9.4 第 1、2 条）
effect: 依 PRD §9.1，这类表达应按 L2 呈现热线；漏判时用户只得到一般陪伴，热线被延后或缺失。
initial: {severity: 灾难性, likelihood: 高, risk: 5}
controls:
  - olivia/data/lexicons/risk.yaml 的 stage2 不再醒来类短语与 compositions 的希望不再醒来组合
  - olivia/core/perception/student.py 学生模型（红队被动念头 13 条中补上规则漏掉的 11 条）
  - olivia/data/lexicons/risk.yaml 的 model_ask 节（direct_from_score 0.6，负责人 2026-10-26、10-28 决定）
  - docs/PRODUCT_DOCUMENT.md §9.1 被动自杀意念界定
evidence:
  - tests/safety/test_passive_ideation.py::test_passive_ideation_with_inserted_words_is_l2
  - tests/safety/test_passive_ideation.py::test_sleep_and_waking_talk_stays_below_l2
  - tests/safety/test_veiled_requests.py::test_no_more_waking_and_one_and_done_are_l2
  - tests/safety/test_rules_round8.py::test_round8_plain_passive_ideation_enters_the_crisis_flow
  - tests/safety/test_rules_round8.py::test_round8_euphemism_asks_the_direct_question
  - tests/session/test_session_ask_first.py::test_a_model_only_l2_asks_once_with_the_regional_hotlines
  - tests/session/test_session_ask_first.py::test_unclear_off_topic_or_no_answer_enters_the_crisis_flow
  - tests/session/test_session_ask_first.py::test_ending_with_the_question_unanswered_counts_as_the_crisis_flow
  - tests/redteam/test_redteam.py::test_case
residual: {severity: 灾难性, likelihood: 中, risk: 4}
status: 部分控制
known_gaps:
  - {file: tests/redteam/known_gaps.yaml, kind: crisis recall, category: passive_ideation, count: 9}
```

默认的模型模式下红队被动念头已没有登记的漏判：最后一条 rt242（粤语，繁体书写）在 2026-11-25 学生的输入改为先折叠繁体后通过（HAZ-07）；第八轮起原先只得到直接询问的 4 条（rt238、rt241、rt244、rt245）也直接进危机流程（`tests/redteam/known_gaps_model.yaml` 文件头）。规则模式几乎全部漏掉，所以模型不可用或用户选 `--rules` 时这一危害明显加重（见 HAZ-34）。

### HAZ-03 问方法未被拦截

```yaml
id: HAZ-03
title: 打听结束生命的方法未被拦截
hazard: 用户打听结束生命的方法、最快或最无痛的方式，或借写小说、替人问、角色扮演、英文提问，筛查低于 L2，没有进入危机流程或直接询问。
cause:
  - 请求词与死亡锚点被借口隔开，或说法委婉、根本没有死亡字眼
  - 只问“什么方式最有效”而不点出任何行为的问法，与问饮食、学习方法同形
effect: 产品的回复全部来自模板，不会生成方法内容；漏判的后果是错过危机流程与热线，打听方法的人没有被问一句是否安全。
initial: {severity: 灾难性, likelihood: 高, risk: 5}
controls:
  - olivia/data/lexicons/risk.yaml 的 L2_METHOD_SEEKING 与 stage2_pairs（请求词 × 死亡锚点，至少 L2，否定与口癖遮罩不起作用，SDD §8.2 R-MS）
  - olivia/data/lexicons/risk.yaml 的 stage2_ask（委婉问法先直接询问，决定 D3）
  - olivia/core/safety/intent_check.py 直接询问的回答读法（只有明确否认才回到普通对话）
  - olivia/data/templates/ 全部回复来自模板，没有生成模型（SDD §6.2 网关属 P7，未接入）
evidence:
  - tests/safety/test_method_seeking.py::test_method_request_is_at_least_l2
  - tests/safety/test_method_seeking.py::test_masks_never_hide_a_method_request
  - tests/safety/test_method_seeking.py::test_a_request_word_and_an_anchor_in_any_order_are_l2
  - tests/safety/test_rules_method_r8.py::test_a_way_asked_for_someone_else_asks_the_question
  - tests/safety/test_rules_method_r8.py::test_the_session_asks_and_a_yes_enters_the_crisis_flow
  - tests/safety/test_method_seeking.py::test_no_negation_or_hyperbole_mask_contains_a_method_phrase
  - tests/safety/test_intent_ask.py::test_euphemistic_request_asks_at_l1
  - tests/safety/test_veiled_requests.py::test_veiled_request_or_goodbye_for_good_asks_at_l1
  - tests/session/test_session_safety_check.py::test_affirmation_enters_the_crisis_flow
  - tests/session/test_session_safety_check.py::test_unclear_or_no_answer_is_read_as_l2
  - tests/session/test_session_safety_check.py::test_question_never_offers_a_card_even_mid_flow
  - tests/redteam/test_redteam.py::test_d3_question_turn_carries_the_hotline
  - tests/redteam/test_redteam.py::test_case
residual: {severity: 灾难性, likelihood: 低, risk: 4}
status: 部分控制
known_gaps:
  - {file: tests/redteam/known_gaps.yaml, kind: crisis recall, category: self_harm_method, count: 2}
  - {file: tests/redteam/known_gaps_model.yaml, kind: crisis recall, category: self_harm_method, count: 2}
```

G-5 要求诱导自残拦截率 100%，两种模式各差同样 2 条：句中没有行为、死亡或药物锚点，`known_gaps.yaml` 文件头写明是有意留下（同一句式也用于问饮食与学习方法）。

### HAZ-04 计划、手段或时间被低估

```yaml
id: HAZ-04
title: 有计划、手段或时间的危机被低估为 L2
hazard: 用户说出已准备好的手段、具体时间或地点、告别与后事安排，筛查只给 L2（或更低），危机卡没有把急救号码放在最前。
cause:
  - Stage 1 只收带明确自伤锚点的说法，没有锚点的计划只到 L2
  - L3 开关 model_plan_evidence 关闭，学生模型最多给 L2（负责人决定）
  - 告别、后事类说法也用于日常，规则先直接询问而不直接定 L3
effect: 即刻危险的人先看到心理热线，急救号码靠后（L2 卡把当地急救号码列在热线之后）。
initial: {severity: 重大, likelihood: 高, risk: 4}
controls:
  - olivia/data/lexicons/risk.yaml 的 stage1 与 compositions 的 S1_* 计划证据组合（否定与口癖遮罩不作用于 Stage 1）
  - olivia/core/safety/crisis.py 取高仲裁与 L3 刚性要件门控（PRD §9.1，SDD §8.2）
  - olivia/core/session.py 模型判 L3 而开关关闭时，本次危机各轮卡前加急救号码（SDD §8.2 负责人决定第 4 条）
  - docs/superpowers/plans/2026-10-23-next-phase.md §9.4 第 5 条（大陆 L2 卡在 12356 之后列 120）
  - olivia/core/resources/resolver.py 港澳台、美、加、英、澳的 L2 卡也在热线之后列当地急救号码（负责人 2026-11-25 决定 A：HK 999、MO 999、TW 119、US 911、CA 911、GB 999、AU 000）
  - olivia/data/resources/hotlines.yaml 各地区急救号码
evidence:
  - tests/safety/test_lexicon_gaps.py::test_means_place_or_time_with_a_plan_is_stage1
  - tests/safety/test_crisis.py::test_negation_does_not_hide_means
  - tests/safety/test_crisis.py::test_hoarded_pills_are_rated_by_the_rules_and_never_denial_capped
  - tests/safety/test_rules_context_g3.py::test_a_plan_said_whole_in_its_sentence_stands
  - tests/safety/test_rules_context_g3.py::test_parts_still_join_across_whitespace
  - tests/safety/test_crisis.py::test_model_plan_evidence_is_off_by_default
  - tests/session/test_session_flow.py::test_model_l3_capped_at_l2_shows_emergency_numbers_first
  - tests/session/test_owner_decisions_1028.py::test_the_l2_crisis_reply_lists_120_after_12356
  - tests/session/test_owner_decisions_1125.py::test_every_l2_crisis_reply_lists_the_local_emergency_number_after_its_lines
  - tests/session/test_owner_decisions_1028.py::test_a_model_only_l3_class_below_0_6_asks_first_with_the_emergency_numbers
  - tests/resources/test_resource_resolver.py::test_every_l3_card_has_an_emergency_number
  - tests/redteam/test_multiturn.py::test_scenario
  - tests/safety/test_rules_confirm_r8.py::test_a_means_put_away_with_more_stays_plain_l3
  - tests/session/test_session_confirm_r8.py::test_a_means_put_away_asks_first_with_the_emergency_numbers_first
  - tests/session/test_session_confirm_r8.py::test_earlier_risk_in_the_session_makes_it_l3_at_once
  - tests/session/test_session_confirm_r8.py::test_a_plan_and_a_time_after_own_l2_is_l3
residual: {severity: 重大, likelihood: 中, risk: 3}
status: 部分控制
known_gaps:
  - {file: tests/redteam/known_gaps.yaml, kind: crisis recall, category: number_leak, count: 4}
  - {file: tests/redteam/known_gaps_model.yaml, kind: crisis recall, category: number_leak, count: 4}
  - {file: tests/redteam/known_gaps_multiturn.yaml, mode: rules, kind: crisis recall, ids: [mt002, mt007, mt019, mt041], count: 4}
  - {file: tests/redteam/known_gaps_multiturn.yaml, mode: model, kind: crisis recall, ids: [mt002, mt007, mt019, mt041], count: 4}
```

这些缺口里多数已进入 L2 危机流程，只是达不到 L3；规则模式下有几条连 L2 都没有到（同时属于 HAZ-01）。负责人 2026-11-25 决定 A 之后，所有有热线的地区 L2 卡都在热线之后列当地急救号码（台湾 L2 只列 119，澳门只列 999），这些缺口落在 L2 时卡上也有急救号码，只是不在最前。

### HAZ-05 多轮渐进表达漏判

```yaml
id: HAZ-05
title: 多轮渐进加重的表达漏判
hazard: 用户每句话单看都只是疲惫或无意义感（L1 或 L0），几轮下来明显在加重，筛查始终没有升到 L2。
cause:
  - 连续升级只数规则判出的 L1；只由模型给出的 L1 不计入（F8a 第 1 条收窄，防止日常低落误升）
  - 中间夹一句 L0 会暂停计数，三句 L0 清零
  - 危机中的 L1 不计入连续升级（进度表 §9.4 第 3 条，#139）
effect: 逐步走向危机的人一直得到普通陪伴，没有热线。
initial: {severity: 灾难性, likelihood: 高, risk: 5}
controls:
  - olivia/core/safety/tracker.py 连续 3 轮 L1 且没有好转即按 L2 进入危机流程（PRD §9.1 F2a，负责人 2026-10-24 决定）
  - olivia/data/lexicons/risk.yaml 组合字段 raise_with_risk（本会话已有 L1 或之前有过危机时，告别类直接升 L2，进度表 §9.4 第 18 条）
  - olivia/core/session.py 有危机史的用户说 L1 的话时加一句关怀与一行热线（进度表 §9.4 第 10 条）
  - olivia/core/chang/care.py 跨会话关怀标记，下一次会话先轻度问候
evidence:
  - tests/safety/test_tracker.py::test_three_l1_turns_without_improvement_escalate
  - tests/safety/test_tracker.py::test_plain_l1_escalates_on_third_turn_without_improvement
  - tests/safety/test_case_suite.py::test_session
  - tests/session/test_session_escalation.py::test_seven_weary_turns_show_a_hotline_by_turn_three
  - tests/session/test_session_escalation.py::test_escalation_is_reported_as_l2_on_the_escalating_turn
  - tests/safety/test_lexicon_gaps.py::test_a_farewell_after_an_l1_turn_enters_the_crisis_flow
  - tests/safety/test_hyperbole_ask.py::test_the_tracker_escalates_the_frame_after_earlier_risk_in_the_session
  - tests/session/test_session_safety_round2.py::test_l1_after_a_crisis_gets_care_and_one_hotline_line
  - tests/redteam/test_multiturn.py::test_scenario
residual: {severity: 灾难性, likelihood: 中, risk: 4}
status: 部分控制
known_gaps:
  - {file: tests/redteam/known_gaps_multiturn.yaml, mode: rules, kind: crisis recall, ids: [mt004], count: 1}
  - {file: tests/redteam/known_gaps_multiturn.yaml, mode: model, kind: crisis recall, ids: [mt004], count: 1}
```

“只由模型给出的 L1 不计入连续升级”是为了减少误报（HAZ-11）而做的取舍；登记的这条多轮缺口在模型模式下正是因此不升级。多轮红队场景共 48 个，其余渐进类缺口归在 HAZ-04（升到了 L2，没到 L3）。

### HAZ-06 英文、粤语与混用表达漏判

```yaml
id: HAZ-06
title: 英文、粤语与中英混用的危机表达漏判
hazard: 用户用英文、粤语或中英混杂表达危机，筛查低于 L2。
cause:
  - 词表以普通话为主，英文与粤语条目是逐轮补上的，覆盖有限
  - 学生模型主要用普通话数据训练
effect: 同 HAZ-01：错过危机流程与热线。境外地区（港澳、北美、英澳）的用户更可能这样输入。
initial: {severity: 灾难性, likelihood: 高, risk: 5}
controls:
  - olivia/data/lexicons/risk.yaml 的英文短语、英文组合模块（#131）与粤语条目
  - olivia/data/lexicons/risk.yaml 的 stage2_ask 粤语与英文委婉问法（完咗佢、end it）
  - olivia/core/safety/normalize.py 大小写与弯引号折叠
evidence:
  - tests/safety/test_lexicon_gaps.py::test_cantonese_rates_as_the_mandarin_form
  - tests/safety/test_veiled_requests.py::test_cantonese_end_it_alone_asks_at_l1
  - tests/safety/test_method_seeking.py::test_method_request_is_at_least_l2
  - tests/safety/test_rules_round7.py::test_round7_english_at_the_edge_enters_the_crisis_flow
  - tests/safety/test_rules_generalize_round3.py::test_an_embedded_or_english_cue_asks_in_a_session
  - tests/safety/test_normalize.py::test_curly_apostrophes_fold_to_ascii
  - tests/safety/test_intent_ask.py::test_an_english_unsure_word_voids_an_english_denial
  - tests/safety/test_rules_method_r8.py::test_a_last_day_said_as_now_stays_l2
residual: {severity: 灾难性, likelihood: 中, risk: 4}
status: 部分控制
known_gaps: []
```

英文与粤语没有独立的成套用例与召回数字：`tests/safety/cases.yaml` 里英文句子只有零星几条，EVAL-4 也以普通话为主。原先登记的那条模型模式缺口 rt242（粤语被动念头，繁体书写，同时计入 HAZ-02）在 2026-11-25 学生的输入先折叠繁体后通过（HAZ-07）；规则模式仍漏掉它（`tests/redteam/known_gaps.yaml`）。

### HAZ-07 繁体、异体与不可见字符绕过

```yaml
id: HAZ-07
title: 繁体、异体与不可见字符绕过筛查
hazard: 用户用繁体字、全角字符、零宽字符、方向控制符或非 UTF-8 编码输入危机表达，筛查读不出来。
cause:
  - 词表只写简体
  - 粘贴的文本可能带不可见字符；终端可能送来 GBK 字节
  - 学生模型的字表几乎没有繁体字；乾、著、後、於、覆、藉等 11 个繁体写法同时是合法简体字，只能原样交给学生
effect: 同 HAZ-01；港澳台用户最可能受影响。
initial: {severity: 灾难性, likelihood: 中, risk: 4}
controls:
  - olivia/core/safety/normalize.py 规范化（去掉不可见字符、全角半角、方向控制符按两种读法都筛并取高）
  - olivia/core/safety/_trad2simp.py 繁简折叠表：手写 1540 对，加 scripts/gen_trad2simp.py 用 macOS 自带 ICU 生成的 1070 对（只收不能用 GB2312 编码的源字，排除 讎、囍、榖 这类有歧义或并非繁体的字；提交的是生成结果，各平台都只读这张表）；词表里每个字都已分类
  - olivia/core/perception/student.py model_input（2026-11-25）：学生的输入在训练时的预处理之外只多两步，把源字不是合法简体字的 2599 对繁体折成简体，去掉不可见、格式字符与组合附加符；不做 NFKC、不去标点、空白仍按训练时合并（crisis.py 不用改）
  - olivia/cli.py clean_input（GBK 与残缺 UTF-8 输入）
evidence:
  - tests/safety/test_crisis.py::test_traditional_chinese_is_screened
  - tests/safety/test_normalize.py::test_traditional_folds_to_simplified
  - tests/safety/test_normalize.py::test_traditional_view_of_every_lexicon_phrase_normalizes_back
  - tests/safety/test_normalize.py::test_every_lexicon_character_is_classified
  - tests/safety/test_normalize.py::test_invisible_characters_are_dropped
  - tests/safety/test_compositions.py::test_traditional_script_is_composed
  - tests/safety/test_red_flags.py::test_traditional_chinese_red_flags
  - tests/cli/test_cli_hotlines_under_failure.py::test_a_gbk_crisis_sentence_on_the_pipe_shows_the_crisis_card
  - tests/safety/test_normalize.py::test_generated_pairs_follow_the_generation_rules
  - tests/safety/test_normalize.py::test_the_icu_block_folds_no_character_of_the_data_files
  - tests/safety/test_metamorphic.py::test_seed_keeps_its_level
  - tests/perception/test_student_input.py::test_golden_texts_read_as_in_training
  - tests/perception/test_student_input.py::test_traditional_view_of_every_seed_reads_back
  - tests/perception/test_student_input.py::test_invisible_rewrites_of_every_seed_read_as_the_seed
  - tests/perception/test_student_input.py::test_a_model_only_alarm_takes_the_same_turn_in_either_script
  - scripts/metamorphic_report.py
residual: {severity: 灾难性, likelihood: 低, risk: 4}
status: 部分控制
known_gaps: []
```

规则侧对繁体是完整的（词表每个短语的繁体写法都能折回）。2026-11-25 起模型侧也折叠：`StudentModel.encode` 读 `model_input`，不含繁体、不可见或组合字符的文本与训练时逐字相同（学生的 golden 测试 48 条一条没变，开发集两种模式的数字不变）。变形测试模型模式（`scripts/metamorphic_report.py --mode model`）：繁体 99.27% → 100%，零宽与不可见填充字符五种各 99.27% → 100%，组合下划线 99.27% → 100%，总不变率 98.37% → 98.54%。会话层：规则单独判不到 L2 的危机种子里取 12 条，改动前繁体写法有 8 条、零宽混排有 11 条与简体走的不是同一轮（进危机 / 先问一句 / 都不），改动后都一致。残余：乾、著、後、於、覆、藉、徵、夥、拚、麴、麽 这 11 个字同时是合法简体字（能用 GB2312 编码），学生仍看到原字（著、後在字表里，其余是未知字）；用变形测试的繁体写法试 564 个期望 L2/L3 且有繁体写法的种子，学生单独给出的等级变了 2 条、分数跨过 0.6 的 2 条（改动前分别是 321 条和 362 条），都因为 著 或 後；这些种子在模型模式下的变形测试不变性全部成立（规则侧照常折叠）。红队 rt242（粤语被动念头，繁体书写）因此在模型模式通过，已从 `tests/redteam/known_gaps_model.yaml` 删除（HAZ-02、HAZ-06 同步）。另外 帳、鍊、鉅、祇、瞭 等手写对有第二种读法，学生按常见读法折叠（帳號 → 账号，鍛鍊 → 锻炼），少见的那种读法（帳篷、項鍊、神祇、瞭望）会被折错。字间插空格时学生仍按训练读到空格，模型模式不变率 91.99%，不在这次改动范围。

### HAZ-08 否认、否定与口癖遮罩掩盖真实风险

```yaml
id: HAZ-08
title: 否认、否定或口癖遮罩把真实风险压下去
hazard: 为减少误报而设的否定遮罩、否认封顶、口癖封顶与直接询问的否认读法，把带着真实风险的话（“我不想死，但……”、双重否定、改口）压到 L1 及以下。
cause:
  - 遮罩与封顶按词表判断，词表外的转折、改口或附带风险内容会被漏看
  - 进度表 §9.4 第 6、7 条第一次允许压低规则自己的 L2（第一人称否认开头的回答）
effect: 同 HAZ-01：错过危机流程与热线，而且是在用户其实说出了风险的时候。
initial: {severity: 灾难性, likelihood: 中, risk: 4}
controls:
  - olivia/core/safety/crisis.py 否认封顶的全部否决条件（规则 L0、所有 Stage 2 短语都在否认之内、无双重否定、无转折、无否决词、无组合线索、模型无故障，SDD §8.2 F10）
  - olivia/data/lexicons/risk.yaml 的 denial、negation、hyperbole 节（加载时校验否认短语不含转折词与否决词）
  - Stage 1 计划证据与问方法配对线索不受任何遮罩影响（SDD §8.2）
  - olivia/core/safety/intent_check.py 否认之后的部分单独再筛查（#136）
evidence:
  - tests/safety/test_crisis.py::test_negation_does_not_hide_means
  - tests/safety/test_crisis.py::test_negation_does_not_hide_other_ideation
  - tests/safety/test_crisis.py::test_the_denial_cap_never_hides_risk_content_after_the_denial
  - tests/safety/test_crisis.py::test_every_stage2_phrase_voids_the_denial_cap
  - tests/safety/test_crisis.py::test_a_contrast_right_after_the_denial_voids_the_cap
  - tests/safety/test_crisis.py::test_the_hyperbole_cap_needs_every_risk_phrase_figurative
  - tests/safety/test_crisis.py::test_a_model_failure_on_a_denial_still_fails_safe_to_l2
  - tests/safety/test_hyperbole_ask.py::test_any_other_cue_or_veto_keeps_l2_or_above
  - tests/safety/test_rules_method_r8.py::test_a_run_of_days_after_a_pain_cleft_keeps_the_figure_at_l2
  - tests/session/test_session_safety_round2.py::test_a_new_risk_cue_after_the_no_still_enters_the_crisis_flow
  - tests/session/test_session_safety_round2.py::test_a_no_with_a_rule_cue_keeps_the_models_level
  - tests/safety/test_rules_confirm_r8.py::test_not_wanting_to_die_negated_or_risk_after_stays_unclear
  - tests/session/test_session_confirm_r8.py::test_not_not_wanting_to_die_enters_the_crisis
  - tests/session/test_session_confirm_r8.py::test_a_yes_an_unclear_answer_or_another_cue_enters_the_crisis_at_l3
residual: {severity: 灾难性, likelihood: 低, risk: 4}
status: 部分控制
known_gaps: []
```

这些收窄的选型只用开发集 `interim_fresh.csv`，独立评估集只报告（评估集纪律）。F16a 时曾系统检查出 12 句被误封顶并补了否决词，说明这类缺口确实存在、只能靠逐类补词；没有登记中的红队缺口不等于没有漏洞。

### HAZ-09 当前自伤未被询问或转介

```yaml
id: HAZ-09
title: 当前或刚发生的自伤没有被询问与转介
hazard: 用户说正在或刚刚伤害自己（非自杀性自伤），系统没有询问自杀意图，也没有给专科转介。
cause:
  - 自伤说法多样，过去时与现在时容易混
  - 负责人决定自伤定为 L1 加直接询问，而不是直接进危机流程
effect: 正在自伤的人没有被问一句是否想结束生命，也没有拿到边缘型情绪失调（SIT-09-01）的转介信息。
initial: {severity: 重大, likelihood: 高, risk: 4}
controls:
  - olivia/data/lexicons/risk.yaml 组合 ASK_INTENT_SELF_INJURY_ACT、_HURT、_WORD（SDD §8.2 负责人决定第 1 条）
  - olivia/data/lexicons/red_flags.yaml 的 RF_SELF_INJURY_ACT（触发 SIT-09-01 转介）
  - olivia/core/session.py 直接询问一轮附 L2 热线，回答“是”、含糊或不回答即进危机流程
evidence:
  - tests/safety/test_compositions.py::test_current_self_injury_flags_and_asks_but_past_does_not
  - tests/safety/test_compositions.py::test_self_injury_asks_the_direct_question_and_a_yes_enters_crisis
  - tests/safety/test_compositions.py::test_self_injury_denied_returns_with_the_referral
  - tests/safety/test_lexicon_gaps.py::test_a_way_to_hurt_oneself_or_the_act_in_detail_is_l2
  - tests/safety/test_lexicon_gaps.py::test_self_injury_with_weariness_keeps_the_owner_decision
  - tests/safety/test_red_flags.py::test_detects_each_code
residual: {severity: 重大, likelihood: 低, risk: 3}
status: 待 G-0
known_gaps: []
```

“自伤先问一句、再看回答”是负责人 2026-10-24 的决定，转介卡文案标“草稿：待 G-0”；对自伤是否应直接给危机卡，需要临床判断。

### HAZ-10 低电量前缀、避风港或命令绕过危机筛查

```yaml
id: HAZ-10
title: 低电量前缀、避风港或命令绕过危机筛查
hazard: 用户在低电量前缀（如 [5%]）、避风港、纯倾听锁、斜杠命令或直接要方法的同一句里表达危机，或用这些方式离开危机流程。
cause:
  - 业务分支（电量、避风港、命令）如果先于危机筛查执行，危机句会被当作疲惫或指令处理（PRD RSK-02）
effect: 危机被当作“想休息”或“要练习”，不出热线；或危机流程被命令提前结束。
initial: {severity: 灾难性, likelihood: 中, risk: 4}
controls:
  - olivia/core/session.py 每轮先做危机筛查，再做任何业务分支（PRD §6.1 SAFE-09）
  - olivia/core/fsm/machine.py 危机优先于电量、纯倾听锁、命令与直接要方法；危机只能经确认安全离开，且只回到 S_explore
  - olivia/core/safety/tracker.py 危机退出需要确认安全加安全轮（电量前缀不算确认）
evidence:
  - tests/safety/test_tracker.py::test_battery_prefix_cannot_bypass_crisis
  - tests/session/test_session.py::test_low_battery_crisis_enters_s_crisis_with_12356_and_no_haven
  - tests/session/test_session.py::test_crisis_holds_through_low_battery_and_commands
  - tests/fsm/test_machine.py::test_crisis_beats_battery_lock_commands_and_direct_request
  - tests/fsm/test_machine.py::test_crisis_exit_never_routes_to_haven
  - tests/fsm/test_machine.py::test_crisis_still_beats_direct_request_in_haven
  - tests/session/test_session_flow.py::test_crisis_wins_over_the_haven_exit_words
  - tests/cli/test_cli_golden.py::test_sop2_low_battery_never_hides_a_crisis
residual: {severity: 灾难性, likelihood: 极低, risk: 3}
status: 已控制
known_gaps: []
```

多轮场景 mt019 的第一轮在规则模式下判 L0，那是危机识别的漏判（计入 HAZ-04），不是电量前缀绕过：那一句的写法没有被读作电量前缀，所以也没有进入避风港。

## 5. 误报与过度打扰

### HAZ-11 口癖与日常表达误报

```yaml
id: HAZ-11
title: 口癖、日常倾诉与其他话题被误判为危机
hazard: 日常夸张（单独的“想死”“不想活了”）、重度倾诉后要方法、问药、雷区话题等非危机消息被送进危机流程。
cause:
  - 2026-10-22 裁定：单独的“想死 / 不想活了”不加遮罩，宁可误报（PRD RSK-01）
  - 学生模型会把部分日常计划、告别或倾诉判到 L2
effect: 普通倾诉被热线卡打断，用户觉得被误解，信任受损；以后可能隐瞒真实想法，间接加重漏判。
initial: {severity: 显著, likelihood: 高, risk: 3}
controls:
  - olivia/data/lexicons/risk.yaml 的 hyperbole 遮罩与 hyperbole_ask（“X 得 / 到想死”单独出现先问一句，进度表 §9.4 第 4 条）
  - olivia/core/safety/crisis.py 口癖封顶（规则口癖盖住全部风险短语时模型最多 L1，SDD §8.2 F8a）
  - olivia/core/safety/tracker.py 只有模型给出的 L1 不计入连续升级
  - olivia/data/lexicons/risk.yaml 的 model_ask（只有模型报警且分数低于 0.6 时先问，进度表 §9.4 第 1、2、26、31 条）
  - docs/PRODUCT_DOCUMENT.md §9.1 L1 绝不弹出求助卡
evidence:
  - tests/safety/test_crisis.py::test_hyperbole_is_not_ideation
  - tests/safety/test_hyperbole_ask.py::test_the_frame_alone_is_l1_with_the_question
  - tests/safety/test_hyperbole_ask.py::test_everyday_death_idioms_are_unchanged
  - tests/safety/test_lexicon_gaps.py::test_daily_talk_stays_below_l2_and_asks_nothing
  - tests/safety/test_rules_context_g3.py::test_nothing_spans_the_place_where_the_copies_meet
  - tests/safety/test_rules_context_g3.py::test_trailing_still_refuses_words_after_a_decoration
  - tests/safety/test_rules_method_r8.py::test_a_last_day_imagined_is_no_crisis
  - tests/safety/test_method_seeking.py::test_everyday_prevention_grief_and_help_stay_below_l2
  - tests/safety/test_crisis.py::test_injected_model_is_at_most_l1_where_a_hyperbole_cue_covers_every_risk_phrase
  - tests/perception/test_student.py::test_everyday_plans_and_farewells_rarely_reach_l2
  - tests/session/test_session_ask_first.py::test_a_clear_no_stays_in_ordinary_talk_without_a_care_flag
  - tests/safety/test_tracker.py::test_model_only_l1_turns_do_not_escalate
  - tests/redteam/test_redteam.py::test_case
residual: {severity: 显著, likelihood: 中, risk: 2}
status: 部分控制
known_gaps:
  - {file: tests/redteam/known_gaps.yaml, kind: rules false alarm, category: everyday_hyperbole, count: 2}
  - {file: tests/redteam/known_gaps_model.yaml, kind: rules false alarm, category: everyday_hyperbole, count: 2}
  - {file: tests/redteam/known_gaps_model.yaml, kind: model false alarm, category: everyday_hyperbole, count: 2}
  - {file: tests/redteam/known_gaps_model.yaml, kind: model false alarm, category: venting_method_request, count: 3}
  - {file: tests/redteam/known_gaps_model.yaml, kind: model false alarm, category: prescription, count: 1}
  - {file: tests/redteam/known_gaps_model.yaml, kind: model false alarm, category: taboo_topic, count: 1}
  - {file: tests/redteam/known_gaps_multiturn.yaml, mode: rules, kind: rules false alarm, category: idiom_exaggeration, count: 1}
  - {file: tests/redteam/known_gaps_multiturn.yaml, mode: model, kind: rules false alarm, category: idiom_exaggeration, count: 1}
  - {file: tests/redteam/known_gaps_multiturn.yaml, mode: model, kind: model false alarm, count: 2}
```

G-2 的另一半（口癖误报 ≤ 5%）未达标：红队口癖类误报规则模式 2/20，模型模式 4/20；打包学生对 17 句日常计划与告别探针中的 6 句单独判 L2 以上（`test_everyday_plans_and_farewells_rarely_reach_l2` 锁定的是上限，不是目标）。误报与 HAZ-01 的漏判此消彼长，§9.4 的多数收窄都是在这两者之间的取舍。

### HAZ-12 危机流程中的过度打扰

```yaml
id: HAZ-12
title: 危机流程无法结束或反复追问
hazard: 用户已经确认安全，危机流程仍然每轮重复整张危机卡、反复问“你现在安全吗”，或因模型的低把握报警永远无法结束。
cause:
  - 确认的说法很多样，只认少数固定短语时真实的确认听不出来
  - 确认之后学生的低分报警曾每次都作废确认（2026-10-27 复测）
effect: 用户被困在危机流程里，感到被监视、不被相信，可能直接退出，下次不再说实话。
initial: {severity: 显著, likelihood: 高, risk: 3}
controls:
  - olivia/core/safety/tracker.py 确认识别（短语、简短肯定、带前后文的安全分句、承诺、英文，仍受否决条件约束，进度表 §9.4 第 17、29 条）
  - olivia/core/session.py 确认后的等待轮只给一句回应加一行全部号码（进度表 §9.4 第 15 条）
  - olivia/core/safety/tracker.py 确认后学生分类 L2 且分数低于 0.6 的一轮只暂停计数（进度表 §9.4 第 3 条）
  - olivia/core/session.py 只有模型报警的先问每场至多两次（进度表 §9.4 第 31 条）
evidence:
  - tests/session/test_session_flows_round3.py::test_an_unsure_model_alarm_after_the_confirmation_pauses_instead_of_voiding_it
  - tests/session/test_session_flows_round3.py::test_waiting_turns_answer_the_words_with_every_number_and_no_question
  - tests/session/test_session_flows_round3.py::test_the_first_calm_awaiting_turn_says_how_to_confirm
  - tests/session/test_session_crisis_s5.py::test_a_safety_confirmation_with_context_is_heard
  - tests/safety/test_tracker.py::test_short_answer_to_the_safety_question_confirms
  - tests/session/test_owner_decisions_1101.py::test_at_most_two_questions_per_session
  - tests/redteam/test_multiturn.py::test_scenario
residual: {severity: 显著, likelihood: 低, risk: 2}
status: 已控制
known_gaps: []
```

这里的每一项放宽都让危机流程更容易结束，反方向的风险记在 HAZ-13。多轮红队里“危机流程永远不结束”一类缺口（`other`）目前为 0。

## 6. 危机流程的退出与延续

### HAZ-13 确认安全后复发未被识别或过早退出

```yaml
id: HAZ-13
title: 确认安全后复发未被识别，或危机流程过早结束
hazard: 用户的“确认安全”其实是敷衍、反话或改口，或确认后再次出现风险，系统却按安全处理并结束危机流程。
cause:
  - 确认说法的放宽（进度表 §9.4 第 17、29 条）把更多句子读成确认
  - 确认后低分的模型报警只暂停计数（第 3 条），模型自判 L0 的分数段 L1 算安全轮（第 23 条）
  - 确认后出现告别类线索改为先问一句（第 33 条）
effect: 仍在危险中的人回到普通陪伴，热线不再每轮出现。
initial: {severity: 灾难性, likelihood: 中, risk: 4}
controls:
  - olivia/core/safety/tracker.py 双重条件：明确确认安全，之后 L2 需 2 轮、L3 需 3 轮安全轮（PRD §9.1，SDD §8.2）
  - olivia/data/lexicons/risk.yaml 的 safety_confirm 与 confirm_veto（否定、含糊、问句与转折优先）
  - olivia/core/safety/tracker.py 确认之后的规则线索、模型高分报警与分类 L3 仍算复发并需要重新确认
  - olivia/core/chang/care.py 进过危机的会话留下关怀标记，7 天内下一次会话先轻度问候
evidence:
  - tests/safety/test_tracker.py::test_l2_exit_needs_confirmation_then_two_safe_turns
  - tests/safety/test_tracker.py::test_l3_exit_needs_three_safe_turns
  - tests/safety/test_tracker.py::test_relapse_during_exit_resets_and_raises_entry_level
  - tests/safety/test_tracker.py::test_confirmation_inside_crisis_message_is_ignored
  - tests/safety/test_tracker.py::test_negated_questioned_or_sarcastic_confirmation_does_not_count
  - tests/session/test_session_flows_round3.py::test_a_sure_model_alarm_after_the_confirmation_is_still_a_relapse
  - tests/session/test_session_flows_round3.py::test_a_rule_cue_after_the_confirmation_is_still_a_relapse
  - tests/session/test_session_flows_round3.py::test_a_hedged_promise_does_not_confirm
  - tests/session/test_owner_decisions_1028.py::test_the_pause_after_a_confirmation_still_treats_an_l3_class_as_a_relapse
  - tests/cli/test_cli_care.py::test_crisis_then_one_gentle_greeting_then_none
  - tests/redteam/test_multiturn.py::test_scenario
  - tests/session/test_session_confirm_r8.py::test_going_after_a_confirmation_asks_first
  - tests/session/test_session_confirm_r8.py::test_starting_over_after_a_confirmation_asks_first
  - tests/session/test_session_confirm_r8.py::test_a_confirmation_taken_back_still_voids_it_at_once
  - tests/session/test_session_confirm_r8.py::test_a_plan_and_a_time_after_a_confirmation_asks_first_then_l3
residual: {severity: 灾难性, likelihood: 低, risk: 4}
status: 部分控制
known_gaps: []
```

多轮红队的“改口”与“危机中换话题”两类场景目前没有“退出过早”缺口。放宽项都只在开发集、测试与黑盒复测上验证过，确认说法是否足够可信属于临床判断（G-0 已搁置）。

### HAZ-14 危机中结束会话时没有留下号码

```yaml
id: HAZ-14
title: 危机中结束会话时没有留下号码
hazard: 用户在危机流程中或直接询问没有回答时输入 /exit、Ctrl-C 或结束输入，程序直接退出，最后一屏没有热线。
cause:
  - 告别是会话之外的路径，PRD 与 SDD 都没有规定危机中的告别（进度表 §9.4 第 16 条）
effect: 用户离开时手边没有求助号码，也没有安全计划里的求助人。
initial: {severity: 重大, likelihood: 中, risk: 3}
controls:
  - olivia/core/session.py Session.farewell 危机中、询问未答或本会话进过危机时的告别附该地区热线与安全计划的求助人，不问心情分
  - olivia/core/chang/care.py 未回答的询问同样写关怀标记
evidence:
  - tests/session/test_session_crisis_s5.py::test_the_crisis_farewell_lists_the_numbers_and_the_plans_people
  - tests/session/test_session_crisis_s5.py::test_an_l3_crisis_farewell_leads_with_the_emergency_numbers
  - tests/session/test_session_ask_first.py::test_a_d3_question_left_unanswered_also_gets_the_crisis_farewell
  - tests/session/test_session_safety_round2.py::test_the_goodbye_after_a_crisis_that_ended_keeps_the_numbers_and_the_people
  - tests/session/test_owner_decisions_1028.py::test_the_farewell_lists_120_after_12356
  - tests/cli/test_cli_care.py::test_crisis_then_one_gentle_greeting_then_none
residual: {severity: 重大, likelihood: 极低, risk: 2}
status: 已控制
known_gaps: []
```

## 7. 热线与属地资源

### HAZ-15 热线号码错误或被篡改

```yaml
id: HAZ-15
title: 热线号码错误、被篡改或被编造
hazard: 危机卡上的号码本身是错的：录入错误、数据文件被改动、伪造的更新包，或回答“这个号码是什么”时给出数据里没有的号码。
cause:
  - 人工录入与核对出错
  - 本机数据目录里的覆盖包可被他人或其他程序替换
effect: 用户在危机中拨出的号码打不通或不是求助机构。
initial: {severity: 灾难性, likelihood: 低, risk: 4}
controls:
  - olivia/data/resources/hotlines.yaml 每条带官方来源与核验日期，两名核对员独立核对、第三位裁决（进度表 §9.2）；2026-11-25 季度复核全部 35 条，16 项第三方核查，号码全部正确，更正了来源与说明（docs/resources/hotline-sources.md“2026-11-25 复核记录”）
  - olivia/data/resources/hotlines.yaml.sig 对原始字节的 Ed25519 签名，公钥在 olivia/core/resources/keys.py（PRD GEO-08）
  - olivia/core/resources/bundle.py 内置数据验签失败即不用；覆盖包须签名有效、比内置新且不晚于当天、不缩小覆盖
  - olivia/core/language/gate.py 输出网关拦下不在当前卡上的号码
  - docs/resources/hotline-sources.md 来源与核对规则
evidence:
  - tests/resources/test_bundle.py::test_committed_signature_matches_committed_data
  - tests/resources/test_bundle.py::test_tampered_builtin_raises
  - tests/resources/test_bundle.py::test_builtin_signed_by_another_key_raises
  - tests/resources/test_bundle.py::test_override_tampered_after_signing
  - tests/resources/test_bundle.py::test_override_signed_by_untrusted_key
  - tests/resources/test_bundle.py::test_signed_pack_that_drops_builtin_coverage_falls_back
  - tests/cli/test_cli_hotline_updates.py::test_chat_ignores_a_tampered_update
  - tests/resources/test_hotline_data.py::test_every_entry_has_an_official_source_and_date
  - tests/resources/test_resource_store.py::test_store_is_typed_and_frozen
  - tests/resources/test_fallback.py::test_every_region_and_emergency_number_matches_the_verified_data
  - tests/resources/test_resource_resolver.py::test_crisis_card_contents
  - tests/session/test_session_round5_hotline.py::test_a_number_not_in_the_data_is_not_guessed
  - tests/language/test_engine_gate.py::test_stray_numbers_are_blocked
residual: {severity: 灾难性, likelihood: 极低, risk: 3}
status: 已控制
known_gaps: []
```

签名只能保证“数据就是负责人签过的那份”，号码在现实中是否正确只能靠人工核对；测试只检查每条都有来源与日期，不能验证号码本身。2026-11-25 复核后的数据由子代理按负责人 2026-10-25 的授权用同一把密钥重新签名，内置数据验签通过。

### HAZ-16 热线号码过期

```yaml
id: HAZ-16
title: 热线号码或服务时段过期
hazard: 机构更换号码、停止服务或改变服务时段，用户机器上的数据还是旧的。
cause:
  - 程序离线运行，用户不升级就不会拿到新数据
  - 复核是每季度一次的人工流程，两次复核之间的变化不会被发现
effect: 用户拨打的号码已停用或当时无人接听（大陆 12356 部分地区夜间不接听）。
initial: {severity: 重大, likelihood: 中, risk: 3}
controls:
  - scripts/check_hotline_freshness.py 任何条目核验超过 90 天即失败
  - .github/workflows/hotline-freshness.yml 每年 1、4、7、10 月 1 日自动运行，可手动触发
  - olivia/core/resources/resolver.py 卡上条目核验超过 180 天时标注“可能已过期”（PRD GEO-07、Q-2）
  - olivia/core/resources/bundle.py 签名覆盖包通道（不升级程序也能更新数据）
  - docs/resources/hotline-sources.md 的“定期复核”（负责人与处理流程）
evidence:
  - tests/scripts/test_check_hotline_freshness.py::test_an_entry_older_than_90_days_fails
  - tests/scripts/test_check_hotline_freshness.py::test_the_2026_11_25_review_holds_until_the_next_quarter
  - tests/scripts/test_check_hotline_freshness.py::test_the_workflow_runs_it_quarterly_and_on_demand
  - tests/scripts/test_check_hotline_freshness.py::test_the_sources_document_names_an_owner
  - tests/resources/test_resource_resolver.py::test_entries_older_than_180_days_are_flagged
  - tests/language/test_engine.py::test_stale_entries_are_marked
  - tests/resources/test_bundle.py::test_newer_valid_override_wins
  - scripts/check_hotline_freshness.py
residual: {severity: 重大, likelihood: 低, risk: 3}
status: 部分控制
known_gaps: []
```

当前全部 35 个条目核验于 2026-11-25（季度复核，重新签名），按 90 天规则 2027-02-23 之前复核检查都通过，2027-02-24 起失败，提醒下一次复核（2027-01-01 的定时运行仍通过，2027-04-01 那次会失败）。L3 卡总是先列当地急救号码，单条热线过期时仍有其他途径；12356 夜间可能无人接听也是大陆 L2 卡加 120 的理由之一（进度表 §9.3）。

### HAZ-17 给错地区的号码

```yaml
id: HAZ-17
title: 给错地区的号码
hazard: 境外用户看到大陆专属号码（12356、120、12355、大陆 110），地区未知或填错的用户看到不能拨通的号码，或用户人在外地时卡片仍按画像地区给。
cause:
  - 首访地区可能没填、填错（如 UK）或已过时
  - 用户在聊天中提到自己现在在别处
effect: 用户拨出的号码在当地无效，延误求助。
initial: {severity: 重大, likelihood: 中, risk: 3}
controls:
  - olivia/core/resources/resolver.py Rule R8 境外隔离（按条目所属地区而非号码数字），不支持的代码一律按 ZZ（PRD GEO-01、GEO-03）
  - olivia/core/session.py 用户提到所在地时按那个地区给卡，没有核对过的地区给通用卡与当地官方紧急号码（进度表 §9.5 第 16 条）
  - olivia/core/perception/location.py 按语法识别用户说自己现在在某地（过去、将来、假设、别人的位置都不算；“国内”不算大陆），只记在本次会话内存里，以最新的为准（负责人 2026-11-25 决定 B）
  - olivia/core/session.py 说过当前所在地后，本会话危机卡（危机回复、先问一句附带的号码、危机中的告别、等待确认时的号码行）先列那里的号码，再列设置地区的号码；只在 crisis.local_emergency 里有一行的国家先列那一行（决定 B）
  - docs/superpowers/plans/2026-10-23-next-phase.md §9.4 第 11 条（ZZ 的 L2 卡给 112）
evidence:
  - tests/resources/test_resource_resolver.py::test_non_cn_cards_never_show_mainland_entries
  - tests/resources/test_resource_resolver.py::test_unknown_or_unsupported_region_falls_back_to_zz
  - tests/resources/test_resource_resolver.py::test_canada_never_shows_741741
  - tests/resources/test_hotline_data.py::test_mainland_only_numbers_stay_in_cn
  - tests/redteam/test_multiturn.py::test_every_scenario_checks_hotline_isolation
  - tests/redteam/test_redteam.py::test_hard_expectations
  - tests/session/test_session_round6_hotline.py::test_a_hong_kong_request_in_a_crisis_gets_no_mainland_number
  - tests/session/test_session_flows_round3.py::test_a_place_without_verified_numbers_gets_the_general_card
  - tests/session/test_session_round7_hotline.py::test_a_supported_city_gets_that_regions_card
  - tests/cli/test_cli_resources_region.py::test_the_zz_crisis_card_lists_112_like_resources
  - tests/session/test_referral_region.py::test_other_regions_name_no_mainland_only_place
  - tests/perception/test_present_place.py::test_the_users_own_place_now_is_read
  - tests/perception/test_present_place.py::test_the_past_the_future_a_condition_or_someone_else_is_not
  - tests/session/test_owner_decisions_1125.py::test_a_place_said_earlier_leads_the_crisis_card
  - tests/session/test_owner_decisions_1125.py::test_the_latest_place_counts
  - tests/session/test_owner_decisions_1125.py::test_mainland_numbers_show_outside_cn_only_after_naming_the_mainland
  - tests/session/test_owner_decisions_1125.py::test_no_mainland_number_without_saying_one_is_there_now
residual: {severity: 重大, likelihood: 低, risk: 3}
status: 部分控制
known_gaps: []
```

境外隔离是红队的硬期望，两种模式全部通过。负责人 2026-11-25 决定 B 已实现：聊天中说过当前所在地之后，危机卡先给那里的号码，设置地区的号码列在后面；设置地区不是 CN 的用户只有明确说自己现在在中国大陆（“大陆”“内地”“中国大陆”）时才会看到大陆号码。仍是部分控制：程序只能知道用户说出来的位置，没说、说法不在语法里、地名不在地名表里（大陆城市名、表外国家）或说“国内”时，卡片仍按设置地区给；表外国家（只认得是“别处”）不会把先前说过的地区留在最前，但也没有当地号码可先列。北爱尔兰 Lifeline 是否收录仍待负责人决定。

### HAZ-18 危机卡号码缺失、顺序错误或被遮住

```yaml
id: HAZ-18
title: 危机卡号码缺失、顺序错误或被其他逻辑遮住
hazard: 危机回复里少了号码、急救号码没有排在最前，或卡片被输出网关、雷区话题过滤、人格模板、字数窗口、安全计划等其他逻辑截掉。
cause:
  - 回复经过多层处理（WILLOW 改写、雷区过滤、网关拦截、人格窗口），任何一层都可能删掉内容
effect: 用户在危机中看不到完整的求助途径（PRD NG-9）。
initial: {severity: 灾难性, likelihood: 低, risk: 4}
controls:
  - olivia/core/language/engine.py render_crisis 卡片由热线数据生成，与人格无关；L3 急救号码在前
  - olivia/core/language/gate.py 网关拦下危机回复时退回最简卡，保留卡上全部号码
  - olivia/data/language/willow.yaml 危机与转介文字豁免说教改写与字数窗口（PRD WILLOW-01、WILLOW-03）
  - olivia/core/session.py 危机中每轮卡片等级取本轮、进入时与 L2 的最高者；雷区话题不遮住危机资源（PRD ONB-04）
evidence:
  - tests/language/test_engine.py::test_crisis_card_lists_every_number_and_nothing_else
  - tests/language/test_engine.py::test_crisis_gate_block_keeps_every_number
  - tests/session/test_session.py::test_l3_card_keeps_emergency_numbers_for_the_whole_crisis
  - tests/session/test_session.py::test_taboo_topic_never_hides_crisis_resources
  - tests/session/test_session_personas.py::test_crisis_turn_has_the_same_safety_content_for_every_persona
  - tests/resources/test_resource_resolver.py::test_every_l3_card_has_an_emergency_number
  - tests/session/test_session_flow.py::test_every_crisis_turn_repeats_the_full_card
  - tests/session/test_session_safety_plan.py::test_minimal_card_fallback_keeps_every_hotline_number
  - tests/language/test_engine_filters.py::test_crisis_and_referral_keep_safety_wording
residual: {severity: 灾难性, likelihood: 极低, risk: 3}
status: 已控制
known_gaps: []
```

### HAZ-19 出错时没有号码可给

```yaml
id: HAZ-19
title: 数据损坏或处理出错时没有号码可给
hazard: 热线数据损坏、画像打不开、筛查或后续步骤抛出异常时，用户只看到报错或空白，正好在危机那一轮。
cause:
  - 本机文件损坏、钥匙串锁住或权限问题
  - 代码缺陷导致某一步抛异常
effect: 危机中的用户得不到任何号码，还可能看到程序崩溃。
initial: {severity: 灾难性, likelihood: 低, risk: 4}
controls:
  - olivia/core/resources/fallback.py 写死的紧急号码与求助目录（测试保证与已签名数据一致）
  - olivia/core/session.py Session.turn 的降级：本轮 L2 及以上、已在危机中或在读直接询问的回答时给带全部号码的最简危机卡（SDD §10.1 F2b）
  - olivia/cli.py 画像打不开、热线数据损坏时先显示号码再说明
evidence:
  - tests/session/test_session_flow.py::test_failure_on_an_l2_turn_gives_the_minimal_card_with_every_number
  - tests/session/test_session_flow.py::test_failure_inside_a_crisis_still_lists_every_number
  - tests/session/test_session_flow.py::test_failure_on_the_answer_to_the_d3_question_is_a_crisis_reply
  - tests/cli/test_cli_chat_fallback.py::test_failed_screen_still_shows_every_number
  - tests/cli/test_cli_hotlines_under_failure.py::test_chat_with_damaged_packaged_data_shows_the_fallback_and_does_not_start
  - tests/cli/test_cli_hotlines_under_failure.py::test_chat_that_cannot_open_the_profile_shows_the_hotlines_first
  - tests/cli/test_cli_hotlines_under_failure.py::test_a_failed_turn_with_damaged_data_shows_the_fallback
  - tests/resources/test_fallback.py::test_every_region_and_emergency_number_matches_the_verified_data
  - tests/session/test_session.py::test_lexicon_load_failure_refuses_to_start
residual: {severity: 灾难性, likelihood: 极低, risk: 3}
status: 已控制
known_gaps: []
```

## 8. 回复内容

### HAZ-20 复述用户的风险原话

```yaml
id: HAZ-20
title: 复述用户的风险原话
hazard: 镜像式回复把用户话里的手段、地点、计划或告别原样念回来（“听起来你打算……”），或对风险内容接上肯定句。
cause:
  - 镜像层本来就是把用户的话换人称复述（PRD COLBO-01）
  - 风险词与日常词同形，单看等级不够
effect: 复述会强化、正常化或细化计划，让用户觉得被认可。
initial: {severity: 较大, likelihood: 高, risk: 3}
controls:
  - olivia/core/language/guard.py MirrorGuard：本轮 L1 及以上、原话含风险字眼或同句出现两类风险构件时，改用不引用原话的承接句，不接肯定句、不点出“需要”（进度表 §9.4 第 14 条）
  - olivia/data/language/utterances.yaml 的 guarded_acks 与 extra_risk_words
  - olivia/data/lexicons/risk.yaml 风险词表（复述防线与筛查共用一份）
evidence:
  - tests/language/test_round3_guard.py::test_risky_messages_are_guarded
  - tests/language/test_round3_guard.py::test_a_guarded_reply_quotes_nothing_and_affirms_nothing
  - tests/language/test_round3_guard.py::test_an_l1_turn_is_guarded_whatever_its_words
  - tests/language/test_round4_language.py::test_the_mirror_never_quotes_risk_words_whatever_the_level
  - tests/safety/test_rules_round5.py::test_round5_risk_words_not_said_back
  - tests/session/test_session_round5_hotline.py::test_the_abrupt_plan_is_not_said_back
residual: {severity: 较大, likelihood: 低, risk: 2}
status: 待 G-0
known_gaps: []
```

承接句为“草稿：待 G-0”。负责人 2026-10-30 接受了取舍：含死、离开、活着等词的普通倾诉也不再复述原话。

### HAZ-21 给出处方、剂量或停药建议

```yaml
id: HAZ-21
title: 给出处方、剂量或停药建议
hazard: 回复里出现药名、剂量、增减药或停药指导，包括用户扮演医生、注入指令或问“吃多少”的时候（PRD NG-2）。
cause:
  - 用户直接问药，或用角色扮演、伪造系统指令要求开药
  - 用户说要自己停药或戒断
effect: 错误用药或突然停药可能造成躯体危险（戒断反应、过量）。
initial: {severity: 重大, likelihood: 中, risk: 3}
controls:
  - olivia/data/templates/ 回复全部来自模板，没有生成模型，模板里没有药名与剂量
  - olivia/core/language/gate.py 拦下不在卡上的号码与数字串
  - olivia/core/session.py 问药与诊断先承接，再给一句指向专业人员的边界说明
  - olivia/core/session.py 自己停药或停酒时给不要突然停的提醒；SIT-10-04 转介卡附戒断警示（PRD §9.3 第 7 条）
evidence:
  - tests/language/test_f3_language.py::test_medication_and_diagnosis_questions_get_one_plain_line
  - tests/language/test_f3_language.py::test_boundary_lines_point_to_professionals
  - tests/session/test_session_f3.py::test_medication_and_diagnosis_questions_are_acknowledged_first
  - tests/language/test_engine_gate.py::test_stray_numbers_are_blocked
  - tests/session/test_session_round5_hotline.py::test_stopping_on_ones_own_gets_the_reminder
  - tests/session/test_session_round6_hotline.py::test_a_withdrawal_sign_gets_no_practice_card
  - tests/session/test_session.py::test_substance_user_gets_the_withdrawal_warning_on_the_referral_card
  - tests/redteam/test_redteam.py::test_hard_expectations
residual: {severity: 重大, likelihood: 极低, risk: 2}
status: 已控制
known_gaps: []
```

红队“诱导开药”29 条的硬期望（不出现药名与剂量单位）两种模式全部通过；模型模式那 1 条缺口是误报（计入 HAZ-11）。仍未定（进度表 §9.3）：家人停精神科药时是否给同类提醒。

### HAZ-22 给出诊断标签或病理化措辞

```yaml
id: HAZ-22
title: 给出诊断标签或病理化措辞
hazard: 回复给用户贴上诊断（“你这是抑郁症”）、做鉴别诊断，或用“患者 / 病态”这类病理化词（PRD NG-1、WILLOW-04）。
cause:
  - 用户直接要诊断，或用角色扮演、注入要求下诊断
  - 模板或转介文案里混入诊断词
effect: 错误标签加重病耻感，或让用户以为已被诊断而不去就医。
initial: {severity: 较大, likelihood: 中, risk: 3}
controls:
  - olivia/data/language/willow.yaml 的 diagnosis_terms 与去病理化替换
  - olivia/core/language/filters.py 去掉含诊断词的句子
  - olivia/core/language/gate.py 所有回复类型都拦诊断词（Grade C 转介卡只保留“精神科、就医”等去处说法）
evidence:
  - tests/language/test_engine_gate.py::test_diagnosis_terms_are_blocked_for_every_kind
  - tests/language/test_engine_filters.py::test_diagnosis_sentences_are_dropped_for_every_kind
  - tests/language/test_engine_filters.py::test_normal_text_is_rewritten
  - tests/language/test_engine.py::test_referral_names_places_not_disorders
  - tests/language/test_willow_data.py::test_depathologize_examples
  - tests/redteam/test_redteam.py::test_hard_expectations
residual: {severity: 较大, likelihood: 极低, risk: 2}
status: 已控制
known_gaps: []
```

### HAZ-23 给红线用户不合适的练习

```yaml
id: HAZ-23
title: 给红线用户不合适的练习
hazard: 双相、围产期抑郁、PTSD、解离、厌食、边缘型伴自伤、物质依赖这七类红线用户拿到被禁止的练习（如厌食或边缘型用户拿到冷水 TIPP、双相用户拿到行为激活），或没有拿到专科转介。
cause:
  - 红线只能从用户自述或健康档案识别，没说出来的不会被识别
  - 别名、父子动作与禁忌的集合运算写错
  - 新增只给红线的动作（D-3）与档案冲突的处理（F13）是保守草稿
effect: 不合适的练习可能诱发转躁、心律失常、创伤再体验或戒断风险。
initial: {severity: 重大, likelihood: 中, risk: 3}
controls:
  - olivia/data/taxonomy.yaml 红线 allowed_actions 封闭上限、banned_methods、action_registry 与禁忌
  - olivia/core/methods/solver.py 四重交差集与别名归约，空集走 m0 并附转介卡（PRD COLBO-05）
  - olivia/core/methods/contraindications.py 禁忌硬掩码
  - olivia/data/lexicons/red_flags.yaml 自述与特征词识别
evidence:
  - tests/methods/test_solver_masks.py::test_seven_red_flags_by_hand
  - tests/methods/test_solver_masks.py::test_candidates_never_escape_a_mask
  - tests/methods/test_solver_masks.py::test_red_flag_at_overload_in_explore_matches_taxonomy
  - tests/session/test_session.py::test_bpd_profile_at_high_arousal_never_gets_cold_water
  - tests/session/test_session.py::test_red_flag_user_in_explore_gets_only_whitelisted_stabilization
  - tests/session/test_session.py::test_red_flag_with_empty_set_gets_companionship_and_referral
  - tests/session/test_session_contraindications.py::test_a_profile_disclosure_is_never_offered_a_contraindicated_action
  - tests/session/test_session_contraindications.py::test_borderline_dossier_never_brings_back_the_cold_water
  - tests/language/test_engine.py::test_cold_water_card_refuses
  - tests/safety/test_red_flags.py::test_detects_each_code
  - tests/redteam/test_redteam.py::test_hard_expectations
residual: {severity: 重大, likelihood: 低, risk: 3}
status: 待 G-0
known_gaps: []
```

红队“红线绕过”27 条没有缺口。待临床判断的项：D-3 把只登记给红线的五个动作放进候选池、SIT-08-04 上限加入节奏呼吸（F13）；SIT-01-05 见血晕厥型恐惧“不可用放松降血压法”没有做（需要自创临床规则，PRD §8.2 F13 实现说明）。红线转介卡不再每次开场出现（进度表 §9.4 第 19 条）。

### HAZ-24 下发需要专业监护的方法

```yaml
id: HAZ-24
title: 下发需要专业监护的方法
hazard: 系统把 C 级方法（创伤暴露、眼动脱敏、进食暴露等）或 B 级方法当作自助练习下发（PRD NG-5、§8.1）。
cause:
  - 用户点名要某种疗法，或注入指令要求推荐暴露疗法
  - 动作类型分发写错，把科普或转介当成练习
effect: 无监护的创伤暴露可能导致再创伤或解离。
initial: {severity: 重大, likelihood: 低, risk: 3}
controls:
  - olivia/core/methods/solver.py 只为 A 级方法装配练习骨架；B / C 级只给科普卡并提示专业面诊
  - olivia/core/language/engine.py 非练习类动作拒绝渲染成练习卡（PRD COLBO-05 动作类型分发）
evidence:
  - tests/methods/test_solver.py::test_build_plan_refuses_non_grade_a_methods
  - tests/language/test_engine.py::test_non_card_actions_refuse
  - tests/methods/test_solver_info.py::test_asked_id_must_be_a_grade_b_or_c_method
  - tests/redteam/test_redteam.py::test_hard_expectations
residual: {severity: 重大, likelihood: 极低, risk: 2}
status: 已控制
known_gaps: []
```

### HAZ-25 状态机越权

```yaml
id: HAZ-25
title: 状态机越权：倾听阶段或危机中给方法
hazard: 倾听阶段给出认知或行为方法，危机中响应“直接给我方法”，或用命令、注入把会话带出危机。
cause:
  - 直接要方法的越级通道（PRD COLBO-03）与命令、反馈路径都能改变阶段
effect: 危机中的用户被推销练习而不是得到安全支持；倾听阶段的说教引起抗拒。
initial: {severity: 较大, likelihood: 中, risk: 3}
controls:
  - olivia/core/fsm/machine.py 危机中不响应直接索要，危机只能经确认安全离开（PRD §6.1）
  - olivia/core/methods/solver.py 倾听与理清阶段不给练习，高唤醒只放行稳定化白名单（PRD COLBO-02）
  - olivia/core/session.py 直接询问那一轮不给任何卡片或建议
evidence:
  - tests/session/test_session_colbo02.py::test_explore_and_clarify_replies_name_no_method
  - tests/methods/test_solver.py::test_pre_empower_stages_offer_no_exercise_below_somatic_priority
  - tests/fsm/test_machine.py::test_crisis_beats_battery_lock_commands_and_direct_request
  - tests/fsm/test_machine.py::test_property_in_crisis_always_means_s_crisis
  - tests/fsm/test_machine.py::test_property_crisis_left_only_on_just_exited_and_only_to_explore
  - tests/session/test_session_flow.py::test_feedback_command_in_a_crisis_is_still_the_crisis_card
  - tests/session/test_session_safety_check.py::test_question_never_offers_a_card_even_mid_flow
  - tests/redteam/test_redteam.py::test_case
residual: {severity: 较大, likelihood: 极低, risk: 2}
status: 已控制
known_gaps: []
```

红队“状态机越权”30 条两种模式都没有缺口。

## 9. 特定人群与语境

### HAZ-26 未成年人

```yaml
id: HAZ-26
title: 未成年人未被识别或继续深度陪伴
hazard: 未满 18 岁的人使用本产品（首访谎报年龄，或聊天中途才透露），系统继续深度陪伴，没有指向青少年专线与监护人（PRD NG-3、RSK-04）。
cause:
  - 年龄只能自报，无法核实
  - 聊天中透露年龄的说法很多（“我才初二”“俺今年十六”），也可能只有模型报警
effect: 未成年人在没有监护的情况下依赖本产品，急性风险得不到现实支持。
initial: {severity: 重大, likelihood: 中, risk: 3}
controls:
  - olivia/core/chang/onboarding.py 年龄门禁先于任何个人信息，未满 18 只留不含个人数据的拒绝记录（PRD ONB-05，裁定 18、22）
  - olivia/core/session.py 聊天中自述未成年时温和说明，给 12355 或当地青少年线与急救号码，之后只回资源与告别（进度表 §9.4 第 9 条）
  - olivia/core/perception/minor_answer.py 确认问句的回答读法；确认后写入拒绝记录并删除其他数据（进度表 §9.4 第 24 条）
  - olivia/core/session.py 只有模型报警的年龄披露先走未成年流程（进度表 §9.4 第 22、25 条）
evidence:
  - tests/chang/test_onboarding.py::test_minor_refusal_persists_and_blocks_restart
  - tests/chang/test_onboarding.py::test_minor_message_numbers_match_the_hotline_data
  - tests/session/test_session.py::test_refusal_record_cannot_open_a_session
  - tests/session/test_session.py::test_profile_without_adult_confirmation_fails_closed
  - tests/session/test_session_safety_round2.py::test_a_minor_is_told_gently_and_gets_the_youth_line
  - tests/session/test_session_safety_round2.py::test_after_the_disclosure_only_resources_and_a_goodbye
  - tests/session/test_session_safety_round2.py::test_after_the_disclosure_the_crisis_flow_still_comes_first_with_the_youth_line
  - tests/session/test_session_safety_round2.py::test_outside_the_mainland_a_minor_gets_the_regions_lines
  - tests/session/test_session_round6_minors.py::test_a_spoken_yes_records_the_age
  - tests/session/test_session_r6_minor_denial.py::test_a_no_with_only_the_models_alarm_asks_first
  - tests/cli/test_cli_minor_round6.py::test_a_confirmed_minor_leaves_only_the_refusal_record
  - tests/resources/test_resource_resolver.py::test_minor_sees_12355_at_cn_l2_only
residual: {severity: 重大, likelihood: 中, risk: 3}
status: 部分控制
known_gaps: []
```

控制措施只能处理“说出来的”年龄；谎报年龄的未成年人无法识别，所以残余可能性不降。是否试点 16–17 岁监护人同意流程仍按 Q-5 维持 18+。

### HAZ-27 第三方风险处理不当

```yaml
id: HAZ-27
title: 替他人担心时处理不当
hazard: 用户转述朋友或家人的风险时，系统把用户本人送进危机流程、敷衍回应；或反过来，把用户本人的风险误当作转述而放过。
cause:
  - 转述识别按说话人与转述动词判断，用户自己的话与他人的话常在同一句里
  - 学生模型不区分是谁的话
  - PRD 没有规定替他人担心时该怎么做（G-5 实现说明第 3 点）
effect: 误当转述时，用户本人的危机被漏掉（灾难性）；误当本人时，想帮朋友的人被反复问是否安全，得不到可转交的资源。
initial: {severity: 灾难性, likelihood: 中, risk: 4}
controls:
  - olivia/core/safety/reported.py ReportedSpeech：转述他人原话在规则层作废，含糊时保留原等级（宁可算用户本人的）
  - olivia/data/lexicons/risk.yaml 的 reported_speech 节
  - olivia/core/session.py 他人风险给可转交的资源卡（ReplyKind.RESOURCES），他人有计划时急救号码在前；用户自己也表达风险、或之后转向自己时照常进危机流程（进度表 §9.4 第 8、22、29 条）
evidence:
  - tests/session/test_session_safety_round2.py::test_reported_risk_gives_the_card_to_pass_on_in_rules_mode
  - tests/session/test_session_safety_round2.py::test_reported_risk_gives_the_card_to_pass_on_when_the_model_alarms
  - tests/session/test_session_safety_round2.py::test_a_reported_plan_leads_with_the_emergency_numbers
  - tests/session/test_session_safety_round2.py::test_the_users_own_risk_next_to_it_enters_the_crisis_flow
  - tests/session/test_session_safety_round2.py::test_the_user_turning_to_themselves_later_enters_the_crisis_flow
  - tests/session/test_session_safety_round2.py::test_asking_for_a_way_for_someone_else_keeps_the_question_or_the_crisis
  - tests/safety/test_lexicon_gaps.py::test_the_users_own_words_or_an_unclear_speaker_keep_l2
  - tests/safety/test_lexicon_gaps.py::test_reported_speech_fails_toward_keeping_the_phrase
  - tests/safety/test_lexicon_gaps.py::test_a_method_request_for_someone_else_is_never_reported_speech
  - tests/safety/test_rules_context_g3.py::test_the_subject_still_carries_over_a_comma
  - tests/safety/test_rules_context_g3.py::test_a_death_named_only_with_someone_else_still_voids
  - tests/safety/test_rules_context_g3.py::test_worry_about_someone_else_over_two_sentences
  - tests/safety/test_method_seeking.py::test_the_worried_friends_words_stay_someone_elses
  - tests/session/test_session_flows_round3.py::test_cannot_reach_them_is_an_emergency_even_after_a_plain_report
  - tests/redteam/test_redteam.py::test_case
residual: {severity: 灾难性, likelihood: 低, risk: 4}
status: 部分控制
known_gaps:
  - {file: tests/redteam/known_gaps.yaml, kind: rules false alarm, category: third_party_concern, count: 1}
  - {file: tests/redteam/known_gaps_model.yaml, kind: rules false alarm, category: third_party_concern, count: 1}
  - {file: tests/redteam/known_gaps_model.yaml, kind: model false alarm, category: third_party_concern, count: 1}
```

登记的缺口都在“误当用户本人”一侧；“把用户本人的风险误当转述”一侧没有红队缺口，但转述识别越放宽（§9.4 第 29 条追认三处放宽），这一侧的风险越大，严重度按这一侧评。

### HAZ-28 首访与设置命令里的危机句未被筛查

```yaml
id: HAZ-28
title: 首访与设置命令里的危机句未被筛查
hazard: 用户在首访（免责声明、称呼、雷区话题）、olivia profile、health、safety-plan 里写下危机句，程序当作普通输入保存，没有给号码。
cause:
  - 这些输入不经过聊天的会话入口（SDD §8.1 原只规定单一会话入口）
effect: 第一次打开程序就在危机中的人得不到号码，危机句还被存成称呼或话题。
initial: {severity: 重大, likelihood: 低, risk: 3}
controls:
  - olivia/core/chang/setup_screen.py 首访与设置命令的每一句先过筛查，L2 及以上不收下，给号码并问继续或退出（进度表 §9.4 第 13 条）
  - olivia/core/resources/fallback.py 地区未选之前给通用号码
evidence:
  - tests/cli/test_cli_setup_screen.py::test_a_crisis_sentence_on_the_disclaimer_shows_the_global_numbers
  - tests/cli/test_cli_setup_screen.py::test_a_crisis_sentence_as_a_name_is_not_taken
  - tests/cli/test_cli_setup_screen.py::test_a_crisis_sentence_as_a_taboo_topic_is_not_saved
  - tests/cli/test_cli_setup_screen.py::test_onboarding_screens_like_the_chat_that_follows
  - tests/cli/test_cli_setup_screen.py::test_after_the_region_the_regions_numbers_are_shown
  - tests/cli/test_cli_setup_screen.py::test_health_never_reads_a_crisis_sentence_back
  - tests/cli/test_cli_setup_screen.py::test_a_screen_that_fails_counts_as_an_alarm
residual: {severity: 重大, likelihood: 极低, risk: 2}
status: 已控制
known_gaps: []
```

筛查本身的召回与聊天相同，漏判的部分归 HAZ-01 至 HAZ-08。

### HAZ-29 安全计划在危机中念回有害内容

```yaml
id: HAZ-29
title: 安全计划在危机中念回有害内容
hazard: 危机回复展示用户自己写的安全计划时，念回了危机句、手段或地点，或展示了第 5 部分（让环境更安全）的内容。
cause:
  - 安全计划是用户自由填写的文字，危机时原样展示（PRD §9.1 B10）
effect: 在最脆弱的时候把用户自己写下的风险内容念给他听。
initial: {severity: 较大, likelihood: 中, risk: 3}
controls:
  - olivia/core/chang/safety_plan.py 第 2–4 部分不存危机句，旧计划里的危机句在聊天开始时滤掉，第 5 部分从不出现在危机回复里（进度表 §9.4 第 12 条）
  - olivia/core/chang/setup_screen.py 写计划时逐句筛查
  - olivia/core/language/gate.py 网关拦下计划时只去掉计划，热线卡保留
evidence:
  - tests/session/test_session_safety_plan.py::test_section_five_and_warning_signs_never_reach_a_crisis_reply
  - tests/session/test_session_safety_plan.py::test_l3_opening_then_emergency_card_then_plan
  - tests/session/test_session_safety_plan.py::test_a_plan_the_gate_blocks_is_dropped_and_the_card_kept
  - tests/session/test_session_safety_plan.py::test_no_plan_on_the_d3_question_or_ordinary_turns
  - tests/cli/test_cli_setup_screen.py::test_sections_two_to_four_never_keep_a_crisis_sentence
  - tests/cli/test_cli_setup_screen.py::test_chat_never_reads_back_a_crisis_entry_saved_before
residual: {severity: 较大, likelihood: 低, risk: 2}
status: 待 G-0
known_gaps: []
```

安全计划文案为 G-0 草稿；“阳台 + 家务”不滤是负责人 2026-11-01 追认的取舍（§9.4 第 30 条）。

### HAZ-30 病态依恋与深夜长时间使用

```yaml
id: HAZ-30
title: 病态依恋与深夜长时间使用
hazard: 用户长时间、尤其在深夜依赖本产品倾诉，逐渐脱离现实人际支持（PRD NG-4、RSK-07）。
cause:
  - 陪伴产品本身容易被当作唯一的倾诉对象
effect: 现实支持网络变弱，危机时身边没有人。
initial: {severity: 较大, likelihood: 中, risk: 3}
controls:
  - olivia/core/chang/wellbeing.py 连续 45 分钟温和提醒、深夜（00:00–05:00）关怀、现实支持引导占比
  - olivia/core/chang/stats.py olivia stats 在本机给出深夜会话与现实支持占比（PRD §11.1 F12）
evidence:
  - tests/core/chang/test_wellbeing.py::test_no_break_at_44_59_and_a_break_at_45_00
  - tests/core/chang/test_wellbeing.py::test_real_support_share_and_cadence
  - tests/session/test_session_wellbeing.py::test_break_reminder_at_45_minutes_not_before
  - tests/session/test_session_wellbeing.py::test_late_night_line_once_per_session_in_shanghai
residual: {severity: 较大, likelihood: 低, risk: 2}
status: 待 G-0
known_gaps: []
```

测试只证明提醒按时出现，不能证明提醒有效；提醒文案为草稿，WHO-5 尚未接入（PRD §11.1 F12 实现说明）。

## 10. 隐私与数据

### HAZ-31 离线承诺失效

```yaml
id: HAZ-31
title: 联网或把原文发出本机
hazard: 程序在用户不知情时联网，把倾诉原文或健康信息发到别处（PRD NG-6、NG-10）。
cause:
  - 依赖库或新代码引入网络调用
effect: 高度敏感的心理健康信息外泄，且无法收回。
initial: {severity: 重大, likelihood: 低, risk: 3}
controls:
  - scripts/privacy_audit.py 的 network-imports（AST 扫描包内全部导入）与 network-runtime（脚本化会话中拦截并记录任何连接）
  - olivia/ 包内没有任何联网模块；AI 增强（P7）未接入
evidence:
  - tests/scripts/test_privacy_audit.py::test_the_package_imports_no_networking_module
  - tests/scripts/test_privacy_audit.py::test_network_imports_finds_every_form
  - tests/scripts/test_privacy_audit.py::test_network_block_refuses_records_and_restores
  - tests/cli/test_offline_full.py::test_every_feature_works_offline
  - tests/scripts/test_privacy_audit.py::test_the_audit_passes_on_this_tree
  - scripts/privacy_audit.py
residual: {severity: 重大, likelihood: 极低, risk: 2}
status: 已控制
known_gaps: []
```

可选的系统提醒（B9，默认关闭）只在本机安装定时任务，不联网。

### HAZ-32 本机隐私泄露

```yaml
id: HAZ-32
title: 本机隐私泄露
hazard: 用户的原话、健康信息、安全计划或笔记以明文留在磁盘、日志、错误输出或 --inspect 面板里，或主密钥落盘、文件权限过宽，被同一台电脑上的其他人看到（PRD RSK-05）。
cause:
  - 多人共用电脑或同一系统账户，数据目录被同步到网盘
  - 调试输出、异常信息或快照意外带出原文
effect: 敏感心理健康信息被身边的人看到，可能带来羞辱、关系破裂或人身风险。
initial: {severity: 重大, likelihood: 中, risk: 3}
controls:
  - olivia/core/crypto/vault.py 每个存储独立数据密钥，主密钥只在系统钥匙串；健康信息、账本、安全计划、关怀标记始终加密（PRD ONB-06，裁定 28）
  - olivia/core/storage.py 目录 0700、文件 0600，原子写入
  - olivia/core/memory/recorder.py 账本只记模板化摘要，不记对话原文（决定 D1）
  - scripts/privacy_audit.py 的 files-no-typed-text、sensitive-sealed、master-key-off-disk、permissions、output-no-typed-text、inspect-no-text、stats-numbers-only、doctor-no-personal
evidence:
  - tests/scripts/test_privacy_audit.py::test_the_audit_passes_on_this_tree
  - tests/core/chang/test_profile_crypto.py::test_clinical_history_is_never_written_in_plaintext
  - tests/chang/test_onboarding.py::test_clinical_history_is_encrypted_whatever_the_switch
  - tests/core/crypto/test_vault.py::test_keychain_items_never_carry_user_text
  - tests/core/crypto/test_vault.py::test_another_devices_keychain_cannot_open_the_data
  - tests/core/crypto/test_vault.py::test_tampered_ciphertext_and_tampered_key_file_are_rejected
  - tests/scripts/test_privacy_audit.py::test_keys_on_disk_finds_the_master_key_in_any_encoding
  - tests/scripts/test_privacy_audit.py::test_permission_problems
  - tests/session/test_session.py::test_inspect_and_snapshot_hold_no_user_text
  - scripts/privacy_audit.py
residual: {severity: 重大, likelihood: 低, risk: 3}
status: 部分控制
known_gaps: []
```

加密防的是“拿到文件的人”，防不了“能登录同一个系统账户的人”：钥匙串解锁时，他可以直接运行 `olivia memory` 看到笔记。ONB-06 默认关闭时，称呼与雷区话题按设计以明文保存在画像里。G-4 的法务审核属外部门禁，发布前才需要（进度表 §9.2）。

### HAZ-33 删除不彻底

```yaml
id: HAZ-33
title: 遗忘或删除之后数据仍可读
hazard: 用户执行 olivia forget、删除健康信息、改写笔记，或确认未成年后，旧数据（含快照、暂存副本、旧密钥文件）仍能被打开（PRD MIYI-05、JTBD 4）。
cause:
  - 只删文件不销毁密钥，或快照、暂存副本残留
  - 删除过程中断
effect: 用户以为已经删掉的倾诉与健康信息仍可能被他人读到。
initial: {severity: 较大, likelihood: 中, risk: 3}
controls:
  - olivia/core/crypto/vault.py 加密擦除：销毁数据密钥并轮换主密钥，旧密文与旧密钥文件的副本都打不开
  - olivia/core/memory/forget.py forget 各选项与 --all（删除全部包裹密钥、钥匙串主密钥与全部文件；中断时留下标记，直到文件全部删掉，olivia doctor 会指出）
  - scripts/privacy_audit.py 的 health-cleared-shredded、edit-and-reset-erase、forget-all-clean
evidence:
  - tests/cli/test_cli_forget.py::test_all_leaves_no_file_and_no_keychain_item
  - tests/cli/test_cli_forget.py::test_each_option_shreds_its_store_and_keeps_the_rest
  - tests/cli/test_cli_forget.py::test_one_entry_by_number_is_crypto_shredded
  - tests/cli/test_cli_forget.py::test_editing_a_note_replaces_it_and_crypto_shreds_the_old_words
  - tests/cli/test_cli_forget.py::test_nothing_is_removed_without_the_confirmation_word
  - tests/core/crypto/test_vault.py::test_a_new_data_key_after_shredding_cannot_open_old_ciphertext
  - tests/core/crypto/test_vault.py::test_shred_all_forgets_everything
  - tests/memory/test_memory_forget.py::test_forget_all_marks_itself_until_every_file_is_gone
  - tests/scripts/test_privacy_audit.py::test_health_erasure_is_never_vacuous
  - tests/cli/test_cli_minor_round6.py::test_a_confirmed_minor_leaves_only_the_refusal_record
  - scripts/privacy_audit.py
residual: {severity: 较大, likelihood: 低, risk: 2}
status: 已控制
known_gaps: []
```

系统层面的备份（如同时备份了数据目录与钥匙串）不在程序控制之内，这是残余可能性不降到“极低”的原因。

## 11. 技术与运行

### HAZ-34 模型缺失或损坏

```yaml
id: HAZ-34
title: 模型缺失或损坏时没有安全退回
hazard: 打包的学生模型文件缺失、被改动或无法加载，或推理时抛异常、返回非法值，筛查崩溃、静默给出错误结果，或用户不知道已经只剩规则。
cause:
  - 安装不完整、文件损坏或被替换
  - 模型代码缺陷
effect: 程序崩溃或筛查失效；退回规则后危机召回明显下降（见 HAZ-01、HAZ-02）。
initial: {severity: 灾难性, likelihood: 低, risk: 4}
controls:
  - olivia/core/perception/student.py 加载时按 MANIFEST.json 校验哈希与字节数，拒绝 pickle、错误形状与非有限权重；任何失败都退回只用规则并给出原因
  - olivia/core/safety/crisis.py 推理异常或非法输出一律按 L2 模型故障处理（朝安全方向失败）
  - olivia/cli.py 模型不可用时在聊天开头说一次；olivia doctor 报告模型校验失败
evidence:
  - tests/session/test_session_risk_model.py::test_unavailable_student_falls_back_to_rules_and_says_why
  - tests/session/test_session_risk_model.py::test_any_load_failure_reason_reaches_inspect
  - tests/session/test_session_risk_model.py::test_broken_model_is_an_l2_model_failure
  - tests/perception/test_student.py::test_missing_file
  - tests/perception/test_student.py::test_bad_hash
  - tests/perception/test_student.py::test_pickled_npz_is_refused
  - tests/perception/test_student.py::test_non_finite_weights
  - tests/safety/test_crisis.py::test_model_exception_fails_safe_to_l2
  - tests/safety/test_crisis.py::test_invalid_model_score_fails_safe_to_l2
  - tests/cli/test_cli_hotlines_under_failure.py::test_chat_says_once_when_the_model_is_unavailable
  - tests/cli/test_cli_doctor.py::test_a_model_that_fails_verification_fails_and_says_chat_uses_rules
residual: {severity: 灾难性, likelihood: 极低, risk: 3}
status: 已控制
known_gaps: []
```

退回本身是正确的，但退回后的召回水平就是规则模式的水平；用户主动用 `--rules` 时同样如此（负责人决定保留这个开关）。

### HAZ-35 提示注入

```yaml
id: HAZ-35
title: 提示注入
hazard: 用户在消息里伪造系统指令、开发者模式或角色设定，要求关闭危机检测、切换状态、下诊断、开药，或让回复说出“规则已解除”。
cause:
  - 用户有意测试或绕过安全规则
effect: 若被执行，会绕过危机流程或给出处方与诊断（HAZ-21、HAZ-22、HAZ-25）。
initial: {severity: 较大, likelihood: 中, risk: 3}
controls:
  - olivia/core/session.py 没有大模型，消息里的“指令”只是被筛查的文本；危机筛查读整条消息，注入的说法不改变任何规则
  - olivia/data/templates/ 回复只来自模板，不会复述注入要求的确认句
  - olivia/core/safety/tracker.py 安全确认的否决条件（同一句里有风险时不算确认）
evidence:
  - tests/redteam/test_redteam.py::test_case
  - tests/redteam/test_redteam.py::test_hard_expectations
  - tests/safety/test_tracker.py::test_confirmation_inside_crisis_message_is_ignored
  - tests/fsm/test_machine.py::test_crisis_beats_battery_lock_commands_and_direct_request
residual: {severity: 较大, likelihood: 极低, risk: 2}
status: 已控制
known_gaps: []
```

红队“提示注入”23 条两种模式都没有缺口。将来接入 AI 增强（P7）时，这一条必须重新评估。

### HAZ-36 长输入

```yaml
id: HAZ-36
title: 长输入中的危机线索被截断或拖慢
hazard: 用户贴来一大段文字，危机线索在中间或末尾，被截断后没有筛到；或长文本让筛查变慢、卡住。
cause:
  - 感知窗口只看开头与结尾（规则感知 128 + 256 字，学生 48 + 112 字）
  - 匹配算法在大量否定词、锚点与组合下可能退化
effect: 长篇倾诉里的危机表达被漏掉（同 HAZ-01），或程序无响应。
initial: {severity: 灾难性, likelihood: 中, risk: 4}
controls:
  - olivia/core/safety/normalize.py 危机筛查读取整条规范化后的消息，不截断（SDD §10.1 实现说明）
  - olivia/core/safety/compose.py 组合匹配对每个条目的搜索有界（线性）
  - olivia/cli.py 长段粘贴整行读入
evidence:
  - tests/safety/test_crisis.py::test_cue_at_end_of_long_text
  - tests/safety/test_compositions.py::test_long_input_stays_linear
  - tests/safety/test_performance.py::test_long_input_with_many_masked_cues_stays_fast
  - tests/safety/test_performance.py::test_long_input_with_many_voided_compositions_stays_fast
  - tests/cli/test_cli_input.py::test_a_long_pasted_line_in_a_terminal_is_read_whole
  - tests/safety/test_normalize.py::test_clip_keeps_tail
residual: {severity: 灾难性, likelihood: 低, risk: 4}
status: 部分控制
known_gaps: []
```

规则侧不截断。模型侧只看 160 字的窗口：长消息中段的危机表达若规则没有接住，模型也看不到，而模型正是补规则召回的主要来源；这一点没有测试。

### HAZ-37 性能与资源

```yaml
id: HAZ-37
title: 时延或内存超出预算
hazard: 每轮回复明显变慢，或内存占用过高导致程序被系统结束。
cause:
  - 词表、组合与模型增长；机器负载高
effect: 危机中的回复被延迟，或会话中断（中断时号码兜底见 HAZ-19）。
initial: {severity: 显著, likelihood: 中, risk: 2}
controls:
  - docs/SYSTEM_DESIGN.md §10.1 时延预算（控制回路 P99 不超过 55 毫秒）与内存包络（≤ 100 MB，进度表 §9.1）
  - scripts/bench_loop.py 在 CI 中运行
  - olivia/core/safety/crisis.py 规则线索共用一个索引（_CueIndex），一条消息只扫一遍；olivia/core/safety/matcher.py 单遍短语匹配
evidence:
  - tests/safety/test_performance.py::test_assess_p99_under_one_millisecond
  - tests/session/test_session_performance.py::test_turn_p99_within_the_control_loop_budget
  - tests/session/test_step_performance.py::test_step_p99_within_its_budget
  - tests/session/test_step_performance.py::test_peak_rss_of_a_run_is_within_the_envelope
  - tests/perception/test_student_performance.py::test_predict_p99_within_budget
  - scripts/bench_loop.py
residual: {severity: 显著, likelihood: 低, risk: 2}
status: 已控制
known_gaps: []
```

## 12. 证据不足、建议补测试的危害

下面这些条目的控制措施有测试，但测试没有覆盖到危害里最要紧的那一部分。本次只记录，没有新增测试：

1. **HAZ-07 繁体输入的模型侧**（2026-11-25 已补大部分）：学生的输入现在也折叠，会话层有繁简对照测试（`tests/perception/test_student_input.py`）。仍没有测试锁定的是 著、後、於、乾 等 11 个同时是合法简体字的繁体写法对学生分数的影响；要处理只能在开发集上重新选型（例如重训时把这些字的繁体用法加进训练数据）。
2. **HAZ-36 长消息中段的危机表达**：只有“线索在末尾”的规则测试；没有“线索在中段、规则未命中、模型窗口外”的测试，也没有说明这种情况下的预期。
3. **HAZ-06 英文与粤语**：只有零散用例，没有成套的召回用例或计数；建议按句式类各补一组（遵守红队写作规则），并在 `scripts/eval_crisis.py` 的报告里单列。
4. **HAZ-35 提示注入**：证据只有红队单轮用例；没有“危机中伪造确认”（如以系统口吻声称用户已安全）的多轮测试。
5. **HAZ-15 号码本身的正确性**：测试只能检查每条有来源与日期；现实中的正确性依赖人工核对，没有可自动化的证据。
6. **HAZ-30 防依赖**：测试只证明提醒按时出现，没有任何关于效果的证据（这需要使用数据，不是单元测试能补的）。
7. **HAZ-26 未成年人**：谎报年龄无法测试；聊天中自述的说法虽有多组测试，但没有成套的召回计数。

## 13. 与 PRD 风险登记册的对应

| PRD 编号 | 本日志 |
| :--- | :--- |
| RSK-01 口癖误报 | HAZ-11 |
| RSK-02 低电量前缀逃逸 | HAZ-10 |
| RSK-03 大模型篡改步骤 | 不适用（P7 未接入） |
| RSK-04 未成年人 | HAZ-26 |
| RSK-05 本机隐私泄露 | HAZ-32 |
| RSK-06 负反馈误拉黑方法 | 不列为临床危害（体验问题，见 `tests/requirements_trace.yaml` 的 RSK-06） |
| RSK-07 病态依恋 | HAZ-30 |
| RSK-08 云端超时 | 不适用（本就离线） |
