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
阶段 6  统计 + 多样性 ──────────────► 门 G6: n=1 无推断，bootstrap CI 报告
阶段 7  TG-DSC 交叉验证 ────────────► 门 G7: 收敛性结论与单方法一致
阶段 8  交付物四表 ────────────────► 门 G8: 与 FINAL 偏差已说明，0/NA 语义明确
阶段 9  写作 ─────────────────────► 门 G9: 术语正确，统计约束写入 Methods
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

### 阶段 6：统计与多样性
- 计算 Shannon H'、Pielou J'、丰富度 S（用 R 4.x 或 Python 脚本，二选一保持一致性）。
- 每处理 n=1 → **禁止 ANOVA**；用峰级 bootstrap 95% CI（参考 `bootstrap_rmp_ci.py`）。
- **门 G6**：报告全部为描述性趋势 + CI，无 p 值推断。

### 阶段 7：TG-DSC 交叉验证（若有数据）
- 读 `biochar-soc-knowledge/references/tgdsc-pygcms-crosswalk.md`，逐条对照：
  ↑PAH/Phenols ↔ ↑TG-T50、↓多糖 ↔ ↓labile、↑N-杂环 ↔ MAOC T50 等。
- **门 G7**：Py-GC-MS 结论与 TG-DSC 方向一致；矛盾处显式说明。

### 阶段 8：交付物四表
- 参考 `build_deliverable.py` 生成：
  `01_sample_metadata.csv` / `02_compound_abundance.csv`(+转置) / `03_compound_annotation.csv` / `04_supplementary_notes.md`
- **门 G8**：交付物（化合物级）与 FINAL（类级，人工裁决版）关系在 04 中说明；0 与 NA 语义明确。

### 阶段 9：写作
- `good-story` 提炼叙事 → `nature-writing` 起草 → `r-to-manuscript` 落统计表述。
- **门 G9**：R_MP 表述为"半定量指示"；n=1 写入 Methods；Bulk 批次假象不解释为剂量效应。

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
