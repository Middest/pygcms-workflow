#!/usr/bin/env python
"""Py-GC-MS Workflow 总编排入口（Stage 0-5）。

一条命令从原始数据跑到 FINAL：
    python scripts/run_workflow.py --config config.yaml

流程:
    G0 preflight -> G1 parse/clean (pipeline.py) -> G2 verify (verify_data.py)
    -> G3 EI resolution (resolve_conflicts_ei.py, 可选) -> G4 TMAH spectral
    (diag_trimethylamine.py, 可选) -> G5 finalize (apply_final.py)

任何 gate 失败（非零退出）立即停止，不产生 FINAL。
每次运行记录 results/run_manifest.json（参数 + 各阶段 PASS/FAIL）。
"""
import os, sys, json, subprocess, argparse, datetime

# Windows GBK 控制台保护
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 子进程统一继承 UTF-8 输出
if "PYTHONIOENCODING" not in os.environ:
    os.environ["PYTHONIOENCODING"] = "utf-8"

STAGES = ["G0", "G1", "G2", "G3", "G4", "G5", "G6"]
STAGE_DIRS = ["00_preflight", "01_clean", "02_verify", "03_ei", "04_tmah", "05_final",
              "06_adjudicate"]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config_utils import (load_config, get_si_rule, si_rule_text,  # noqa: E402
                          DEFAULT_SI_THRESHOLD)


def run_stage(cmd, label, manifest, stage, out_root, overwrite):
    """执行一个阶段。

    退出码约定（与 adjudicate.py 等阶段脚本一致）：
        0 = PASS       2 = REVIEW（需人工介入，但不是失败）       其他 = FAIL
    """
    print(f"\n{'='*70}\n[{stage}] {label}\n{'='*70}")
    # overwrite guard: refuse to clobber existing stage output unless allowed
    stage_dir = os.path.join(out_root, STAGE_DIRS[STAGES.index(stage)])
    if os.path.exists(stage_dir) and not overwrite:
        print(f"[{stage}] SKIP: {stage_dir} exists (set workflow.overwrite=true to rerun)")
        manifest["stages"][stage] = "SKIP"
        return True
    proc = subprocess.run(cmd, shell=False)
    if proc.returncode == 2:
        print(f"\n[{stage}] REVIEW ({label}) — 需人工复核，不阻断后续阶段")
        manifest["stages"][stage] = "REVIEW"
        manifest.setdefault("review_stages", []).append(stage)
        return True
    if proc.returncode != 0:
        print(f"\n[{stage}] FAIL ({label})")
        manifest["stages"][stage] = "FAIL"
        manifest["failure_stage"] = stage
        manifest["failure_command"] = " ".join(cmd)
        return False
    print(f"[{stage}] PASS")
    manifest["stages"][stage] = "PASS"
    return True


