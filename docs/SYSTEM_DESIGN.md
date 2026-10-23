# O.L.I.V.I.A. 系统架构与底层工程设计规范 (System Design Document)

| 工程元数据 (Engineering Control) | 详细规格说明 (System Specifications) |
| :--- | :--- |
| **文档编号 (Document ID)** | `SDD-OLIVIA-V3.2-CLINICAL-SPEC` |
| **版本号 (Version)** | `v3.2.0` (实施对齐交付版) |
| **系统全称 (System Name)** | **O.L.I.V.I.A.** (*Observant Listener & Introspective Verbal Interaction Agent*，善察的倾听者与内省式言语交互智能体) |
| **架构范式 (Paradigm)** | 四位一体神经符号混合双擎架构 (Quad-Pillar Neuro-Symbolic Dual-Engine Architecture) |
| **四大核心工程子系统** | **M.I.Y.I.** (*Memory Indexing & Yearning Introspection*，记忆索引与渴望内省子系统)<br>**C.O.L.B.O.** (*Compassionate Observation & Logical Belief Organizer*，慈悲观察与逻辑信念编排子系统)<br>**W.I.L.L.O.W.** (*Warm Introspective Language & Lexical Oriented Wisdom*，温润内省言语与词汇意境重塑系统)<br>**C.H.A.N.G.** (*Co-evolving Human-agent Adaptation & Narrative Growth System*，人机协同演化与叙事成长系统) |
| **统一分类标准 (SSOT)** | 严格绑定并继承根目录统一分类标准规范 (`taxonomy.yaml` v3.2.0) |
| **底层核心公理** | **「离线自足为基，AI激活升华」**：离线基线以 $P_{99} \le 55\text{ms}$ 的确定性延迟闭环运行，保障绝对隐私与可靠助人；开启 AI 增强时，系统基于“结构先行，语态后润”双通道与本地校验器，实现生活记忆缝合与沉浸式角色转译。 |
| **性能服务等级目标 (SLO / Latency)** | 符号状态机与镜像翻转: $P_{99} < 1.5\text{ms}$；中文上下文感知前向推断: $P_{99} \le 45.0\text{ms}$；离线端到端控制回路总耗时: $P_{99} \le 55.0\text{ms}$；AI 增强流式首字指标 (TTFT): $P_{90} < 1200\text{ms}$ (降级不增加额外等待延迟) |
| **资源消耗约束 (Resource Envelope)** | 运行时常驻内存 (RSS) $< 50\text{MB}$；感知权重与知识协议静态体积 $< 4.0\text{MB}$；核心逻辑实现零第三方重型深度学习框架依赖 |
| **对应产品文档 (Companion PRD)** | `PRD-OLIVIA-V3.2-CLINICAL-SPEC` (《O.L.I.V.I.A. 产品需求与体验设计说明书》) |
| **文档性质 (Doc Nature)** | 研发前置系统架构与工程规范说明书 (Pre-Development System Architecture Specification) |

---

## 架构修订历史与技术评审签署 (Revision History & Architectural Sign-off)

### 架构修订记录 (Revision History)
| 版本 | 发布日期 | 主导架构师 | 评审性质 | 核心技术变更摘要 |
| :--- | :---: | :---: | :---: | :--- |
| **v1.0.0** | 2026-09-15 | 核心架构组 | 初始设计 | 确立双系统架构雏形，提出 ELIZA 镜像与状态机控制框架。 |
| **v2.0.0** | 2026-10-18 | 核心架构组 | 架构重构 | 剥离具体文件路径依赖，确立抽象领域契约与六状态有限状态机。 |
| **v2.1.0** | 2026-10-19 | 联合技术委员会 | 临床深化 | 引入两阶段漏斗危机检查与三级疗法分类，完成 60 份困扰档案与 75 种疗法集成。 |
| **v3.1.0** | 2026-10-20 | 首席架构师 / 临床总监 | 权威基线 | 1. 修复两阶段危机检测时序漏洞（SAFE-09：危机筛查强制前置于低电量避风港判断）；<br>2. 形式化对齐 `taxonomy.yaml` v3.1.0，修正 7 处转介红线编号与 75 种疗法分级映射；<br>3. 补全 GEO-01~08 属地化与海外危机资源解析协议；<br>4. 统一感知网络为 8 头多任务架构，损失函数严格对齐；<br>5. 规范纯 Thompson 采样模型，废除矛盾的 10% ε-greedy；<br>6. 明确核心信念判定限制在「本会话实时上下文」，增加模块实现映射索引。 |
| **v3.2.0** | 2026-10-21 | 架构委员会 / 临床总监 | 实施对齐 | 1. 临床禁忌症统一收敛为 13 种固定枚举体系，32 个 Grade A 方法全面对齐；<br>2. 临床转介红线使用稳定动作与禁用 ID，并建立 S_explore 高唤醒稳定化微干预 ID 白名单；<br>3. 危机状态机出口统一为 SafetyConfirmEvent + 连续安全轮数（L2: 2 轮, L3: 3 轮）；<br>4. 属地化与海外资源模型全面升级为 ResourceCard 与 Ed25519 签名；<br>5. PersonaProfile 升级为 UserRegion 架构并新增 clinical_history 敏感健康信息授权；<br>6. 危机前置防御时序图对齐 0.20 低电量避风港阈值与 Stage 1 明确线索熔断；<br>7. 补全各状态字数窗口阻尼模型及危机卡刚性豁免，将存储物理抹除升级为加密擦除 (Crypto-Shredding)。 |

### 技术评审委员会签署表 (Architectural Sign-off)
| 评审席位 | 签署代表 | 审核领域 | 签署状态 | 签署日期 |
| :--- | :--- | :--- | :---: | :---: |
| **系统架构委员会** | 首席架构师 | 架构拓扑、领域契约、状态机代数模型、时延与内存预算 | **待签署 (Pending Review)** | 2026-10-21 |
| **临床伦理技术组** | 临床总监 | 危机状态机出口闭环、7 处转介红线拦截、禁忌症硬掩码 | **待签署 (Pending Review)** | 2026-10-21 |
| **安全与合规工程组** | 安全负责人 | PIPL 敏感数据隔离、本地 AES-256 存储加密、防篡改签名 | **待签署 (Pending Review)** | 2026-10-21 |

---

## 目录索引 (Table of Contents)

