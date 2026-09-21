# Py-GC-MS 项目模板（开箱即用骨架）

复制本模板到新项目，替换 `<project>` 与 `{Fraction}` 占位符。

```
<project>/PY-GC-MS/
├── Bulk原始数据/                 # 放入 NIST 导出 TXT（1.TXT, 2.TXT...）+ .qgd
├── POC原始数据/
├── MAOC原始数据/
├── sample_map.json               # 样品→处理映射（模板见下）
├── corrections.json              # 修正记录（模板见下，可选）
├── 00_design_notes.md            # 实验设计 + 统计约束声明
├── run_pipeline.bat              # 一键执行脚本（模板见下）
├── cleaned/                      # 阶段1输出（自动生成）
├── cleaned_keepTMAH/             # 阶段1对照组（自动生成）
├── verification/                 # 阶段2输出（自动生成）
├── conflict_resolution/          # 阶段3输出（自动生成）
├── FINAL_EIresolved_class_composition.json   # 阶段5输出
├── FINAL_EIresolved_class_composition.md
├── cleaned_deliverable/          # 阶段8输出（01-04四表）
└── qa-checklist.md               # 严谨性清单存档
```

---

## sample_map.json 模板

```json
{
  "_notes": "键 = TXT/QGD 文件前缀编号，值 = 处理名（保持与 manuscript 一致）",
  "1": "CK",
  "2": "BC7.5",
  "3": "BC15",
  "4": "BC30"
}
```

## corrections.json 模板

```json
{
  "_notes": "键 = 处理名，嵌套键 = RT（字符串），值 = 修正后的化合物名。仅用于谱证实的修正",
  "BC15": {
    "3.215": "Toluene"
  },
  "BC30": {
    "18.729": "Pentadecanenitrile"
  }
}
```

## 00_design_notes.md 模板

```markdown
# 实验设计与统计约束声明

- 实验设计：CRD（完全随机设计）/ RCBD / 裂区 —— 按实际填写
- 处理：CK / BC7.5 / BC15 / BC30（n=1 单次上机）
- 碳库（物理分级）：Bulk / POC / MAOC
- 统计约束：每处理 n=1 → 处理级无 ANOVA；仅描述性趋势 + 峰级 bootstrap 95% CI
- 仪器：Shimadzu GC-MS（Py-GC-MS，TMAH 衍生化，500°C）
- 分析批次：____（记录哪些样品同批次，跨批次比较需注记）
- 脚本与命令记录：<粘贴实际运行命令与日期>
```

## run_pipeline.bat 模板

```bat
@echo off
REM 一键执行：解析→清洗→验证（修改路径后使用）
set SKILL=C:\Users\Administrator\.claude\skills\pygcms-batch\scripts
set PROJ=C:\path\to\<project>\PY-GC-MS

REM 阶段1：pipeline（TMAH 默认剔除）
python %SKILL%\pipeline.py --input %PROJ%\Bulk原始数据 --output %PROJ%\cleaned --sample_map %PROJ%\sample_map.json
python %SKILL%\pipeline.py --input %PROJ%\Bulk原始数据 --output %PROJ%\cleaned_keepTMAH --keep_tmah --sample_map %PROJ%\sample_map.json

REM 阶段2：验证
python %SKILL%\verify_data.py --input %PROJ%\Bulk原始数据 --output %PROJ%\verification --qgd %PROJ%\Bulk原始数据 --sample_map %PROJ%\sample_map.json

echo 完成。检查 verification 报告与 qa-checklist.md
pause
```

---

## 使用步骤（快速上手）

1. **建目录**：按上方骨架创建项目目录
2. **放数据**：NIST 导出 TXT（+ QGD）放入 `{Fraction}原始数据/`
3. **写映射**：编辑 `sample_map.json` 与 `00_design_notes.md`
4. **跑阶段1**：`pipeline.py`（主 + keepTMAH 对照）→ 过门 G1
5. **跑阶段2**：`verify_data.py` → 过门 G2（S0-S4 方向稳定）
6. **跑阶段3**：`resolve_conflicts_ei.py`（有 QGD 时）→ 过门 G3（批次排查）
7. **跑阶段4**：`diag_trimethylamine.py` → 过门 G4（m/z 58 试剂峰）
8. **跑阶段5**：`correct_final_tma.py` 生成 FINAL → 过门 G5
9. **跑阶段6**：`adjudicate.py` 逐峰判定（识别仲裁）→ 过门 G6（改判留痕；isomer-ambiguous 逐条看谱）
10. **阶段7-8**：统计/多样性 + TG-DSC 交叉 → 过门 G7/G8
11. **阶段9**：`build_deliverable.py` 生成四表 → 过门 G9
12. **阶段10**：写作 → 过门 G10
13. **最终**：过完整 `qa-checklist.md`，存档到项目目录

> 每个 `{Fraction}`（Bulk/POC/MAOC）重复步骤 4-6。若只有一个碳库，忽略其余。
> 阶段 6 也可由 `run_workflow.py` 作为 Stage G6 自动执行（`adjudicate.enabled: true`）。
