# Py-GC-MS 数据结果人工验证指南（Human Verification Guide）

> 自动 QC 保证"管道正确"（脚本跑通、闭合、无 NaN）；人工验证保证"科学正确"
> （峰鉴定合理、裁决可靠、结论经得起审稿）。两者缺一不可。
> 本指南配合 `rigor-checklist.md` 使用：清单是全项目流程自检，本文件专讲
> **拿到结果后如何人工核验其可靠性**。

---

## 0. 验证时机

- **每次** workflow 跑完后（Stage 0-5 输出即验证）
- **重点**：在结果进入统计/写作之前（Stage 6-9 之前）
- **再审**：投稿前对照 reviewer 可能质疑的点再过一遍

---

## 1. 验证输入（工作流自动产物）

| 文件 | 验证什么 |
|------|---------|
| `results/05_final/final_qc.json` | 7 项自动 QC 是否全 PASS |
| `results/run_manifest.json` | 参数留痕、各阶段 PASS/FAIL、有无 SKIP |
| `results/01_clean/features_clean.csv` | 峰级原始数据（name_raw 不可变基线） |
| `results/03_ei/ei_decisions.csv` | EI 冲突裁决表（UNIFIED/GENUINE_DIFF） |
| `results/04_tmah/tmah_decisions.csv` | TMAH 试剂峰决策表（EXCLUDE/REVIEW） |
| `results/05_final/audit_trail.csv` | 逐峰变更记录（RECLASS/EXCLUDE） |
| `results/05_final/features_final.csv` | FINAL 峰级数据（论文数据来源） |
| `results/05_final/class_composition_final.csv` | 类级组成（核心结果表） |

---

## 2. 验证层次与操作

### 第 1 层：自动 QC 结果审查（~5 分钟）

```python
import json
qc = json.load(open(r"results/05_final/final_qc.json"))
print(qc["status"])                      # 必须 PASS
for k, v in qc["checks"].items():
    print(("OK  " if v["ok"] else "FAIL"), k, "|", v["detail"])
```

- [ ] `final_qc.json` status == PASS
- [ ] 每样品面积闭合 ≈ 100%（99.99-100.01）
- [ ] peak_id 0 重复、无 NaN、无负面积
- [ ] `run_manifest.json` 中无意外 SKIP（无 QGD 时 G3/G4 SKIP 属正常，但必须在报告中声明"未做谱级验证"）
- [ ] manifest 参数与实验记录一致（SI 阈值、cosine、TMAH 阈值）

### 第 2 层：数据完整性对账（~15 分钟）

峰数链条必须对得上：

```
原始 TXT 峰数 ──SI/污染/TMAH 剔除──> features_clean 峰数 ──EI/TMAH 决策──> FINAL 活跃峰数
```

- [ ] 用 `04_supplementary_notes` 或手动汇总三处峰数，逐步解释每个减少环节
- [ ] 抽查 3-5 个原始 TXT 峰：在 `features_clean.csv` 中能找到，RT/面积/SI 一致
- [ ] 0 与 NA 语义核对：`status=EXCLUDED` + `exclusion_reason` 非空（未被静默删除）

### 第 3 层：关键决策抽样复核（~30 分钟，最重要）

**EI 裁决抽样**（`ei_decisions.csv`）：
- [ ] 按 RT 排序抽 10-20%（至少 10 条），UNIFIED 与 GENUINE_DIFF 都要覆盖
- [ ] 对每条：用 `qgd_reader.py` 提取各处理该 RT 的 EI 谱，肉眼确认 cosine≥0.85 合理
- [ ] 重点检查 UNIFIED 中改类幅度大的（如 Other_N→Alkenes、Phenols→MAH）
- [ ] GENUINE_DIFF 是否真的是不同化合物（而非批次/柱老化造成的谱漂移）

**TMAH 剔除抽样**（`tmah_decisions.csv`）：
- [ ] 抽全部 EXCLUDE 峰，确认谱型 = m/z 58 基峰 + 59/42 特征簇
- [ ] 确认没有把真实含 N 化合物误删（有高分子量碎片 ≠ 试剂峰）
- [ ] 如检出 REVIEW（weak signal），人工裁定保留或剔除并记录理由

**audit_trail 检查**：
- [ ] 每条 RECLASS 的 before/after 类是否合理（如 Naphthalene 从 Alkenes→PAH 正确）
- [ ] 确认没有峰被"改名成不存在的东西"或消失无痕

### 第 4 层：谱级金标准验证（关键化合物，~30 分钟）

