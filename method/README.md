# 📚 现代循证与经典心理治疗方法全景百科库 (Comprehensive Psychotherapy Methods Repository)

> **定位与说明**：本目录（[`method/`](./)）系统收录了当代临床心理学与精神医学中 **75 种核心心理治疗流派、专项循证方案与躯体/表达性干预方法**。  
> 每一份 `.md` 档案均为独立的临床级技术手册，完整包含：**① 理论基础与神经心理起效机制、② 适用情况与安全禁忌红线、③ 核心技术与方法工具箱、④ 标准化分步实施流程（含临床长程流程与 5 分钟日常自助/AI陪伴微练习版）、⑤ 具体实施案例与逐轮对话/工作表实操示范、⑥ 权威 APA 格式学术参考文献（References）**。

---

## ⚠️ 临床安全分级核心红线 (Clinical Safety Tiers)
根据临床暴露风险、自主微练习可行性及医学监护要求，本库 75 种疗法严格执行三级安全门控：
- 🟢 **Grade A（32 种自主微干预）**：系统在 $S_{empower}$ 状态下允许向用户推荐的 2–5 分钟自主微练习，支持 ActionSkeleton 骨架装配；
- 🟡 **Grade B（26 种科普与概念重塑）**：仅用于 $S_{clarify}$ 阶段的概念科普与温和照见，严禁作为孤立练习直接下发；
- 🔴 **Grade C（17 种专业转介提示）**：需持证专业心理师或精神科医师在场督导的高风险深度技术（如暴露、眼动、系统家庭治疗）。系统**严禁在无督导下向用户推送自主执行指令**，仅供医疗转介提示。下表中带 🔴 的项目属于专科就医转介类方法。

---

## 🧭 一、 按临床困扰与症状快速检索矩阵 (Clinical Indication Quick-Match Matrix)

