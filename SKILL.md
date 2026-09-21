---
name: pygcms-workflow
description: 端到端 Py-GC-MS 数据分析工作流编排器。从 NIST 导出 TXT 原始数据到论文级结果的完整流程：数据准备 → 解析清洗 → 严谨性验证（10 项检查）→ EI 冲突裁决 → TMAH 试剂峰谱检剔除 → FINAL 组成生成 → 统计与多样性分析 → TG-DSC 交叉验证 → 交付物 → 写作。内置每阶段自我复核门（QA gates）与严谨性清单，确保结果可复现、可审计、方向稳健。调用 pygcms-batch、biochar-soc-knowledge、tg-dsc-analysis、nature-statistics、r-to-manuscript、experimental-design-validator、good-story 等 skill 协同完成。
---

# Py-GC-MS 端到端数据分析工作流

**目标**：把 NIST 导出的 Py-GC-MS TXT（+可选 QGD 原始数据）处理成**经严谨性复核**的分析结果与论文级交付物。
**核心原则**：每一步由脚本产生（可复现）、每阶段有复核门（可审计）、关键结论必须通过敏感性检查（方向稳健）。

---

## 0. 何时使用本 skill

用户提出以下任一需求时，加载 `pygcms-workflow` 作为总编排，并联动其他 skill：

- "处理 Py-GC-MS / 分子组成 / 化合物分类数据"
- "验证 / 复核 Py-GC-MS 数据"、"TMAH 副产物"、"R_MP"、"EI 冲突"、"分子网络"
- "基于 Py-GC-MS 结果写 Results/Discussion"、"分子多样性 / Shannon / 均匀度"
- 任何涉及 `*_原始数据/*.TXT`、`*.qgd`、`shahriar_library` 的任务

---

## 1. 插件（Skill）矩阵 — 各环节用哪个 skill

| 环节 | 主 skill | 辅助 skill / 脚本 | 输出 |
|------|----------|-------------------|------|
| 0 实验设计复核 | `experimental-design-validator` | — | 设计类型、伪重复检查、统计约束声明 |
| 1 解析+初步清洗 | `pygcms-batch` | `scripts/pipeline.py` | 多 sheet Excel（筛选统计/分类/来源） |
| 2 严谨性验证 | `pygcms-batch` | `scripts/verify_data.py` | 10 项检查报告 + 对齐矩阵 + 冲突清单 |
| 3 EI 冲突裁决 | `pygcms-batch` | `scripts/resolve_conflicts_ei.py` + `qgd_reader.py` | conflict_resolution.csv + unified 组成 |
| 4 TMAH 试剂峰谱检 | `pygcms-batch` | `scripts/diag_trimethylamine.py` | m/z 58 试剂峰清单（独立于 NIST 名称） |
| 5 FINAL 组成生成 | 工作流脚本 | `correct_final_tma.py` 参考实现 | FINAL_EIresolved_class_composition.json/md |
| 6 统计与多样性 | `nature-statistics` / `r-to-manuscript` | bootstrap CI、Shannon/Pielou 脚本 | 统计表、多样性指数、R 代码 |
| 7 交叉验证 | `biochar-soc-knowledge` + `tg-dsc-analysis` | `references/tgdsc-pygcms-crosswalk.md` | 多方法收敛性结论 |
| 8 交付物 | 工作流脚本 | `build_deliverable.py` 参考实现 | 01-04 四表 + 说明文档 |
| 9 写作 | `good-story` / `nature-writing` / `r-to-manuscript` | `biochar-soc-knowledge` 术语 | Results/Discussion 段落 |

---

## 2. 主流程（阶段 × 复核门）