def main():
    ap = argparse.ArgumentParser(description="Py-GC-MS Workflow runner (Stage 0-5)")
    ap.add_argument("--config", required=True, help="config.yaml path")
    ap.add_argument("--batch_scripts", default=None,
                    help="pygcms-batch scripts dir (default: auto-detect from this repo)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    inp = cfg.get("input", {})
    flt = cfg.get("filters", {})
    aln = cfg.get("alignment", {})
    ei = cfg.get("ei", {})
    tmah = cfg.get("tmah", {})
    out_root = cfg.get("output", {}).get("root", "results")
    wf = cfg.get("workflow", {})
    stop_on_fail = wf.get("stop_on_gate_failure", True)
    overwrite = wf.get("overwrite", False)

    # locate pygcms-batch scripts
    here = os.path.dirname(os.path.abspath(__file__))
    if args.batch_scripts:
        batch = args.batch_scripts
    else:
        candidates = [
            os.path.join(here, "..", "..", "pygcms-batch", "scripts"),  # .claude/skills layout
            os.path.join(here, "..", "pygcms-batch", "scripts"),
            os.path.join(here, "pygcms-batch", "scripts"),
        ]
        batch = next((c for c in candidates if os.path.isdir(c)), None)
    if not batch:
        print("Cannot locate pygcms-batch scripts. Pass --batch_scripts <dir>.")
        sys.exit(1)
    batch = os.path.abspath(batch)
    print(f"pygcms-batch scripts: {batch}")

    py = sys.executable
    smap_path = inp.get("sample_map", "")
    smap_abs = os.path.abspath(smap_path) if smap_path else ""
    si_threshold, si_operator = get_si_rule(cfg)
    print(f"SI 硬门槛 (filters): {si_rule_text(si_threshold, si_operator)}")
    manifest = {
        "project": cfg.get("project", {}).get("name", "pygcms_project"),
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "config": os.path.abspath(args.config),
        "parameters": {
            "si_threshold": si_threshold,
            "si_operator": si_operator,
            "si_rule": si_rule_text(si_threshold, si_operator),
            "rt_tolerance": aln.get("rt_tolerance", 0.10),
            "ei_cosine": ei.get("cosine_threshold", 0.85),
            "tmah_mz58_fraction": tmah.get("mz58_fraction_threshold", 0.12),
            "tmah_rt_tolerance": tmah.get("rt_tolerance", 0.35),
            "tmah_tic_min": tmah.get("tic_min", 50000),
        },
        "stages": {},
        "input_files": {},
    }
    os.makedirs(out_root, exist_ok=True)

    ok = True

    # ---- G0: preflight ----
    pre = os.path.join(here, "preflight.py")
    ok = run_stage([py, pre, "--config", os.path.abspath(args.config), "--out_dir", out_root],
                   "Preflight", manifest, "G0", out_root, overwrite)
    if not ok and stop_on_fail:
        _finish(manifest, out_root, failed=True); sys.exit(1)

    # ---- G1: pipeline (parse/clean) ----
    pipe = os.path.join(batch, "pipeline.py")
    g1_out = os.path.join(out_root, "01_clean")
    cmd1 = [py, pipe, "--input", os.path.abspath(inp.get("txt_dir", "")),
            "--output", g1_out, "--sample_map", smap_abs]
    if si_threshold is not None:
        cmd1 += ["--si_threshold", f"{si_threshold:g}"]
    if not flt.get("remove_contaminants", True):
        cmd1.append("--keep_contaminants")
    if not flt.get("remove_tmah_by_name", True):
        cmd1.append("--keep_tmah")
    if not flt.get("renormalize", True):
        cmd1.append("--no_renormalize")
    if aln.get("reference_sample"):
        cmd1 += ["--reference", str(aln["reference_sample"])]
    ok = run_stage(cmd1, "Parse & Clean (pipeline.py)", manifest, "G1", out_root, overwrite)
    if not ok and stop_on_fail:
        _finish(manifest, out_root, failed=True); sys.exit(1)

    # ---- G2: verify ----
    verify = os.path.join(batch, "verify_data.py")
    g2_out = os.path.join(out_root, "02_verify")
    cmd2 = [py, verify, "--input", os.path.abspath(inp.get("txt_dir", "")),
            "--output", g2_out, "--sample_map", smap_abs]
    if inp.get("qgd_dir") and ei.get("enabled", True):
        cmd2 += ["--qgd", os.path.abspath(inp["qgd_dir"])]
    ok = run_stage(cmd2, "Verification (verify_data.py)", manifest, "G2", out_root, overwrite)
    if not ok and stop_on_fail:
        _finish(manifest, out_root, failed=True); sys.exit(1)

    # ---- G3: EI resolution (optional) ----
    if ei.get("enabled", True) and inp.get("qgd_dir"):
        resolve = os.path.join(batch, "resolve_conflicts_ei.py")
        g3_out = os.path.join(out_root, "03_ei")
        matrix = os.path.join(g1_out, "analysis_ready_matrix.csv")
        cmd3 = [py, resolve, "--matrix", matrix, "--qgd", os.path.abspath(inp["qgd_dir"]),
                "--sample_map", smap_abs, "--cosine", str(ei.get("cosine_threshold", 0.85)),
                "--top_ions", str(ei.get("top_ions", 12)), "--output", g3_out]
        ok = run_stage(cmd3, "EI Resolution (resolve_conflicts_ei.py)", manifest, "G3", out_root, overwrite)
        if not ok and stop_on_fail:
            _finish(manifest, out_root, failed=True); sys.exit(1)
    else:
        print(f"\n[G3] SKIP: EI disabled or no QGD dir")
        manifest["stages"]["G3"] = "SKIP"

    # ---- G4: TMAH spectral check (optional) ----
    if tmah.get("enabled", True) and inp.get("qgd_dir"):
        diag = os.path.join(batch, "diag_trimethylamine.py")
        g4_out = os.path.join(out_root, "04_tmah")
        features = os.path.join(g1_out, "features_clean.csv")
        cmd4 = [py, diag, "--qgd", os.path.abspath(inp["qgd_dir"]),
                "--txt", os.path.abspath(inp.get("txt_dir", "")),
                "--sample_map", smap_abs, "--features", features,
                "--rt_tolerance", str(tmah.get("rt_tolerance", 0.35)),
                "--tic_min", str(tmah.get("tic_min", 50000)),
                "--output", g4_out]
        ok = run_stage(cmd4, "TMAH Spectral Check (diag_trimethylamine.py)", manifest, "G4", out_root, overwrite)
        if not ok and stop_on_fail:
            _finish(manifest, out_root, failed=True); sys.exit(1)
    else:
        print(f"\n[G4] SKIP: TMAH disabled or no QGD dir")
        manifest["stages"]["G4"] = "SKIP"

    # ---- G5: finalize ----
    apply_final = os.path.join(here, "apply_final.py")
    g5_out = os.path.join(out_root, "05_final")
    cmd5 = [py, apply_final,
            "--features", os.path.join(g1_out, "features_clean.csv"),
            "--out_dir", g5_out]
    ei_csv = os.path.join(out_root, "03_ei", "ei_decisions.csv")
    if manifest["stages"].get("G3") == "PASS" and os.path.exists(ei_csv):
        cmd5 += ["--ei", ei_csv]
    tmah_csv = os.path.join(out_root, "04_tmah", "tmah_decisions.csv")
    if manifest["stages"].get("G4") == "PASS" and os.path.exists(tmah_csv):
        cmd5 += ["--tmah", tmah_csv]
    ok = run_stage(cmd5, "Finalize (apply_final.py)", manifest, "G5", out_root, overwrite)
    if not ok and stop_on_fail:
        _finish(manifest, out_root, failed=True); sys.exit(1)

    # ---- G6: per-peak adjudication (optional) ----
    adj_cfg = cfg.get("adjudicate", {}) or {}
    if adj_cfg.get("enabled", True):
        adj_script = os.path.join(here, "adjudicate.py")
        ok = run_stage([py, adj_script, "--config", os.path.abspath(args.config),
                        "--out_dir", out_root],
                       "Per-peak adjudication (adjudicate.py)", manifest, "G6",
                       out_root, overwrite)
        if not ok and stop_on_fail:
            _finish(manifest, out_root, failed=True); sys.exit(1)
    else:
        print("\n[G6] SKIP: adjudicate.enabled = false")
        manifest["stages"]["G6"] = "SKIP"

    # ---- manifest ----
    manifest["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    states = list(manifest["stages"].values())
    if "FAIL" in states:
        manifest["overall"] = "FAIL"
    elif "REVIEW" in states:
        manifest["overall"] = "REVIEW"
    elif all(s in ("PASS", "SKIP") for s in states):
        manifest["overall"] = "PASS"
    else:
        manifest["overall"] = "PARTIAL"
    _finish(manifest, out_root, failed=False)
    print(f"\nWorkflow complete. Overall: {manifest['overall']}")
    print(f"SI 口径: {manifest['parameters']['si_rule']}")
    print(f"Final: {os.path.join(out_root, '05_final', 'features_final.csv')}")
    print(f"       {os.path.join(out_root, '05_final', 'class_composition_final.csv')}")
    print(f"       {os.path.join(out_root, 'run_manifest.json')}")
    sys.exit({"PASS": 0, "REVIEW": 2}.get(manifest["overall"], 1))


def _finish(manifest, out_root, failed=False):
    if failed:
        manifest["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        manifest["overall"] = "FAIL"
    path = os.path.join(out_root, "run_manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"Manifest: {path}")


if __name__ == "__main__":
    main()
