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
```

### 第 3 步：过复核门 → 交付
每个阶段过对应 QA 门（G0-G9，见 SKILL.md §2），最终交付前过完整 `references/rigor-checklist.md` 清单。

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

## 文件导航

- `SKILL.md` — 工作流主文档（阶段 × 复核门）
- `references/rigor-checklist.md` — 严谨性自检清单（A-H 八组）
- `references/project-template.md` — 项目骨架模板 + 配置模板
- `../pygcms-batch/` — 核心脚本（pipeline / verify / resolve / diag）
- `../biochar-soc-knowledge/` — 领域知识与 TG-DSC 交叉验证