1. [系统总体架构蓝图与四位一体工程哲学 (Architecture Blueprint & Quad-System Philosophy)](#1-系统总体架构蓝图与四位一体工程哲学-architecture-blueprint--quad-system-philosophy)
2. [通用领域模型与抽象数据契约规范 (Universal Domain Models & Data Contracts)](#2-通用领域模型与抽象数据契约规范-universal-domain-models--data-contracts)
3. [子系统 I：M.I.Y.I. 认知感知与透明记忆引擎 (M.I.Y.I. Perception & Memory Engine)](#3-子系统-i-miyi-认知感知与透明记忆引擎-miyi-perception--memory-engine)
   - 3.1 中文上下文多任务心理感知网络与 8 头联合损失函数
   - 3.2 萨提亚冰山内省器与会话内核心信念判定准则
   - 3.3 3D 艾宾浩斯记忆检索与本地静态加密协议
4. [子系统 II：C.O.L.B.O. 符号状态机与临床协议编排器 (C.O.L.B.O. Symbolic Core & FSM)](#4-子系统-iicolbo-符号状态机与临床协议编排器-colbo-symbolic-core--fsm)
   - 4.1 语境感知代词镜像重述算法与第三人称冲突消解
   - 4.2 七状态门控有限状态自动机代数模型 (含回退、越级与闭环出口)
   - 4.3 32 种 A 级微干预编排、禁忌症硬掩码与只陪伴基线 ($m_0$)
5. [子系统 III：W.I.L.L.O.W. 温润内省言语与词汇意境重塑引擎 (W.I.L.L.O.W. Language & Metaphor Engine)](#5-子系统-iiiwillow-温润内省言语与词汇意境重塑引擎-willow-language--metaphor-engine)
   - 5.1 去机械化语调塑形与违规说教词表过滤
   - 5.2 概念隐喻织造算法与萨提亚意境对齐
   - 5.3 沉静呼吸节奏与黄金字数窗口阻尼模型
6. [子系统 IV：C.H.A.N.G. 人机协同演化与叙事成长引擎 (C.H.A.N.G. Co-evolving Adaptation Engine)](#6-子系统-ivchang-人机协同演化与叙事成长引擎-chang-co-evolving-adaptation-engine)
   - 6.1 首访角色契约领域模型与四维人格光谱配置规范
   - 6.2 「结构先行，语态后润」双通道网关与本地校验器
   - 6.3 闭环贝叶斯自进化数学模型 (纯 Thompson 采样与探索安全门禁)
   - 6.4 7 天情绪周记时空数据聚合算法 (基于用户自评数据)
   - 6.5 记忆档案原子级写入安全协议 (影子写入与三版本快照)
   - 6.6 本地静态加密：密钥层级与加密擦除 (B1)
7. [多推理模型适配网关与个人信息保护管线 (Inference Gateway & PIPL Pipeline)](#7-多推理模型适配网关与个人信息保护管线-inference-gateway--pipl-pipeline)
8. [多级安全防御体系、四级危机响应与能力绝对边界 (Multi-Tiered Safety & Crisis Protocols)](#8-多级安全防御体系四级危机响应与能力绝对边界-multi-tiered-safety--crisis-protocols)
   - 8.1 危机前置防御时序模型 (SAFE-09 强制合规)
   - 8.2 四级危机分级与权威热线联动
   - 8.3 属地化与全球危机援助资源解析流水线 (GEO-01 ~ GEO-08)
   - 8.4 7 处强制临床转介红线与能力绝对边界
9. [离线感知模型训练与蒸馏工程流水线 (Training & Distillation Pipeline)](#9-离线感知模型训练与蒸馏工程流水线-training--distillation-pipeline)
10. [系统可靠性、性能预算与可观测性工程 (Reliability, Latency Budget & Observability)](#10-系统可靠性性能预算与可观测性工程-reliability-latency-budget--observability)
11. [逻辑架构与工程模块组件映射索引 (Modular Implementation Mapping)](#11-逻辑架构与工程模块组件映射索引-modular-implementation-mapping)

---

## 1. 系统总体架构蓝图与四位一体工程哲学 (Architecture Blueprint & Quad-System Philosophy)

### 1.1 双擎协作与四位一体分工体系
系统在底层确立了**神经符号混合双擎（Neuro-Symbolic Dual-Engine）**架构，将卡尼曼双系统认知理论（Dual-Process Theory）映射为工程模块，并由四大核心子系统形成全功能覆盖：
- **系统 1（快直觉感知与符号反射层）**：
  - **M.I.Y.I.**：负责轻量多任务前向推断，毫秒级提取情感极性、归一化唤醒度（$0.0\text{–}1.0$）、深层渴望与历史胜任资产；
  - **W.I.L.L.O.W.**：负责语言本能反射与意境塑形，消除生硬官腔，提供沉静留白。
- **系统 2（离散符号控制与长效演化层）**：
  - **C.O.L.B.O.**：作为从状态机拓扑上提供确定性约束的硬规则护栏，主导七状态门控有限状态机，求解 32 种 A 级临床协议并生成不可篡改的**临床干预动作骨架（Action Skeleton）**；
  - **C.H.A.N.G.**：贯穿会话周期之外的纵向主枢纽，管理首访角色契约、调度离线/AI双模、驱动纯 Thompson 采样自进化并生成散文式情绪周记。

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   O.L.I.V.I.A. 总体架构拓扑图                                   │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                 │
│  [终端交互与接入层 / Interaction Presentation Layer]                                            │
│  用户输入捕获 ──► 交互终端控制器 ──► 心力电量/碎片解析 ──► 内部可观测性遥测面板                    │
│                                           │                                                     │
│                                           ▼                                                     │
│  [协调调度网关 / Orchestration Gateway Layer]                                                   │
│  全局主调度器 ──► 前置两阶段安全检查器 (SAFE-09) ──► 运行模式管理器                             │
│         │                                                                                       │
│         ├───► [子系统 I: M.I.Y.I. 认知感知与透明记忆底座] (olivia/core/perception/*)            │
│         │     ├─► 中文上下文多任务心理感知网络 (8头并发 / 极性 / 唤醒度 / 否定句法消歧)         │
│         │     ├─► 萨提亚冰山内省器与会话内核心信念判定 (拒绝跨会话未授权嗅探)                   │
│         │     └─► 3D 艾宾浩斯记忆检索 (时间指数衰减 / 语义余弦 / 显著性资产保护)                │
│         │                                                                                       │
│         ├───► [子系统 II: C.O.L.B.O. 符号状态机与临床协议编排器] (olivia/core/fsm/*、methods/solver.py) │
│         │     ├─► 语境感知代词镜像重述引擎 (第一人称从句安全翻转)                                │
│         │     ├─► A.L.I.C.E. 七状态门控自动机 (就绪/探索/理清/赋能/避风港/结束/危机，含回退/越级)    │
│         │     └─► 32 种 A 级临床协议编排与动作骨架生成器 (含只陪伴基线 m_0 及禁忌硬掩码)        │
│         │                                                                                       │
│         ├───► [子系统 III: W.I.L.L.O.W. 温润内省言语与词汇意境重塑引擎] (olivia/core/language/*) │
│         │     ├─► 去机械化语调塑形 (官腔/说教排比清单剔除与温润邀请式转换)                       │
│         │     ├─► 概念隐喻意境织造 (柔韧柳枝 / 流水绕石 / 四季草木冬眠心理外化)                 │
│         │     └─► 沉静呼吸留白控制 (黄金字数窗口 [140, 260] 阻尼与视觉舒缓断句)                 │
│         │                                                                                       │
│         └───► [子系统 IV: C.H.A.N.G. 人机协同演化与叙事成长中枢] (olivia/core/chang/*、methods/bandit.py) │
│               ├─► 首访契约共创与四维人格光谱 (GENTLE_HOLDING / 哲思 / 战友 / 树洞，18+ 门禁)    │
│               ├─► 「结构先行，语态后润」双通道网关与本地校验器 (降级不增加额外等待延迟)         │
│               ├─► 真正贝叶斯自进化 (纯 Beta-Bernoulli Thompson 采样 / 探索安全门禁)             │
│               ├─► 7 天情绪周记时空数据聚合 (基于用户自评数据 / 复原力年鉴卡片)                  │
│               └─► 记忆档案原子级写入安全协议 (影子写入 Shadow-Write 容灾)                       │
│                                           │                                                     │
│                                           ▼                                                     │
│  [底层持久化与模型网关 / Persistence & Inference Adapters]                                      │
│  纯文本双向透明账本 (可选本地加密) ◄──► 双模推理网关 (本地离线模板 / 本地小模型 / 云端大模型)   │
│  属地化与海外危机资源库 (olivia/core/resources/*，GEO-01~08，Ed25519 签名防篡改)                 │
│                                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 「离线自足为基，AI激活升华」的核心工程公理
1. **纯本地离线基线绝对完备公理 (Offline Completeness)**：脱机状态下，系统完全依托本地 8 头多任务感知与符号状态机闭环执行，基于 `taxonomy.yaml` 的 32 种 A 级微方法推荐严密可靠，周记基于离线结构化槽位合成，保障 100% 隐私安全与可用性；
2. **符号骨架不可穿透公理 (Skeleton Inviolability)**：在 AI 增强激活时，大模型**仅被允许担任表现层语态转译与意境润色**，严禁擅自修改 C.O.L.B.O. 锁定的临床协议类型、步骤约束与安全边界，输出经本地校验器严格验证；
3. **降级无额外延迟公理 (Zero-Overhead Fallback)**：大模型端点发生网络波动、超时或校验不通过时，网关瞬间切换回本地模板输出，终端用户不经历额外等待卡顿；
4. **透明记忆双向平权公理 (Radical Memory Transparency)**：所有记忆均以人类可读的标记语言明文存储，支持可选静态加密，用户享有随时查阅、修改、加密擦除 (Crypto-Shredding) 的绝对主权。

---

## 2. 通用领域模型与抽象数据契约规范 (Universal Domain Models & Data Contracts)

系统采用强类型无副作用的抽象数据契约进行跨子系统通信，严格映射 `taxonomy.yaml`：

### 2.1 长期用户人格档案模型 (`PersonaProfile`)
```
Type PersonaProfile:
    user_name: String                   # 用户希望被称呼的名字 (默认: "朋友")
    agent_name: String                  # 陪伴者名称 (默认: "Olivia")
    persona_spectrum: PersonaEnum       # GENTLE_HOLDING | ZEN_PHILOSOPHER | RATIONAL_PEER | SILENT_ANCHOR
    directiveness_preference: Float     # 指导性偏好 [0.0: 纯倾听, 1.0: 强引导] (默认 0.5)
    taboo_topics: List<String>          # 用户声明的安全雷区词汇/话题
    region: UserRegion                  # 用户属地模型 (含国家码、省市编码、显示名与 IANA 时区；未知标记为 ZZ)
    clinical_history: Optional<List<String>> # 用户明确授权录入的既往病史标签 (如 SIT-08-04, 见 PIPL 合规条款)
    age_confirmed_18_plus: Boolean      # 18+ 成年人准入确认标识 (必须为 True)
    enable_at_rest_encryption: Boolean  # 是否开启本地静态存储加密 (Crypto-Shredding 销毁保障)
    created_at: ISO8601String           # 契约建立时间戳
    updated_at: ISO8601String           # 最近一次修改时间戳
```

> [!IMPORTANT]
> `clinical_history` 属于 PIPL 第 28–32 条规定的敏感个人健康信息。系统严格遵循：
> 1. 绝不通过多任务感知网络被动揣测或跨会话未授权嗅探，仅允许由用户在首访契约或设置面板中主动声明并明示同意（Explicit Consent）；
> 2. 数据在本地以用户主密钥派生密钥进行 AES-256-GCM 独立加密；
> 3. 严格纳入一键遗忘（Crypto-Shredding）物理与密码学抹除范围。

### 2.2 单轮与单会话运行时状态模型 (`SessionState`)
```
Type SessionState:
    session_id: UUID                    # 会话唯一标识符
    current_stage: HelpStage            # S_ready | S_explore | S_clarify | S_empower | S_haven | S_closing | S_crisis
    global_turn_count: Integer          # 会话全局轮次累计计数器
    stage_turn_count: Integer           # 当前阶段内连续轮次计数器
    pure_listening_locked: Boolean      # 纯倾听硬锁标识 (True 则阻断向后跃迁；用户明确说“只想说说/不要建议”一类话时开启)
    social_battery: Float               # 本次会话的心力电量 [0.0, 1.0] (电量前缀跨轮保留，直到下一次前缀或会话结束；从未给出时默认 0.6)
    current_risk_level: CrisisLevel     # L0 | L1 | L2 | L3
    consecutive_l1_count: Integer       # 当前升级窗口内的 L1 轮数（镜像危机追踪器的计数：单个 L0 轮不打断，连续 3 轮 L0、任一 L2/L3 轮或危机退出时清零）
    user_shelved_actions: List<MethodKey> # 本次会话用户置入锦囊待执行的方法
```

### 2.3 心理感知上下文模型 (`PerceptionContext`)
```
Type PerceptionContext:
    valence: Float                      # 连续情感极性 [-1.0, 1.0]
    arousal: Float                      # 归一化生理唤醒度 [0.0, 1.0] (映射 taxonomy.yaml)
    fine_grained_emotion: String        # 16 种核心离散情绪之一
    empathy_intent: String              # 共情策略意图 (如: "EXPLORATION", "VALIDATION")
    risk_level: CrisisLevel             # L0 | L1 | L2 | L3 (四分类头离散预测)
    crisis_confidence: Float            # 危机置信度得分 [0.0, 1.0] (连续回归预测)
    communication_stance: SatirStance   # 5 种萨提亚应对姿态之一
    readiness_to_change: Float          # 改变准备度得分 [0.0, 1.0]
    distress_vector: Map<String, Float> # 11 大谱系 / 60 项困扰倾向打分 (基于语义嵌入与词表)
    detected_distortions: List<DistortionType> # 本轮识别出的认知扭曲 (如 PERSONALIZATION)
    detected_schemas: List<SchemaType>  # 本轮内省器识别出的早期图式 (最大 3 项)
    deep_yearning: SatirYearning        # 5 大萨提亚底层核心渴望之一 (SAFETY 等)
    somatic_stabilization_eligible: Boolean # 当 Arousal >= 0.80 时激活自下而上稳定化白名单
```

### 2.4 临床干预动作骨架模型 (`ActionSkeleton`)
```
Type ActionSkeleton:
    method_id: MethodKey                # 方法唯一枚举标识，沿用 taxonomy 形式 (方法如 "01"，子动作如 "12:tipp_breathing")
    safety_grade: SafetyGrade           # GRADE_A (自主微练习) | GRADE_B (科普重塑) | GRADE_C (专业转介)
    clinical_rationale: String          # 选定该方法的机制依据
    core_action_steps: List<String>     # 规范化的 2-3 个核心微动作步骤
    duration_minutes: Integer           # 预估耗时 (2-5 分钟)
    stealth_workplace_compatible: Boolean # 是否支持工位无痕隐形执行
    contraindications: List<String>     # 禁忌症清单 (如: 心脏病、神经性厌食症心动过缓禁做冷水浸没)
```

### 2.5 属地化与全球危机援助资源卡片模型 (`ResourceCard`)
```
Type ResourceCard:
    region_used: String                 # 本次卡片生效的地区代码（"CN"、"HK"、"US"、"ZZ" 等，按国家/地区解析）
    level: CrisisLevel                  # 卡片对应的危机等级（CRISIS 模式只接受 L2 / L3）
    mode: CardMode                      # CRISIS（危机卡）| BROWSING（olivia resources 浏览，按类别分组）
    emergency: List<EmergencyNumber>    # 急救与报警号码（L3 必含，排在热线之前）
    lines: List<HotlineEntry>           # 热线、短信线与求助目录（按数据文件中的优先顺序）
    stale_entries: List<String>         # 核验日期超过 180 天的已显示条目 id，界面提示“可能已过期”
    compiled_on: Date                   # 资源库整理日期
    directory_version: Integer          # 资源库版本号
    # 签名在加载时校验（GEO-08，`resources/bundle.py`），未通过签名的数据不会进入卡片。
```

---

## 3. 子系统 I：M.I.Y.I. 认知感知与透明记忆引擎 (M.I.Y.I. Perception & Memory Engine)

### 3.1 中文上下文多任务心理感知网络与 8 头联合损失函数
感知网络采用双向子词/卷积特征编码，重点针对中文否定前缀进行句法注意力加权（准确区分“我不想活了”与“我不想死了”）。在共享表征 $\mathbf{h} \in \mathbb{R}^{128}$ 之上并发优化 8 头联合损失函数：

$$\mathcal{L}_{total}(\Theta) = \sum_{k=1}^8 \lambda_k \mathcal{L}_k(\Theta)$$

1. **连续极性损失 $\mathcal{L}_{val}$**：均方误差损失 (MSE)，预测情感效价 $[-1.0, 1.0]$；
2. **细粒度情绪损失 $\mathcal{L}_{emo}$**：交叉熵损失 (Cross-Entropy)，16 分类核心情绪；
3. **归一化唤醒度损失 $\mathcal{L}_{aro}$**：均方误差损失 (MSE)，目标区间 $[0.0, 1.0]$；
4. **共情策略意图损失 $\mathcal{L}_{intent}$**：交叉熵损失，识别助人策略意向；
5. **四级危机风险等级损失 $\mathcal{L}_{risk}$**：带类别惩罚的多分类交叉熵 (L0, L1, L2, L3)；
6. **危机置信度损失 $\mathcal{L}_{crisis}$**：带正样本重惩罚项 ($\gamma_{pos} = 15.0$) 的加权二元交叉熵 (BCE)；
7. **萨提亚沟通姿态损失 $\mathcal{L}_{stance}$**：交叉熵损失，5 分类应对姿态；
8. **改变准备度损失 $\mathcal{L}_{readiness}$**：均方误差损失 (MSE)，评估动机就绪度 $[0.0, 1.0]$。

通过 GradNorm 动态平衡多任务梯度震荡，确保端侧前向推断时延满足 $P_{99} \le 45\text{ms}$。

### 3.2 萨提亚冰山内省器与会话内核心信念判定准则
内省器将用户输入按 6 层冰山模型解耦，提取 5 大核心渴望（`SAFETY`、`ACCEPTANCE`、`AUTONOMY`、`COMPETENCE`、`CONNECTION`）。维护 20 类早期图式的模式识别规则。
- **CoreBeliefIdentified 会话内判定准则**：
  为恪守数据最小化与个人隐私保护原则，**系统严禁在未经授权的情况下跨历史会话深挖或拼接用户敏感图式标签**。核心信念的判定严格限制在**本次会话实时上下文**内：
  1. 用户在阶段二对话中显式认同了某种深层信念或图式模式（例如用户输入：“确实，我总觉得只有必须做到完美才配被爱”）；**或者**
  2. 在本次会话内部，内省器连续 2 轮对同一图式输出高置信度匹配（置信度 $> 0.70$），且与当前的萨提亚深层渴望形成拓扑印证。
- **高唤醒抑制**：当唤醒度 $Arousal \ge 0.80$ 时，内省器自动挂起深层图式分析，防止过深的反思加剧用户前额叶认知负荷。

### 3.3 3D 艾宾浩斯记忆检索与本地静态加密协议
检索历史记忆时执行三维加权函数：

$$\text{RelevanceScore}(e_i, \mathbf{c}_{curr}) = w_{rec} \cdot \exp\left(-\alpha \frac{t_{curr} - t_{e_i}}{\tau}\right) + w_{sim} \cdot \cos(\mathbf{v}_{e_i}, \mathbf{v}_{curr}) + w_{sal} \cdot \mathcal{S}_{sal}(e_i)$$

其中 $\tau = 7 \text{ 天}$。持久化层支持 AES-256-GCM 本地加密存储；当用户触发“一键遗忘”时，安全协议首先销毁本地派生的 AES-256 密钥槽（加密擦除 Crypto-Shredding，使得所有密文即刻在数学上不可逆解密），并同步物理清除/覆盖临时未加密缓存、影子文件、历史快照及历史周记，实现彻底不可逆的数据被遗忘权。

**实现（B4）**：`olivia/core/memory/retrieval.py`。按上式加权求和：$w_{rec} = 0.4$、$w_{sim} = 0.4$、$w_{sal} = 0.2$、$\alpha = 1$（裁定 29），$\tau = 7$ 天，年龄按天计（可带小数，未来时间按 0 计）；$\mathcal{S}_{sal}$ 对显著条目为 1、否则为 0。显著条目（当轮 ≥ L2 或用户标记；笔记总是显著）永久保护（Q-7）：时间项恒为 1，不随时间衰减。$\cos$ 是字符 2–3 元组 TF-IDF 余弦（NFKC 规范化并统一大小写，只在连续的文字字符内取元组；词频取原始计数，IDF 为 $\ln\frac{1+N}{1+df} + 1$），上式没有规定向量化方式，以上为实现选择。可检索的只有条目本身已有的内容：笔记是原文；会话摘要是正文所用的日常说法（阶段、困扰谱系、用户看到的练习卡标题与反馈、危机与显著两行），不含时间、日期与标题。同分时新者在前，再按条目 id，排序确定。默认取前 3 条（MIYI-04）。每次载入账本建一次索引（415 条约 11 ms），单次查询 P99 约 0.4 ms（预算 2 ms，`tests/memory/test_retrieval_performance.py`）。规则模式下没有使用方：MIYI-04 的使用场景是阶段二/三组装上下文，SOP 3 的“记忆缝合”属于 AI 增强部分（裁定 19、35，P7），所以暂不接入会话。

---

## 4. 子系统 II：C.O.L.B.O. 符号状态机与临床协议编排器 (C.O.L.B.O. Symbolic Core & FSM)

### 4.1 语境感知代词镜像重述算法与第三人称冲突消解
传统机械镜像将“我觉得你根本不在乎我”翻转为“你觉得我根本不在乎你”，在人际叙述中会产生“AI承认不在乎用户”的荒谬冲突。
改进算法：
1. **主从从句语法分析**：仅在第一人称主从句（如“我觉得我很失败”）中执行代词翻转；
2. **语境安全模板插槽**：当检测到句子指向外部第三人称（如“伴侣”、“领导”、“你”）时，优先采用人本主义复述模板：
   $$\text{"我觉得你根本不在乎我"} \to \text{"听起来在那段关系里，你深深感到对方没有真正在意你的感受……"}$$

### 4.2 七状态门控有限状态自动机代数模型 (含回退、越级与闭环出口)
$$M = (Q, \Sigma_{in}, \delta, q_0, F)$$
- 状态集 $Q = \{S_{ready}, S_{explore}, S_{clarify}, S_{empower}, S_{haven}, S_{closing}, S_{crisis}\}$；
- 初始状态 $q_0 = S_{ready}$（用户启动程序/首轮交互时跃迁入 $S_{explore}$ 或 $S_{haven}$）；
- 终止状态集 $F = \{S_{ready}\}$；

状态转移矩阵表 $\delta(q, \sigma)$：

| 当前状态 $q$ | 转移触发条件 $\sigma$ | 下一状态 $\delta(q, \sigma)$ | 动作与工程保障 |
| :--- | :--- | :---: | :--- |
| **任意非危机状态** | 危机检测复核判定为 L2 或 L3 级别 | **$S_{crisis}$** | **最高安全熔断**：瞬间中断正常流程，由 GEO 模块呈现属地化危机干预与急救卡片 |
| **任意非危机状态** | 两阶段危机复核通过 且 `social_battery` $\le 0.20$ 且 当前非 $S_{crisis}$ | **$S_{haven}$** | 冻结提问，输出极低字数沉静陪伴，仅做在场确认与安全守候（严禁危机逃逸） |
| **任意非危机状态** | 用户显式要求方法 (JTBD 4) | **$S_{empower}$** | 尊重用户自主掌控权，动态跳过理清阶段直达赋能推荐；候选仍经红线掩码与唤醒检查，`SILENT_ANCHOR` 人格同样适用；掩码后可用集合为空时给 $m_0$ + 转介卡 |
| **$S_{explore}$** | `stage_turn_count` $\ge 2$ 且 $Arousal < 0.80$ 且 无纯倾听锁 且 `social_battery` $\ge 0.40$ | **$S_{clarify}$** | 推进至理清阶段，探查图式与萨提亚深层渴望 |
| **$S_{clarify}$** | (`CoreBeliefIdentified` == True OR 用户要求 OR 当前阶段内轮次达5轮) 且 无纯倾听锁 且 非静默人格 且 `social_battery` $\ge 0.40$ | **$S_{empower}$** | 推进至循证赋能阶段，推荐 32 种 A 级微干预动作骨架 |
| **$S_{empower}$** | 用户唤醒度激增 ($\Delta Arousal \ge 0.25$ 或 $Arousal \ge 0.85$) 或 表达反感 | **$S_{explore}$** | **紧急安全回退**：撤回认知方法，激活稳定化通道在场承接 (生理叹息/感官着陆) |
| **$S_{empower}$** | 用户发出 `/unhelpful` 或明确说方法没帮助（“这个不适合我”）(`UNHELPFUL`) | **$S_{explore}$** | 记录 `UNHELPFUL`，按 §6.3 对该方法施加软衰减，回到倾听 |
| **$S_{empower}$** | 用户发出 `/done` (完成微练习) 或 `/not-now` (存入锦囊，`NOT_NOW`)，或用日常的话明确说出同样的意思（“做完了”“今天先不做了”） | **$S_{closing}$** | 进入结束仪式，建立 Gollwitzer 实施意向与温和道别 |
| **$S_{haven}$** | 用户心力恢复 (`social_battery` $\ge 0.35$) 或 发起新探索议题 | **$S_{explore}$** | 平滑退出避风港模式，恢复常规双向探索对话 |
| **$S_{closing}$** | 实施意向确认完成 或 会话自然关闭 | **$S_{ready}$** | **结束状态出口**：原子写入会话摘要与经历账本，就绪等待下一次会话 |
| **$S_{crisis}$** | 用户显式确认安全（`SafetyConfirmEvent`）且之后连续 N 轮处于安全区间 (L2: 2 轮, L3: 3 轮) | **$S_{explore}$** | **危机状态出口**：唯一合法出口，解除危机熔断，恢复温和陪伴，保留关怀标记 |

补充说明：
- **轮次**：`stage_turn_count` 与“5轮”都指当前阶段内的轮次，进入新阶段时重新计数。
- **ΔArousal 基线**：$\Delta Arousal$ 以进入当前阶段时的唤醒度为基线计算。
- **直接索要方法**：任何非危机状态均可触发（$S_{crisis}$ 中不响应）；候选动作仍经红线掩码与唤醒检查；`SILENT_ANCHOR` 人格也可由此进入 $S_{empower}$；掩码后可用集合为空时给 $m_0$（`EMOTIONAL_HOLDING_PRESENCE`）并附转介卡。
- **日常说法的反馈（路线图 R-7b）**：反馈不只来自斜杠命令。卡片等待反馈时，感知层把明确的日常说法读成对应命令（`TurnSignals.feedback`），会话按命令原路处理，效果与命令完全相同；含糊的回应（`feedback_unclear`）先问一次是否收进锦囊，下一轮的“好/可以”（`answer`）记为 `NOT_NOW`。对自己的贬低从不算 `UNHELPFUL`；斜杠命令优先；筛查为 L2/L3 的一轮从不读反馈。“锦囊里那个再给我看看”（`kit_recall`）按直接索要处理，重新递上锦囊里最近存入、且当前仍被求解器放行并有卡片的方法；锦囊跨会话保存（步骤 B3，见 §6.3），所以新会话里“上次存的那个”也能调回；锦囊为空时温和说明。$S_{closing}$ 中整句的“好/可以”等同实施意向确认，“不用了”得到一句温和回应并留在 $S_{closing}$。

### 4.3 32 种 A 级微干预编排、禁忌症硬掩码与只陪伴基线 ($m_0$)
进入 $S_{empower}$ 后，系统求解最优微干预：
1. **硬掩码过滤与 13 种统一禁忌症枚举**：
   排除黑名单方法，并严格根据 `ActionSkeleton.contraindications` 与实时检测到的禁忌状态进行位掩码与运算（Bitwise AND）。系统收敛定义 13 种标准禁忌症枚举体系：
   - `CRISIS_ACTIVE_RISK`（急性危机风险，源自 `CRISIS_DETECTOR`）
   - `RED_FLAG_PSYCHOSIS`（精神病性症状，源自 `RED_FLAG_DETECTOR / USER_PROFILE`）
   - `RED_FLAG_MANIA`（双相躁狂期，源自 `SIT-02-04 / USER_PROFILE`）
   - `RED_FLAG_PTSD_FLASHBACK`（创伤急性闪回，源自 `SIT-06-01 / USER_PROFILE`）
   - `RED_FLAG_DISSOCIATION`（急性严重解离，源自 `SIT-06-05 / Arousal`）
   - `RED_FLAG_ANOREXIA`（神经性厌食，源自 `SIT-08-04 / USER_PROFILE`，禁冷水 TIPP）
   - `RED_FLAG_BPD_NSSI`（边缘情绪伴自伤冲动，源自 `SIT-09-01 / USER_PROFILE`，禁冷水）
   - `RED_FLAG_SUBSTANCE_WITHDRAWAL`（物质急性戒断，源自 `SIT-10-04 / USER_PROFILE`）
   - `ACUTE_AROUSAL_OVERLOAD`（交感神经过载 $Arousal \ge 0.85$，阻断认知辨析）
   - `TOXIC_SHAME_SPIRAL`（毒性羞耻螺旋，源自 `DEFECTIVENESS` 图式，禁内观添麻烦第3问）
   - `ACUTE_BEREAVEMENT_SHOCK`（急性丧亲剧烈期，源自 `SIT-06-04`，遵从 $m_0$ 陪伴基线）
   - `CARDIORESPIRATORY_INSTABILITY`（严重心血管/呼吸不稳，源自用户病史，禁剧烈屏气/冷水）
   - `INTERPERSONAL_SAFETY_HAZARD`（活动性家暴/人身威胁，源自 `CRISIS_DETECTOR`）
2. **S_explore 稳定化微干预 ID 白名单 (`explore_stabilization_whitelist`)**：
   当用户处于 $S_{explore}$ 探索阶段且 $Arousal \ge 0.80$ 时，COLBO-02 原则上禁止推荐认知方法，但破例放行自下而上稳定化白名单方法：
   `["28", "29", "30:grounding", "12:tipp_breathing"]`（生理性叹息、渐进式肌肉放松、5-4-3-2-1 感官着陆、DBT TIPP 节奏呼吸）。
   $Arousal \ge 0.85$ 时，方法 28 因自身禁忌 `ACUTE_AROUSAL_OVERLOAD` 被排除，仍放行 `29`、`30:grounding` 与 `12:tipp_breathing`。
3. **显式只陪伴基线 ($m_0$ = `EMOTIONAL_HOLDING_PRESENCE`)**：$m_0$ 不参与 Thompson 采样，由固定规则选用：可用集合为空、处于避风港模式，或识别为延长哀伤（`SIT-06-04`）、极度虚无（`SIT-11-01`）时直接选用，此时享有最高优先级，避免盲目推送行动方案。
4. **谱系映射与 Thompson 采样维度键**：
   困扰 11 大谱系（两位数字 `"01"` 至 `"11"`）与 11 种英文大写枚举（`ANXIETY_PANIC` 至 `EXISTENTIAL_MEANING`）通过 `distress_category_mapping` 保持 1:1 双向映射。Thompson 采样模型使用两位数字字符串 `"01"` 至 `"11"` 作为困扰维度 $d$ 的标准索引键。
5. **子动作登记表 (Action Registry) 与禁用标签展开**：
   系统建立全局 `action_registry`，显式登记所有跨方法拆解的子动作与红线专用动作（如 `12:tipp_breathing`, `12:tipp_cold_water`, `30:grounding`, `SAFE_PLACE_CONTAINER` 等），每项均具名规范其步骤、时长与适用情境；同时通过 `banned_tag_mappings` 将抽象禁用标签（如 `RADICAL_COGNITIVE_DEBATE`, `DEEP_SCHEMA_EXCAVATION`, `HIGH_COGNITIVE_LOAD` 等）展开为具体的方法 ID 列表，使状态机掩码与骨架装配能够确定性完成集合运算。
6. **子动作与父方法继承规则 (Sub-action & Parent Method Inheritance Rules)**：
   - **父级禁忌独立性原则 (Parent Contraindication Isolation)**：父方法的 `contraindications` 仅作用于父方法自身的 `core_action_steps`（即以父方法整体形式输出时），子动作严格依据自身在 `action_registry` 中声明的 `contraindications` 进行独立过滤与阻断。例如方法 12 DBT 的父级禁忌不含心脏病/呼吸不稳与厌食症，该类禁忌已下沉归属于子动作 `12:tipp_cold_water`；有心血管病史或厌食史的用户仍可正常使用 STOP 技巧与 `12:tipp_breathing`（节奏呼吸）。
   - **父级禁用向下穿透与显式白名单豁免 (Parent Ban Penetration with Explicit Whitelist Exemption)**：当红线规则或临床黑名单禁用父方法 ID（如禁用 `"12"`）时，其下属所有子动作默认一并级联禁用；唯一的例外是：若红线病种的 `allowed_actions` 白名单中显式指定了该子动作（如 BPD 红线显式允许 `DBT_TIPP_MODIFIED_BREATHING` / `12:tipp_breathing`），则该子动作破例获得豁免放行。
7. **动作候选池求解公理与名单优先级公式 (Resolution Priority Formula)**：
   系统在任何状态（无论是 $S_{explore}$ 还是 $S_{empower}$）求解可用动作集合时，遵循如下确定性集合运算公式：
   $$\mathcal{A}_{available} = (\mathcal{C}_{candidates} \cap \mathcal{A}_{allowed}) \setminus \mathcal{B}_{banned} \setminus \mathcal{X}_{contraindicated}$$
   其中：
   - $\mathcal{C}_{candidates}$：当前状态的准入动作集合（例如在 $S_{explore}$ 高唤醒时为 `explore_stabilization_whitelist`，在 $S_{empower}$ 时为 32 种 A 级动作候选池）；
   - $\mathcal{A}_{allowed}$：**红线封闭集公理 (Red Flag Closure Axiom)**。若用户触发了临床红线（如双相情感障碍 `SIT-02-04`），$\mathcal{A}_{allowed} = \text{RedFlag.allowed\_actions}$，构成用户实际可用交互的**绝对封闭上限边界**。例如双相用户的 $\mathcal{A}_{allowed}$ 仅为 `[CIRCADIAN_RHYTHM_STABILIZATION, ENVIRONMENT_STIMULUS_REDUCTION, REFERRAL_CARD_PRESENTATION]`，此时即使在 $S_{explore}$ 高唤醒状态，白名单中的 `["28", "29", "30:grounding", "12:tipp_breathing"]` 因交集为空而被完全阻断，绝不违规推送；若用户未触发任何临床红线，$\mathcal{A}_{allowed} = \Omega$（全集）；
   - $\mathcal{B}_{banned}$：红线或临床规则禁用的方法及标签展开集（通过 `banned_tag_mappings` 展开至具体方法 ID），作为第二道纵深防御；
   - $\mathcal{X}_{contraindicated}$：当前命中用户禁忌症（如病史、急性生理指标）的方法与子动作集合。
   - **别名标准归约前置原则 (Alias Canonicalization Pre-processing)**：参与集合运算前，所有动作标识符（包括来自 `allowed_actions`、`banned_methods`、`explore_stabilization_whitelist` 及候选池的 ID 或别名）必须先经 `action_registry` 的别名映射表统一规约为标准 ID。例如 `DBT_TIPP_MODIFIED_BREATHING` 规约为 `12:tipp_breathing`，`GROUNDING_54321` 规约为 `30:grounding`，确保交差集运算准确匹配，杜绝因别名不一致导致假空集。
   - **空集保底降级与转介联动 (Empty Set Fallback & Referral Binding)**：若四重交差集求解结果为空集（$\mathcal{A}_{available} = \emptyset$），系统确定性降级为 `EMOTIONAL_HOLDING_PRESENCE`（纯在场陪伴基线 $m_0$）；若当前命中临床红线，则并行追加呈现 `REFERRAL_CARD_PRESENTATION`（国家精神心理专科就诊指引卡）。系统严禁抛出异常，也严禁盲目回退到未经验证的其它常规方法。
   - **动作类型多通道分发协议 (Action Type Multi-Channel Dispatch Protocol)**：当输出为 32 种 A 级父方法整方法骨架时，默认按 `MICRO_EXERCISE`（认知/行为微练习）装配执行；登记于 `action_registry` 的子动作则严格依据声明的 `action_type` 分流装配，严禁将所有动作一律当作微练习指令下发：
     - `MICRO_EXERCISE`（A 级整方法默认）/ `STABILIZATION`：装配为微练习跟练骨架（带有动作时长与分步跟练提示）；
     - `COMPANIONSHIP`（如 `EMOTIONAL_HOLDING_PRESENCE` / $m_0$）：输出去自责、去说教的纯温和在场守护语料，不带任何练习要求；
     - `PSYCHOEDUCATION`（如 `CIRCADIAN_RHYTHM_STABILIZATION`、`WITHDRAWAL_RISK_WARNING`）：渲染为生活作息稳态贴士或戒断风险警示卡；
     - `REFERRAL`（如 `REFERRAL_CARD_PRESENTATION`）：移交危机与属地卡片模块渲染专科就诊指引与属地援助热线。

### 4.4 C.O.L.B.O. 双翼干预架构 (Bilateral Wing Architecture) 与 SUDS 标尺映射
C.O.L.B.O. 循证微干预体系在临床神经生物学层面划分为两大互补干预机理：
1. **左翼 (Left Wing / Somatic & Compassion)**：
   - **机理路径**：自下而上 (Bottom-up) 神经调节。通过呼吸节律、双侧刺激、感官外感受着陆与 Neff 自我关怀，直接作用于脑干与迷走神经复合体（Vagal Brake），降低交感神经激惹，重建本体生理安全感；
   - **激活条件**：$Arousal \ge 0.80$（对应临床 SUDS $\ge 8/10$）或情绪剧烈过载；在 $S_{explore}$ 状态下激活稳定化在场白名单通道。
2. **右翼 (Right Wing / Cognitive & Action)**：
   - **机理路径**：自上而下 (Top-down) 认知重构与行为激活。通过前额叶理性检验（CBT NAT/好友视角）、去灾难化、元认知解离与行为激活 (BA 2分钟微破冰)，打破思维反刍回路并建立现实行动支点；
   - **激活条件**：$Arousal < 0.80$ 且心力电量 $social\_battery \ge 0.40$，且状态机推进至 $S_{empower}$ 阶段。
3. **双翼协同 (Bilateral Synergy)**：
   - 当困扰档案标定为双翼协同（如 `SIT-01-01` GAD、`SIT-11-02` 人生危机）时，系统严格执行“先左后右”序贯原则：在高唤醒期先由左翼稳定化平抑交感过载，待生理指标平稳后无缝桥接右翼认知赋能。
4. **SUDS 0–10 标尺与系统归一化连续谱映射**：
   - 困扰档案采用临床通用的主观痛苦量表（SUDS, 0–10 整数标尺，如 `6-8/10`）；系统内部与算法统一采用 $[0.0, 1.0]$ 连续闭区间，二者满足严格线性双向映射：
     $$Arousal = \frac{\text{SUDS}}{10}$$
     例如档案中 `2-4/10` 映射 $[0.20, 0.40]$（低唤醒低动力），`6-8/10` 映射 $[0.60, 0.80]$（中高警觉内耗），`8-10/10` 映射 $[0.80, 1.00]$（急性交感神经过载）。

---

## 5. 子系统 III：W.I.L.L.O.W. 温润内省言语与词汇意境重塑引擎 (W.I.L.L.O.W. Language & Metaphor Engine)

### 5.1 去机械化语调塑形与违规说教词表过滤
语调重塑算子 $\mathcal{T}_{warm}: \mathcal{S} \to \mathcal{S}'$ 扫描并剔除违规说教词表 $\mathcal{V}_{didactic} = \{\text{"你应该"}, \text{"必须"}, \text{"首先"}, \text{"其次"}, \text{"再次"}, \text{"总而言之"}\}$，将祈使句重塑为人本主义邀请语态。

### 5.2 概念隐喻织造算法与萨提亚意境对齐
映射函数 $\Phi: \mathcal{D}_{distress} \times \mathcal{Y}_{yearning} \to \mathcal{M}_{nature}$：
- 完美主义内耗 $\to$ 柳枝随风低伏却永不折断；
- 思维反刍卡点 $\to$ 溪流绕石而不争；
- 耗竭倦怠 $\to$ 四季草木冬眠蓄力。

### 5.3 沉静呼吸节奏与黄金字数窗口阻尼模型
系统按不同助人状态与人格光谱实施分层字数窗口阻尼约束：
1. **常规双向交互阶段 ($S_{explore}, S_{clarify}, S_{empower}$)**：黄金字数区间 $[140, 260]$ 汉字。定义惩罚函数：
   $$\mathcal{P}_{cadence}(L) = \begin{cases} 
   \kappa_{under} \cdot (140 - L)^2, & L < 140 \\
   0, & 140 \le L \le 260 \\
   \kappa_{over} \cdot (L - 260)^2, & L > 260 
   \end{cases}$$
   严格限制单段 $\le 80$ 汉字，段间强制插入呼吸空行；
2. **避风港模式 ($S_{haven}$)**：字数窗口刚性约束在 $[15, 40]$ 汉字，冻结一切追问，彻底消除阅读与认知压迫感；
3. **静默树洞型人格 (`SILENT_ANCHOR`)**：字数窗口收缩至 $[10, 30]$ 汉字，仅提供极简情感回声与中立安全在场；
4. **危机状态 ($S_{crisis}$) 与 Grade C 医疗转介卡片**：**享有刚性字数豁免权**，确保紧急救援电话、心理援助热线、营业时间及转介指引无损完整呈现，绝不因字数上限截断生命防线信息。

*实现说明（计划 D-1，2026-10-23）*：每种人格一个模板文件（`olivia/data/templates/gentle_holding.yaml`、`zen_philosopher.yaml`、`rational_peer.yaml`、`silent_anchor.yaml`，映射见 `language/data.py` 的 `PERSONA_TEMPLATE_FILES`），各自在 `window` 中声明字数窗口；`load_language_data` 启动时载入并校验全部四份，`LanguageData.for_persona(persona)` 选出会话用的一份（`Session` 按 `PersonaProfile.persona_spectrum` 选择）。`LanguageEngine.window_penalty` 读当前人格的窗口：$S_{haven}$ 用 `window.haven`，$S_{empower}$ 用 `window.empower`（缺省同常规窗口，且不计卡片正文），其余常规阶段用 `window.normal`。`GENTLE_HOLDING`、`ZEN_PHILOSOPHER`、`RATIONAL_PEER` 为常规 $[140, 260]$、单段 $\le 80$、避风港 $[15, 40]$，三段式结构相同；`SILENT_ANCHOR` 的 $S_{explore}$、$S_{clarify}$ 只有一段且不要求槽位，常规窗口 $[10, 30]$，避风港取交集 $[15, 30]$，$S_{empower}$ 因须写出三个反馈命令按 $[10, 70]$、单段 $\le 50$ 计（待 G-0 确认），其 $S_{clarify}$ 不追加 B 级视角卡。危机首句以外的求助电话行由 `render.yaml` 与 `ResourceCard` 生成，与人格无关；`followups.safety_check`（决定 D3）四份逐字一致，加载时校验。每份模板都有 `wellbeing`（B7）、`S_ready.returning_after_check`（A3）与 `followups.health_hint`（A1）；`SILENT_ANCHOR` 的这些句子都是陈述句，休息与深夜提示单段 $\le 30$ 字；它的回复只有一段、没有可替换的 invite，所以不做现实支持引导（`real_support` 不会出现），模型模式的图式镜像提问（决定 D4）也不对它出现。

---

## 6. 子系统 IV：C.H.A.N.G. 人机协同演化与叙事成长引擎 (C.H.A.N.G. Co-evolving Adaptation Engine)

### 6.1 首访角色契约领域模型与四维人格光谱配置规范
预置四大基准人格光谱：
- **`GENTLE_HOLDING` (温和包裹型)**：温暖柔和、多情感抚慰与包裹、高接纳词频；
- **`ZEN_PHILOSOPHER` (沉静哲思型)**：自然意境、开阔深远、低言语密度、高留白；
- **`RATIONAL_PEER` (平视战友型)**：平视坦诚、机敏条理、并肩拆解现实挑战；
- **`SILENT_ANCHOR` (静默树洞型)**：极简回声、零判断、纯倾听、无任何建议要求。

### 6.2 「结构先行，语态后润」双通道网关与本地校验器
当开启 AI 增强模式时：
1. 本地 `C.O.L.B.O.` 生成不可篡改的 `ActionSkeleton`；
2. 大模型接收结构化 Prompt 仅进行语态润色与生活记忆缝合；
3. **本地校验器 (Local Validator)** 审查大模型输出：
   - 检查动作步骤核心语义是否被篡改；
   - 检查是否引入未在 32 种 A 级白名单中的方法；
   - 检查是否包含病理化医学诊断词汇；
4. 若校验不通过，网关直接无缝退回本地离线受控模板，降级过程不增加额外等待延迟。

### 6.3 闭环贝叶斯自进化数学模型 (纯 Thompson 采样与探索安全门禁)
系统彻底采用标准 **Beta-Bernoulli Thompson 采样**进行个性化推荐自进化，完全废除与概率采样相冲突的固化 $\epsilon$-greedy 策略。
对每个（方法 $m$ $\times$ 困扰谱系 $d$）维护独立的后验分布：

$$\theta_{m, d} \sim \text{Beta}(\alpha_{m, d}, \beta_{m, d})$$

每次反馈只更新主导谱系 $d$ 的后验，即 `distress_vector` 中得分最高的一项所属的谱系。

- **临床证据等级先验映射**：
  - Level I（跨诊断黄金循证，如 CBT, ACT, MCT）: $\alpha_0 = 4.0, \ \beta_0 = 1.0$；
  - Level II（良好实证支持，如 BA, CFT, MSC）: $\alpha_0 = 3.0, \ \beta_0 = 1.0$；
  - Level III（临床探索性支持，如森田、内观）: $\alpha_0 = 2.0, \ \beta_0 = 1.0$；
- **三档用户反馈信号自适应更新**：
  - 用户反馈 `HELPFUL`（有帮助）：$\alpha_{m, d} \leftarrow \alpha_{m, d} + 1.0$；
  - 用户反馈 `NOT_NOW`（存入锦囊）：保持当前参数不变，零负向扣分；
  - 用户反馈 `UNHELPFUL`（不适用/排斥）：$\beta_{m, d} \leftarrow \beta_{m, d} + 1.0$；采用软性时间衰减降权函数：
    $$\beta_{eff} = 1.0 + (\beta_{m, d} - 1.0) \cdot \exp\left(-\lambda_{decay} \Delta t\right)$$
    其中 $\lambda_{decay} = 0.1$/天（`taxonomy.yaml` 的 `thompson_sampling_index.lambda_decay_per_day`），$\Delta t$ 以天计；随时间推移自动衰减恢复探索概率，并在透明档案中供用户查阅与一键解除；
- **探索安全门禁 (Exploration Safety Gating)**：
  - 仅在用户生理唤醒度 $Arousal \le 0.60$ 且候选池严格处于 32 种 Grade A 方法时，允许利用后验方差进行探索性采样；
  - 当 $Arousal > 0.60$ 时，采样方差强制归零，系统强制退化为最高确定性均值策略（Exploit Only）或自下而上躯体稳定化协议。
- **跨会话持久化（步骤 B3，`olivia/core/memory/state.py`）**：后验与锦囊在会话之间保存，下次会话的推荐沿用之前的反馈。存储只含两样：`ThompsonSampler.to_dict()`（即 `Session.snapshot()["bandit"]`：谱系编号、动作编号、$\alpha$、$\beta$ 与最近一次 `UNHELPFUL` 的时间）和锦囊（动作编号与存入时间，旧到新，最多 10 条，保留最新的），不含任何用户原文。文件为数据目录下的 `state.bin`，内容是带版本号的 JSON（`{"olivia_state": 1, "bandit": ..., "kit": [{"id", "at"}]}`），**不论 ONB-06 开关如何始终加密**（存储名 `state`），原子写入、不留快照。命令行在会话开始时读取，在每一轮改变了后验或锦囊之后以及每个退出路径（`/exit`、输入结束、Ctrl-C）保存，内容没变就不写。文件打不开或解析失败（篡改、截断、密钥已擦除）时静默从头开始，下次保存时覆盖；更高版本写入的文件忽略且不覆盖；钥匙串暂时锁定时同样不覆盖；没有钥匙串时什么都不写，也不额外提示（B2 已告知记忆不可用）。分类标准里已不存在的动作或谱系的后验在载入时逐条丢弃。会话内语义不变：本次会话存入锦囊的方法在本次会话内不再被采样；从之前会话带来的锦囊条目不屏蔽采样，但被禁忌症或求解器排除、或没有卡片的条目在调回时跳过；锦囊里的方法再次出现（调回或被采样到）即离开锦囊，`/not-now` 再放回并记新的时间。`StateStore.shred()` 供 B5 的 `olivia forget` 使用。

### 6.4 7 天情绪周记时空数据聚合算法 (基于用户自评数据)
满 7 天且会话活跃时，周记聚合器提取：
1. 用户会话前后 0–10 分困扰自评均值与心力电量走势；
2. 本周高频困扰外化命名；
3. 产生积极反馈的 A 级微方法复盘；
4. 若当周触发过 L2/L3 危机，周记自动转为庄重守护口吻，严禁轻浮轻淡散文。

**实现（步骤 B6，裁定 30）**：`olivia/core/chang/journal.py`，文案 `olivia/data/templates/journal.yaml`（G-0 草稿）。

*自评*：`olivia chat` 开场（提示语之后）问一句「此刻的心情，0 到 10 你会打几分？（0 是很糟，10 是很好；直接回车跳过）」，会话结束时问同一句：`/exit` 时（当前段有过对话才问），以及状态机 S_closing → S_ready 那一轮的回复之后。只认 0–10 的整数（全角数字也算），其他一律当作跳过、不再追问；不是回答的非空文字（例如直接开始说话，或在结束时又想说一句）不会丢掉，而是作为下一句对话交给会话，危机筛查照常看到它。自评只写进账本会话摘要的 `self_rating.before` / `after`，没有别的存储：开场分数记在本次会话的第一段；`/exit` 的分数记在当前段；S_closing → S_ready 时摘要已先写入，分数到手后用同一条目 id 原地重写。以下情况不问：没有可用钥匙串（或此刻打不开）；本次开场是 A3 的关怀问候（问候保持第一句、单独出现，不问开场分数、不提周记；结束时照常可问）；会话中任何一轮进入过危机流程、筛查到 L2 及以上或问过意图确认（D3）之后不问结束分数；处于 S_haven 或电量不高于避风港阈值时不问（“避风港中不问”）；输入结束与 Ctrl-C 不问。

*周记*：只读账本，不产生新的用户文字。窗口为滚动 7 天（`now − 7 天` 起），内容：会话段数；各段“开始 → 结束”心情分（缺的写“没打”）与其中聊完后分数升高的次数；最常出现的困扰谱系（最多 3 个，按出现的会话数，用 `memory.yaml` 的日常说法）；试过的小练习（卡片标题）与各自的反馈；用户要求记住的话只给条数（原话留在账本里，SOP 5 未规定，按计划取条数）。窗口内有会话进入过危机流程时，开头与结尾换成庄重守护口吻，并指向 `olivia resources`。除自评分与次数外不出现数字，文案经 WILLOW 与输出网关检查，不含诊断词。SOP 5 的“复原力金句”需要对话原文，与决定 D1 冲突，不做。

*何时*：开场分数之后，当窗口内会话摘要 ≥ 2 条、且窗口内没有任何周记记录（看过或婉拒都算）时，问「这周的小结写好了，想看看吗？」：回答“好/想看”等即展示，随后问「这份小结对你有帮助吗？」（有 / 没有，可跳过，对应 PRD §11.1 的周记满意度）；回答“不用”或直接回车即婉拒，并告诉用户 `olivia journal` 随时可看。婉拒同样算一次，7 天内不再提（PRD Q-3“杜绝压迫感”）。`olivia journal` 随时展示同一份周记（窗口内没有会话时温和说明），并问同样的满意度问题。没有钥匙串时不提、不展示。SOP 5 的“周日 20:30”定时提醒属系统通知，留给 B9。

*记录*：每次提出周记都写一条账本条目 `kind: journal`（`olivia_ledger: 1`，字段 `offered_at`、`shown`、`helpful`，正文是“某天的一周小结 / 看了或没看 / 有没有帮助”），先在展示时写入，得到满意度后用同一 id 重写；和其他条目一样始终加密，`Ledger.shred()` 一并擦除。选账本而不是 B3 的 `state.bin`：只是在账本里多一种条目（约 40 行），对用户透明（B5 的 `olivia memory` 列账本时能看到；B4/B5 遍历条目时需认得 `JournalEntry`），而改 `state.bin` 要升版本号并让会话把它原样带过去，否则聊天退出时的保存会把它覆盖掉。旧版本读到 `journal` 条目时按“未知条目”跳过计数，不报内容。`--inspect` 不变：这些都不是轮次级数据。

### 6.5 记忆档案原子级写入安全协议
遵循影子替换协议：
$$\text{MemoryLedger} \to \text{ledger.tmp} \to \text{Flush \& Sync} \to \text{Atomic Rename} \to \text{Persistent Ledger}$$
并保留最近 3 个版本的容灾备份快照，确保数据 100% 具备容错自愈能力。

**实现（B2，决定 D1）**：`olivia/core/memory/`（`ledger.py`、`notes.py`、`recorder.py`、`text.py`；文案 `olivia/data/templates/memory.yaml`，“记住”线索 `olivia/data/lexicons/memory.yaml`）。

*只记两类条目*（B6 另加一种不含文字的 `journal` 记录，见 §6.4），其余用户说的话一概不存：

| 条目 | 内容 | 何时写 |
| :--- | :--- | :--- |
| 会话摘要 `summary` | 首末轮时间；阶段路径（相邻重复合并，如 `S_ready → S_explore → S_empower → S_closing`）；主要困扰谱系 id（最多 3 个，按出现次数）；展示过的练习卡 id 与各自反馈（`HELPFUL` / `NOT_NOW` / `UNHELPFUL` / 无）；是否进入危机流程（只记标志与等级）；会话前后 0–10 自评（B6，见 §6.4）；显著标记（裁定 29：当轮 ≥ L2 或用户标记）与 `marked_by_user` | 会话结束时：状态机 S_closing → S_ready（之后若继续聊，算新的一段、另记一条），或 `/exit`、输入结束、Ctrl-C。按“会话 id + 段号”定条目 id，重复关闭不会多出条目；没有任何一轮的段不写 |
| 笔记 `note` | 用户明确要求记住的话：消息**开头**是「记住：」「帮我记一下」「请记得」等线索时，线索之后的文字原样保存（≤ 500 字），回复末尾简短确认、不复述内容 | 当轮。当轮在危机流程中、筛查 ≥ L1、或是意图确认（D3）时一律不记，也不确认——危机处理优先，显著标记已足够；“我记住了他说的话”这类不在开头或不带分隔符的说法不是请求 |

*格式*：每个条目是一份带 YAML 头的 Markdown。头部是记录本身；正文是由头部生成的简短中文小结（阶段、谱系与反馈都用日常说法，不用病名），笔记的正文就是笔记原文：

```
---
olivia_ledger: 1
id: 3f9c0e5d2b7a41c8a9e6d012
kind: summary
started_at: '2026-10-22T23:31:00+08:00'
ended_at: '2026-10-22T23:52:00+08:00'
stage_path: [S_ready, S_explore, S_empower, S_closing]
spectra: ['02', '05']
methods:
- {id: '12:tipp_breathing', feedback: HELPFUL}
crisis: {entered: false, level: null}
self_rating: {before: null, after: null}
significant: false
marked_by_user: false
---
## 2026-10-22 的一次聊天
- 时间：23:31 – 23:52
- 经过：开始 → 倾听 → 小练习 → 收尾
- 主要聊到：低落和没劲、累和耗尽
- 试过的小练习：……（有帮助）
```

*存储*：**始终加密**，与 ONB-06 开关无关。每个条目一个文件 `<数据目录>/ledger/<id>.olv`，用 `ledger` 数据密钥（§6.6）以 AES-256-GCM 封装，标签 `e_<id>`，所以改名或挪到别的 id 上就打不开。选“每条一个文件”而不是“整本一个密文”：追加只是一次小写入，不需要读出、解密、改写整本历史，崩溃或写坏只可能影响正在写的那一条；每次写入仍走 `storage.atomic_write_bytes`（临时文件 → fsync → 原子改名）。条目只写一次（同一会话段重写时原地替换），不存在可回退的旧明文，所以不做快照。读不开或解析不了的条目跳过并计数（`Ledger.skipped`），不报出内容。文件 0600、目录 0700。

*没有钥匙串*：账本停用，什么都不写；每台电脑在聊天开场温和告知一次（`ledger/.memory-unavailable-told` 标记，空文件，不含用户数据）；用户要求记住时，每次都回答“这句我先不记了”。钥匙串中途被锁导致小结没写进去时，告别前说一句。

*遗忘*：`Ledger.shred()` 先加密擦除 `ledger` 数据密钥（`Vault.shred`，随后轮换主密钥），再删除全部条目文件；`Ledger.forget_entry(id)` 加密擦除单条：其余条目先以暂存存储 `ledger_rekey` 重新封装到 `ledger/.rekey/` 并写提交标记 `complete`，再 `Vault.shred("ledger")`（主密钥随之轮换）、删除全部在用条目、用新的 `ledger` 密钥写回，最后删提交标记、擦除 `ledger_rekey` 并清空暂存区；提交标记之前中断则丢弃暂存、账本不变，之后中断则下一次读、写或遗忘从暂存副本补完（每一步都可重复），任何时刻幸存条目至少能被一把密钥打开。命令行入口 `olivia memory` / `olivia forget`（B5，`memory/forget.py`）。

### 6.6 本地静态加密：密钥层级与加密擦除 (B1)

实现：`olivia/core/crypto/`（`aead.py`、`keychain.py`、`vault.py`）与 `olivia/core/chang/profile.py`。决定 Q6（`cryptography` 的 AES-256-GCM）、Q7（主密钥存系统钥匙串，经 `keyring`）、裁定 28。

**密钥层级（信封加密）**

| 层级 | 位置 | 内容 |
| :--- | :--- | :--- |
| 主密钥（KEK） | 系统钥匙串，服务名 `olivia`，条目 `master-key`（轮换时临时有 `master-key-next`） | 256 位随机密钥 + 8 字节密钥编号；首次需要加密时才创建 |
| 数据密钥（DEK） | `<数据目录>/keys/<store>.key`，每个存储一个（`profile`、之后的 `ledger`、`kit`、`safety_plan`、`posteriors`） | 用主密钥以 AES-256-GCM 包裹；不做快照 |
| 数据 | 各存储自己的文件 | 用该存储的 DEK 以 AES-256-GCM 加密；随机 96 位 nonce；附加数据 = 格式魔数 + 版本 + 存储名 + 标签，换存储、换标签、换版本都打不开 |

**画像的三种文件形态**：未开开关且没有敏感字段时为明文 JSON（不需要钥匙串）；有 `clinical_history`（A1 起含 `contraindications`）时，这些字段移入 `sealed_fields` 密文，其余仍为明文；开关（ONB-06，默认关）打开时整份画像只剩 `sealed_profile` 密文。敏感字段在任何情况下都不以明文落盘，包括快照：每次保存后删除不符合当前保护级别的旧快照。旧版明文画像在读取时自动迁移并清除明文快照。

**加密擦除**：`Vault.shred(store)` 删除该存储的包裹密钥文件，并轮换主密钥（其余 DEK 重新包裹、旧主密钥从钥匙串删除），因此即使被删的密钥文件在磁盘上残留副本也无法解开；删最后一个存储时直接删除主密钥。`Vault.shred_all()`（“全部遗忘”）删除所有包裹密钥与主密钥。轮换可在任意一步中断：新主密钥先写入 `master-key-next`，下一个进程会补完。命令行入口为 `olivia forget`（B5，见 §11）：单个存储走 `Vault.shred`，`--all` 走 `Vault.shred_all` 后删除全部文件。

**钥匙串不可用**（如无后端的无头 Linux，或 `keyring` 只有不推荐的明文后端）：不保存任何敏感字段，首访跳过加密开关与健康信息两问，并温和告知“健康信息没办法在这台电脑上加密保存”；其他功能照常。钥匙串只是暂时打不开（锁定、拒绝访问）时，不改动任何文件，提示后退出，稍后可重试。

**威胁模型**

- 防：数据文件被复制、同步到网盘、被同机其他账户读取（文件 0600、目录 0700）；密文或密钥文件被篡改（GCM 认证失败即报错，绝不退回明文）；把一份存储的密文或密钥文件挪给另一份存储；擦除后从磁盘残留中恢复（需要已删除的主密钥）。
- 不防：以同一用户身份运行的恶意程序（它也能读钥匙串）；已解锁会话中的内存读取；能写数据目录的人删除或回滚文件（明文部分未做认证，`sealed_fields` 可被整体删掉）；SSD / 写时复制文件系统上已删除的旧明文块（迁移前写下的明文只能删除，不能保证物理覆盖）。
- 不记录日志；钥匙串条目名与错误信息只含固定标识符，从不含用户文字。不联网。
- 换电脑或重置钥匙串后，加密数据无法读取（与“删钥即擦除”是同一性质）；主密钥丢失而包裹密钥仍在时，系统不会悄悄生成新主密钥覆盖，避免钥匙串偶发读空造成数据永久丢失。

---

## 7. 多推理模型适配网关与个人信息保护管线 (Inference Gateway & PIPL Pipeline)

- **《个人信息保护法》(PIPL) 合规**：开启 AI 增强前必须单独弹窗征得明示同意；
- **本地小模型优先**：提供本地量化小模型选项，保障敏感数据不出设备；
- **服务商留存透明度**：使用云端服务时明确提示数据传输范围与服务商数据留存政策；
- **流式首字指标 (TTFT)**：推理网关监控首字流式输出时间，确保交互连贯性。

---

## 8. 多级安全防御体系、四级危机响应与能力绝对边界 (Multi-Tiered Safety & Crisis Protocols)

### 8.1 危机前置防御时序模型 (SAFE-09 强制合规)
```
用户输入文本 ──► [Stage 1: Aho-Corasick 明确自杀计划/工具/时限线索初筛 (< 0.2ms)] ──► 命中明确高危线索判 L3 熔断
                        │ (未命中明确线索，或含口癖/歧义词)
                        ▼
           [执行 M.I.Y.I. 中文上下文 8 头多任务感知前向推断]
                        │
                        ▼
           [Stage 2: 危机置信度与中文口癖复核 (< 1.0ms)] ──► 识别中文口癖与真正轻生意念
                        │
                        ├─► 判定为 L2/L3 危机 ──► 直接触发 S_crisis 熔断输出热线
                        │
                        ▼ (判定为 L0/L1 安全)
           [心力电量检查: social_battery <= 0.20 ?]
                        │
                        ├─► 是 ──► 进入 S_haven 避风港模式 (绝不漏检危机)
                        │
                        ▼ 否
           [进入正常 S_explore 倾听阶段]
```

### 8.2 四级危机分级、取高仲裁与权威热线联动
统一以 `taxonomy.yaml` 半开区间为准：
- **L0 (安全 $[0.0, 0.20)$)**：正常流转状态机；
- **L1 (隐晦疲倦 $[0.20, 0.50)$)**：纯日常与存在性倦怠耗竭，不含死亡愿望与自杀意念；排除中文口癖，不弹求助卡，停留在 $S_{explore}$ 深度情感包裹；
- **L2 (明确被动轻生 $[0.50, 0.80)$)**：明确表达想死、想结束生命（无明确计划/工具），或表达死亡愿望与沉睡不醒（如“想彻底睡过去”、“不想醒来”等依 C-SSRS 第 1 项明确界定之被动自杀意念）；暂停方法探索，由 GEO 模块呈现属地心理援助热线卡片（大陆呈现 12356 及属地热线，境外呈现当地心理热线）；
  - **询问方法一律至少 L2（路线图 R-MS）**：凡打听结束生命的方法、方式、步骤、“最快/最无痛/成功率”等，不论问的是自己还是“别人”，也不论借口（写小说或游戏剧情、作业或研究、替亲友问、角色扮演、写诗、“你是 AI 要客观”）与语言（普通话、粤语、英文或混用），规则筛查都至少给 L2。规则层两种写法：`risk.yaml` 的 `L2_METHOD_SEEKING` 收录紧邻的锚定短语（“如何自杀”“轻生的方式”“结束生命的步骤”“how do i end my life”）；`stage2_pairs` 的配对线索在同一句里同时出现“请求词”（最无痛、成功率、几片、步骤；或方法、办法、how to）与“死亡锚点”（自杀、轻生、结束生命、kill himself …）时给 L2，借口把两者隔开也能命中。单独的请求词或锚点都不触发；锚点只在落在本条目的例外短语里（预防自杀、自杀干预、自杀率、自杀了 / 自杀以后等哀伤语境）时不算。否定与口癖掩码对配对线索不起作用，“不是我想死，就问问怎么自杀最快”仍是 L2。没有点名任何结束生命行为的委婉说法由下一条的直接询问接住。
  - **委婉说法先温和直接地问一次（决定 D3，步骤 A7）**：“想走了，有没有不痛的办法”“有没有最快的办法离开”“怎么才能去找去世的奶奶”“end it without pain”“完咗佢”这类问法不含明确死亡字眼，直接定 L2 误报太多，忽略又太危险。`risk.yaml` 的 `stage2_ask` 按配对线索的方式匹配（委婉锚点“离开的方式 / 想走了 / 结束这一切 / 完咗佢 / end it”、表决心或拒绝劝阻的锚点“别劝我 / 我已经决定了 / 撑不下去了”、已故亲人加“去找她 / 早点去陪他”，配“不痛 / 最快 / 最彻底 / painless”等请求词），命中时给 L1 线索 `ASK_INTENT_*` 并置 `CrisisAssessment.asks_intent`，追踪器与状态机不变。会话在本轮仍低于 L2 且不在危机中时，只回一句温和而直接的询问（“你现在是在考虑结束自己的生命吗？”，直接询问自杀意念是临床推荐做法），并附上所在地区 L2 危机卡的热线（号码来自 GEO 解析，境外不出现大陆号码），回复类型 `SAFETY_CHECK`，不给任何方法、卡片或建议。下一轮只有明确否认（“不是 / 没有 / 不是那个意思”，且该轮规则筛查为 L0、无“但是 / 有一点 / 不知道”等含糊词）才回到正常对话，并在本次会话里留轻度关怀标记（跨会话保存见 A3/B3）；回答“是”、含糊、不回答或出现新的危机线索，一律按 L2 进入危机流程。本轮自身已筛到 L2/L3 时直接进危机，询问从不延误真实危机。`--inspect` 只显示 `safety_check: asked / affirmed / denied / unclear`，不显示原文。
- **L3 (急性自杀危机 $[0.80, 1.00]$)**：最高安全熔断，强制呈现属地心理热线与属地紧急急救/治安电话 (大陆 110/120，北美 911，英国 999 等)；
- **双头预测最高安全仲裁规则**：
  $$\text{RiskLevel} = \max(L_{cls}, L_{score})$$
  若初步定级为 L3 但缺乏明确计划、工具或时限证据 (`HasPlanMeansOrImminentThreat == False`)，安全降级为高危 L2 处理，防止误报 110/911。
  计划证据默认只来自 Stage 1 线索。`SafetyScreen(..., model_plan_evidence=False)` 是唯一开关：只有设为 `True` 时，注入的感知模型才可提供计划证据；该开关出厂关闭，待独立评估集通过后再打开。
- **危机状态机安全出口闭环准则**：
  处于 $S_{crisis}$ 状态时，严禁因用户单轮低电量输入（如 `[5%] 好累`）直接绕过安全确认跳转至 $S_{haven}$。退出危机态的唯一合法路径为**双重确认安全机制**：
  1. 用户明确确认安全（`SafetyConfirmEvent`，如明确表达“我已经联系上朋友了”、“我现在安全了，想聊点别的”）；**并且**
  2. 确认之后连续 $N$ 轮会话输入经两阶段危机筛查均为安全轮（依初始危机等级：L2 需连续 2 轮安全，L3 需连续 3 轮安全）。确认之后只有 L0 轮计为安全轮；L1 轮暂停计数（既不计入，也不清零）；L2/L3 轮清零，并需要用户重新确认安全。
  在满足上述双重条件前，系统严格维持在 $S_{crisis}$ 守护态，优先承接人身安全支持。危机态中每轮回复都重复呈现危机卡的精简版；跨会话的“关怀标记”存入用户画像，供下次会话启动时做轻度安全问候。

### 8.3 属地化与全球危机援助资源解析流水线 (GEO-01 ~ GEO-08)
- **国家级基准线**：全国统一心理援助热线 `12356`（国家卫生健康委统一热线，每日不少于 18 小时，各地时段不同，部分地区夜间不接听，L3 同时给 110/120）；12355 青少年服务台仅在 `is_minor` 为真（ONB-05 婉拒路径）时呈现；
- **按国家/地区解析**：`UserRegion.country_code` 属于数据中的地区则取该地区，`None`、`ZZ` 或不支持的代码（如 `UK`，英国应为 `GB`）一律回退 `ZZ`。大陆 12356 按来电地自动转接，无需城市/省级路由或行政区划索引（2026-10-22 官方核验，各省原热线均已并入 12356）；
- **卡片组装**：CRISIS 模式下，L2 卡片取该地区 `levels` 含 L2 的热线（仅当该地区没有 L2 热线时才附急救号码）；L3 卡片先列全部急救号码，再列 `levels` 含 L3 的热线；同组内按数据文件顺序（即优先级）。BROWSING 模式（`olivia resources`）呈现该地区全部条目，热线按类型分组。任一呈现条目 `verified_on` 距今超过 180 天时记入 `stale_entries`，界面标注“可能已过期”。L0/L1 不生成危机卡；
- **Rule R8 境外隔离与属地矩阵**：非大陆用户的卡片绝不出现任何大陆条目（12356、120、12355 及大陆的 110 条目）；澳门、台湾的 110 是当地号码，属于该地区条目，按地区而非号码数字校验。香港（`18111` / `2389 2222` / `2382 0000`，急救 `999`）、澳门（`2852 5222`，急救 `999` / `110` / `112`）、台湾（`1925` / `1995`，L2 另有 `1980`，急救 `110` / `119`）、美国（`988` 电话/短信、L2 另有 `741741`，急救 `911`）、加拿大（`988` 电话/短信、L2 另有 Kids Help Phone `686868`，不呈现 `741741`，急救 `911`）、英国 GB（`116 123` / `111`，L2 另有 Shout `85258`，急救 `999`）、澳洲（`13 11 14`，L2 另有短信 `0477 13 11 14` 与 Beyond Blue `1300 22 4636`，急救 `000`）、未知地区 ZZ（findahelpline.com / befrienders.org，急救 `112`）；
- **Ed25519 签名验真防篡改**：热线数据统一维护在 `olivia/data/resources/hotlines/` 树状目录中，由发布工具生成 Ed25519 签名包 `hotlines.bundle`，客户端利用公钥核签验证，无有效签名拒绝加载。
  - *GEO-08 实现说明（P2）*：当前采用分离式签名，而非打包的 `hotlines.bundle`。数据文件为 `olivia/data/resources/hotlines.yaml`，签名文件 `hotlines.yaml.sig` 存放对该文件**原始字节**的 Ed25519 签名（base64）；公钥（32 字节原始公钥的 base64）提交在 `olivia/core/resources/keys.py` 的 `HOTLINE_PUBLIC_KEY_B64`。私钥只保存在发布机仓库之外的 `~/.config/olivia/signing/hotlines.ed25519.signing.key`（PEM，文件 0600、目录 0700），从不打印、不入库（`.gitignore` 另有 `*.signing.key` 兜底）；每次修改数据后须运行 `python scripts/sign_hotlines.py` 重新签名，换钥用 `--rotate` 并同步更新 `keys.py`。`olivia/core/resources/bundle.py` 加载时：用户数据目录中的覆盖包仅在签名有效且 `compiled_on` 晚于内置数据（且不晚于当天）时启用，否则退回内置数据并给出原因供 `--inspect` 显示；内置数据签名校验失败则抛出 `BundleIntegrityError`，不显示未验真号码。`.gitattributes` 对这两个文件关闭换行转换，保证各平台检出的字节与签名一致。

### 8.4 7 处强制临床转介红线、动作白名单与禁忌症
系统对以下 7 处高危精神障碍严禁任何认知辨析、行为暴露或探查性微练习，仅允许动作白名单并强制 Grade C 专科转介：
1. **双相情感障碍 (`SIT-02-04`)**：允许动作 `[CIRCADIAN_RHYTHM_STABILIZATION, ENVIRONMENT_STIMULUS_REDUCTION, REFERRAL_CARD_PRESENTATION]`。严禁 `"03"` (BA 行为激活) 与 `"RADICAL_COGNITIVE_DEBATE"`；
2. **围产期与产后抑郁困扰 (`SIT-02-06`)**：允许动作 `[EMOTIONAL_HOLDING_PRESENCE, CIRCADIAN_RHYTHM_STABILIZATION, REFERRAL_CARD_PRESENTATION]`。严禁 `"DEEP_SCHEMA_EXCAVATION"`, `"HIGH_COGNITIVE_LOAD"`；
3. **急性应激障碍与 PTSD (`SIT-06-01`)**：允许动作 `[GROUNDING_54321, SAFE_PLACE_CONTAINER, REFERRAL_CARD_PRESENTATION]`。严禁 `"04"` (ERP), `"05"` (系统脱敏), `"26"` (NET), `"27"` (TF-CBT), `"65"` (表达性书写), `"66"` (IRT 梦魇重演)；
4. **解离状态与人格解体 (`SIT-06-05`)**：允许动作 `[GROUNDING_54321, ENVIRONMENT_PHYSICAL_ANCHOR, REFERRAL_CARD_PRESENTATION]`。严禁 `"ABSTRACT_EXISTENTIAL_INQUIRY"`, `"01"` (CBT 认知重构)；
5. **神经性厌食症 (`SIT-08-04`)**：允许动作 `[EMOTIONAL_HOLDING_PRESENCE, REFERRAL_CARD_PRESENTATION]`。严禁 `"12:tipp_cold_water"`, `"13"` (RO-DBT), `"DIET_WEIGHT_MANAGEMENT"`；
6. **边缘型情绪失调伴自伤倾向 (`SIT-09-01`)**：允许动作 `[EMOTIONAL_HOLDING_PRESENCE, DBT_TIPP_MODIFIED_BREATHING, 29:pmr_release, REFERRAL_CARD_PRESENTATION]`。严禁 `"12:tipp_cold_water"`, `"TRAUMA_DETAIL_EXPLORATION"`；
7. **成瘾物质依赖 (`SIT-10-04`)**：允许动作 `[WITHDRAWAL_RISK_WARNING, REFERRAL_CARD_PRESENTATION]`。严禁 `"SELF_DETOX_GUIDANCE"`, `"10"` (HRT 习惯逆转)。

> [!NOTE]
> 允许动作的规范步骤与时长由 `taxonomy.yaml` 的 `action_registry` 统一定义，由骨架装配器直接查询加载；所有宏观禁用标签由 `banned_tag_mappings` 展开为具体方法 ID 集合，红线掩码层据此实行无死角阻断。

> [!IMPORTANT]
> **红线封闭集与名单优先级规则**：
> 1. 对命中临床红线的用户而言，`allowed_actions` 构成了其实际允许交互的**绝对封闭上限边界**（Closed Upper Bound），而 `banned_methods` 仅作为第二道纵深防御保险；
> 2. 状态机动作求解遵循统一交差集公式 $\mathcal{A}_{available} = (\mathcal{C}_{candidates} \cap \mathcal{A}_{allowed}) \setminus \mathcal{B}_{banned} \setminus \mathcal{X}_{contraindicated}$。当红线生效时，即使在 $S_{explore}$ 触发高唤醒（$Arousal \ge 0.80$），若常规白名单中的动作（如生理性叹息 28、渐进式肌肉放松 29）不在该红线病种的 `allowed_actions` 中，求交集后结果直接为空，绝不会越界推送给红线用户；
> 3. **别名预先归约与空集兜底**：集合运算前必须经 `action_registry` 统一归约别名（如 `DBT_TIPP_MODIFIED_BREATHING` $\to$ `12:tipp_breathing`、`GROUNDING_54321` $\to$ `30:grounding`）。若交差集结果为空集，系统一律降级为 `EMOTIONAL_HOLDING_PRESENCE`（纯在场守护 $m_0$）并附带 `REFERRAL_CARD_PRESENTATION`（专科转介卡），绝不报错且不旁路回退；
> 4. **动作类型分通道处理**：当输出为 32 种 A 级整方法时默认按 `MICRO_EXERCISE` 处理，子动作依声明的 `action_type` 分流处理（练习类装配骨架、在场类纯语态守护、科普类作息贴士、转介类卡片渲染），严禁将转介卡或科普当成微练习下发。

---

## 9. 离线感知模型训练与蒸馏工程流水线 (Training & Distillation Pipeline)

- **中文真实语料驱动**：清洗对齐 PsyQA 中文心理支持语料，结合 60 份困扰档案第四节“典型内心独白”作为种子样本；
- **对抗样本增强**：针对否定句（“我不想死”与“我想死”）构建专项对比数据集；
- **轻量静态参数导出**：权重矩阵序列化为纯静态数组，无外部深度学习框架依赖。

---

## 10. 系统可靠性、性能预算与可观测性工程 (Reliability, Latency Budget & Observability)

### 10.1 毫秒级时延预算分配表 (单核 CPU 离线基线)
| 执行阶段 | 核心操作 | $P_{50}$ | $P_{99}$ 上限 | 容灾降级策略 |
| :--- | :--- | :---: | :---: | :--- |
| **Step 1** 输入规范化与危机初筛 | 正则扫描与哈希比对 | $0.2\text{ms}$ | $0.5\text{ms}$ | 纯内存扫描，绝不超时 |
| **Step 2** M.I.Y.I. 中文多任务推断 | 特征稠密映射与矩阵前向 | $25.0\text{ms}$ | $45.0\text{ms}$ | 保留开头 128 字符与末尾 256 字符（双端保全防丢危机线索） |
| **Step 3** M.I.Y.I. 3D记忆检索 | AST 遍历与三维算分 | $0.8\text{ms}$ | $2.0\text{ms}$ | 仅检索最近 10 条经历记录 |
| **Step 4** C.O.L.B.O. 状态机与镜像翻转 | 代词语境分析与 FSM 门控 | $0.5\text{ms}$ | $1.5\text{ms}$ | 降级为默认安全探索态 |
| **Step 5** C.O.L.B.O. 协议求解与骨架生成 | Thompson 采样与动作骨架装配 | $1.0\text{ms}$ | $3.0\text{ms}$ | 降级为纯在场陪伴回复 (m0)，不输出任何干预动作卡 |
| **Step 6** C.H.A.N.G. & W.I.L.L.O.W. 生成 | 离线模板组装与留白塑形 | $0.5\text{ms}$ | $2.0\text{ms}$ | 纯静态插槽填充 |
| **汇总** | **离线控制回路端到端总时延** | **$28.0\text{ms}$** | **$55.0\text{ms}$** | **单核 CPU 极致流畅可信** |

### 10.2 内部可观测性遥测面板规范
```
╔════════════════════════════════════════════════════════════════════════════════════════╗
║                          O.L.I.V.I.A. 内部认知与控制遥测面板                          ║
╠════════════════════════════════════════════════════════════════════════════════════════╣
║ [会话轮次] Global #5, Stage #2  [助人状态] S_empower (循证赋能)   [硬锁] Inactive      ║
║ [人格光谱] GENTLE_HOLDING (温和包裹)  [心力电量] 0.70  [运行模式] AI_ENHANCED (已激活) ║
║ [情感极性] -0.60 (负向)  [生理唤醒度] 0.58 (中等唤醒)  [细粒度情绪] 焦虑心慌 (anxiety)  ║
║ [11大谱系] 01_焦虑与惊恐 (SIT-01-01 GAD): 0.82 | 04_完美主义苛责: 0.70                 ║
║ [萨提亚冰山] 姿态: 超理智型  ==>  核心渴望: 安全感与秩序感 (SAFETY)                     ║
║ [临床动作骨架] 01 (CBT 认知行为疗法) (A级微动作, 步骤: 3步, 禁忌症校验通过)           ║
║ [本地校验器] Method ID & Steps 未改动, 无诊断标签, 校验通过 (TTFT: 820ms)             ║
║ [安全红线] 风险等级: L0 (安全) | 危机置信度: 0.01 (安全)                               ║
╚════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## 11. 逻辑架构与工程模块组件映射索引 (Modular Implementation Mapping)

为了实现系统设计与工程代码实现的无缝对接，本设计规范各章节在逻辑实现层严格映射至核心模块接口规范：

状态标注：`[已实现 / 步骤]` 表示代码已合并（步骤号见路线图 `docs/superpowers/plans/2026-10-22-remaining-roadmap.md` 或下一阶段计划 `2026-10-23-next-phase.md`）；`[待实现 / 步骤]` 表示计划中的模块，接口以实现时为准。本表于 2026-10-23（计划步骤 A5）按代码逐行核对。

| 设计规范章节 | 领域逻辑职责 | 核心代码实现模块路径 | 核心导出接口与类型契约 |
| :--- | :--- | :--- | :--- |
| **§ 2 通用领域模型** | 全局类型与数据契约 | `olivia/core/models.py` [已实现 / P0] | `PersonaProfile`, `SessionState`, `PerceptionContext`, `ActionSkeleton`, `UserRegion`（枚举：`CrisisLevel`, `HelpStage`, `PersonaSpectrum`, `SafetyGrade`, `ActionType`）；`SessionState.consecutive_l1_count` 只是 `CrisisTracker.consecutive_l1_count` 的镜像，由 `fsm.step` 每轮写入 |
| **§ 2.1 画像持久化** | 画像读写与快照恢复 | `olivia/core/chang/profile.py` [已实现 / P0] | `ProfileStore(base_dir: Path \| None = None)`: `.path`, `.load() -> PersonaProfile \| None`, `.save(profile: PersonaProfile) -> None`; `ProfileCorruptError`（`clinical_history` 目前仍为明文，加密 [待实现 / B1]） |
| **§ 3.1 感知分类基准** | SSOT 分类标准与阈值访问 | `olivia/core/taxonomy.py` [已实现 / P0] | `load_taxonomy(path: Path \| None = None) -> Taxonomy`; `Taxonomy.version`, `.threshold(dotted_path) -> float`, `.values(name) -> tuple[str, ...]`, `.canonical_label(kind, label) -> str`, `.spectrum_ids()`, `.methods()`, `.grade_a_ids()`, `.action_registry()`, `.canonical_action_id(action_id) -> str`, `.red_flags()`, `.banned_tag_methods(tag)`, `.is_banned_tag(entry)`, `.stabilization_whitelist()`, `.emotion_profiles()`, `.emotion_name(emotion_id)`, `.bands(scale)`, `.band_of(scale, value)`, `.crisis_level_for_score(score) -> CrisisLevel`, `.crisis_exit_safe_turns(level) -> int`; `TaxonomyError`, `UnknownActionError` |
| **§ 3.1 规则感知桩** | 规则模式下从词表与电量前缀填出 `PerceptionContext` 与本轮控制信号 | `olivia/core/perception/rule_stub.py`、`lexicon.py`、`signals.py` [已实现 / P3-1、P3-5、R-7b] | `RuleStub(tax, lexicon: PerceptionLexicon)`: `.perceive(text, assessment: CrisisAssessment) -> tuple[PerceptionContext, TurnSignals]`; `dominant_spectrum(distress_vector) -> str \| None`; `EmpathyIntent`; `load_perception_lexicon(tax, directory: Path \| None = None) -> PerceptionLexicon`, `strip_marks(text) -> str`, `PerceptionLexiconError`; `TurnSignals`（`battery`, `direct_request`, `listening_lock_on/off`, `aversion`, `intent_confirmed`, `command`, `feedback`, `feedback_unclear`, `answer` 等，只含标志与数值，不含原文）, `Command`, `Answer` |
| **§ 3.1 / § 9 感知学生模型** | 纯 NumPy 字符级 CNN 学生模型的加载、校验与风险头推理（规则仍是底线） | `olivia/core/perception/student.py` [已实现 / P6-6a，默认关闭（R-P6a）]；其余感知头接入 [待实现 / C1] | `try_load_student(directory=None) -> StudentLoad`（不抛异常，失败给出原因）, `load_student(directory=None) -> StudentModel`, `default_student() -> StudentLoad`; `StudentModel.predict_heads(text)`, `.risk(text) -> tuple[CrisisLevel, float]`; `StudentRiskModel(student)`: `.predict(text) -> RiskPrediction`; `choose_risk_model(model: RiskModel \| None = None, *, student: bool = False) -> RiskChoice`; `StudentUnavailableError` |
| **§ 3.2 萨提亚冰山内省器** | 认知扭曲、图式、渴望（两种模式，词表）；图式镜像与 C_2 核心信念确认（仅模型模式，决定 D4） | `olivia/core/perception/introspector.py`，词表 `perception.yaml` 的 `introspection` 段，镜像文案 `language/schema_mirror.yaml` [已实现 / C2] | `load_introspection_lexicon(tax, directory=None) -> IntrospectionLexicon`, `Introspector(lexicon)`: `.read(text) -> Introspection`, `.apply(text, context) -> PerceptionContext`; `SchemaMirror`, `read_mirror_answer(answers, text) -> MirrorAnswer \| None`, `MirrorStatus`, `load_mirror_lines(tax, directory=None)`, `shame_spiral(context) -> bool`（`TOXIC_SHAME_SPIRAL` 的感知来源）; `IntrospectionLexiconError`；状态机 `Reason.CLARIFY_CORE_BELIEF`、`TurnSignals.core_belief_confirmed` |
| **§ 3.3 存储与数据根基** | 应用级持久化目录与影子写入 | `olivia/core/storage.py` [已实现 / P0] | `app_data_dir() -> Path`, `atomic_write_text(path: Path, text: str) -> None`, `read_text_with_recovery(path: Path, is_valid: Callable[[str], bool]) -> str`, `snapshot_paths(path: Path) -> list[Path]`, `SNAPSHOT_KEEP = 3`, `StorageCorruptError` |
| **§ 3.3 / § 6.6 静态加密与加密擦除** | 钥匙串主密钥、AES-256-GCM 文件信封、按存储数据密钥、加密擦除 | `olivia/core/crypto/` [已实现 / B1]；`olivia/core/chang/profile.py` | `seal_bytes(key, plaintext, *, store, label='')`, `open_bytes(...)`, `KeyBackend`, `KeyringBackend`, `Vault(base_dir, backend=None)` 及 `.available/.check/.seal/.open/.shred/.shred_all/.rotate_master_key`, `ProfileStore(base_dir=None, vault=None)`, `SENSITIVE_FIELDS`, `ProfileLockedError`, `CryptoError` 族 |
| **§ 3.3 / § 6.5 透明账本** | 加密的会话摘要与用户要求记住的笔记（决定 D1） | `olivia/core/memory/ledger.py`、`notes.py`、`recorder.py`、`text.py` [已实现 / B2] | `Ledger(base_dir: Path \| None = None, vault: Vault \| None = None, *, text=None, method_titles: Mapping[str, str] \| None = None)`: `.available() -> bool`, `.append_summary(summary: SessionSummary, *, key: str) -> str`（同一 key 原地替换）, `.add_note(text: str, *, now: datetime \| None = None) -> str`, `.entries(since: datetime \| None = None) -> tuple[LedgerEntry, ...]`（旧到新）, `.notes() -> tuple[NoteEntry, ...]`, `.read_markdown(entry_id) -> str`, `.render(entry) -> str`, `.body(entry) -> str`（模板化小结或笔记原文）, `.forget_entry(entry_id) -> int`（B5：重新加密其余条目后擦除旧密钥，返回顺带清理的打不开条目数）, `REKEY_STORE`, `.shred() -> None`, `.take_unavailable_notice() -> bool`, `.skipped`; `SessionSummary`（`.entered_crisis`, `.significant`）, `MethodRecord`, `SummaryEntry`, `NoteEntry`, `LedgerEntry`, `LedgerUnavailableError(permanent)`, `NOTE_MAX_CHARS`; `SessionRecorder(ledger, session_id, now)`: `.observe(message, result: TurnResult) -> TurnResult`（可能追加笔记确认）, `.close() -> bool`, `.enabled`; `load_note_cues() -> NoteCues`（`.find(message) -> str \| None`）, `load_memory_text() -> MemoryText` |
| **§ 3.3 / § 6.3 跨会话状态** | Thompson 后验与锦囊持久化（只存编号、数值与时间，始终加密，存储名 `state`，文件 `state.bin`，锦囊最多 10 条）；关怀标记见 A3 一行 | `olivia/core/memory/state.py` [已实现 / B3]；`session.py`、`cli.py` | `StateStore(base_dir=None, vault=None)`: `.load() -> CarriedState \| None`（损坏、更高版本、钥匙串锁定时为 None）, `.save(state) -> bool`（无钥匙串抛 `NoKeychainError`）, `.shred()`；`StateRecorder(store, baseline).observe(state)`（有变化才写）；`CarriedState(bandit, kit)`（`.to_dict()`, `.from_dict()`）, `KitEntry(action_id, shelved_at)`, `restore_sampler(tax, bandit) -> ThompsonSampler`, `KIT_MAX`, `FORMAT_VERSION`；`Session.open(..., carried=None)`, `Session.kit()`, `Session.carried_state()` |
| **§ 3.3 / § 6.6 查看与遗忘** | `olivia memory`：只在屏幕上列出账本条目（旧到新编号，模板化小结与笔记原文）与其余数据的名字，不显示健康信息与安全计划内容，打不开的条目只计数；`olivia forget`：一条记录（`Ledger.forget_entry` 重新加密其余条目并擦除旧账本密钥）、全部聊天记录（账本 + 关心提醒）、锦囊与方法偏好、安全计划（各自 `shred`：销毁数据密钥并轮换主密钥）、全部数据（`Vault.shred_all` 后删除 `DATA_FILES`/`DATA_DIRS` 下全部文件，含画像快照，下次 `chat` 重新首访）；每次删除需输入确认词（`--yes` 跳过），输入结束即取消；钥匙串被锁时前四项不改动，`--all` 照删文件并说明主密钥未删；未成年人拒绝记录保留（`--all` 删除其余数据并用 `kept_minor` 说明）。新增存储须登记到 `DATA_FILES` 或 `DATA_DIRS` | `olivia/core/memory/forget.py`，文案 `templates/forget.yaml` [已实现 / B5]；`cli.py` | `DataStores.open(base_dir=None, *, method_titles=None)`（共用一个 `Vault`）; `run_memory(say, stores, text=None) -> int`; `run_forget(ask, say, stores, *, target: Target \| None = None, entry: int \| None = None, assume_yes=False, text=None) -> int`; `forget_ledger(stores)`, `forget_kit(stores)`, `forget_safety_plan(stores)`, `forget_all(stores, *, keep=frozenset()) -> bool`（False：钥匙串未响应、主密钥未删）; `Target`, `MENU`, `DATA_FILES`, `DATA_DIRS`; `load_forget_text(directory=None) -> ForgetText`, `ForgetTextError` |
| **§ 3.3 3D 检索** | 3D 艾宾浩斯检索 | `olivia/core/memory/retrieval.py` [已实现 / B4；规则模式未接入] | `MemoryIndex(entries: Iterable[LedgerEntry], *, text: MemoryText \| None = None, method_titles: Mapping[str, str] \| None = None)`: `.rank(query, now, k=TOP_K) -> list[tuple[LedgerEntry, float]]`, `.scores(query, now)`, `.similarities(query)`; `rank(query, entries, now, k=TOP_K, *, text=None, method_titles=None)`; `recency(entry, now)`, `searchable_text(entry, *, text=None, method_titles=None)`, `char_ngrams(text)`; `W_REC`、`W_SIM`、`W_SAL`、`ALPHA`、`TAU_DAYS`、`TOP_K` |
| **§ 4.2 符号状态机** | 七状态 FSM 代数流转 | `olivia/core/fsm/machine.py`（由 `olivia/core/fsm/__init__.py` 导出）[已实现 / P3-2、P3-5] | `step(tax: Taxonomy, state: SessionState, inp: TurnInput) -> Transition`（纯函数，不修改入参）; `close_session(state: SessionState) -> Transition`; `TurnInput(perception, crisis: CrisisStatus, signals: TurnSignals, persona)`, `Transition(previous, state, reason)`, `Reason` |
| **§ 4.3 协议与骨架编排** | 32 种 A 级动作与禁忌掩码 | `olivia/core/methods/solver.py` [已实现 / P3-3] | `allowed_actions(tax, SolverInput) -> AllowedSet`（候选集、是否走 $m_0$、需转介的红线）→ 由 `methods/bandit.py` 的 `ThompsonSampler.choose` 选定 → `build_plan(tax, chosen_id, allowed) -> ActionPlan`（`ActionPlan` = 主动作 `ActionSkeleton` + 转介红线列表）；另有 `active_contraindications(tax, inp)`, `banned_actions(tax, flags)`, `M0_ACTION_ID`, `M0_SITUATIONS`；方法 ID 用 taxonomy 形式（`"01"`、`"12:tipp_breathing"`） |
| **§ 4.3 禁忌症与情境接通** | 13 种禁忌症按各自 `detection_source` 推导（画像自述、红线、危机状态、感知线索），SIT-06-04 / SIT-11-01 情境，会话内有效 | `olivia/core/methods/contraindications.py` [已实现 / A1（决定 D2）] | `SessionContraindications(tax, profile_contraindications)`: `.observe(signals, perception, status, red_flags) -> ActiveContext`, `.unsaved_disclosures()`, `.mark_hinted(ids)`; `source_links(tax) -> SourceLinks`; `ActiveContext(contraindications, situations)`；`PROFILE_CONTRAINDICATIONS`（`models.py`） |
| **§ 6.3 Thompson 采样** | Beta-Bernoulli 后验、三档反馈、软衰减、高唤醒只利用 | `olivia/core/methods/bandit.py` [已实现 / P3-4；跨会话持久化已实现 / B3，见 `memory/state.py`] | `ThompsonSampler(tax, state: Mapping[str, object] \| None = None)`: `.choose(candidates, spectrum, arousal, rng, now) -> str`, `.update(action_id, spectrum, feedback: Feedback, now) -> None`, `.posterior(action_id, spectrum, now) -> tuple[float, float]`, `.to_dict()`; `Feedback`（`HELPFUL` / `UNHELPFUL` / `NOT_NOW`） |
| **PRD §9 危机后轻度安全问候** | 跨会话关怀标记（只存时间与 L2/L3/ASK_DENIED，始终加密，存储名 `care`，7 天有效，用一次即清除） | `olivia/core/chang/care.py` [已实现 / A3]；`session.py`、`cli.py` | `CareStore(base_dir=None, vault=None)`: `.save(marker) -> bool`, `.take(now) -> CareMarker \| None`, `.shred()`；`CareRecorder(store, clock).observe(result, snapshot)`；`care_kind(result, snapshot) -> CareKind \| None`；`CareMarker(at, kind)`, `CareKind`, `MAX_AGE`；`Session.care_greeting(*, light=False) -> str`，`inspect["care_greeting"]` |
| **PRD §9 个人安全计划** | Stanley-Brown 式安全计划（五部分，每部分可跳过），只在 `olivia safety-plan` 里填写、查看、修改和清空；始终加密（存储名 `safety_plan`），无钥匙串不保存；危机回复展示第 2–4 部分（L2 在热线卡之前、L3 与带急救号码的卡在其后），第 5 部分从不进入危机回复；计划号码只对该条回复放行，网关拦截时只丢计划不丢卡；首次 $S_{closing}$ 每台电脑提示一次命令（决定 D8） | `olivia/core/chang/safety_plan.py`，文案 `templates/safety_plan.yaml` [已实现 / B10]；`session.py`、`language/engine.py`、`cli.py` | `SafetyPlan`（`.lines(section)`, `.is_empty`, `.to_json()`, `.from_json(raw)`）, `Contact(name, phone)`, `Section`, `SECTIONS`, `CRISIS_SECTIONS`; `SafetyPlanStore(base_dir=None, vault=None)`: `.load()`, `.load_quietly()`, `.save(plan)`, `.clear()`, `.shred()`, `.should_suggest()`, `.mark_suggested()`; `SafetyPlanDamagedError`; `crisis_block(plan, text=None) -> str`; `run_command(ask, say, store, text=None) -> int`; `load_safety_plan_text(directory=None)`; `Session.open(..., safety_plan=None, suggest_safety_plan=False)`, `Session.safety_plan_suggested`, `inspect["safety_plan_shown"]`; `LanguageEngine.render_crisis(card, slots, *, plan_block="")`, `.last_plan_gate` |
| **§ 6.1 健康信息查看与修改** | `olivia health`：临床史编号与两项自述禁忌症（决定 D2），加密保存；首访在授权后多一步勾选清单 | `olivia/core/chang/health.py` [已实现 / A1] | `HealthEditor(tax, store, now, text=None)`: `.prompt() -> HealthPrompt`, `.answer(text) -> HealthPrompt \| HealthDone`, `.outcome`; `parse_choices(reply, keys)`（`onboarding.py`） |
| **§ 6.1 首访角色契约** | 首访流程 ONB-01~05、07、08（18+ 门禁先于采集任何个人信息） | `olivia/core/chang/onboarding.py` [已实现 / P4-2] | `OnboardingFlow(tax, store: ProfileStore, now: datetime, text: OnboardingText \| None = None)`: `.prompt() -> Prompt`, `.answer(text) -> Prompt \| Completed \| Refused`, `.step`, `.outcome`; `load_onboarding_text(directory=None) -> OnboardingText`（`.persona_labels`）, `canonical_timezone(raw) -> str \| None`, `persona_from_reply(reply, labels) -> PersonaSpectrum \| None`; `Step`, `RefusalReason`, `PERSONA_CHOICES`, `DEFAULT_PERSONA`（ONB-03 四选一，计划 D-1） |
| **§ 6.2 双通道校验网关** | 本地离线校验与降级 | `olivia/core/chang/gateway.py` [待实现 / P7（裁定 35）] | `validate_ai_response(response, skeleton) -> bool`（草案） |
| **§ 6.4 情绪周记与自评** | 滚动 7 天周记（只读账本，模板化，危机周转庄重口吻）、会话前后 0–10 自评（只存账本摘要）、开场周记提示（窗口内 ≥ 2 次会话且 7 天内没提过）、满意度（有 / 没有）；`olivia journal` 随时查看 | `olivia/core/chang/journal.py`，文案 `templates/journal.yaml` [已实现 / B6]；`memory/ledger.py`（`journal` 条目）、`memory/recorder.py`、`cli.py` | `ChatChecks(tax, ledger, recorder, ask, say, *, method_titles=None, text=None)`: `.opening(now) -> Carry`, `.observe(result)`, `.after_turn(state) -> Carry`, `.at_exit(state) -> Carry`, `.may_ask_after(state)`; `Carry(line, ended)`; `gather(ledger, now) -> Week`, `is_due(week)`, `render_journal(week, text, memory, method_titles=None) -> str`, `run_command(ask, say, ledger, now, *, method_titles=None, text=None) -> int`; `parse_rating(text)`, `parse_yes_no(text, words)`, `load_journal_text(directory=None)`; `WINDOW`, `MIN_SESSIONS`; `Ledger.record_journal(offered_at, *, shown, helpful=None, entry_id=None) -> str`, `JournalEntry`; `SessionRecorder.rate_before(r)`, `.rate_after(r) -> bool`, `.closed_segment`, `.segment_open` |
| **PRD § 11.1 / RSK-07 防依赖提示** | 会话满 45 分钟的休息提醒、深夜（taxonomy `late_night`，按画像时区）关怀、现实支持引导占比；只上常规回复，不上危机、卡片与跟进句（决定 D5） | `olivia/core/chang/wellbeing.py` [已实现 / B7]；文案在 `gentle_holding.yaml` 的 `wellbeing` | `Wellbeing(tax, timezone, started_at)`: `.prompt(reply, *, now, stage, eligible, locked, templates, render) -> Prompted`, `.due(now)`, `.is_late_night(now)`, `.real_support_share`; `Reminder`, `BREAK_AFTER`; `Taxonomy.late_night_window()`；`inspect["reminder"]`、`inspect["real_support_share"]` |
| **§ 8.3 危机资源签名数据** | Ed25519 分离式签名校验与覆盖包选择（GEO-08） | `olivia/core/resources/bundle.py`、`keys.py` [已实现 / P2-3] | `load_hotlines_bytes(override_dir: Path \| None, *, today: date) -> LoadedBundle`（`LoadedBundle(data: bytes, source: "override" \| "builtin", reason: str \| None)`；内置数据验签失败抛 `BundleIntegrityError`）; `verify_signature(data: bytes, signature_b64: bytes, public_key_b64: str) -> bool`; `REASON_*` 常量; `keys.HOTLINE_PUBLIC_KEY_B64` |
| **§ 8.3 属地热线动态解析** | GEO 属地与多模式解析器 | `olivia/core/resources/resolver.py`、`store.py`、`card.py` [已实现 / P2-1、P2-2] | `resolve(store, region, level, *, mode: CardMode, today, is_minor=False) -> ResourceCard`, `resolve_region_code(store, region) -> str`; `parse_store(data) -> ResourceStore`, `load_store(path=None) -> ResourceStore`, `ResourceDataError`; `ResourceCard.stale`, `.lines_by_kind()` |
| **§ 8.3 危机卡片文案渲染** | 属地化危机求助卡文本渲染 | `olivia/core/language/engine.py` [已实现 / P4-3a] | `LanguageEngine.render_crisis(card: ResourceCard, slots) -> str`（急救号码在前；被网关拦截时仍保留卡上全部号码） |
| **§ 5.1–5.3 语言引擎** | 模板组合、隐喻、字数窗口 | `olivia/core/language/engine.py`、`data.py` [已实现 / P4-3a；`render_info` 运行时接入待实现 / A4] | `LanguageEngine(tax, *, rng, data: LanguageData \| None = None)`: `.build_slots(...)`, `.compose(stage, slots, *, card="", returning_after_crisis=False)`, `.render_card(skeleton)`, `.render_info(method_id)`, `.render_referral(flags)`, `.window_penalty(stage, text)`; `load_language_data(tax, root=None, *, persona=GENTLE_HOLDING) -> LanguageData`（`.personas`、`.for_persona(persona)`，四种人格模板，计划 D-1）, `PERSONA_TEMPLATE_FILES`, `load_willow(root=None) -> WillowData`, `ContentKind` |
| **§ 4.1 代词镜像** | 代词安全镜像重述 | `olivia/core/language/mirror.py` [已实现 / P4-3a] | `mirror(user_text) -> str` |
| **§ 5.1 WILLOW 过滤与输出审查网关** | 说教改写、去病理化、诊断词拦截、号码与越级方法名拦截 | `olivia/core/language/filters.py`、`gate.py` [已实现 / P4-3a] | `apply_willow(text, kind)`、`OutputGate(tax, data)`: `.check(text, *, kind, stage, allowed_numbers=()) -> GateResult`, `.reasons(...)` |
| ~~**§ 8.3 属地行政区划索引**~~ | ~~国标行政区划与国际城市库~~ | ~~`olivia/core/resources/divisions.py`、`world_cities.py`~~ **[已废弃，不实现]** | §8.3 只按国家/地区解析，大陆 12356 按来电地自动转接，不需要城市/省级路由或行政区划索引（2026-10-22 官方核验） |
| **§ 8.3 规则仲裁与 R8 隔离** | 官方裁定规则与属地过滤 | `olivia/core/resources/resolver.py` [已实现 / P2-2] | R8：非大陆地区不显示大陆条目（按地区判断，澳门、台湾的 110 是当地号码）；未知或不支持的地区回落到 ZZ（求助目录 + 112） |
| **§ 8.4 转介红线识别** | 7 处强制转介红线的文本识别与会话累积 | `olivia/core/safety/red_flags.py` [已实现 / P1] | `RedFlagDetector(tax: Taxonomy, lexicons: SafetyLexicons)`: `.detect(text: str) -> frozenset[str]`, `.profile_flags(clinical_history: Iterable[str]) -> frozenset[str]`; `SessionRedFlags(detector: RedFlagDetector, clinical_history: Iterable[str] = ())`: `.active -> frozenset[str]`, `.observe(text: str) -> frozenset[str]`; `UnknownRedFlagError` |
| **§ 8.4 转介红线过滤网** | 7 处强制转介红线安全掩码 | `olivia/core/methods/solver.py` [已实现 / P3-3] | 红线掩码在 `allowed_actions` 内完成：多个红线的 `allowed_actions` 取交集、禁用取并集；有任一红线时 `AllowedSet.referral_flags` 非空，必须呈现转介卡 |
| **§ 8.1 输入归一化与感知截断** | 风险匹配前的文本折叠（NFKC、大小写、繁体转简体、弯引号转直引号、去除空白与不可见字符）与感知窗口截取 | `olivia/core/safety/normalize.py` [已实现 / P1] | `normalize(text: str) -> str`, `clip_for_perception(text: str) -> str`, `PERCEPTION_HEAD = 128`, `PERCEPTION_TAIL = 256` |
| **§ 8.1 多模式短语匹配** | 单遍扫描的 Aho-Corasick 短语匹配 | `olivia/core/safety/matcher.py` [已实现 / P1] | `PhraseMatcher(phrases: Mapping[str, str])`: `.find_all(text: str) -> list[Match]`; `Match(key: str, start: int, end: int)` |
| **§ 8.1 安全词表加载** | 危机与红线词表的加载与校验 | `olivia/core/safety/lexicon.py` [已实现 / P1] | `load_safety_lexicons(tax: Taxonomy, directory: Path \| None = None) -> SafetyLexicons`; `SafetyLexicons.cues(section: RiskSection) -> tuple[RiskCue, ...]`; `RiskCue`, `RedFlagCue`, `LexiconError` |
| **§ 8.1 单一会话入口** | 每轮按固定顺序串联安全筛查 → 感知 → 危机跟踪 → 红线 → 状态机 → 求解 → 语言与输出网关 → 反馈，调用方无法跳过 | `olivia/core/session.py` [已实现 / P4-3b] | `Session.open(tax, profile, *, rng, now, model: RiskModel \| None = None, student: bool = False, carried: CarriedState \| None = None) -> Session`（`carried` 为 B3 的跨会话状态；`student=True` 即 `olivia chat --model`，默认只用规则；18+ 门禁未过抛 `AgeGateRefusedError`）; `.turn(text) -> TurnResult`（`reply`, `reply_kind`, `stage`, `crisis_level`, `in_crisis`, `resource_card`, `action_id`, `referral_flags`, `inspect`）; `.state -> SessionState`（副本）; `.snapshot() -> dict`（不含原文）; `ReplyKind`, `FeedbackSource` |
| **§ 8.1 / § 8.2 危机分级与仲裁** | 两阶段危机筛查与等级仲裁 | `olivia/core/safety/crisis.py` [已实现 / P1、SAFE-2] | `SafetyScreen(tax: Taxonomy, lexicons: SafetyLexicons, model: RiskModel \| None = None, *, model_plan_evidence: bool = False)`: `.assess(text: str) -> CrisisAssessment`（`model_plan_evidence` 只能以关键字传入，见 §8.2，出厂关闭）; `RiskModel.predict(text: str) -> RiskPrediction`; `RuleRiskModel(tax, lexicons)`; `arbitrate(tax: Taxonomy, l_cls: CrisisLevel, score: float, has_plan_evidence: bool) -> CrisisLevel`; `CrisisAssessment`, `RiskPrediction` |
| **§ 8.2 危机态进出追踪** | 会话级危机进入、升级与退出判定 | `olivia/core/safety/tracker.py` [已实现 / P1、SAFE-1] | `CrisisTracker(tax: Taxonomy, lexicons: SafetyLexicons)`: `.observe(assessment: CrisisAssessment, text: str, valence: float \| None = None) -> CrisisStatus`, `.consecutive_l1_count -> int`（只读，L1 计数的唯一来源）; `CrisisStatus`（含 `consecutive_l1_count`） |
| **§ 10.2 命令行与观测面板** | `olivia chat [--inspect] [--model]`、`olivia resources`、`olivia region`、`olivia health`（查看与修改加密的健康信息，A1）、`olivia persona [序号或简称]`（查看与切换人格，JTBD 4）、`olivia safety-plan`（B10）、`olivia memory` 与 `olivia forget [--entry N \| --ledger \| --kit \| --safety-plan \| --all] [--yes]`（查看与遗忘，JTBD 4，B5） | `olivia/cli.py` [已实现 / P2-4、P4-4、A1、D-1、B10、B5] | `main(argv=None, *, stdin=None, stdout=None, clock=None, rng=None) -> int`, `build_parser()`, `inspect_panel(result: TurnResult) -> list[str]`（不显示原文与城市）, `render_browsing(card, tax) -> str` |

本系统设计规范全面确立了 **O.L.I.V.I.A.** 四位一体的工程架构标准，具备高工业级鲁棒性与严谨临床心理伦理双重标准。
