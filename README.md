# Py-GC-MS 数据分析工作流 — 快速上手

一套开箱即用的 Py-GC-MS 数据分析工作流，内置**严谨性自我复核**。

## 我有哪些数据？

| 数据类型 | 说明 | 必需？ |
|---------|------|--------|
| NIST 导出 TXT | 峰表 + MS 检索结果（每个样品一个文件） | ✅ 必需 |
| QGD 原始文件 | Shimadzu 原始数据（EI 谱验证/冲突裁决用） | ⭐ 强烈建议 |
| sample_map.json | 样品编号 → 处理名映射 | ✅ 必需 |

## 三步上手

### 第 1 步：建项目骨架
复制 `references/project-template.md` 的目录结构，放入数据、写好 `sample_map.json`。

### 第 2 步：跑一键脚本（或让 Claude 按工作流执行）
```bash
# 解析 + 清洗（TMAH 默认剔除）
python pygcms-batch/scripts/pipeline.py --input <TXT目录> --output cleaned --sample_map sample_map.json

# 对照组（保留 TMAH，严谨性对比必需）
python pygcms-batch/scripts/pipeline.py --input <TXT目录> --output cleaned_keepTMAH --keep_tmah --sample_map sample_map.json

# 10 项验证
python pygcms-batch/scripts/verify_data.py --input <TXT目录> --output verification --qgd <QGD目录> --sample_map sample_map.json

# EI 冲突裁决（有 QGD 时）
python pygcms-batch/scripts/resolve_conflicts_ei.py --matrix cleaned/analysis_ready_matrix.csv --qgd <QGD目录> --sample_map sample_map.json

# TMAH 试剂峰谱检（有 QGD 时，严谨性关键）
python pygcms-batch/scripts/diag_trimethylamine.py --qgd <QGD目录> --txt <TXT目录> --sample_map sample_map.json

# 逐峰判定（识别仲裁；同峰异名 / 候选 SI 接近时必做）
python pygcms-workflow/scripts/adjudicate.py --config config/config.yaml --out_dir results
```

### 第 3 步：过复核门 → 交付
每个阶段过对应 QA 门（G0-G10，见 SKILL.md §2），最终交付前过完整 `references/rigor-checklist.md` 清单。

## 逐峰判定（阶段 6）解决什么问题