| 困扰领域 / 临床表征 | 首选一线循证疗法 (Tier-1 Evidence-Based) | 深度图式/体验/系统协同疗法 (Depth & Integrative) |
| :--- | :--- | :--- |
| **抑郁低落、动力丧失、严重拖延** | [03 BA 行为激活](./03_BA_Behavioral_Activation.md)、[01 CBT 认知行为疗法](./01_CBT_Cognitive_Behavioral_Therapy.md)、[14 MBCT 正念认知疗法](./14_MBCT_Mindfulness_Based_Cognitive_Therapy.md)、[49 IPT 人际心理治疗](./49_IPT_Interpersonal_Psychotherapy.md) | [09 CBASP 慢性抑郁分析系统](./09_CBASP_Cognitive_Behavioral_Analysis_System.md)、[13 RO-DBT 彻底开放辩证行为](./13_RO_DBT_Radically_Open_DBT.md)、[57 PPT 积极心理与幸福感疗法](./57_PPT_Positive_Psychotherapy_and_Well_Being_Therapy.md) |
| **广泛性焦虑、精神内耗、反刍思维** | [16 MCT 元认知疗法](./16_MCT_Metacognitive_Therapy.md)、[11 ACT 接纳承诺疗法](./11_ACT_Acceptance_and_Commitment_Therapy.md)、[75 ERT 情绪调节疗法](./75_ERT_Emotion_Regulation_Therapy.md)、[08 UP 跨诊断统一方案](./08_UP_Unified_Protocol_Transdiagnostic.md) | [61 森田疗法（顺其自然·为所当为）](./61_Morita_Therapy.md)、[02 REBT 理性情绪行为疗法](./02_REBT_Rational_Emotive_Behavior_Therapy.md)、[15 MBSR 正念减压](./15_MBSR_Mindfulness_Based_Stress_Reduction.md) |
| **惊恐发作、疾病焦虑/疑病、急性应激** | [28 生理性叹息与自主神经调节](./28_Polyvagal_and_Autonomic_Somatic_Regulation.md)、[70 HRV 生物反馈共振呼吸](./70_Biofeedback_and_HRV_Neuroregulation_Therapy.md)、[73 CBT-HA 疾病焦虑认知行为疗法](./73_CBT_HA_Health_Anxiety_and_Somatic_Symptoms.md) | [05 系统脱敏与内感受暴露](./05_Systematic_Desensitization_and_Exposure.md)、[29 PMR 渐进性肌肉放松与自律训练](./29_PMR_and_Autogenic_Training.md)、[30 PFA 心理急救与自我安全自检](./30_PFA_Psychological_First_Aid_and_Crisis_Intervention.md) |
| **慢性失眠、睡前大脑停不下来、噩梦** | [06 CBT-I 失眠认知行为疗法](./06_CBT_I_Insomnia_Cognitive_Behavioral_Therapy.md)、[66 IRT 意象预演与梦魇改写](./66_IRT_Imagery_Rehearsal_Therapy_for_Nightmares.md) | [29 PMR 渐进性肌肉放松与自律训练](./29_PMR_and_Autogenic_Training.md)、[28 生理性叹息微松脱](./28_Polyvagal_and_Autonomic_Somatic_Regulation.md) |
| **强迫观念与强迫行为 (OCD)、抽动/拔毛** | [04 ERP 暴露与反应阻止疗法](./04_ERP_Exposure_and_Response_Prevention.md)、[10 HRT 习惯逆转训练与权变管理](./10_HRT_Habit_Reversal_and_Contingency_Management.md) | [16 MCT 元认知疗法](./16_MCT_Metacognitive_Therapy.md)、[11 ACT 认知解离](./11_ACT_Acceptance_and_Commitment_Therapy.md)、[61 森田疗法](./61_Morita_Therapy.md) |
| **严苛自责、羞耻感、完美主义、休息羞耻** | [17 CFT 慈悲聚焦疗法](./17_CFT_Compassion_Focused_Therapy.md)、[18 MSC 正念自我关怀](./18_MSC_Mindful_Self_Compassion.md)、[19 图式疗法 Schema Therapy](./19_Schema_Therapy.md) | [47 IFS 内在家庭系统](./47_IFS_Internal_Family_Systems.md)、[40 EFT 情绪聚焦双椅对话](./40_EFT_Emotion_Focused_Therapy.md)、[68 哈科米正念躯体探针](./68_Hakomi_Mindful_Somatic_Psychotherapy.md) |
| **创伤后应激 (PTSD)、童年创伤、闪回** | [21 EMDR 眼动脱敏与再加工](./21_EMDR_Eye_Movement_Desensitization_Reprocessing.md)、[22 CPT 认知加工疗法](./22_CPT_Cognitive_Processing_Therapy.md)、[23 PE 延长暴露](./23_PE_Prolonged_Exposure_Therapy.md)、[27 TF-CBT 创伤聚焦与意象改写](./27_TF_CBT_Trauma_Focused_CBT.md) | [24 SE 躯体体验疗法](./24_SE_Somatic_Experiencing.md)、[25 SP 感官运动心理治疗](./25_SP_Sensorimotor_Psychotherapy.md)、[26 NET 叙事暴露疗法](./26_NET_Narrative_Exposure_Therapy.md) |
| **情绪剧烈波动、怕被抛弃、边缘性人格特质** | [12 DBT 辩证行为疗法](./12_DBT_Dialectical_Behavior_Therapy.md)、[33 MBT 心智化基础疗法](./33_MBT_Mentalization_Based_Treatment.md)、[34 TFP 移情焦点治疗](./34_TFP_Transference_Focused_Psychotherapy.md) | [19 图式疗法](./19_Schema_Therapy.md)、[35 客体关系与依恋取向治疗](./35_Object_Relations_and_Attachment_Based_Therapy.md)、[36 科胡特自体心理学](./36_Self_Psychology_Kohut.md) |
| **人际边界模糊、讨好委屈、伴侣/家庭冲突** | [48 萨提亚冰山与转化式系统治疗](./48_Satir_Transformational_Systemic_Therapy.md)、[53 戈特曼伴侣治疗法](./53_Gottman_Method_Couples_Therapy.md)、[71 ABFT 依恋取向家庭治疗](./71_ABFT_Attachment_Based_Family_Therapy.md)、[74 PCIT 亲子互动去威胁肯定](./74_PCIT_Parent_Child_Interaction_Therapy.md) | [50 鲍温家庭系统与自我分化](./50_Bowen_Family_Systems_Therapy.md)、[51 结构与策略派家庭治疗](./51_Structural_and_Strategic_Family_Therapy.md)、[54 TA 交互分析与戏剧三角](./54_TA_Transactional_Analysis.md) |
| **丧失亲人、失恋分离、存在性空虚与迷茫** | [58 CGT 复杂性哀伤疗法与双程模型](./58_CGT_Complicated_Grief_Therapy.md)、[72 意义重构哀伤疗法](./72_Meaning_Reconstruction_Grief_Therapy.md)、[41 存在主义心理治疗](./41_Existential_Psychotherapy.md)、[42 弗兰克尔意义疗法](./42_Logotherapy_Viktor_Frankl.md) | [43 格式塔疗法（空椅未完成事件）](./43_Gestalt_Therapy.md)、[63 心理剧疗法](./63_Psychodrama_Moreno.md)、[65 潘尼贝克表达性书写](./65_Expressive_Writing_Pennebaker.md) |
| **改变动机矛盾、现实问题卡壳、短程赋能** | [46 MI 动机式访谈与自我决策平衡](./46_MI_Motivational_Interviewing.md)、[55 SFBT 焦点解决短程治疗](./55_SFBT_Solution_Focused_Brief_Therapy.md)、[07 PST 问题解决疗法](./07_PST_Problem_Solving_Therapy.md) | [56 叙事疗法（问题外化）](./56_Narrative_Therapy.md)、[69 SSI 单次微干预与成长型思维](./69_SSI_Single_Session_and_Growth_Mindset_Intervention.md) |

---

## 🗂️ 二、 75 种心理治疗方法完整分类总目录 (Master Catalog of 75 Psychotherapy Methods)

