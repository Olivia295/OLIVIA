# 剩余开发路线图：问题处理与 P2–R2

> 状态：**已批准（2026-10-22）**，按“执行顺序”自动推进，只在需要你本人完成的事（写评估集、授权、G-0 签字）出现时停下。

**目标**：把 P1 之后暴露的问题逐一处理掉，并按 PRD/SDD V3.2 完成 P2、P3、P4、P5、R1、P6、R2，使系统具备：规则模式可内测（R1），感知模型版可在独立评估集达标后发布（R2）。

**依据**：`docs/DEVELOPMENT_PLAN.md`、`docs/PRODUCT_DOCUMENT.md`、`docs/SYSTEM_DESIGN.md`、`olivia/data/taxonomy.yaml`；2026-10-22 的需求梳理（约 50 处文档矛盾与缺口，见下文“规格裁定”）；可行性实验结果（`DEVELOPMENT_PLAN.md` §5 P6 小节）。

---

## 1. 当前状态（2026-10-22）

| 项 | 状态 |
| :--- | :--- |
| P0 工程地基、P1 安全主链 | 已合并到 `main`，CI 三平台通过 |
| P6 可行性实验 | 第一轮完成；第二版笔记本（交叉验证 + 温度缩放）已写好，未在 Colab 上跑 |
| P2、P3、P4、P5、R1、R2、P7 | 未开始 |

## 2. 问题清单与处理方式

| # | 问题 | 处理方式 | 对应步骤 |
| :--- | :--- | :--- | :--- |
| I-1 | 规则模式对新说法召回很低（L3 0/12） | 不再靠补词；R1 的发布条件不变；模型路线（P6）提前到与 P3/P4 并行 | P6-* |
| I-2 | 第一轮阈值过低导致误报 10/14 | 第二版笔记本已改；在 Colab 重跑拿到 OOF 指标 | P6-0 |
| I-3 | 没有独立评估集 | 写标注规范与评估集模板；你本人编写正式评估集；同时由“盲写”子代理产出过渡评估集，只用于开发跟踪 | EVAL-* |
| I-4 | 安全设计待定：模型能否给 L3；L1 是否算安全轮次 | 见第 6 节问题 Q4、Q5 | SAFE-* |
| I-5 | 多个会话在同一目录改代码，分支被切换 | 每个阶段在独立 worktree 与分支上做，PR 合并；不在主目录直接改 | 全部 |
| I-6 | 研究用数据集没有商用许可；Drive 授权范围较大 | 产品模型只用自产数据（合成 + 人工抽检 + 临床评估集）训练；研究数据只做对照基准；Drive 授权在训练结束后由你撤销 | P6-1~3 |
| I-7 | PRD/SDD/taxonomy 之间约 50 处矛盾或缺口 | 本计划第 5 节逐条给出裁定，SPEC 步骤同步修文档，代码按裁定实现 | SPEC-1 |

## 3. 执行顺序与步骤

记法：`[大小]`，`Blocked by` 列出必须先完成的步骤；同一时刻 Blocked by 全部完成的步骤可以并行（由子代理在各自 worktree 中执行）。每步完成标准包括 `bash scripts/check.sh` 全绿与 CI 三平台通过，下表只写额外的验证。

### 阶段 0：基础整理

| ID | 步骤 | 验证 | 主要文件 | Blocked by |
| :--- | :--- | :--- | :--- | :--- |
| SPEC-1 [M] | 按第 5 节裁定修改 PRD/SDD/taxonomy 的矛盾处（如 `AUTONOMOUS_PRACTICE`→`MICRO_EXERCISE`、BPD 允许列表补 29、m0 统一命名、补 `λ_decay` 等阈值进 taxonomy） | `scripts/validate_taxonomy.py` 通过；新增 taxonomy 一致性测试 | `docs/*.md`、`taxonomy.yaml`、`olivia/data/taxonomy.yaml`、`olivia/core/taxonomy.py` | 计划批准 |
| SAFE-1 [S] | 按 Q5 修改危机退出时 L1 的计数；同步 SDD §8.2 | `tests/safety/sessions.yaml` 新增会话用例 | `olivia/core/safety/tracker.py` | 计划批准 |
| SAFE-2 [S] | 按 Q4 实现“模型提供计划证据”的开关（默认值按你的决定） | `test_crisis.py` 新增仲裁用例 | `olivia/core/safety/crisis.py` | 计划批准 |
| HOUSE-1 [XS] | 删除远端已合并的 `feat/p1-safety-core`；开发计划 §8 三个待定项写入裁定 | `git ls-remote` | `docs/DEVELOPMENT_PLAN.md` | 计划批准 |

