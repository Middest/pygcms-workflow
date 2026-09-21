#!/usr/bin/env python
"""Stage 0: Preflight 输入检查。

检查 TXT/QGD/sample_map/输出目录/Python 依赖，输出 G0 判定 JSON。
任何关键项失败 -> exit code != 0，总 workflow 必须停止。

用法:
    python preflight.py --config config.yaml [--out_dir results]
"""
import os, sys, json, importlib, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config_utils import load_config, get_si_rule, si_rule_text, resolve_path  # noqa: E402

# Windows GBK 控制台无法打印部分 Unicode 字符（如中文路径），强制 UTF-8 输出
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="Stage 0 preflight check")
    ap.add_argument("--config", required=True, help="config.yaml path")
    ap.add_argument("--out_dir", default="results", help="output root")
    args = ap.parse_args()

    cfg = load_config(args.config)
    inp = cfg.get("input", {})
    # 相对路径一律从项目根解析（config/ 下的配置 → 项目根），避免依赖当前工作目录
    txt_dir = resolve_path(args.config, inp.get("txt_dir", ""))
    qgd_dir = resolve_path(args.config, inp.get("qgd_dir", ""))
    sample_map_path = resolve_path(args.config, inp.get("sample_map", ""))
    out_root = args.out_dir

    report = {
        "gate": "G0",
        "status": "PASS",
        "checks": {},
    }
    problems = []

    def check(name, ok, detail):
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            problems.append(name)

    # 1. txt_dir
    txt_exists = os.path.isdir(txt_dir)
    check("txt_dir_exists", txt_exists, txt_dir)

    # 2. TXT 数量
    txts = []
    if txt_exists:
        txts = sorted(f for f in os.listdir(txt_dir)
                      if f.lower().endswith(".txt"))
    check("txt_found", len(txts) > 0, f"{len(txts)} TXT files")

    # 3. qgd_dir（可选）
    qgd_exists = os.path.isdir(qgd_dir) if qgd_dir else False
    qgds = []
    if qgd_exists:
        qgds = sorted(f for f in os.listdir(qgd_dir)
                      if f.lower().endswith(".qgd"))
    check("qgd_dir_exists", qgd_exists or not qgd_dir, qgd_dir)
    check("qgd_found", len(qgds) > 0 or not qgd_dir, f"{len(qgds)} QGD files")

    # 4. sample_map
    smap_exists = os.path.isfile(sample_map_path) if sample_map_path else False
    sample_map = {}
    if smap_exists:
        with open(sample_map_path, encoding="utf-8") as f:
            sample_map = {k: v for k, v in json.load(f).items() if k != "_notes"}
    check("sample_map_exists", smap_exists, sample_map_path)

    # 5. TXT 与 sample_map 互相覆盖
    txt_ids = {f.split(".")[0] for f in txts}
    map_ids = set(sample_map.keys())
    unmapped = sorted(txt_ids - map_ids)          # 有 TXT 但不在 map 中
    missing_txt = sorted(map_ids - txt_ids)       # map 中有但 TXT 不存在
    check("all_txt_mapped", len(unmapped) == 0,
          f"unmapped TXT: {unmapped}" if unmapped else "all TXT mapped")
    check("all_map_has_txt", len(missing_txt) == 0,
          f"missing TXT: {missing_txt}" if missing_txt else "all mapped samples have TXT")

    # 6. QGD/TXT 对应（可选）
    qgd_ids = {f.split(".")[0] for f in qgds}
    missing_qgd = sorted(txt_ids - qgd_ids) if qgd_dir else []
    check("qgd_covers_txt", len(missing_qgd) == 0 or not qgd_dir,
          f"missing QGD: {missing_qgd}" if missing_qgd else "QGD covers TXT (or no QGD required)")

    # 7. 输出目录可写
    try:
        os.makedirs(os.path.join(out_root, "00_preflight"), exist_ok=True)
        check("out_dir_writable", True, out_root)
    except OSError as e:
        check("out_dir_writable", False, str(e))

    # 8. Python 依赖（yaml 为硬依赖：手写回退会把 'false' 误当真值）
    deps = ["openpyxl", "olefile", "yaml"]
    missing_deps = [d for d in deps if importlib.util.find_spec(d) is None]
    check("python_deps", len(missing_deps) == 0,
          f"missing: {missing_deps}" if missing_deps else "deps OK")

    # 9. SI 硬门槛口径（必须在看结果前定死，且全库统一）
    try:
        si_thr, si_op = get_si_rule(cfg)
        si_text = si_rule_text(si_thr, si_op)
        si_ok = True
        si_detail = si_text
    except Exception as exc:
        si_thr, si_op, si_text = None, ">=", ""
        si_ok, si_detail = False, f"SI 口径配置非法: {exc}"
    check("si_rule_defined", si_ok, si_detail)
    report["si_rule"] = si_text
    report["si_threshold"] = si_thr
    report["si_operator"] = si_op

    # 汇总
    report["status"] = "PASS" if not problems else "FAIL"
    report["txt_count"] = len(txts)
    report["qgd_count"] = len(qgds)
    report["mapped_samples"] = len(map_ids)
    report["unmapped_samples"] = unmapped
    report["missing_txt"] = missing_txt
    report["missing_qgd"] = missing_qgd

    out_path = os.path.join(out_root, "00_preflight", "preflight_report.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"[G0 Preflight] {'PASS' if not problems else 'FAIL'}")
    for name, c in report["checks"].items():
        print(f"  [{'OK' if c['ok'] else 'XX'}] {name}: {c['detail']}")
    print(f"Report: {out_path}")

    if problems:
        print(f"\nPreflight FAILED on: {', '.join(problems)}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