### 第一部分：第一、二代认知与行为治疗流派 (1st & 2nd Wave Cognitive & Behavioral Therapies)
1. [**01_CBT_Cognitive_Behavioral_Therapy.md**](./01_CBT_Cognitive_Behavioral_Therapy.md) — 🟢 Grade A **传统认知行为疗法 (CBT)** | Aaron T. Beck, Judith S. Beck, David Burns | 识别自动思维、苏格拉底式提问、三栏/五栏思维记录表、去灾难化、双重标准好友视角与行为实验
2. [**02_REBT_Rational_Emotive_Behavior_Therapy.md**](./02_REBT_Rational_Emotive_Behavior_Therapy.md) — 🟢 Grade A **理性情绪行为疗法 (REBT)** | Albert Ellis | ABCDE 模型、拆解三大绝对化要求（Musturbations）、反糟糕至极化、提升挫折耐受度与无条件自我接纳 (USA)
3. [**03_BA_Behavioral_Activation.md**](./03_BA_Behavioral_Activation.md) — 🟢 Grade A **行为激活疗法 (BA)** | Christopher Martell, Sona Dimidjian, Peter Lewinsohn | 行动先于动力、TRAP $\rightarrow$ TRAC 回避模式阻断、愉悦感与掌控感 (M&P) 监测、零阻力 2 分钟微破冰
4. [**04_ERP_Exposure_and_Response_Prevention.md**](./04_ERP_Exposure_and_Response_Prevention.md) — 🔴 Grade C **暴露与反应阻止疗法 (ERP)** | Victor Meyer, Edna Foa, Michelle Craske | 强迫症 (OCD) 一线金标准：暴露阶梯构建、仪式行为阻止、习惯化与抑制性学习模型（预期违背）
5. [**05_Systematic_Desensitization_and_Exposure.md**](./05_Systematic_Desensitization_and_Exposure.md) — 🔴 Grade C **系统脱敏、分级暴露与内感受暴露疗法** | Joseph Wolpe, David Barlow | 交互抑制原理、SUDS 主观焦虑阶梯、特定恐惧症分级脱敏与惊恐障碍内感受暴露 (Interoceptive Exposure)
6. [**06_CBT_I_Insomnia_Cognitive_Behavioral_Therapy.md**](./06_CBT_I_Insomnia_Cognitive_Behavioral_Therapy.md) — 🟢 Grade A **失眠认知行为疗法 (CBT-I)** | Arthur Spielman, Richard Bootzin, Allison Harvey | 慢性失眠一线金标准：3P 模型、刺激控制、睡眠限制、睡前烦恼暂存盒 (Constructive Worry Pad) 与矛盾意向
7. [**07_PST_Problem_Solving_Therapy.md**](./07_PST_Problem_Solving_Therapy.md) — 🟢 Grade A **问题解决疗法 (PST)** | Thomas D'Zurilla, Arthur Nezu | 积极问题取向调校、问题定义与目标拆解、头脑风暴去评判法则、决策利弊矩阵与执行复盘
8. [**08_UP_Unified_Protocol_Transdiagnostic.md**](./08_UP_Unified_Protocol_Transdiagnostic.md) — 🟢 Grade A **情绪障碍跨诊断统一方案 (UP)** | David H. Barlow | 针对焦虑与抑郁共病核心机制：情绪三成分 ARC 分析、非评判性正念情绪觉察、识别并逆转情绪驱动行为 (EDB)
9. [**09_CBASP_Cognitive_Behavioral_Analysis_System.md**](./09_CBASP_Cognitive_Behavioral_Analysis_System.md) — 🟡 Grade B **认知行为分析系统心理治疗 (CBASP)** | James P. McCullough Jr. | 专为慢性持续性抑郁设计：情境分析 (Situational Analysis) 六步法、重要他人印记识别与人际区分练习
10. [**10_HRT_Habit_Reversal_and_Contingency_Management.md**](./10_HRT_Habit_Reversal_and_Contingency_Management.md) — 🟢 Grade A **习惯逆转训练与权变管理 (HRT & CM)** | Nathan Azrin, Douglas Woods, Stephen Higgins | 针对抽动、拔毛、咬甲及行为成瘾：早期前兆冲动觉察训练、竞争性反应训练、刺激控制与即时强化物权变管理