### 阶段 1：评估集（越早越好，周期最长）

| ID | 步骤 | 验证 | 主要文件 | Blocked by |
| :--- | :--- | :--- | :--- | :--- |
| EVAL-1 [S] | 写危机分级标注规范（L0–L3 定义、C-SSRS 对照、口癖与否定说明，**不含任何词表短语或用例原句**）与评估集模板（300 条配额）；写给你的编写说明 | 你能照着开始写 | `docs/eval/crisis-annotation-guide.md`、`docs/eval/fresh-eval-template.csv` | 计划批准 |
| EVAL-2 [S] | 过渡评估集：由一个**看不到**用例、词表、探针与训练数据的子代理按规范盲写 300 条；只用于开发跟踪 | 导出脚本 `--fresh-eval` 能读入；与训练集近似重复为 0 | `build/eval/interim_fresh.csv`（不入库） | EVAL-1 |
| EVAL-3 [你] | 你按规范编写正式评估集 300 条（L3 60、L2 80、L1 60、L0 100，其中口癖 40）；写之前不看词表、用例和合成数据 | **确认步骤**：收到文件后检查条数、配额与格式 | `docs/eval/fresh_eval.csv`（不进训练） | EVAL-1 |

### 阶段 2：P3 状态机与动作求解（关键路径）

| ID | 步骤 | 验证 | 主要文件 | Blocked by |
| :--- | :--- | :--- | :--- | :--- |
| P3-1 [M] | 规则感知桩：从词表与电量前缀给出 `PerceptionContext` 最小字段（arousal、主导谱系、情绪）；纯倾听锁开启/解除词表 | 单元测试 + 一组标注句子上的唤醒度分档准确率报告 | `olivia/core/perception/rule_stub.py`、`olivia/data/lexicons/perception.yaml` | SPEC-1 |
| P3-2 [M] | 七状态 FSM，严格按 SDD §4.2 与第 5 节裁定；hypothesis 属性测试 | 转移表每行一个测试；“S_crisis 只能经安全出口离开”属性测试 | `olivia/core/fsm/` | SPEC-1 |
| P3-3 [M] | 动作求解：别名归约、四重交集、继承规则、红线掩码、空集降级 m0 + 转介卡、按 `action_type` 分发 | 7 个红线病种在高唤醒下的可用集合与 taxonomy 逐一比对 | `olivia/core/methods/solver.py` | SPEC-1 |
| P3-4 [S] | Thompson 采样：证据等级先验、三档反馈、软衰减、高唤醒只利用 | 固定随机种子的统计测试 | `olivia/core/methods/bandit.py` | P3-3 |

### 阶段 3：P2 属地资源（可与 P3 并行）

| ID | 步骤 | 验证 | 主要文件 | Blocked by |
| :--- | :--- | :--- | :--- | :--- |
| P2-1 [M] | 热线数据重新整理：每条记录官方来源 URL、核验日期、服务时间；范围按 Q 假设 A-4；未核验条目不进卡片 | 每条都有来源与日期；`GEO-03` 测试（非大陆不出现 12356/110/120/12355） | `olivia/data/resources/hotlines.yaml` | SPEC-1 |
| P2-2 [M] | 行政区划（GB/T 2260 最新版）与世界城市索引（GeoNames，CC BY 4.0）；解析器 GEO-01~07 | 抽样城市解析测试；未知地区走 ZZ | `olivia/core/resources/`、`olivia/data/resources/` | SPEC-1 |
| P2-3 [S] | 签名包：Ed25519 签名与校验、180 天过期提示、损坏时退回内置兜底 | 篡改包被拒绝的测试 | `olivia/core/resources/bundle.py`、`scripts/sign_hotlines.py` | P2-1，Q6 |
| P2-4 [S] | `olivia resources`、`olivia region` 命令与 L2/L3 卡片渲染 | CLI 快照测试 | `olivia/cli.py` | P2-2 |

### 阶段 4：P4 首访与会话闭环（R1 关键路径）

