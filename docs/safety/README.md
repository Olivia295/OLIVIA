# docs/safety：安全证据

> **这不是 DCB0129 的正式安全档案，未经临床安全官签署。** 这里的文件参照 DCB0129 的结构整理工程证据，
> 没有临床安全官（Clinical Safety Officer）签署，也没有临床安全案例报告（Clinical Safety Case Report）。
> 发布门禁 G-0（临床审阅）已由负责人搁置（`docs/superpowers/plans/2026-10-23-next-phase.md` §9.2），
> 所以其中的风险评级是工程判断，不是临床结论；残余风险能否接受由产品负责人判断。

## 这里有什么

| 文件 | 是什么 | 怎么保持准确 |
| :--- | :--- | :--- |
| `hazard-log.md` | 危害日志草稿：每条危害的原因、后果、初始与残余风险（5 × 5 矩阵）、控制措施、证据和状态。 | `scripts/check_hazard_log.py`（在 `scripts/check.sh` 里）检查字段、风险矩阵、证据测试是否存在、引用的已知缺口条数与 `tests/redteam/known_gaps*.yaml` 是否一致，以及汇总表是否最新。 |
| `mutation-report.md` | 危机筛查三个文件（`compose.py`、`tracker.py`、`crisis.py`）的变异测试结果、等价变异的理由和补的测试。 | 静态文档，写明了基于的提交；不会自动重跑，代码大改后需要另做一轮。 |
| `README.md` | 本页。 | — |

相关证据在别处：红队用例与严格 xfail 的已知缺口（`tests/redteam/`）、变形测试的已知缺口
（`tests/safety/known_metamorphic_gaps.yaml`）、需求追溯表（`tests/requirements_trace.yaml`）、热线来源与复核记录
（`docs/resources/hotline-sources.md`）。

## 一条命令复跑

```sh
PYTHONPATH=$PWD .venv/bin/python scripts/safety_report.py [--eval-dir DIR] [--out PATH] [--skip-model]
```

依次运行并汇总成一页 Markdown，默认写到 `build/reports/safety-evidence-<短提交号>.md`（`build/` 不进 git）：

1. **危机识别**：`scripts/eval_crisis.py` 在开发集（`interim_fresh.csv`）与 EVAL-4（`eval4.csv`）上跑规则与模型两种
   模式，报告 L2+L3 召回与 L0 误报（k/n 与 Wilson 95% 区间）。评估集不在仓库里，默认找 `build/eval/`，找不到就写
   “评估集不在本机，跳过”。**开发集用于选型，EVAL-4 只报告。** 每次的统计 JSON 存在报告旁边，可以用
   `scripts/compare_eval.py` 与另一次比较。
2. **变形测试**：`scripts/metamorphic_report.py` 两种模式的总不变率与最差的五种变换。
3. **红队与多轮**：三份 `known_gaps*.yaml` 按类型与类别从条目实际统计，并与文件头写的计数比较，不一致就失败。
4. **危害日志**：`scripts/check_hazard_log.py` 的检查结果，按状态与残余风险的计数，残余风险 ≥ 3 的编号。
5. **变异测试**：引用 `mutation-report.md` 的汇总表（不重跑）。
6. **热线**：`scripts/check_hotline_freshness.py` 的结果、最近核验日期与复核截止日期。
7. **隐私审计与需求追溯**：`scripts/privacy_audit.py`、`scripts/trace_requirements.py` 的结果。

报告头写明提交号、日期、实际运行的风险模型（规则 / 学生模型及其 id）和 Python 版本，结尾列出每项的通过 / 失败 /
跳过。有任何一项失败时退出码为 1，否则为 0（评估集缺失算跳过，不算失败）。`--skip-model` 只跑规则模式，不加载
学生模型。

报告与 JSON **只有计数、比率、日期和检查名**：评估集的句子与 id 从不打印、从不写入；评估脚本失败时只报告退出码
（它的错误信息可能带行 id）。报告反映的是运行时工作区里的代码，工作区有未提交改动时报告头会注明。