### 第二部分：第三代认知行为、正念与慈悲流派 (3rd Wave CBT, Mindfulness & Compassion Therapies)
11. [**11_ACT_Acceptance_and_Commitment_Therapy.md**](./11_ACT_Acceptance_and_Commitment_Therapy.md) — 🟢 Grade A **接纳承诺疗法 (ACT)** | Steven C. Hayes, Russ Harris | 心理灵活性六边形模型 (Hexaflex)、认知解离广播前缀、情绪扩展空间呼吸、观察性自我、痛苦背面的价值罗盘与承诺行动
12. [**12_DBT_Dialectical_Behavior_Therapy.md**](./12_DBT_Dialectical_Behavior_Therapy.md) — 🟢 Grade A **辩证行为疗法 (DBT)** | Marsha M. Linehan | 接纳与改变的辩证综合：智慧心 (Wise Mind)、痛苦耐受 (TIPP/STOP/彻底接纳)、情绪调节 (相反行动) 与人际效能 (DEAR MAN / GIVE / FAST)
13. [**13_RO_DBT_Radically_Open_DBT.md**](./13_RO_DBT_Radically_Open_DBT.md) — 🟢 Grade A **彻底开放辩证行为疗法 (RO-DBT)** | Thomas R. Lynch | 专治过度控制 (Overcontrol)、严苛完美主义与难治性抑郁：Big Three + 1 社交安全信号激活、灵活心与自我探究 (Self-Enquiry)
14. [**14_MBCT_Mindfulness_Based_Cognitive_Therapy.md**](./14_MBCT_Mindfulness_Based_Cognitive_Therapy.md) — 🟢 Grade A **正念认知疗法 (MBCT)** | Zindel Segal, Mark Williams, John Teasdale | 预防抑郁复发金标准：从“行动模式 (Doing Mode)”切换到“存在模式 (Being Mode)”、三分钟呼吸空间与念头去中心化
15. [**15_MBSR_Mindfulness_Based_Stress_Reduction.md**](./15_MBSR_Mindfulness_Based_Stress_Reduction.md) — 🟢 Grade A **正念减压疗法 (MBSR)** | Jon Kabat-Zinn | 正念七大态度支柱、全身躯体扫描 (Body Scan)、正念呼吸与行走、RAIN 四步情绪安顿法、打破自动应激反应
16. [**16_MCT_Metacognitive_Therapy.md**](./16_MCT_Metacognitive_Therapy.md) — 🟢 Grade A **元认知疗法 (MCT)** | Adrian Wells | 阻断认知注意综合征 (CAS)：念头列车站台法（超然正念 Detached Mindfulness）、担忧/反刍推迟实验与注意力训练技术 (ATT)
17. [**17_CFT_Compassion_Focused_Therapy.md**](./17_CFT_Compassion_Focused_Therapy.md) — 🟢 Grade A **慈悲聚焦疗法 (CFT)** | Paul Gilbert | 进化心理学三大情绪调节系统（威胁/驱力/安抚系统）平衡、“非你的错 (Tricky Brain)”去羞耻化、抚慰节奏呼吸与慈悲书信
18. [**18_MSC_Mindful_Self_Compassion.md**](./18_MSC_Mindful_Self_Compassion.md) — 🟢 Grade A **正念自我关怀疗法 (MSC)** | Kristin D. Neff, Christopher Germer | 自我友善 × 共通人性 × 正念觉察：自我关怀三步轻抚暂停 (Self-Compassion Break)、催产素安抚性轻触与重塑内在关怀之声
19. [**19_Schema_Therapy.md**](./19_Schema_Therapy.md) — 🟡 Grade B **图式疗法 (Schema Therapy)** | Jeffrey E. Young, Arnoud Arntz | 五大核心情感需求、18 种早期适应不良图式、图式模式对话（安抚脆弱儿童、对抗严苛惩罚型父母、赋能健康成人）与有限再养育
20. [**20_FAP_Functional_Analytic_Psychotherapy.md**](./20_FAP_Functional_Analytic_Psychotherapy.md) — 🟡 Grade B **功能分析心理治疗 (FAP)** | Robert Kohlenberg, Mavis Tsai | 临床相关行为 (CRB1 问题行为 / CRB2 当下改善行为) 实时识别与自然强化、觉察-勇气-爱 (ACL) 人际联结模型

### 第三部分：创伤、危机与躯体神经科学流派 (Trauma-Focused, Crisis & Somatic Therapies)
21. [**21_EMDR_Eye_Movement_Desensitization_Reprocessing.md**](./21_EMDR_Eye_Movement_Desensitization_Reprocessing.md) — 🔴 Grade C **眼动脱敏与再加工疗法 (EMDR)** | Francine Shapiro | WHO 推荐创伤一线疗法：适应性信息加工模型 (AIP)、八阶段标准协议、双侧刺激 (BLS)、安全岛建构与蝴蝶拍安抚法 (Butterfly Hug)
22. [**22_CPT_Cognitive_Processing_Therapy.md**](./22_CPT_Cognitive_Processing_Therapy.md) — 🔴 Grade C **认知加工疗法 (CPT)** | Patricia A. Resick | PTSD 一线认知疗法：识别创伤同化与过度顺应卡点 (Stuck Points)、撰写创伤影响力声明、重构安全/信任/控制/自尊/亲密五大主题
23. [**23_PE_Prolonged_Exposure_Therapy.md**](./23_PE_Prolonged_Exposure_Therapy.md) — 🔴 Grade C **延长暴露疗法 (PE)** | Edna B. Foa | 情绪加工理论、恐惧结构修正、现场暴露 (In Vivo) 与创伤记忆想象暴露 (Imaginal Exposure) 及热点加工
24. [**24_SE_Somatic_Experiencing.md**](./24_SE_Somatic_Experiencing.md) — 🔴 Grade C **躯体体验疗法 (SE)** | Peter A. Levine | 创伤的自主神经冻僵解冻模型：SIBAM 五通道追踪、资源化、滴定法 (Titration)、摆荡法 (Pendulation) 与完成防御反应
25. [**25_SP_Sensorimotor_Psychotherapy.md**](./25_SP_Sensorimotor_Psychotherapy.md) — 🔴 Grade C **感官运动心理治疗 (SP)** | Pat Ogden | 自下而上 (Bottom-Up) 躯体加工、容受之窗 (Window of Tolerance) 调控、躯体边界姿态实验与程序性记忆重塑
26. [**26_NET_Narrative_Exposure_Therapy.md**](./26_NET_Narrative_Exposure_Therapy.md) — 🔴 Grade C **叙事暴露疗法 (NET)** | Maggie Schauer, Frank Neuner, Thomas Elbert | 针对多重与复合创伤：冷热记忆整合、生命之绳 (Lifeline：鲜花与石头) 铺设与自传体时间线连贯叙事构建
27. [**27_TF_CBT_Trauma_Focused_CBT.md**](./27_TF_CBT_Trauma_Focused_CBT.md) — 🔴 Grade C **创伤聚焦认知行为疗法与意象重构 (TF-CBT & ImRs)** | Judith Cohen, Arnoud Arntz | PRACTICE 八步组件模型、渐进式创伤叙事与早期创伤记忆意象改写 (Imagery Rescripting) 三阶段法
28. [**28_Polyvagal_and_Autonomic_Somatic_Regulation.md**](./28_Polyvagal_and_Autonomic_Somatic_Regulation.md) — 🟢 Grade A **生理性叹息与自主神经躯体调节法** | Stephen Porges, Deb Dana, Andrew Huberman | 神经觉与自主神经调节、斯坦福生理性叹息（两短吸一长呼）、迷走神经张力激活与下颌双肩微松脱
29. [**29_PMR_and_Autogenic_Training.md**](./29_PMR_and_Autogenic_Training.md) — 🟢 Grade A **渐进性肌肉放松与自律训练法 (PMR & AT)** | Edmund Jacobson, Johannes Schultz | 16/7/4 肌群“绷紧-松弛”对比训练、躯体残余张力扫描与自律训练六大温暖/沉重感标准暗示公式
30. [**30_PFA_Psychological_First_Aid_and_Crisis_Intervention.md**](./30_PFA_Psychological_First_Aid_and_Crisis_Intervention.md) — 🟢 Grade A **心理急救与自我安全自检模型 (PFA)** | WHO / NCTSN, Stanley & Brown | 急性危机稳定化：观看-倾听-联结三原则、5-4-3-2-1 感官着陆锚、自我安全需求盘点与 Stanley-Brown 自杀预防安全计划