同一色谱峰在不同处理中 NIST 首位候选 (Hit#1) 常常不同；当候选间 SI 很接近时
（如 92 vs 91），**SI 排序不具区分度**，不能用它决定归属。

`scripts/adjudicate.py` 对**每一个峰**判定「化合物类」，判据按事先确定的优先级施用：

| 优先级 | 判据 |
|---|---|
| **P0 SI 硬门槛** | `SI >= 80`（`filters.si_threshold` / `filters.si_operator`）；无 SI 的峰视为未鉴定，一律剔除 |
| **P1 谱图证据** | 实测 EI 诊断离子判据（验证一致率：PAH 100%、脂肪酸甲酯 100%、MAH 86%） |
| **P2 跨处理比对** | 同一馏分内其它处理中质谱最相似的峰（余弦 ≥ `cos_min`，RT 窗 ±`rt_win`）其 Hit#1 的类别 |
| **P3 兜底** | Hit#1 自身的类别 |

产出 `results/06_adjudicate/`：门判定摘要 + 每馏分的 R 值与类别组成 + **逐峰判定明细 CSV**
（`rule` 列写明是 P1 / P2 / P3 还是 `isomer-ambiguous`）+ `adjudication_si_gate.csv`
（逐样品剔除计数：峰表总数 = 面积≤0 + 副产物 + 无 SI + SI 不达标 + 保留）。

### SI 门槛如何"真正贯穿"（而不是看起来生效）

SI 口径必须在看结果前定死：`'>='` 与 `'>'` 在本项目数据集上相差 **53 个峰（3.34%）**，
足以静默改变论文里的每一个百分比。G6 做两件事，**缺一即 FAIL**（除非
`adjudicate.require_si_enforcement: false`）：

1. **传给后端** —— 通过 `inspect` 在 `run_fraction` 上找 `si_threshold` / `si_operator` 形参并传入；
2. **独立复核** —— 逐峰检查后端返回结果里的 SI 列，**不信任后端是否真的执行了**；
   找不到 SI 列也判 FAIL（不能假设）。

后端不支持 SI 形参时不会静默通过，而是由第 2 步兜底判 FAIL——**响亮失败优于静默降级**。

**难降解比例**：`R = PAH + 长链烷烃 + MAH + 烯烃 + 木质素`（V1；V2 把木质素算易降解，两版都报）。

**两条硬边界**：
1. P2 依赖质谱余弦，**无法区分同分异构体**（C8H10 的二甲苯 vs 环戊二烯类，余弦 0.93–0.95）；
   此类峰默认不改判并标注 `isomer-ambiguous`，**必须逐条看谱确认**。
2. 识别判据必须**事先确定、对所有样品统一施用**——不得按预期结论挑选候选
   （同一操作也能给出相反结果，属把假设写进判据）。

## 建议的 AI 使用方式

在 Claude Code / DeepSeek 会话中直接说：

- "用 pygcms-workflow 处理这批 Py-GC-MS 数据" → 加载工作流 skill
- "按严谨性清单复核我的结果" → 执行 QA 清单
- "R_MP 算出来是多少？记得 TMAH 处理" → 自动带出 TMAH 双值对比

## 常见问题

**Q: 没有 QGD 文件怎么办？**
→ 跳过阶段 3/4（EI 裁决 + 谱检），在报告中注明"未做谱级验证"，类组成以名称剔除为准。

**Q: 每个处理只有 1 个样品（n=1）？**
→ 正常。禁止 ANOVA/p 值，用描述性趋势 + bootstrap CI。

**Q: 结果能直接写进论文吗？**
→ 正文用 FINAL 版（人工裁决 + 谱检），补充材料用 deliverable 化合物级明细。
   与阶段 6 逐峰判定的 R 并列报告；两者差异来自识别口径的部分要说明。

**Q: 明明该是芳香类的峰被判成别的类了，能挑候选改回来吗？**
→ 可以改，但必须走**统一规则**：用 `adjudicate.py` 的 P1（谱图）或 P2（跨处理比对），
   并对所有样品一致施用，改判逐条留在 `adjudication_peaks.csv`。
   **不能**按"哪个候选能让结果符合预期"来挑——原始文件里的 SI 可被复核，
   而且同一做法反向操作就能得到相反结论。

**Q: SI 门槛到底该用 `>` 还是 `>=`？为什么这么较真？**
→ 因为两者在本项目数据集上相差 **53 个峰（3.34%）**，会静默改变论文里的每一个百分比。
   必须在看结果前定死，并写进 `filters.si_operator`（本项目用 `>=`，与历史 SI80 工作簿一致）。
   G6 会**独立复核**每个返回峰的 SI，通不过直接 FAIL——避免"配置写了但没生效"。

**Q: 为什么没有 PyYAML 时不能退回手写解析？**
→ 手写解析把 `false` 变成字符串 `"false"`，而 `bool("false") == True`。
   后果是 `enabled: false` 阶段照跑、`allow_isomer_switch: false` 被静默打开、
   `keep_artifacts: false` 副产物被静默保留。科研流程里这种静默错误比直接报错危险得多，
   因此 `config_utils.load_config` 强制依赖 PyYAML，缺失即抛错。

## 文件导航

- `SKILL.md` — 工作流主文档（阶段 × 复核门）
- `references/rigor-checklist.md` — 严谨性自检清单（A-H 八组；C6-C9 / E6-E7 为识别仲裁项）
- `references/project-template.md` — 项目骨架模板 + 配置模板
- `scripts/config_utils.py` — 配置读取与 SI 门槛的**唯一来源**（强制 PyYAML）
- `scripts/adjudicate.py` — 阶段 6 逐峰判定（识别仲裁 + SI 门槛复核）
- `scripts/preflight.py` — 阶段 0 输入检查（含 SI 口径检查）
- `scripts/run_workflow.py` — 一键编排（G0-G6；退出码 0=PASS / 2=REVIEW / 1=FAIL）
- `scripts/apply_final.py` — 阶段 5 FINAL 收口
- `tests/` — 回归测试（配置布尔正确性、SI 门槛复核、退出码语义）
- `config/config.example.yaml` — 统一配置（含 `filters.si_operator` 与 `adjudicate:` 段）
- `../pygcms-batch/` — 核心脚本（pipeline / verify / resolve / diag）
- `../biochar-soc-knowledge/` — 领域知识与 TG-DSC 交叉验证
