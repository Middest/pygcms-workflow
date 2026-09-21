#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
阶段 G6：逐峰判定（识别仲裁）— per-peak adjudication
===================================================
解决：同一色谱峰在不同处理中 NIST 首位候选 (Hit#1) 不一致；候选间 SI 接近
（如 92 vs 91）时 SI 排序不具区分度。

判据优先级（事先确定，对所有峰统一施用）：
    P0 SI 硬门槛   —— SI >= 80（本项目口径）；无 SI 的峰视为未鉴定，一律剔除
    P1 谱图证据   —— 实测 EI 诊断离子判据（验证一致率：PAH 100%、脂肪酸甲酯 100%、MAH 86%）
    P2 跨处理比对 —— 同一馏分内其它处理中质谱最相似的峰（余弦 ≥ cos_min，RT 窗 ±rt_win）
                      其 Hit#1 的类别
    P3 兜底       —— Hit#1 自身的类别

判定只到「类」；输出难降解比例 R = PAH + 长链烷烃 + MAH + 烯烃 + 木质素
（Shahriar 2026；V2 变体把木质素算作易降解）与逐峰改判明细。

SI 门槛是 G6 合同的一部分
--------------------------
SI 口径必须在看结果前定死（'>=' 与 '>' 在本数据集相差 53 峰 / 3.34%）。
本阶段做两件事，缺一即 FAIL（除非 require_si_enforcement: false）：
    1. 把 SI 门槛传给后端（若后端 run_fraction 暴露 si_threshold 形参）；
    2. **独立复核**返回的每一个峰是否满足门槛 —— 不信任后端是否真的执行了。
这样 SI 口径真正贯穿全链路，而不是"在编排层看起来生效"。

门 G6：
    PASS   —— 所有馏分均产出 R(V1)/R(V2) 与改判明细，且 SI 门槛已落实
    REVIEW —— 存在 isomer-ambiguous 峰（P2 因同分异构体歧义未改判），需人工看谱确认
    FAIL   —— SI 门槛无法落实或未通过复核；配置/路径错误

配置（config.yaml）：
    filters:
      si_threshold: 80        # 硬门槛
      si_operator: ">="       # 本项目口径；'>' 为严格大于
    adjudicate:
      enabled: true
      require_si_enforcement: true   # SI 门槛无法落实时 FAIL（默认 true）
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
import inspect
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
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config_utils import (load_config, resolve_path, si_passes,  # noqa: E402
                          get_si_rule, si_rule_text)

GATE = "G6"

# 后端可能使用的 SI 形参名（按优先级）
SI_PARAM_NAMES = ("si_threshold", "si_min", "min_si", "similarity_threshold")
# 结果表里可能出现的 SI 列名
SI_COLUMN_NAMES = ("si", "SI", "similarity", "similarity_index", "match_factor", "match")


def ensure_pygcms(cfg, cfg_path):
    """让 pygcms 可导入：优先配置项 / 环境变量（不再硬编码机器路径）。"""
    cands = []
    adj = cfg.get("adjudicate", {}) or {}
    if adj.get("pygcms_path"):
        cands.append(resolve_path(cfg_path, adj["pygcms_path"]))
    if os.environ.get("PYGCMS_HOME"):
        cands.append(os.path.expanduser(os.path.expandvars(os.environ["PYGCMS_HOME"])))
    for c in cands:
        if c and Path(c).is_dir() and c not in sys.path:
            sys.path.insert(0, c)
    try:
        import pygcms.adjudicate  # noqa: F401
        return True
    except Exception:
        return False


def resolve_fractions(cfg, cfg_path):
    """返回 {馏分名: {处理名: txt 绝对路径}}。"""
    adj = cfg.get("adjudicate", {}) or {}
    fr = adj.get("fractions")
    if fr:
        return {str(frac): {str(t): resolve_path(cfg_path, p)
                            for t, p in (mapping or {}).items()}
                for frac, mapping in fr.items()}

    # 回退：input.txt_dir + sample_map 视为一个馏分
    inp = cfg.get("input", {}) or {}
    txt_dir = resolve_path(cfg_path, inp.get("txt_dir", ""))
    smap = resolve_path(cfg_path, inp.get("sample_map", ""))
    if not txt_dir or not Path(txt_dir).is_dir():
        return {}
    mapping = {}
    if smap and Path(smap).exists():
        raw = json.loads(Path(smap).read_text(encoding="utf-8"))
        mapping = {str(k): v for k, v in raw.items() if k != "_notes"}
    files = {}
    for f in sorted(Path(txt_dir).iterdir()):
        if f.is_file() and f.suffix.lower() == ".txt":
            files[f.stem] = str(f)
    if not files:
        return {}
    group = ({str(label): files[stem] for stem, label in mapping.items() if stem in files}
             if mapping else dict(files))
    return {"ALL": group} if group else {}


def _find_si_column(peaks):
    """在结果表里定位 SI 列（用于独立复核）。"""
    cols = list(getattr(peaks, "columns", []))
    if not cols:
        return None
    for name in SI_COLUMN_NAMES:
        if name in cols:
            return name
    lower = {str(c).lower(): c for c in cols}
    for name in SI_COLUMN_NAMES:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def verify_si_enforced(peaks, threshold, operator):
    """独立复核：返回 (是否通过, 说明文字)。

    不信任后端是否真的执行了门槛 —— 这里逐峰检查返回值。
    """
    if threshold is None:
        return True, "未启用 SI 门槛"
    col = _find_si_column(peaks)
    if col is None:
        return False, "结果表中找不到 SI 列，无法复核 SI 门槛是否落实"
    vals = list(peaks[col])
    n_bad = sum(0 if si_passes(v, threshold, operator) else 1 for v in vals)
    if n_bad:
        return False, (f"{len(vals)} 个峰中有 {n_bad} 个不满足 SI {operator} {threshold:g}"
                       f"（列 '{col}'）")
    return True, f"{len(vals)} 个峰全部满足 SI {operator} {threshold:g}"


def run_fraction_with_si(run_fraction, mapping, rt_win, cos_min, keep_art,
                         allow_iso, si_threshold, si_operator):
    """调用后端，尽量把 SI 门槛传进去（后端支持时）。"""
    kwargs = dict(rt_win=rt_win, cos_min=cos_min,
                  drop_artifacts=not keep_art,
                  drop_ambiguous_isomers=not allow_iso)
    backend_si_param = None
    if si_threshold is not None:
        try:
            sig = inspect.signature(run_fraction)
            backend_si_param = next((p for p in SI_PARAM_NAMES if p in sig.parameters), None)
        except (TypeError, ValueError):
            backend_si_param = None
        if backend_si_param:
            kwargs[backend_si_param] = si_threshold
            if "si_operator" in inspect.signature(run_fraction).parameters:
                kwargs["si_operator"] = si_operator
    return run_fraction(mapping, **kwargs), backend_si_param


def write_failure(stage_dir, reason, threshold, operator):
    """SI 门槛未落实时写出 FAIL 记录。"""
    stage_dir.mkdir(parents=True, exist_ok=True)
    payload = {"gate": GATE, "verdict": "FAIL",
               "si_rule": si_rule_text(threshold, operator), "reason": reason}
    (stage_dir / "adjudication_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (stage_dir / "adjudication_summary.md").write_text(
        f"# 阶段 {GATE}：FAIL\n\n- SI 硬门槛：`{si_rule_text(threshold, operator)}`\n"
        f"- 原因：{reason}\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="阶段 G6：逐峰判定（识别仲裁）")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out_dir", required=True)
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
    except Exception as exc:
        print(f"[{GATE}] FAIL: config error: {exc}")
        return 1

    adj = cfg.get("adjudicate", {}) or {}
    if not adj.get("enabled", True):
        print(f"[{GATE}] SKIP: adjudicate.enabled = false")
        return 0

    stage_dir = Path(args.out_dir) / "06_adjudicate"
    stage_dir.mkdir(parents=True, exist_ok=True)

    try:
        si_threshold, si_operator = get_si_rule(cfg)
    except ValueError as exc:
        print(f"[{GATE}] FAIL: {exc}")
        return 1
    require_si = bool(adj.get("require_si_enforcement", True))

    if not ensure_pygcms(cfg, args.config):
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

    print(f"[{GATE}] SI 硬门槛: {si_rule_text(si_threshold, si_operator)}"
          f"（require_si_enforcement={require_si}）")

    summary, n_review = [], 0
    for frac, mapping in fractions.items():
        missing = [t for t, p in mapping.items() if not Path(p).exists()]
        if missing:
            reason = f"[{frac}] 文件不存在 -> {', '.join(missing)}"
            write_failure(stage_dir, reason, si_threshold, si_operator)
            print(f"[{GATE}] FAIL: {reason}")
            return 1
        try:
            res, backend_si_param = run_fraction_with_si(
                run_fraction, mapping, rt_win, cos_min, keep_art, allow_iso,
                si_threshold, si_operator)
        except Exception as exc:
            reason = f"[{frac}] 后端调用失败: {type(exc).__name__}: {exc}"
            write_failure(stage_dir, reason, si_threshold, si_operator)
            print(f"[{GATE}] FAIL: {reason}")
            return 1

        peaks = res["peaks"]
        # ---- 独立复核 SI 门槛 ----
        ok_si, si_detail = verify_si_enforced(peaks, si_threshold, si_operator)
        if not ok_si and require_si:
            reason = f"[{frac}] SI 硬门槛未落实: {si_detail}"
            write_failure(stage_dir, reason, si_threshold, si_operator)
            print(f"[{GATE}] FAIL: {reason}")
            print(f"[{GATE}]   后端 run_fraction 的 SI 形参: {backend_si_param or '（无）'}")
            return 1

        fdir = stage_dir / frac
        rp = write_report(res, fdir, title=f"逐峰判定 · {frac}")
        # 若后端提供了门槛执行审计表，一并落盘
        diag = res.get("si_diag")
        if hasattr(diag, "to_csv"):
            diag.to_csv(fdir / "adjudication_si_gate.csv", index=False,
                        encoding="utf-8-sig")

        n_iso = int(peaks["rule"].astype(str).str.contains("isomer-ambiguous").sum())
        n_review += n_iso
        row = {"fraction": frac, "n_peaks": int(len(peaks)),
               "n_changed": int(peaks["changed"].sum()), "n_isomer_ambiguous": n_iso,
               "si_enforced": bool(ok_si), "si_detail": si_detail,
               "backend_si_param": backend_si_param,
               "R_V1": {t: round(float(v), 2) for t, v in res["resistant"].items()},
               "R_V2": {t: round(float(v), 2) for t, v in res["resistant_v2"].items()},
               "report": str(rp)}
        summary.append(row)
        print(f"[{GATE}] [{frac}] 峰 {row['n_peaks']}，改判 {row['n_changed']}，"
              f"isomer-ambiguous {n_iso} | SI 复核: {si_detail}")
        print("        R(V1) = " + ", ".join(f"{t} {v:.1f}%" for t, v in res["resistant"].items()))

    # ---- 门 ----
    verdict = "REVIEW" if n_review else "PASS"
    md = [f"# 阶段 {GATE}：逐峰判定（识别仲裁）\n",
          f"判据：**SI 硬门槛（{si_rule_text(si_threshold, si_operator)}）"
          f"→ P1 谱图证据 → P2 同馏分内跨处理比对（余弦≥{cos_min}，RT 窗 ±{rt_win} min）"
          f"→ P3 Hit#1**；判定只到「类」。\n",
          "SI 门槛做了两件事：传给后端 + **独立复核每个返回峰的 SI**；"
          "两者缺一即 FAIL（除非 require_si_enforcement: false）。\n",
          "难降解比例 R = PAH + 长链烷烃 + MAH + 烯烃 + 木质素（V1；V2 把木质素算易降解）。\n",
          f"\n## 门 {GATE}：**{verdict}**\n"]
    if n_review:
        md.append(f"- 存在 **{n_review}** 个 isomer-ambiguous 峰：P2 因同分异构体歧义未改判，"
                  f"需人工查看谱图确认后再决定是否改判。\n")
    md.append(f"- 参数：si_threshold={si_threshold}, si_operator={si_operator!r}, "
              f"rt_win={rt_win}, cos_min={cos_min}, "
              f"allow_isomer_switch={allow_iso}, keep_artifacts={keep_art}\n")
    md.append("\n## 各馏分结果\n")
    md.append("| 馏分 | 峰数 | 改判 | isomer-ambiguous | SI 复核 | R(V1) |")
    md.append("|---|---:|---:|---:|---|---|")
    for r in summary:
        md.append(f"| {r['fraction']} | {r['n_peaks']} | {r['n_changed']} | "
                  f"{r['n_isomer_ambiguous']} | {'通过' if r['si_enforced'] else '**未通过**'} | " +
                  ", ".join(f"{t} {v:.1f}%" for t, v in r["R_V1"].items()) + " |")
    md.append("\n## 判读提示\n")
    md.append("- R 的绝对值随识别口径变化；**处理间的相对关系与趋势**才是可比较的量。")
    md.append("- SI 算子（'>=' vs '>'）在本项目数据集相差 53 峰 / 3.34%，"
              "**必须在看结果前定死**，且全库统一。")
    md.append("- P2 依赖质谱余弦，无法区分同分异构体；isomer-ambiguous 必须逐条看谱确认。")
    md.append("- 识别判据须事先确定、对所有样品统一施用；不得按预期结论挑选候选。")
    md.append("- 建议同时报告 R 的 V1/V2 两版（木质素归属不同）。")
    (stage_dir / "adjudication_summary.md").write_text("\n".join(md), encoding="utf-8")
    (stage_dir / "adjudication_summary.json").write_text(
        json.dumps({"gate": GATE, "verdict": verdict,
                    "si_rule": si_rule_text(si_threshold, si_operator),
                    "si_threshold": si_threshold, "si_operator": si_operator,
                    "fractions": summary}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[{GATE}] {verdict}")
    print(f"[{GATE}] 汇总: {stage_dir / 'adjudication_summary.md'}")
    return 2 if verdict == "REVIEW" else 0


if __name__ == "__main__":
    sys.exit(main())