### 第四部分：精神分析与现代心理动力学流派 (Psychoanalytic & Psychodynamic Therapies)
31. [**31_Classical_Psychoanalysis_and_Free_Association.md**](./31_Classical_Psychoanalysis_and_Free_Association.md) — 🔴 Grade C **经典精神分析与自由联想/防御分析** | Sigmund Freud, Anna Freud | 潜意识冲突、自我防御机制层级识别（压抑/投射/理智化/反向形成/升华）、自由联想、移情解析与修通
32. [**32_STPP_Short_Term_Psychodynamic_Psychotherapy.md**](./32_STPP_Short_Term_Psychodynamic_Psychotherapy.md) — 🔴 Grade C **短程心理动力学与时间限定动力治疗 (STPP / TLDP)** | David Malan, Lester Luborsky, Hanna Levenson | 冲突三角形与人际三角形、核心冲突关系主题 (CCRT：愿望-他人反应-自我反应) 与循环适应不良模式 (CMP) 修正
33. [**33_MBT_Mentalization_Based_Treatment.md**](./33_MBT_Mentalization_Based_Treatment.md) — 🟡 Grade B **心智化基础疗法 (MBT)** | Anthony Bateman, Peter Fonagy | 提升情绪高唤醒下的心智化能力：识别心理等同（想即事实）与假装模式、保持“不知之态 (Not-Knowing)”与暂停倒回技术
34. [**34_TFP_Transference_Focused_Psychotherapy.md**](./34_TFP_Transference_Focused_Psychotherapy.md) — 🔴 Grade C **移情焦点心理治疗 (TFP)** | Otto F. Kernberg, Frank Yeomans | 识别客体关系二元配对与角色反转、澄清-面质-诠释三步技术、整合“全好/全坏”分裂表象
35. [**35_Object_Relations_and_Attachment_Based_Therapy.md**](./35_Object_Relations_and_Attachment_Based_Therapy.md) — 🟡 Grade B **客体关系与依恋取向心理治疗** | Donald Winnicott, Melanie Klein, John Bowlby | “足够好的母亲 (Good-Enough)”、抱持性环境、真自我 vs 顺从型假自我、安全基地与依恋内部工作模型重塑
36. [**36_Self_Psychology_Kohut.md**](./36_Self_Psychology_Kohut.md) — 🟡 Grade B **自体心理学治疗 (Self Psychology)** | Heinz Kohut | 三大自体客体需求（镜映需求 Mirroring、理想化需求 Idealizing、孪生需求 Twinship）修复、共情浸润与变形内化
37. [**37_Jungian_Analytical_Psychology.md**](./37_Jungian_Analytical_Psychology.md) — 🟡 Grade B **荣格分析心理学与积极想象技术** | Carl Gustav Jung | 自性化进程、人格面具 (Persona) 与阴影 (Shadow) 整合、情结探索、积极想象对话 (Active Imagination) 与梦境扩充
38. [**38_Adlerian_Individual_Psychology.md**](./38_Adlerian_Individual_Psychology.md) — 🟡 Grade B **阿德勒个体心理学疗法** | Alfred Adler, Rudolf Dreikurs | 目的论（原因论 vs 目的论）、自卑感超越、早期记忆与生活风格分析、“课题分离 (Separation of Tasks)”、仿佛技术与社会兴趣赋能