- [ ] 列出支撑核心结论的化合物清单（如 PAH、lignin 标记物、N-杂环、FAME）
- [ ] 逐个用 `qgd_reader.QGDFile.get_spectrum_at_rt(rt)` 提取 EI 谱，与 NIST 库谱并排对比
- [ ] 记录每个关键化合物的 MSI 置信度（Level 1-4），论文中如实标注
- [ ] **核心规则**：错误 ID 会通过分类被放大成"碳库机制"错误——关键化合物必须人工确认

### 第 5 层：统计与解释审查（~15 分钟）

- [ ] n=1 时：无 ANOVA/p 值，只有描述性趋势 + bootstrap CI（峰级）
- [ ] CI 重叠时：表述为"无法区分"，不写"趋势显著"
- [ ] R_MP 表述为"半定量指示"，不写"微生物碳/植物碳比例"
- [ ] 相对峰面积表述：`the relative contribution of X-derived pyrolysis products`
      而非 `X carbon increased by Y%`
- [ ] 结论与 TG-DSC 等独立方法方向收敛（若有数据）

### 第 6 层：可复现性与敏感性验证（~20 分钟）

- [ ] 相同 config 重跑：结果逐位一致（随机过程设 seed）
- [ ] 换 SI 阈值（70/80/90）重跑：核心结论方向稳定
- [ ] （有 QGD 时）换 EI cosine（0.80/0.85/0.90）：UNIFIED/DIFF 比例合理变化
- [ ] 记录所有重跑命令与日期到项目日志

---

## 3. 快速抽样脚本（推荐）

```python
"""人工验证抽样工具：从决策表抽取待人工复核的峰。"""
import csv, random

random.seed(42)

def sample_verdicts(path, n=10):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    by = {}
    for r in rows:
        by.setdefault(r["verdict"], []).append(r)
    picks = []
    for verdict, items in by.items():
        picks += random.sample(items, min(n, len(items)))
    return picks

# EI 裁决抽样
for r in sample_verdicts("results/03_ei/ei_decisions.csv"):
    print(f"{r['feature_id']} RT={r['rt_ref']} {r['verdict']} cosine={r['cosine_min']} -> {r['unified_class']}")

# TMAH 剔除抽样
for r in sample_verdicts("results/04_tmah/tmah_decisions.csv", n=5):
    print(f"{r['peak_id']} RT={r['rt_min']} {r['decision']} mz58={r['mz58_fraction']} {r['reason']}")
```

## 4. 验证结果记录（模板）

```markdown
# 人工验证记录 <project> <date>

## 验证人 / 日期
## 第1层 QC：PASS/FAIL（附 final_qc.json 摘要）
## 第2层 对账：峰数链 ____→____→____，抽查 n 峰全部一致/发现问题：____
## 第3层 抽样：EI 抽 n 条（UNIFIED n/GENUINE_DIFF n），TMAH 抽 n 条
##       发现问题：____ 处理：____
## 第4层 谱级：关键化合物 n 个确认，MSI 分布 L2:n L3:n L4:n
## 第5层 统计：n=1 约束确认 / 发现违规表述：____
## 第6层 重跑：结果一致（是/否），SI 敏感性方向稳定（是/否）
## 结论：数据可靠性 ____（可靠 / 有条件可靠-需修正____ / 不可靠-需重跑）
```

---

## 5. 常见人工发现与处理

| 人工发现 | 处理 |
|---------|------|
| UNIFIED 改类不合理（cosine 高但类别跳跃大） | 回 Stage 3 加 corrections/人工裁定，重跑 G5 |
| TMAH EXCLUDE 误删真实含 N 化合物 | 从 `tmah_decisions.csv` 改为 KEEP，重跑 G5 |
| 关键化合物 SI 低但支撑结论 | 谱级确认后如实标注 MSI Level 3/4，弱化该证据 |
| 峰数对账对不上 | 回 Stage 1 检查解析/过滤，禁止手工补数 |
| 批次差异（时间戳/总面积） | 跨批次结论加注记或排除，不解释为处理效应 |
| 重跑结果不一致 | 检查 seed/版本，修复后重跑，两者都保留记录 |

---

## 6. 原则

1. **人工验证不是"再跑一遍脚本"**，而是"用独立视角质疑结果"
2. **发现任何问题 → 改配置/改决策 → 重跑脚本**，禁止手工改 CSV
3. **验证记录存档**（如 `PY-GC-MS/human-verification.md`），投稿时随附可应对审稿
4. 自动 QC 与人工验证的分工：自动管"数字正确"，人工管"化学/科学正确"