```
阶段 0  实验设计复核 ──────────────► 门 G0: 设计类型/伪重复/统计约束已声明
阶段 1  解析 + SI 过滤 + TMAH 副产物剔除 ─► 门 G1: SI 分布/峰数合理，NA≠0 语义正确
阶段 2  verify_data.py 10 项验证 ──────► 门 G2: S0-S4 敏感性方向稳定，对账闭合
阶段 3  EI 冲突裁决（QGD cosine≥0.85）──► 门 G3: UNIFIED/GENUINE_DIFF 合理，批次假象已排查
阶段 4  TMAH 试剂峰谱检剔除（m/z 58）──► 门 G4: 试剂峰独立于名称剔除，报告 keep/removed 双值
阶段 5  FINAL 组成（脚本生成）──────► 门 G5: 由脚本产出非手动，Bulk 批次注记保留
阶段 6  逐峰判定（识别仲裁）─────────► 门 G6: 改判逐条留痕，isomer-ambiguous 已人工确认
阶段 7  统计 + 多样性 ──────────────► 门 G7: n=1 无推断，bootstrap CI 报告
阶段 8  TG-DSC 交叉验证 ────────────► 门 G8: 收敛性结论与单方法一致
阶段 9  交付物四表 ────────────────► 门 G9: 与 FINAL 偏差已说明，0/NA 语义明确
阶段 10 写作 ─────────────────────► 门 G10: 术语正确，统计约束写入 Methods
```

**任一复核门失败** → 停止向下游传递该数据，回到对应阶段修正后重新执行。所有修正必须**重新运行脚本**，禁止交互式改数。

---

## 3. 阶段细节与命令

### 阶段 0：实验设计复核
- 调用 `experimental-design-validator` 检查：设计类型（CRD/RCBD…）、每处理 n、伪重复风险。
- **Py-GC-MS 特有陷阱**：单次上机 n=1、峰面积≠浓度、不同批次不可直接比较（见 G3）。
- 产出：`00_design_notes.md`（含统计约束声明）。

### 阶段 1：解析与初步清洗
```bash
# 基本流程（TMAH 副产物默认剔除 + 重归一化）
python <skill_dir>/pygcms-batch/scripts/pipeline.py \
    --input <TXT_dir> --output <out_dir> \
    --sample_map sample_map.json [--corrections corrections.json]

# 对照组（保留 TMAH，用于对比报告）
python <skill_dir>/pygcms-batch/scripts/pipeline.py \
    --input <TXT_dir> --output <out_dir>_keepTMAH --keep_tmah
```
- 检查 `筛选统计` sheet：峰数、SI 分布、总面积。
- **门 G1**：SI≥80 保留比例合理；异常峰（A/H>20、单峰>30%、窗口>1min）标 NA 而非 0。

### 阶段 2：严谨性验证（核心）
```bash
python <skill_dir>/pygcms-batch/scripts/verify_data.py \
    --input <TXT_dir> --output <verify_dir> \
    [--qgd <QGD_dir>] --sample_map sample_map.json [--corrections corrections.json]
```
10 项检查：完整性 / 异常峰 / 类组成 / R_MP / RT 对齐 / ID 冲突 / 分类修正 / 敏感性 S0-S4 / 对账 / EI 谱验证。
- **门 G2**：S3（推荐主结果）与 S4 方向一致；峰数对账闭合（Σ 关系式成立）。

### 阶段 3：EI 冲突裁决
```bash
python <skill_dir>/pygcms-batch/scripts/resolve_conflicts_ei.py \
    --matrix <verify_dir>/analysis_ready_matrix.csv \
    --qgd <QGD_dir> --sample_map sample_map.json \
    --cosine 0.85 --top_ions 12 --output <dir>/conflict_resolution
```
- **门 G3**：先查批次假象（文件时间戳/总面积）——若多批次，GENUINE_DIFF 可能只是批次差异而非真实处理差异；同批次内 UNIFIED 需多数票合理。

### 阶段 4：TMAH 试剂峰谱检剔除（严谨性关键）
```bash
python <skill_dir>/pygcms-batch/scripts/diag_trimethylamine.py
```
- 扫描各处理 QGD 的 EI 谱，**基峰 m/z 58 + 59/42 碎片比例** → 判为 TMAH 试剂峰，无论 NIST 命名。
- 剔除后重归一化，重新计算类组成与 R_MP。
- **门 G4**：报告 keep-TMAH vs removed 两组 R_MP；N 来源叙事必须在剔除后仍成立。

### 阶段 5：FINAL 组成生成
- 参考 `correct_final_tma.py`：定向剔除谱证实的试剂峰 + 重归一化，输出 FINAL JSON/MD。
- **门 G5**：FINAL 由脚本生成（可复现）；与阶段 2 的 v2 组成偏差在注释中说明原因。