### 第五部分：人本主义、存在主义与体验聚焦流派 (Humanistic, Existential & Experiential Therapies)
39. [**39_PCT_Person_Centered_Therapy.md**](./39_PCT_Person_Centered_Therapy.md) — 🟡 Grade B **以人为中心疗法 / 来访者中心疗法 (PCT)** | Carl R. Rogers | 治疗改变的三大核心条件（真诚一致、无条件积极关注、准确共情理解）、解除价值条件化、深度情感反映与陪伴倾听
40. [**40_EFT_Emotion_Focused_Therapy.md**](./40_EFT_Emotion_Focused_Therapy.md) — 🟡 Grade B **情绪聚焦疗法 (EFT)** | Leslie S. Greenberg, Sue Johnson | 剥离次生防御性愤怒以触及原发脆弱情绪、“以情绪转化情绪”、自我批判双椅对话、未竟事务空椅工作与伴侣追逃循环解构
41. [**41_Existential_Psychotherapy.md**](./41_Existential_Psychotherapy.md) — 🟡 Grade B **存在主义心理治疗** | Irvin D. Yalom, Rollo May | 直面四大终极存在议题（死亡、自由与责任、存在性孤独、无意义感）、转化未活出生命的“存在性内疚”、生命回顾练习
42. [**42_Logotherapy_Viktor_Frankl.md**](./42_Logotherapy_Viktor_Frankl.md) — 🟢 Grade A **意义疗法 (Logotherapy)** | Viktor E. Frankl | 意义意志、发现意义的三大途径（创造/体验/苦难中的态度价值）、矛盾意向法 (Paradoxical Intention) 与去反省法 (Dereflection)
43. [**43_Gestalt_Therapy.md**](./43_Gestalt_Therapy.md) — 🟡 Grade B **格式塔疗法 / 完形疗法 (Gestalt Therapy)** | Fritz Perls, Laura Perls | 此时此地觉察连续体、改变的悖论理论、空椅子技术 (Empty Chair)、优劣势犬 (Topdog-Underdog) 内在冲突整合与夸张实验
44. [**44_Focusing_Oriented_Psychotherapy.md**](./44_Focusing_Oriented_Psychotherapy.md) — 🟢 Grade A **聚焦取向心理治疗 (Focusing)** | Eugene T. Gendlin | 连接身体模糊的整体内隐感受——“体会 (Felt Sense)”、聚焦标准六步法（清理空间 $\rightarrow$ 体会 $\rightarrow$ 把手词 $\rightarrow$ 核对 $\rightarrow$ 询问 $\rightarrow$ 领受）
45. [**45_AEDP_Accelerated_Experiential_Dynamic_Psychotherapy.md**](./45_AEDP_Accelerated_Experiential_Dynamic_Psychotherapy.md) — 🟡 Grade B **加速体验动力学心理治疗 (AEDP)** | Diana Fosha | 撤销孤立 (Undoing Aloneness)、二元情感调节、转化性四状态模型与元治疗加工（“体验到改变正在发生的感觉如何？”）
46. [**46_MI_Motivational_Interviewing.md**](./46_MI_Motivational_Interviewing.md) — 🟢 Grade A **动机式访谈与自我决策平衡 (MI)** | William R. Miller, Stephen Rollnick | 化解改变矛盾心理：PACE 核心精神、克制纠正反射、识别改变谈话与决策平衡利弊自主盘点微练习

### 第六部分：家庭系统、人际与内在部分流派 (Systemic, Interpersonal & Internal Parts Therapies)
47. [**47_IFS_Internal_Family_Systems.md**](./47_IFS_Internal_Family_Systems.md) — 🟡 Grade B **内在家庭系统疗法 (IFS)** | Richard C. Schwartz | “没有坏的部分”：识别管理者 (Managers)、救火员 (Firefighters) 与流放者 (Exiles)；唤醒 8C 核心真我 (Self) 与 6F 接触解负流程
48. [**48_Satir_Transformational_Systemic_Therapy.md**](./48_Satir_Transformational_Systemic_Therapy.md) — 🟡 Grade B **萨提亚转化式系统治疗与冰山模型** | Virginia Satir, John Banmen | 个人内在冰山七层探索（行为 $\rightarrow$ 应对姿态 $\rightarrow$ 感受 $\rightarrow$ 观点 $\rightarrow$ 期待 $\rightarrow$ 渴望 $\rightarrow$ 自我）、五种沟通姿态转化与家庭雕塑
49. [**49_IPT_Interpersonal_Psychotherapy.md**](./49_IPT_Interpersonal_Psychotherapy.md) — 🟡 Grade B **人际心理治疗与社会节律疗法 (IPT & IPSRT)** | Gerald Klerman, Myrna Weissman, Ellen Frank | 聚焦四大现实人际领域（哀伤、角色冲突、角色转换、人际缺失）、人际关系盘点与生物-社会节律稳定化
50. [**50_Bowen_Family_Systems_Therapy.md**](./50_Bowen_Family_Systems_Therapy.md) — 🔴 Grade C **鲍温家庭系统理论与自我分化治疗** | Murray Bowen | 自我分化 (Differentiation of Self)、去三角化 (Detriangulation)、代际传递家谱图 (Genogram) 分析与“我立场”表达
51. [**51_Structural_and_Strategic_Family_Therapy.md**](./51_Structural_and_Strategic_Family_Therapy.md) — 🔴 Grade C **结构派与策略派家庭治疗** | Salvador Minuchin, Jay Haley | 调整纠缠或疏离的家庭边界、打破病态跨代同盟、现场重演 (Enactment)、良性重贴标签与悖论症状处方
52. [**52_Milan_Systemic_Family_Therapy.md**](./52_Milan_Systemic_Family_Therapy.md) — 🔴 Grade C **米兰系统派家庭治疗与循环提问** | Mara Selvini Palazzoli, Luigi Boscolo, Gianfranco Cecchin | 假设-循环-好奇心三原则、差异性/关系性/时间性循环提问 (Circular Questioning) 与积极赋义
53. [**53_Gottman_Method_Couples_Therapy.md**](./53_Gottman_Method_Couples_Therapy.md) — 🟡 Grade B **戈特曼伴侣治疗法** | John & Julie Gottman | 健全关系之屋七层模型、识别关系末日四骑士（批评/鄙视/防御/冷战）及其解药、柔和开场白与修补尝试
54. [**54_TA_Transactional_Analysis.md**](./54_TA_Transactional_Analysis.md) — 🟡 Grade B **交互分析疗法 / 沟通分析 (TA)** | Eric Berne, Stephen Karpman | 父母-成人-儿童 (PAC) 自我状态切换、跳出卡普曼戏剧三角（迫害者/拯救者/受害者）与人生脚本重决断

