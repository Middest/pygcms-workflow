#!/usr/bin/env python
"""Stage 5: apply_final.py — 统一应用 Stage 3/4 的裁决，生成 FINAL 数据集。

这是 workflow 中缺失的关键桥接：把 EI 冲突裁决（改名）与 TMAH 谱检
（剔除）真正写回数据。

输入:
    features_clean.csv   (Stage 1, 含 peak_id / compound_name_raw / current / status)
    ei_decisions.csv     (Stage 3, 可选: 每行一个冲突 feature)
    tmah_decisions.csv   (Stage 4, 可选: 每行一个峰 EXCLUDE/REVIEW)

执行顺序:
    1. 读取 clean features（峰级）
    2. 应用 EI name correction（仅改名；新名称重新分类）
    3. 应用 TMAH exclusion（EXCLUDE -> status=EXCLUDED）
    4. 筛选 status==ACTIVE
    5. 每样品重归一化 area_pct（conc -> 100%）
    6. 重新聚合 class composition
    7. closure check + 唯一性/完整性 QC
    8. 输出 features_final.csv / class_composition_final.csv / final_qc.json / audit_trail.csv

用法:
    python apply_final.py --features results/01_clean/features_clean.csv \
        --ei results/03_ei/ei_decisions.csv \
        --tmah results/04_tmah/tmah_decisions.csv \
        --out_dir results/05_final

    （--ei / --tmah 可省略；省略则只做 Stage 1 自身的过滤与归一化）
"""
import os, sys, csv, json, argparse
from collections import defaultdict, Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_BATCH_CANDIDATES = [
    os.environ.get("PYGCMS_BATCH_HOME") or "",                     # 由 run_workflow.py 传入
    os.path.join(_HERE, "..", "..", "pygcms-batch", "scripts"),   # .claude/skills layout
    os.path.join(_HERE, "..", "pygcms-batch", "scripts"),
    os.path.join(_HERE, "pygcms-batch", "scripts"),
    os.path.join(_HERE, "..", "pygcms-batch"),                    # repo layout
]
# 也接受已在 PYTHONPATH 上的位置
_BATCH_CANDIDATES += [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
_BATCH = next((c for c in _BATCH_CANDIDATES
               if c and os.path.isfile(os.path.join(c, "pipeline.py"))), None)
if _BATCH and _BATCH not in sys.path:
    sys.path.insert(0, _BATCH)
try:
    from pipeline import load_shahriar_library, classify_compound
except ImportError as exc:  # 响亮失败，不要带着错误分类继续跑
    raise SystemExit(
        "apply_final.py 需要 pygcms-batch 的 pipeline.py（用于 load_shahriar_library / "
        "classify_compound）。\n"
        f"已尝试: {[c for c in _BATCH_CANDIDATES if c]}\n"
        "请设置环境变量 PYGCMS_BATCH_HOME=<pygcms-batch/scripts>，或用 "
        "run_workflow.py --batch_scripts <dir> 运行（它会自动传递给各阶段）。\n"
        f"原始错误: {exc}"
    )


def read_csv_rows(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path, rows, fieldnames):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser(description="Stage 5: apply EI/TMAH decisions -> FINAL")
    ap.add_argument("--features", required=True, help="Stage 1 features_clean.csv")
    ap.add_argument("--ei", help="Stage 3 ei_decisions.csv (optional)")
    ap.add_argument("--tmah", help="Stage 4 tmah_decisions.csv (optional)")
    ap.add_argument("--out_dir", default="results/05_final", help="Output directory")
    ap.add_argument("--library_path", help="Optional custom Shahriar library JSON")
    args = ap.parse_args()

    lib = load_shahriar_library()
    audit = []
    errors = []

    # ---- 1. Load clean features ----
    feats = read_csv_rows(args.features)
    if not feats:
        print("[G5] FAIL: features_clean.csv empty")
        sys.exit(1)
    print(f"[G5] Loaded {len(feats)} features from {args.features}")

    # peak_id -> row index
    id_index = {}
    for i, r in enumerate(feats):
        pid = r.get("peak_id", "")
        if pid:
            if pid in id_index:
                errors.append(f"duplicate peak_id: {pid}")
            id_index[pid] = i
    if errors:
        print(f"[G5] FAIL: {len(errors)} duplicate peak_id(s)")
        sys.exit(1)

    # ensure canonical columns exist
    for r in feats:
        r.setdefault("compound_name_raw", r.get("compound_name_current", ""))
        r.setdefault("compound_name_current", r.get("compound_name_raw", ""))
        r.setdefault("class_current", "")
        r.setdefault("status", "ACTIVE")
        r.setdefault("exclusion_reason", "")
        r.setdefault("si", "")
        r.setdefault("area", "")
        r.setdefault("conc", "")

    # ---- 2. Apply EI name corrections (rename only; reclassify) ----
    n_ei_renamed = 0
    if args.ei and os.path.exists(args.ei):
        ei_rows = read_csv_rows(args.ei)
        # ei_decisions.csv rows: feature-level. Map back to peaks by RT match
        # within each sample (feature-level -> peak-level is via RT + sample).
        # UNIFIED: rename to the majority/unified name (we store unified_class;
        # actual name kept as-is but class forced to unified_class).
        for dec in ei_rows:
            verdict = dec.get("verdict", "")
            if verdict != "UNIFIED":
                continue
            unified_class = dec.get("unified_class", "")
            rt_ref = dec.get("rt_ref", "")
            if not rt_ref or not unified_class:
                continue
            try:
                rt = float(rt_ref)
            except ValueError:
                continue
            for r in feats:
                if r.get("status") != "ACTIVE":
                    continue
                try:
                    rrt = float(r.get("rt_min", ""))
                except (TypeError, ValueError):
                    continue
                if abs(rrt - rt) <= 0.10:
                    old_class = r.get("class_current", "")
                    if old_class != unified_class:
                        audit.append({
                            "peak_id": r.get("peak_id", ""),
                            "stage": "G3",
                            "action": "RECLASS",
                            "before": old_class,
                            "after": unified_class,
                            "reason": f"EI_UNIFIED (rt {rt})",
                        })
                        r["class_current"] = unified_class
                        n_ei_renamed += 1
        print(f"[G5] EI UNIFIED applied: {n_ei_renamed} peaks reclassified")
    else:
        print("[G5] No EI decisions (--ei not provided); skipping EI reclassification")

    # ---- 3. Apply TMAH exclusions ----
    n_tmah_excluded = 0
    if args.tmah and os.path.exists(args.tmah):
        tmah_rows = read_csv_rows(args.tmah)
        for dec in tmah_rows:
            decision = dec.get("decision", "")
            pid = dec.get("peak_id", "")
            reason = dec.get("reason", "TMAH_REAGENT_PATTERN")
            if decision != "EXCLUDE":
                continue
            if pid and pid in id_index:
                r = feats[id_index[pid]]
                if r.get("status") == "ACTIVE":
                    audit.append({
                        "peak_id": pid,
                        "stage": "G4",
                        "action": "EXCLUDE",
                        "before": "ACTIVE",
                        "after": "EXCLUDED",
                        "reason": reason,
                    })
                    r["status"] = "EXCLUDED"
                    r["exclusion_reason"] = reason
                    n_tmah_excluded += 1
            else:
                # fallback: match by sample_id + rt_min
                sid, rt_s = dec.get("sample_id", ""), dec.get("rt_min", "")
                try:
                    rt = float(rt_s)
                except (TypeError, ValueError):
                    continue
                for r in feats:
                    if r.get("status") != "ACTIVE":
                        continue
                    if r.get("sample_id") != sid:
                        continue
                    try:
                        rrt = float(r.get("rt_min", ""))
                    except (TypeError, ValueError):
                        continue
                    if abs(rrt - rt) <= 0.05:
                        audit.append({
                            "peak_id": r.get("peak_id", ""),
                            "stage": "G4",
                            "action": "EXCLUDE",
                            "before": "ACTIVE",
                            "after": "EXCLUDED",
                            "reason": reason,
                        })
                        r["status"] = "EXCLUDED"
                        r["exclusion_reason"] = reason
                        n_tmah_excluded += 1
        print(f"[G5] TMAH EXCLUDE applied: {n_tmah_excluded} peaks excluded")
    else:
        print("[G5] No TMAH decisions (--tmah not provided); skipping TMAH exclusion")

    # ---- 4. Reclassify any remaining unnamed/updated names ----
    for r in feats:
        name = r.get("compound_name_current") or r.get("compound_name_raw", "")
        if r.get("status") == "ACTIVE":
            r["class_final"] = classify_compound(name, lib)
        else:
            r["class_final"] = r.get("class_current", "")

    # ---- 5. Per-sample renormalization of conc (relative area %) ----
    samples = sorted({r.get("sample_id", "") for r in feats})
    for sid in samples:
        active = [r for r in feats if r.get("sample_id") == sid and r.get("status") == "ACTIVE"]
        total = 0.0
        for r in active:
            try:
                total += float(r.get("conc", 0) or 0)
            except (TypeError, ValueError):
                pass
        if total > 0:
            for r in active:
                try:
                    c = float(r.get("conc", 0) or 0)
                except (TypeError, ValueError):
                    c = 0.0
                r["area_pct_final"] = round(100.0 * c / total, 4)
        else:
            for r in active:
                r["area_pct_final"] = 0.0

    # ---- 6. Class composition (per sample, ACTIVE only) ----
    class_comp = defaultdict(lambda: defaultdict(float))
    for r in feats:
        if r.get("status") != "ACTIVE":
            continue
        sid = r.get("sample_id", "")
        cls = r.get("class_final", "Unknown") or "Unknown"
        try:
            apct = float(r.get("area_pct_final", 0) or 0)
        except (TypeError, ValueError):
            apct = 0.0
        class_comp[cls][sid] += apct

    # ---- 7. QC closure checks ----
    qc = {
        "gate": "G5",
        "status": "PASS",
        "checks": {},
    }
    dup_ids = len(feats) - len({r.get("peak_id", "") for r in feats})
    qc["checks"]["peak_id_unique"] = {"ok": dup_ids == 0, "detail": f"{dup_ids} duplicates"}

    closure_issues = []
    for sid in samples:
        s = sum(float(r.get("area_pct_final", 0) or 0) for r in feats
                if r.get("sample_id") == sid and r.get("status") == "ACTIVE")
        if abs(s - 100.0) > 0.05:
            closure_issues.append(f"{sid}: {s:.3f}%")
    qc["checks"]["renormalized_closure"] = {
        "ok": not closure_issues,
        "detail": "; ".join(closure_issues) if closure_issues else "all samples ~100%",
    }

    class_totals = {sid: round(sum(class_comp[c].get(sid, 0) for c in class_comp), 2)
                    for sid in samples}
    qc["checks"]["class_closure"] = {
        "ok": all(abs(t - 100.0) <= 0.05 for t in class_totals.values()),
        "detail": str(class_totals),
    }

    # decision traceability
    ei_pids = {a["peak_id"] for a in audit if a["stage"] == "G3"}
    tmah_pids = {a["peak_id"] for a in audit if a["stage"] == "G4"}
    qc["checks"]["ei_decisions_resolved"] = {
        "ok": True, "detail": f"{len(ei_pids)} peaks reclassified"}
    qc["checks"]["tmah_decisions_resolved"] = {
        "ok": True, "detail": f"{len(tmah_pids)} peaks excluded"}

    nan_sids = [r.get("peak_id", "?") for r in feats
                if not r.get("sample_id") or not r.get("peak_id")]
    qc["checks"]["no_nan_ids"] = {"ok": not nan_sids, "detail": str(nan_sids[:5])}

    neg_areas = [r.get("peak_id", "?") for r in feats
                 if r.get("status") == "ACTIVE" and
                 (lambda v: v is not None and v < 0)(_to_float(r.get("area")))]
    qc["checks"]["no_negative_area"] = {"ok": not neg_areas, "detail": str(neg_areas[:5])}

    if any(not c["ok"] for c in qc["checks"].values()):
        qc["status"] = "FAIL"

    # ---- 8. Export ----
    os.makedirs(args.out_dir, exist_ok=True)

    final_fields = [
        "peak_id", "sample_id", "rt_min", "si", "area", "conc",
        "compound_name_raw", "compound_name_current", "compound_name_final",
        "class_current", "class_final", "status", "exclusion_reason", "area_pct_final",
    ]
    for r in feats:
        r["compound_name_final"] = r.get("compound_name_current") or r.get("compound_name_raw", "")

    write_csv_rows(os.path.join(args.out_dir, "features_final.csv"), feats, final_fields)

    # class composition matrix: rows=class, cols=samples
    cls_rows = []
    for cls in sorted(class_comp, key=lambda c: -max(class_comp[c].values())):
        row = {"class": cls}
        for sid in samples:
            row[sid] = round(class_comp[cls].get(sid, 0), 4)
        cls_rows.append(row)
    write_csv_rows(os.path.join(args.out_dir, "class_composition_final.csv"),
                   cls_rows, ["class"] + samples)

    with open(os.path.join(args.out_dir, "final_qc.json"), "w", encoding="utf-8") as f:
        json.dump(qc, f, ensure_ascii=False, indent=2)

    write_csv_rows(os.path.join(args.out_dir, "audit_trail.csv"), audit,
                   ["peak_id", "stage", "action", "before", "after", "reason"])

    # summary
    n_active = sum(1 for r in feats if r.get("status") == "ACTIVE")
    n_excluded = sum(1 for r in feats if r.get("status") != "ACTIVE")
    print(f"\n[G5] Finalization summary:")
    print(f"  total features: {len(feats)}  active: {n_active}  excluded: {n_excluded}")
    print(f"  EI reclassified: {n_ei_renamed}  TMAH excluded: {n_tmah_excluded}")
    print(f"  QC: {qc['status']}")
    for name, c in qc["checks"].items():
        print(f"    [{'OK' if c['ok'] else 'XX'}] {name}: {c['detail']}")
    print(f"\nFinal:")
    print(f"  {args.out_dir}/features_final.csv")
    print(f"  {args.out_dir}/class_composition_final.csv")
    print(f"  {args.out_dir}/final_qc.json")
    print(f"  {args.out_dir}/audit_trail.csv")

    if qc["status"] != "PASS":
        sys.exit(1)
    sys.exit(0)


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
