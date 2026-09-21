#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
阶段 G6：逐峰判定（识别仲裁）— per-peak adjudication
===================================================
解决：同一色谱峰在不同处理中 NIST 首位候选 (Hit#1) 不一致；候选间 SI 接近
（如 92 vs 91）时 SI 排序不具区分度。

判据优先级（事先确定，对所有峰统一施用）：
    P1 谱图证据   —— 实测 EI 诊断离子判据（验证一致率：PAH 100%、脂肪酸甲酯 100%、MAH 86%）
    P2 跨处理比对 —— 同一馏分内其它处理中质谱最相似的峰（余弦 ≥ cos_min，RT 窗 ±rt_win）
                     其 Hit#1 的类别
    P3 兜底       —— Hit#1 自身的类别

判定只到「类」；输出难降解比例 R = PAH + 长链烷烃 + MAH + 烯烃 + 木质素
（Shahriar 2026；V2 变体把木质素算作易降解）与逐峰改判明细。

门 G6：
    PASS   —— 所有馏分均产出 R(V1)/R(V2) 与改判明细
    REVIEW —— 存在 isomer-ambiguous 峰（P2 因同分异构体歧义未改判），需人工看谱确认

配置（config.yaml）：
    adjudicate:
      enabled: true
      pygcms_path: F:/deepseekharness/pygcms      # 可选；或用环境变量 PYGCMS_HOME
      rt_win: 0.6
      cos_min: 0.90
      allow_isomer_switch: false
      keep_artifacts: false
      fractions:                                   # 每个馏分：处理名 -> TXT 路径
        POC:
          CK:   data/raw/txt/5.TXT
          BC7.5: data/raw/txt/6.TXT
        MAOC:
          CK:   data/raw/txt/5.txt
      # 未提供 fractions 时：用 input.txt_dir + input.sample_map 视为单个馏分

用法：
    python scripts/adjudicate.py --config config/config.yaml --out_dir results
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

if "PYTHONIOENCODING" not in os.environ:
    os.environ["PYTHONIOENCODING"] = "utf-8"

GATE = "G6"


def load_config(path):
    """与 run_workflow.py / preflight.py 一致的配置读取（有 yaml 用 yaml，否则简易解析）。"""
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        cfg, cur = {}, None
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.split("#")[0].rstrip()
                if not line.strip():
                    continue
                if not line.startswith(" ") and ":" in line:
                    cur = cfg[line.split(":", 1)[0].strip()] = {}
                elif cur is not None and ":" in line:
                    k, v = line.split(":", 1)
                    cur[k.strip()] = v.strip()
        return cfg


def ensure_pygcms(cfg):
    """让 pygcms 可导入：优先配置项 / 环境变量 / 常见路径。"""
    cands = []
    adj = cfg.get("adjudicate", {}) or {}
    if adj.get("pygcms_path"):
        cands.append(str(adj["pygcms_path"]))
    if os.environ.get("PYGCMS_HOME"):
        cands.append(os.environ["PYGCMS_HOME"])
    cands.append(r"F:\deepseekharness\pygcms")
    for c in cands:
        if c and Path(c).is_dir() and str(c) not in sys.path:
            sys.path.insert(0, str(c))
    try:
        import pygcms.adjudicate  # noqa: F401
        return True
    except Exception:
        return False


def resolve_fractions(cfg, cfg_path):
    """返回 {馏分名: {处理名: txt 绝对路径}}。"""
    root = Path(cfg_path).resolve().parent.parent
    adj = cfg.get("adjudicate", {}) or {}
    fr = adj.get("fractions")

    def abspath(p):
        p = Path(str(p))
        return str(p if p.is_absolute() else (root / p))

    if fr:
        out = {}
        for frac, mapping in fr.items():
            out[str(frac)] = {str(t): abspath(p) for t, p in (mapping or {}).items()}
        return out

    # 回退：input.txt_dir + sample_map 视为一个馏分
    inp = cfg.get("input", {}) or {}
    txt_dir = abspath(inp.get("txt_dir", ""))
    smap = inp.get("sample_map")
    if not txt_dir or not Path(txt_dir).is_dir():
        return {}
    mapping = {}
    if smap:
        sp = Path(abspath(smap))
        if sp.exists():
            mapping = json.loads(sp.read_text(encoding="utf-8"))
    files = {}
    for f in sorted(Path(txt_dir).glob("*.txt")) + sorted(Path(txt_dir).glob("*.TXT")):
        files[f.stem] = f
    if not files:
        return {}
    if mapping:
        group = {str(label): str(files[stem]) for stem, label in mapping.items() if stem in files}
    else:
        group = {stem: str(p) for stem, p in files.items()}
    return {"ALL": group}


def main():
    ap = argparse.ArgumentParser(description="阶段 G6：逐峰判定（识别仲裁）")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out_dir", required=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    adj = cfg.get("adjudicate", {}) or {}
    if not adj.get("enabled", True):
        print(f"[{GATE}] SKIP: adjudicate.enabled = false")
        return 0

    stage_dir = Path(args.out_dir) / "06_adjudicate"
    stage_dir.mkdir(parents=True, exist_ok=True)

    if not ensure_pygcms(cfg):
        print(f"[{GATE}] FAIL: 无法导入 pygcms.adjudicate —— 请在 config 的 "
              f"adjudicate.pygcms_path 或环境变量 PYGCMS_HOME 指定工具链路径")
        return 1

    from pygcms.adjudicate import run_fraction, write_report

    fractions = resolve_fractions(cfg, args.config)
    if not fractions:
        print(f"[{GATE}] FAIL: 未解析到任何馏分（检查 adjudicate.fractions 或 input.txt_dir）")
        return 1

    rt_win = float(adj.get("rt_win", 0.6))
    cos_min = float(adj.get("cos_min", 0.90))
    allow_iso = bool(adj.get("allow_isomer_switch", False))
    keep_art = bool(adj.get("keep_artifacts", False))

    summary, n_review = [], 0
    for frac, mapping in fractions.items():
        missing = [t for t, p in mapping.items() if not Path(p).exists()]
        if missing:
            print(f"[{GATE}] [{frac}] FAIL: 文件不存在 -> {', '.join(missing)}")
            return 1
        res = run_fraction(mapping, rt_win=rt_win, cos_min=cos_min,
                           drop_artifacts=not keep_art,
                           drop_ambiguous_isomers=not allow_iso)
        fdir = stage_dir / frac
        rp = write_report(res, fdir, title=f"逐峰判定 · {frac}")
        peaks = res["peaks"]
        n_iso = int(peaks["rule"].astype(str).str.contains("isomer-ambiguous").sum())
        n_review += n_iso
        row = {"fraction": frac, "n_peaks": int(len(peaks)),
               "n_changed": int(peaks["changed"].sum()), "n_isomer_ambiguous": n_iso,
               "R_V1": {t: round(float(v), 2) for t, v in res["resistant"].items()},
               "R_V2": {t: round(float(v), 2) for t, v in res["resistant_v2"].items()},
               "report": str(rp)}
        summary.append(row)
        print(f"[{GATE}] [{frac}] 峰 {row['n_peaks']}，改判 {row['n_changed']}，"
              f"isomer-ambiguous {n_iso}")
        print("        R(V1) = " + ", ".join(f"{t} {v:.1f}%" for t, v in res["resistant"].items()))

    # ---- 门 ----
    verdict = "REVIEW" if n_review else "PASS"
    md = [f"# 阶段 {GATE}：逐峰判定（识别仲裁）\n",
          f"判据：**P1 谱图证据 → P2 同馏分内跨处理比对（余弦≥{cos_min}，RT 窗 ±{rt_win} min）"
          f"→ P3 Hit#1**；判定只到「类」。\n",
          f"难降解比例 R = PAH + 长链烷烃 + MAH + 烯烃 + 木质素（V1；V2 把木质素算易降解）。\n",
          f"\n## 门 {GATE}：**{verdict}**\n"]
    if n_review:
        md.append(f"- 存在 **{n_review}** 个 isomer-ambiguous 峰：P2 因同分异构体歧义未改判，"
                  f"需人工查看谱图确认后再决定是否改判。\n")
    md.append(f"- 参数：rt_win={rt_win}, cos_min={cos_min}, "
              f"allow_isomer_switch={allow_iso}, keep_artifacts={keep_art}\n")
    md.append("\n## 各馏分结果\n")
    md.append("| 馏分 | 峰数 | 改判 | isomer-ambiguous | R(V1) |")
    md.append("|---|---:|---:|---:|---|")
    for r in summary:
        md.append(f"| {r['fraction']} | {r['n_peaks']} | {r['n_changed']} | "
                  f"{r['n_isomer_ambiguous']} | " +
                  ", ".join(f"{t} {v:.1f}%" for t, v in r["R_V1"].items()) + " |")
    md.append("\n## 判读提示\n")
    md.append("- R 的绝对值随识别口径变化；**处理间的相对关系与趋势**才是可比较的量。")
    md.append("- P2 依赖质谱余弦，无法区分同分异构体；isomer-ambiguous 必须逐条看谱确认。")
    md.append("- 识别判据须事先确定、对所有样品统一施用；不得按预期结论挑选候选。")
    md.append("- 建议同时报告 R 的 V1/V2 两版（木质素归属不同）。")
    (stage_dir / "adjudication_summary.md").write_text("\n".join(md), encoding="utf-8")
    (stage_dir / "adjudication_summary.json").write_text(
        json.dumps({"gate": GATE, "verdict": verdict, "fractions": summary},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[{GATE}] {verdict}")
    print(f"[{GATE}] 汇总: {stage_dir / 'adjudication_summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