### 第七部分：后现代建构主义、积极心理学与专项临床方案 (Postmodern, Positive & Specialized Protocols)
55. [**55_SFBT_Solution_Focused_Brief_Therapy.md**](./55_SFBT_Solution_Focused_Brief_Therapy.md) — 🟢 Grade A **焦点解决短程治疗 (SFBT)** | Steve de Shazer, Insoo Kim Berg | 未来与资源导向：奇迹提问 (Miracle Question)、探寻例外经验 (Exceptions)、0-10 分评量提问与应对提问
56. [**56_Narrative_Therapy.md**](./56_Narrative_Therapy.md) — 🟡 Grade B **叙事疗法 (Narrative Therapy)** | Michael White, David Epston | “人是人，问题是问题”：问题外化对话 (Externalizing)、发掘闪光事件 (Unique Outcomes) 与重写偏爱生命故事
57. [**57_PPT_Positive_Psychotherapy_and_Well_Being_Therapy.md**](./57_PPT_Positive_Psychotherapy_and_Well_Being_Therapy.md) — 🟢 Grade A **积极心理治疗与幸福感疗法 (PPT & WBT)** | Martin Seligman, Tayyab Rashid, Giovanni Fava | PERMA 幸福模型、三件好事练习、24 项性格优势识别与运用、阻断“不配感到快乐”的自动信念
58. [**58_CGT_Complicated_Grief_Therapy.md**](./58_CGT_Complicated_Grief_Therapy.md) — 🟡 Grade B **复杂性哀伤疗法与双程应对模型 (CGT & DPM)** | M. Katherine Shear, Margaret Stroebe | 在“丧失导向”与“重建导向”之间健康摆荡、与逝者的想象对话、转化幸存者内疚与重建生活联结
59. [**59_CBT_E_Enhanced_CBT_for_Eating_Disorders.md**](./59_CBT_E_Enhanced_CBT_for_Eating_Disorders.md) — 🔴 Grade C **进食障碍强化认知行为疗法 (CBT-E)** | Christopher G. Fairburn | 跨诊断进食障碍一线方案：重构自我价值过度依赖体型饼图、建立规律进食、阻断身材核查与情绪性暴食
60. [**60_Coherence_Therapy_and_Memory_Reconsolidation.md**](./60_Coherence_Therapy_and_Memory_Reconsolidation.md) — 🟡 Grade B **一致性疗法与治疗性记忆再巩固技术** | Bruce Ecker, Laurel Hulley | 症状必然性原则、发现内隐情绪真相、通过“并置体验 (Juxtaposition Experience)”在神经突触层面改写旧情绪学习