| ID | 步骤 | 验证 | 主要文件 | Blocked by |
| :--- | :--- | :--- | :--- | :--- |
| P4-1 [M] | 语料编写：`GENTLE_HOLDING` 各状态模板、隐喻映射、说教词与诊断词表、去病理化替换表、32 张 A 级卡的 2–5 分钟跟练脚本（按 taxonomy 的三步，不照搬 method/*.md 中的禁用做法） | 字数窗口测试；禁用词扫描为 0；卡片脚本待 G-0 签字 | `olivia/data/templates/`、`olivia/data/lexicons/language.yaml` | SPEC-1 |
| P4-2 [M] | 首访 ONB-01~05、07、08（18+ 门禁先于城市采集） | SOP 1 黄金对话 | `olivia/core/chang/onboarding.py` | P2-2 |
| P4-3 [M] | 单一入口 `Session.turn()` 串联安全筛查 → 危机跟踪 → 红线 → FSM → 求解 → 语言 → 输出审查网关 | SOP 2、SOP 4 黄金对话；`[5%] 不想活了` 进入 S_crisis | `olivia/core/session.py`、`olivia/core/language/` | P3-2、P3-3、P4-1 |
| P4-4 [S] | `olivia chat` 循环与 `--inspect` 面板（不显示原文与城市） | 断网端到端：首访 → 对话 → 危机 → 退出 | `olivia/cli.py` | P4-3、P2-4 |

### 阶段 5：P5 记忆、周记与隐私

| ID | 步骤 | 验证 | 主要文件 | Blocked by |
| :--- | :--- | :--- | :--- | :--- |
| P5-1 [M] | 透明账本格式（Markdown 带 front-matter）、写入规则（只记会话摘要模板与自评，不记原文）、3D 检索（P6 前用字符 n-gram TF-IDF 余弦） | 检索排序测试 | `olivia/core/memory/` | P4-3 |
| P5-2 [M] | AES-256-GCM 静态加密与一键遗忘（密钥存放见 Q7）；加密关闭时遗忘 = 安全删除全部文件 | 遗忘后残留文件无法解密的测试 | `olivia/core/memory/crypto.py` | P5-1，Q6，Q7 |
| P5-3 [S] | 7 天周记（滚动 7 天、会话 ≥ 2 次、有 L2/L3 时庄重语气）、45 分钟与深夜提醒（危机与避风港中不提醒） | SOP 5 黄金对话 | `olivia/core/chang/journal.py` | P5-1 |

### 阶段 6：R1 规则模式发布候选

| ID | 步骤 | 验证 | Blocked by |
| :--- | :--- | :--- | :--- |
| R1-1 [S] | G-1 断网全功能测试；G-3 控制回路基准（本机单核，P99 ≤ 55 ms） | `scripts/bench_loop.py` 报告 | P4-4、P5-3 |
| R1-2 [S] | G-4 隐私自动审计清单（无原文日志、无城市日志、加密开关、遗忘）；法务审查作为外部门禁登记 | 审计脚本输出 | P5-2 |
| R1-3 [M] | G-5 红队集（诱导开药、诱导自伤方法、状态机越权、诊断请求）≥ 150 条，拦截 100% | 红队测试全过 | P4-4 |
| R1-4 [人] | G-0：两名注册心理师审核 32 张卡片；G-2：你的评估集上测规则模式，并由临床人员复核后才对外发布 | **确认步骤**：收到签字与评估结果 | EVAL-3、P4-1 |

### 阶段 7：P6 感知模型（与阶段 2–5 并行推进，训练在 Colab）

| ID | 步骤 | 验证 | 主要文件 | Blocked by |
| :--- | :--- | :--- | :--- | :--- |
| P6-0 [S] | 在 Colab 重跑第二版可行性笔记本，记录 OOF 指标与过渡评估集结果 | `calibration.json`、`fresh_summary.md` | `training/colab/` | EVAL-2 |
| P6-1 [M] | 八头标注规范：补全 empathy intent 标签集（建议 6 类：VALIDATION、EXPLORATION、REFLECTION、INFORMATION、STABILIZATION、REFERRAL）、readiness 与 valence 的打分锚点 | 规范审阅 | `docs/eval/perception-annotation-guide.md` | SPEC-1 |
| P6-2 [L→拆] | 合成训练数据：以 60 份困扰档案的内心独白与系统映射为种子，由本环境的子代理分批生成并标注八头标签；每批保存提示词与原始输出 | 配额报告；与评估集近似重复为 0 | `training/data_gen/`、`build/train_data/` | P6-1 |
| P6-3 [S] | 交叉复核：由另一组子代理（看不到原标注）对每头各 50 条独立标注，计算一致率；不一致的条目剔除或复标 | 一致率报告（目标 ≥ 85%） | `training/review/` | P6-2 |
| P6-4 [M] | 教师模型：Colab 上训练八头（只用自产数据），交叉验证定阈值，温度缩放 | OOF：L2+L3 召回 ≥ 98%，口癖误报 ≤ 5% | `training/colab/teacher.ipynb` | P6-3 |
| P6-5 [M] | 蒸馏：字符级 CNN 学生模型，导出 NumPy `.npz`（< 4 MB） | 学生与教师一致率；本机 P99 ≤ 45 ms | `training/colab/distill.ipynb`、`olivia/data/models/` | P6-4 |
| P6-6 [M] | NumPy 推理与 `RiskModel` 接入，规则作底线；`PerceptionContext` 全字段；内省器（图式、渴望、扭曲） | 规则模式安全用例零回退；黄金对话通过 | `olivia/core/perception/` | P6-5、P3-1 |

### 阶段 8：R2 模型版发布

| ID | 步骤 | 验证 | Blocked by |
| :--- | :--- | :--- | :--- |
| R2-1 [S] | 在临床评估集上测模型版：危机召回 ≥ 98%、口癖误报 ≤ 5%、精确率 ≥ 90% | `fresh_summary.md` | EVAL-3、P6-6 |
| R2-2 [人] | G-0 ~ G-5 全部签字 | **确认步骤** | R2-1、R1-4 |

## 4. Always / Never

- **Always**：每步在独立 worktree 与分支上做，PR 合并；危机检测先于一切；评估集永不进训练；数据来源与许可逐条记录；提交不加 AI 署名。
- **Never**：用探针或评估集结果回头调阈值；把研究用数据训练出的权重放进产品；在日志中写原文或城市；未经你确认的授权、付款或对外发布。

## 5. 规格裁定（文档矛盾与缺口的默认处理，可推翻）

**P3**
1. 方法 28（生理性叹息）的禁忌 `ACUTE_AROUSAL_OVERLOAD` 保留：唤醒 ≥ 0.85 时白名单只放行 `30:grounding` 与 `12:tipp_breathing`；SOP 3 示例改用 30。
2. `AUTONOMOUS_PRACTICE` 统一改为 `MICRO_EXERCISE`。
3. m0 统一叫 `EMOTIONAL_HOLDING_PRESENCE`；不参与 Thompson 竞争，只在可用集合为空或避风港时使用。
4. S_explore → S_clarify 采用 SDD 的条件（含 `social_battery ≥ 0.40`）；“5 轮”指当前阶段内轮次。
5. 直接索要方法：任何非危机状态均可触发；仍经红线掩码与唤醒检查；SILENT_ANCHOR 也可进入 S_empower；掩码后为空时给 m0 + 转介卡。
6. ΔArousal 以进入当前阶段时的唤醒度为基线。
7. S_empower 中 UNHELPFUL → 回到 S_explore 并软衰减；完成判定用显式命令（`/done`、`/not-now`、`/unhelpful`）。
8. 纯倾听锁开启：用户明确说“只想说说 / 不要建议”一类话。
9. 电量前缀跨轮保留，直到下一次前缀或会话结束；无前缀时默认 0.6。
10. Thompson 只更新主导谱系（`distress_vector` 最大项所属谱系）。
11. `λ_decay = 0.1/天` 写入 taxonomy。
12. BPD 允许列表补入 29（渐进肌肉放松），与政策文字一致。
13. 求解器返回 `ActionPlan`（主动作 + 可选转介卡），掩码放在 `methods/solver.py`；方法 ID 统一用 taxonomy 的 `"01"` 形式。
14. 危机态中每轮重复呈现卡片的精简版；跨会话“关怀标记”存入画像。

**P2**
15. 澳门 L3：999 + 110 + 112 以官方核验为准；香港 L2：18111 + 撒玛利亚防止自杀会 2389 2222，另核验“生命热线”；741741 只用于美国，加拿大以官方文本线为准。
16. R31 未知属地：只显示 findahelpline 与当地急救号码（112 兜底）；内置兜底包含所有已核验地区。
17. 签名包超过 180 天仍显示，并加“可能过期”提示；无有效签名时用内置兜底。
18. 非大陆未成年人：显示当地青少年热线（已核验者），否则显示通用热线与急救号码。

**P4**
19. 黄金对话按字数窗口改写示例，不按示例放宽窗口；SOP 3 拆为“规则部分”（P4 验收）与“AI 增强部分”（P7）。
20. 去病理化替换跳过方法名与卡片标题。
21. 雷区话题为硬过滤（不在模型生成与模板中出现），镜像用户原话除外，安全文案豁免。
22. 首访先年龄门禁再采集城市；未成年拒绝写入画像，阻止再次进入深度干预。
23. `clinical_history` 授权放在首访最后一步，可跳过。
24. 未知地区统一用 `ZZ`，不用 `None`。
25. S_clarify 在规则模式下只做情绪与需要的镜像，不做图式判定。
26. Grade B/C 只提供一段机制科普文字（P4-1 编写），不提供练习。
27. `--inspect` 在 R1 显示等级、线索 id、状态、唤醒度、可用动作，不显示原文。

**P5**
28. 加密开关默认关闭；`clinical_history` 无论开关都加密。
29. 检索权重 `w_rec = 0.4、w_sim = 0.4、w_sal = 0.2`，α = 1；显著事件 = 当轮 ≥ L2 或用户标记。
30. 周记按滚动 7 天；自评在会话开始与结束各一次（可跳过），避风港中不问。
31. 不做“导出到外部笔记软件”。

**R1/P6/P7**
32. G-3 参考硬件为本机单核；G-4 先做自动审计清单，法务报告作为外部门禁。
33. 精确率 ≥ 90% 加入 R2 门禁。
34. 认知扭曲以 taxonomy 的 9 项为准，修正“8 Core”字样。
35. P7（AI 增强）不在本轮范围：需要法务评审与模型供应商选择，R2 之后另立计划。

## 6. 需要你决定的问题（一次问清）

Q1 合并方式；Q2 训练数据生成方式；Q3 评估集作者；Q4 模型能否给 L3；Q5 L1 是否算安全轮次；Q6 加密依赖；Q7 密钥存放；Q8 R1 人格范围。答案写入下方决定日志。

## 7. 假设（不同意就指出，否则按此执行）

- A-1 Colab 使用你的 Pro 额度，按需选 T4/L4；Drive 继续用 `OLIVIA_crisis/`（P6 改为 `OLIVIA_perception/`）。
- A-2 浏览器操作用 ego lite；涉及登录、授权、付款的步骤交给你。
- A-3 热线与行政区划数据重新整理，不从回收站取回旧数据。
- A-4 L2/L3 卡片支持的地区：中国大陆、香港、澳门、台湾、美国、加拿大、英国、澳大利亚，其余走 ZZ。
- A-5 推理只用 NumPy（按 SDD），不用 ONNX Runtime。
- A-6 每完成一个阶段，更新本文件的进度表与 `DEVELOPMENT_PLAN.md` 状态。

## 8. 尚未能具体规划的部分（到时再调研）

- P6 合成数据的规模与配额，要等 P6-1 规范定稿和第一批抽检结果后确定。
- 蒸馏学生模型的结构细节，要看教师模型在 OOF 上的表现。
- R2 之后的 P7。

## 9. 决定日志（2026-10-22）

| # | 决定 | 理由 / 代价 |
| :--- | :--- | :--- |
| Q1 | 每步开 PR，CI 三平台通过后由我合并 | 进度不卡在审阅上；你可随时叫停或在 PR 上提意见 |
| Q2 | 合成训练数据由本环境子代理分批生成 | 不需要 API 密钥；较慢、可复现性弱，所以每批保存提示词与输出 |
| Q3 | 正式独立评估集由你本人编写 | 你没看过词表与用例，算不同作者；不是临床人员，G-2 仍需临床复核后才能对外发布 |
| Q4 | 模型给 L3 的开关先实现、默认关闭 | 评估集上“普通句被判 L3”为 0 且 L3 召回达标后由你决定打开 |
| Q5 | 危机退出时 L1 暂停计数（不算安全轮，也不清零） | 退出更晚；需改 SDD §8.2 |
| Q6 | 新增运行时依赖 `cryptography` | 一个包同时覆盖 Ed25519 与 AES-GCM |
| Q7 | 主密钥存系统钥匙串（新增依赖 `keyring`） | 不用每次输入口令；一键遗忘即删除钥匙串条目 |
| Q8 | R1 只做 `GENTLE_HOLDING` | 其余三个人格放到 R2 前 |
| Q9 | 你的评估集 300 条：L3 60、L2 80、L1 60、L0 100（含口癖 40） | L3 召回置信区间下限约 90%，足够做上线前判断 |
| Q10 | 合成数据由另一组子代理交叉复核 | 不占用你的时间；与生成同源，偏差可能被放大，靠你的评估集兜底 |
| — | 第 5 节 35 条裁定与第 7 节假设全部按原文执行 | 批准时一并确认 |

## 10. 进度

| 步骤 | 状态 | 证据 |
| :--- | :--- | :--- |
| 计划 | 已批准 | 本文件 |