### 阶段 6：逐峰判定（识别仲裁）
解决一个具体而常见的问题：**同一色谱峰在不同处理中 NIST 首位候选 (Hit#1) 不一致**；
且候选间 SI 很接近时（如 92 vs 91），SI 排序**不具区分度**——此时不能用 SI 决定归属。

判据按事先确定的优先级施用（对所有峰、所有样品统一）：

| 优先级 | 判据 |
|---|---|
| **P0 SI 硬门槛** | `SI >= 80`（`filters.si_threshold` / `filters.si_operator`）。**无 SI 的峰视为未鉴定，一律剔除** |
| **P1 谱图证据** | 实测 EI 诊断离子判据。已验证与名称判类的一致率：**PAH 100%、脂肪酸甲酯 100%、MAH 86%** |
| **P2 跨处理比对** | 同一馏分内其它处理中质谱最相似的峰（余弦 ≥ `cos_min`，RT 窗 ±`rt_win`，默认 0.6 min 以容纳跨批漂移）其 Hit#1 的类别 |
| **P3 兜底** | Hit#1 自身的类别 |

判定只到「**类**」为止——聚合指标（难降解比例、类别组成）只需要类，不需要精确化合物身份。

**SI 算子必须在看结果前定死**：`'>='` 与 `'>'` 在本项目数据集上相差 **53 个峰（3.34%）**，
足以静默改变论文里的每一个百分比。实测口径阶梯（1589 峰）：不过滤 100% → `>=70` 82.5%
→ `>=80` 60.5% → `>80` 57.2% → `>=90` 27.7%。本项目用 `>=`（与历史 SI80 工作簿一致）。

**SI 门槛如何"真正贯穿"**：G6 做两件事，缺一即 FAIL（除非
`adjudicate.require_si_enforcement: false`）：
1. 通过 `inspect` 在 `run_fraction` 上找 `si_threshold` / `si_operator` 形参并**传入后端**；
2. **独立复核**后端返回的每一个峰的 SI —— 不信任后端是否真的执行了；找不到 SI 列也判 FAIL。

后端不支持 SI 形参时不静默通过，而是由第 2 步兜底判 FAIL：**响亮失败优于静默降级**。

```bash
python <skill_dir>/pygcms-workflow/scripts/adjudicate.py --config config/config.yaml --out_dir results
# 也可由 run_workflow.py 作为 Stage G6 自动执行（config 中 adjudicate.enabled: true）
#   filters.si_threshold / si_operator           SI 硬门槛（唯一来源）
#   adjudicate.require_si_enforcement            SI 无法落实时 FAIL（默认 true）
#   adjudicate.rt_win / cos_min / allow_isomer_switch / keep_artifacts / fractions
```

产出（`results/06_adjudicate/`）：
- `adjudication_summary.md` / `.json` —— 门 G6 判定 + SI 口径 + 各馏分 R 摘要
- `<馏分>/adjudication.md` —— SI 门槛执行情况、难降解比例 R、类别组成、改判明细
- `<馏分>/adjudication_peaks.csv` —— **逐峰判定与依据**（含 `si` / `si_pass`；`rule` 列写明 P1/P2/P3 或 isomer-ambiguous）
- `<馏分>/adjudication_si_gate.csv` —— 逐样品剔除计数（峰表总数 = 面积≤0 + 副产物 + 无 SI + SI 不达标 + 保留）
- `<馏分>/adjudication_composition.csv`

**难降解比例 R**（Shahriar 2026 降解难易分类）：`R = PAH + 长链烷烃 + MAH + 烯烃 + 木质素`
（V1；V2 把木质素算作易降解）。**两版都要报**——木质素归属在文献中本身有两版。

- **门 G6**：
  1. 所有馏分均产出 R(V1)/R(V2) 与逐峰明细；
  2. **SI 门槛已落实且独立复核通过**（否决项：复核不通过即 FAIL，不允许"配置写了就算"）；
  3. `rule` 含 `isomer-ambiguous` 的峰**必须逐条看谱确认**后才能决定是否改判（门判定为 REVIEW）；
  4. 识别判据事先确定、统一施用——**不得按预期结论挑选候选**（见 §4 一票否决项）。

**P2 的边界**：P2 依赖质谱余弦，**无法区分同分异构体**（如 C8H10 的二甲苯 vs 环戊二烯类，
余弦可达 0.93–0.95）。工具在「两名称互为对方候选」时默认**不采纳 P2 改判**并标注
`isomer-ambiguous`；`--allow-isomer-switch` 可强制改判，但必须在报告中说明理由。

### 阶段 7：统计与多样性
- 计算 Shannon H'、Pielou J'、丰富度 S（用 R 4.x 或 Python 脚本，二选一保持一致性）。
- 每处理 n=1 → **禁止 ANOVA**；用峰级 bootstrap 95% CI（参考 `bootstrap_rmp_ci.py`）。
- **门 G7**：报告全部为描述性趋势 + CI，无 p 值推断。

### 阶段 8：TG-DSC 交叉验证（若有数据）
- 读 `biochar-soc-knowledge/references/tgdsc-pygcms-crosswalk.md`，逐条对照：
  ↑PAH/Phenols ↔ ↑TG-T50、↓多糖 ↔ ↓labile、↑N-杂环 ↔ MAOC T50 等。
- **门 G8**：Py-GC-MS 结论与 TG-DSC 方向一致；矛盾处显式说明。

### 阶段 9：交付物四表
- 参考 `build_deliverable.py` 生成：
  `01_sample_metadata.csv` / `02_compound_abundance.csv`(+转置) / `03_compound_annotation.csv` / `04_supplementary_notes.md`
- **门 G9**：交付物（化合物级）与 FINAL（类级，人工裁决版）关系在 04 中说明；0 与 NA 语义明确。

### 阶段 10：写作
- `good-story` 提炼叙事 → `nature-writing` 起草 → `r-to-manuscript` 落统计表述。
- **门 G10**：R_MP 表述为"半定量指示"；n=1 写入 Methods；Bulk 批次假象不解释为剂量效应。

---

## 4. 严谨性自我复核清单（QA 总表）

交付前逐项自检（详细版见 `references/rigor-checklist.md`）：

- [ ] 每个数值结果都由脚本生成，命令记录在案（可复现）
- [ ] TMAH 副产物剔除（6 种）+ 试剂峰谱检剔除（m/z 58）都执行并报告
- [ ] keep-TMAH 与 removed 双值对比已呈现
- [ ] EI 冲突裁决使用 QGD 谱 cosine≥0.85，非信任 NIST 名称
- [ ] 批次假象已排查（时间戳/总面积），Bulk 跨批处理结论有注记
- [ ] S0-S4 敏感性方向稳定，S3 为主结果
- [ ] 峰数对账闭合；类组成用峰数（SI≥70）与网络节点数（全部谱）分别声明
- [ ] n=1 → 无统计推断；bootstrap CI 报告
- [ ] 0 = 未检出，NA = 峰存在但面积不可靠（绝不混用）
- [ ] 论文正文用 FINAL（人工裁决版），补充材料用 deliverable（化合物级）
- [ ] TG-DSC 交叉验证完成（若数据存在）
- [ ] 术语符合 `_shared/core/user-profile.md`（SOC/MBC/CK/BCxx 等）

---

## 5. 项目标准目录结构

```
<project>/PY-GC-MS/
├── {Fraction}原始数据/          # NIST 导出 TXT (+ .qgd)
├── sample_map.json              # {'5':'CK','6':'BC7.5',...}
├── corrections.json             # {'BC15':{'3.215':'Toluene'}}（可选）
├── cleaned/                     # pipeline 输出（含 _keepTMAH 对照）
├── verification/                # verify_data.py 报告
├── conflict_resolution/         # EI 裁决输出
├── FINAL_EIresolved_class_composition.json
├── cleaned_deliverable/         # 01-04 四表
└── 00_design_notes.md
```

模板见 `references/project-template.md`。

---

## 6. 参考与联动

- **pygcms-batch**：核心脚本与分类库（Shahriar 2026 / Chen 2023 / Kallenbach 2016）
- **biochar-soc-knowledge**：领域知识中心、术语、文献、TG-DSC crosswalk
- **tg-dsc-analysis**：热稳定性分析
- **nature-statistics / r-to-manuscript**：统计与报告
- **good-story / nature-writing**：叙事与写作
- **experimental-design-validator**：设计复核
- 记忆检查点：`pygcms-data-rigor-2026.md`（2026-08-01 严谨性工作流实证）

---

## 7. 工程化流水线（v0.1，一条命令跑通 Stage 0-5）

> 2026-08-25 依据外部审查（saas-nexus-1787639405595）实施的工程化改造：
> 统一配置 + 永久 peak_id + 改名/删除分离 + 数据契约 + 总编排。

### 一键运行
```bash
python scripts/run_workflow.py --config config/config.example.yaml
```
（复制 `config.example.yaml` 为 `config.yaml` 并填写路径；`--batch_scripts` 可指定
pygcms-batch 脚本目录，默认自动探测 `.claude/skills` 布局。）

### 数据契约（Stage 输入/输出标准）
```
results/
├── 00_preflight/preflight_report.json   G0 输入检查（TXT/QGD/sample_map/依赖）
├── 01_clean/features_clean.csv          G1 峰级数据（peak_id/name_raw/current/status）
├── 02_verify/verification_report.md     G2 验证报告 + aligned_peak_matrix.csv
├── 03_ei/ei_decisions.csv               G3 EI 裁决（UNIFIED/GENUINE_DIFF/NO_SPECTRA）
├── 04_tmah/tmah_decisions.csv           G4 TMAH 谱检（EXCLUDE/REVIEW/NO_SPECTRUM）
├── 05_final/features_final.csv          G5 FINAL（EI 改名+重新分类+TMAH 剔除+重归一化）
│           class_composition_final.csv
│           final_qc.json                （闭合/唯一性/完整性 7 项 QC）
│           audit_trail.csv              （逐峰变更记录：RECLASS/EXCLUDE）
└── run_manifest.json                    参数 + 各阶段 PASS/FAIL + 时间戳
```

### 关键规则（v0.1 强制）
1. **peak_id 永久唯一**：`{sample_id}__{seq:04d}`，后续决策一律以 peak_id 关联，禁用浮点 RT 作为唯一键
2. **name_raw 永不可改**：`compound_name_raw` 保留原始 NIST 名称；EI 裁决只写 `compound_name_current`/`class_final`
3. **改名 ≠ 删除**：EI 裁决（改名）走 `ei_decisions.csv`，TMAH 剔除走 `tmah_decisions.csv`，两套系统独立；**禁止**把剔除语义塞进 corrections.json
4. **Stage 3/4 只出 decision，不改数据**：真正写回统一在 Stage 5 `apply_final.py`
5. **EI 改名后必须重新分类**：`class_final` 基于改名后的名称重算
6. **参数唯一来源**：SI 阈值、RT 容差、EI cosine、TMAH 阈值全部从 `config.yaml` 读取，脚本内禁止硬编码
7. **失败即停**：任一 gate 非零退出，workflow 立即停止，不产生下游数据

### 10 项验收标准（v0.1 完成）
- [x] `run_workflow.py --config` 一键启动全流程
- [x] 无需人工修改中间 CSV
- [x] Stage 0-5 自动连续运行（真实 POC 数据验证：G0-G5 全 PASS）
- [x] 每个峰唯一 peak_id（516 features，0 重复）
- [x] EI 改名 / TMAH 删除两套独立 decision
- [x] Stage 3/4 不直接修改原始结果
- [x] Stage 5 统一应用所有 decision（70 峰 EI 改类）
- [x] EI 改名后重新分类（audit_trail 逐条记录）
- [x] FINAL 每样品面积闭合 100%（4 样品全 100.0%）
- [x] 关键 Stage 失败即停止并明确报错

---

## 8. 人工验证（Human Verification）

自动 QC 保证"管道正确"，人工验证保证"科学正确"。**每次 workflow 跑完后、
结果进入统计/写作之前**，按 `references/human-verification-guide.md` 执行
六层验证：

1. **自动 QC 审查**：final_qc.json 全 PASS、manifest 无意外 SKIP
2. **数据完整性对账**：峰数链 原始→clean→final 逐步核对
3. **关键决策抽样复核**（最重要）：EI 裁决与 TMAH 剔除各抽 10-20%，
   用 QGD 原始谱肉眼确认（cosine、m/z 58 谱型）
4. **谱级金标准**：支撑核心结论的关键化合物逐个 EI 谱 vs NIST 库对比，
   标注 MSI 置信度
5. **统计与解释审查**：n=1 无推断、R_MP 半定量表述、相对面积措辞合规
6. **可复现性**：同 config 重跑一致；SI 70/80/90 方向稳定

**核心原则**：发现任何问题 → 改配置/决策 → 重跑脚本，禁止手工改 CSV；
验证记录存档（`human-verification.md`），投稿时可应对审稿。