### 第八部分：东方本土、表达性艺术与前沿专项微干预流派 (Eastern Indigenous, Expressive Arts & Specialized Neuro-Interventions)
61. [**61_Morita_Therapy.md**](./61_Morita_Therapy.md) — 🟢 Grade A **森田疗法 (Morita Therapy)** | 森田正马 (Shoma Morita) | “顺其自然，为所当为”：打破精神交互作用与思想矛盾、揭示生的欲望、从情绪本位转向目的本位行动
62. [**62_Naikan_Therapy.md**](./62_Naikan_Therapy.md) — 🟢 Grade A **内观疗法 (Naikan Therapy)** | 吉本伊信 (Ishin Yoshimoto) | 结构化关系“自省三问”（对方为我做了什么/我回报了什么/我添了什么麻烦）、修正自我中心记忆偏见与日常感恩内省
63. [**63_Psychodrama_Moreno.md**](./63_Psychodrama_Moreno.md) — 🟡 Grade B **心理剧疗法 (Psychodrama)** | Jacob L. Moreno, Zerka Moreno | 在“盈余现实”舞台上激活自发性：角色互换 (Role Reversal)、内心替身扩音 (Doubling)、镜照与单人微心理剧
64. [**64_Sandplay_and_Expressive_Arts_Therapy.md**](./64_Sandplay_and_Expressive_Arts_Therapy.md) — 🟡 Grade B **沙盘游戏与表达性艺术治疗** | Dora Kalff, Natalie Rogers | 自由与受保护的空间、绕过语言防御的视觉/触觉象征外化、情绪曼陀罗绘画与多模态创造性联结
65. [**65_Expressive_Writing_Pennebaker.md**](./65_Expressive_Writing_Pennebaker.md) — 🟢 Grade A **表达性书写疗法 (Expressive Writing)** | James W. Pennebaker, Sian Beilock | 连续 4 天 × 15 分钟深度情绪叙事书写、代词视角转换、考前 10 分钟工作记忆担忧卸载书写
66. [**66_IRT_Imagery_Rehearsal_Therapy_for_Nightmares.md**](./66_IRT_Imagery_Rehearsal_Therapy_for_Nightmares.md) — 🟢 Grade A **意象预演疗法与梦魇改写技术 (IRT)** | Barry Krakow | 慢性噩梦一线疗法：白天清醒状态下截断并改写梦魇结局、视觉化预演新安全剧本
67. [**67_Yalom_Interpersonal_Group_Psychotherapy.md**](./67_Yalom_Interpersonal_Group_Psychotherapy.md) — 🟡 Grade B **亚隆人际团体心理治疗与 11 个疗效因子** | Irvin D. Yalom, Molyn Leszcz | 普遍性去孤立化、利他主义赋能、此时此地人际镜照反馈闭环与修正性情绪体验
68. [**68_Hakomi_Mindful_Somatic_Psychotherapy.md**](./68_Hakomi_Mindful_Somatic_Psychotherapy.md) — 🟡 Grade B **哈科米正念躯体心理治疗 (Hakomi)** | Ron Kurtz | 道家非暴力顺势原则、正念状态言语探针实验 (Verbal Probes)、接管防御 (Taking Over) 与滋养缺失体验
69. [**69_SSI_Single_Session_and_Growth_Mindset_Intervention.md**](./69_SSI_Single_Session_and_Growth_Mindset_Intervention.md) — 🟢 Grade A **单次结构化心理微干预与成长型思维赋能 (SSI)** | Moshe Talmon, Jessica L. Schleider | B.E.S.T. 单次起效框架：脑科学神经可塑性去标签、“说服同路人即内化于己”练习与 If-Then 执行意图
70. [**70_Biofeedback_and_HRV_Neuroregulation_Therapy.md**](./70_Biofeedback_and_HRV_Neuroregulation_Therapy.md) — 🟢 Grade A **生物反馈与心率变异性共振呼吸疗法 (HRVB)** | Paul Lehrer, Evgeny Vaschillo | 0.1 Hz 共振频率呼吸（4 秒轻吸 : 6 秒慢呼）、最大化迷走神经张力与心血管压力反射共振
71. [**71_ABFT_Attachment_Based_Family_Therapy.md**](./71_ABFT_Attachment_Based_Family_Therapy.md) — 🔴 Grade C **依恋取向家庭治疗 (ABFT)** | Guy S. Diamond, Gary M. Diamond | 针对青年抑郁与原生家庭关系裂痕：从症状指责转向依恋修复五任务、剥离愤怒下的脆弱与矫正性依恋对话
72. [**72_Meaning_Reconstruction_Grief_Therapy.md**](./72_Meaning_Reconstruction_Grief_Therapy.md) — 🟢 Grade A **意义重构哀伤疗法 (Meaning Reconstruction)** | Robert A. Neimeyer | 持续性联结 (Continuing Bonds)、生命印记与精神遗产盘点、“你好，再相逢”书信与生命之书新章节重写
73. [**73_CBT_HA_Health_Anxiety_and_Somatic_Symptoms.md**](./73_CBT_HA_Health_Anxiety_and_Somatic_Symptoms.md) — 🟡 Grade B **疾病焦虑与躯体症状认知行为疗法 (CBT-HA)** | Paul M. Salkovskis, Hilary Warwick | 针对疑病与恐病网络搜索：理论 A vs 理论 B 双重假说检验、躯体注意聚光灯实验、停止查体与网搜实验
74. [**74_PCIT_Parent_Child_Interaction_Therapy.md**](./74_PCIT_Parent_Child_Interaction_Therapy.md) — 🟢 Grade A **亲子互动去威胁肯定疗法 (PCIT)** | Sheila M. Eyberg | 连接先于纠正：每日 5 分钟特殊时光、PRIDE 五大具体正向关注技术与戒除“命令/审问/挑刺”三毒药
75. [**75_ERT_Emotion_Regulation_Therapy.md**](./75_ERT_Emotion_Regulation_Therapy.md) — 🟢 Grade A **情绪调节疗法 (ERT)** | Douglas S. Mennin, David M. Fresco | 校准“安全刹车 vs 奖赏油门”动机失衡、按神经负荷由浅入深三级时序调节（注意定向 $\rightarrow$ 时空去中心化 $\rightarrow$ 勇气与慈悲重估）

---

## 📖 三、 跨流派奠基与循证总参考文献 (Foundational & Meta-Analytic Master References)

1. **American Psychological Association (APA), Division 12 (Society of Clinical Psychology).** (2024). *Empirically Supported Treatments (PsychologicalTreatments.org)*. Based on Tolin, D. F., McKay, D., Forman, E. M., Klonsky, E. D., & Thombs, B. D. (2015). Empirically supported treatment: Recommendations for a new model. *Clinical Psychology: Science and Practice*, 22(4), 317–338.
2. **Barkham, M., Lutz, W., & Castonguay, L. G. (Eds.).** (2021). *Bergin and Garfield's handbook of psychotherapy and behavior change* (7th ed.). John Wiley & Sons.
3. **Wampold, B. E., & Imel, Z. E.** (2015). *The great psychotherapy debate: The evidence for what makes psychotherapy work* (2nd ed.). Routledge.
4. **Norcross, J. C., & Wampold, B. E.** (2018). A new therapy for each patient: Evidence-based relationships and responsiveness. *Journal of Clinical Psychology*, 74(11), 1889–1906.
5. **Cuijpers, P., Miguel, C., Harrer, M., Plessen, C. Y., Ciharova, M., Ebert, D., & Karyotaki, E.** (2023). Cognitive behavior therapy vs. control conditions, other psychotherapies, pharmacotherapies and combined treatment for depression: A comprehensive meta-analysis including 409 trials with 52,702 patients. *World Psychiatry*, 22(1), 105–115.
6. **Hofmann, S. G., Asnaani, A., Vonk, I. J., Sawyer, A. T., & Fang, A.** (2012). The efficacy of cognitive behavioral therapy: A review of meta-analyses. *Cognitive Therapy and Research*, 36(5), 427–440.
7. **Prochaska, J. O., & Norcross, J. C.** (2018). *Systems of psychotherapy: A transtheoretical analysis* (9th ed.). Oxford University Press.
