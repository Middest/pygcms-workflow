#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""G6 SI 门槛落实测试 + run_workflow 退出码语义测试。

运行: python tests/test_si_enforcement.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adjudicate as G6  # noqa: E402
import run_workflow as RW  # noqa: E402

_n = 0


def ok(cond, msg):
    global _n
    _n += 1
    if not cond:
        raise AssertionError(f"FAIL: {msg}")
    print(f"  ok {_n:02d} {msg}")


def test_si_verification():
    print("SI 独立复核 (verify_si_enforced):")
    df = pd.DataFrame({"name": ["A", "B"], "si": [90.0, 85.0]})
    passed, detail = G6.verify_si_enforced(df, 80, ">=")
    ok(passed, "全部达标 → 通过")
    ok("全部满足" in detail, f"说明文字正确: {detail}")

    df_bad = pd.DataFrame({"name": ["A", "B", "C"], "si": [90.0, 75.0, 60.0]})
    passed, detail = G6.verify_si_enforced(df_bad, 80, ">=")
    ok(not passed, "存在不达标峰 → 不通过")
    ok("2 个" in detail, f"报出不达标数量: {detail}")

    # 边界：SI 恰好 = 80
    df_edge = pd.DataFrame({"si": [80.0]})
    ok(G6.verify_si_enforced(df_edge, 80, ">=")[0], "'>=' 下 SI=80 通过")
    ok(not G6.verify_si_enforced(df_edge, 80, ">")[0], "'>' 下 SI=80 不通过（严格）")

    # 缺 SI 列 / SI 为空 → 无法复核，必须判不通过
    df_nocol = pd.DataFrame({"name": ["A"], "area": [1.0]})
    passed, detail = G6.verify_si_enforced(df_nocol, 80, ">=")
    ok(not passed, "找不到 SI 列 → 不通过（不能假设后端已执行）")
    ok("找不到 SI 列" in detail, f"说明文字正确: {detail}")

    df_null = pd.DataFrame({"si": [None, None]})
    ok(not G6.verify_si_enforced(df_null, 80, ">=")[0], "SI 全空 → 不通过")

    # 不设门槛时无条件通过
    ok(G6.verify_si_enforced(df_nocol, None, ">=")[0], "不设门槛 → 通过")

    # 列名识别（SI / similarity / match_factor）
    for col in ("si", "SI", "similarity", "match_factor"):
        ok(G6._find_si_column(pd.DataFrame({col: [90]})) == col, f"识别 SI 列名 '{col}'")


def test_backend_param_binding():
    print("SI 门槛传入后端:")
    calls = {}

    def backend(files, rt_win=0.6, cos_min=0.9, drop_artifacts=True,
                drop_ambiguous_isomers=True, si_threshold=None, si_operator=">="):
        calls.update(si_threshold=si_threshold, si_operator=si_operator)
        return {"peaks": pd.DataFrame({"si": [90.0]})}

    res, param = G6.run_fraction_with_si(backend, {"CK": "x.txt"}, 0.6, 0.9,
                                         False, False, 80, ">=")
    ok(param == "si_threshold", "在 run_fraction 上通过 inspect 找到 si_threshold 形参")
    ok(calls["si_threshold"] == 80 and calls["si_operator"] == ">=",
       "SI 门槛与算子已传入后端")

    # 后端不支持 SI 形参（符合其余调用契约）→ 不传 SI，靠独立复核兜底
    def backend_legacy(files, rt_win=0.6, cos_min=0.9, drop_artifacts=True,
                       drop_ambiguous_isomers=True):
        return {"peaks": pd.DataFrame({"name": ["A", "B"], "si": [90.0, 60.0]})}

    res, param = G6.run_fraction_with_si(backend_legacy, {"CK": "x"}, 0.6, 0.9,
                                         False, False, 80, ">=")
    ok(param is None, "后端无 SI 形参 → 不传参（由独立复核兜底）")
    passed, detail = G6.verify_si_enforced(res["peaks"], 80, ">=")
    ok(not passed, "该情形下独立复核判定不通过 → G6 会 FAIL")
    ok("1 个" in detail, f"精确报出不达标峰数: {detail}")

    # 不设门槛时不传 SI 参数
    res, param = G6.run_fraction_with_si(backend_legacy, {"CK": "x"}, 0.6, 0.9,
                                         False, False, None, ">=")
    ok(param is None, "不设门槛 → 不传 SI 参数")
    ok(G6.verify_si_enforced(res["peaks"], None, ">=")[0], "不设门槛 → 复核通过")

    # 后端连基础契约都不满足 → 直接抛错（响亮失败，不静默降级）
    def backend_broken(files):
        return {"peaks": pd.DataFrame({"si": [90.0]})}

    try:
        G6.run_fraction_with_si(backend_broken, {"CK": "x"}, 0.6, 0.9,
                                False, False, 80, ">=")
        ok(False, "后端不符合同约应抛错")
    except TypeError:
        ok(True, "后端不符合同约 → TypeError（响亮失败，不静默降级）")


def test_runner_exit_codes():
    print("run_workflow 退出码语义 (0=PASS 2=REVIEW 其他=FAIL):")
    py = sys.executable
    tmp = Path(tempfile.mkdtemp(prefix="pygcms_rw_"))

    m = {"stages": {}}
    ok(RW.run_stage([py, "-c", "pass"], "ok", m, "G6", str(tmp), True), "退出码 0 → 阶段继续")
    ok(m["stages"]["G6"] == "PASS", "记为 PASS")

    m = {"stages": {}}
    ok(RW.run_stage([py, "-c", "import sys; sys.exit(2)"], "review", m, "G6",
                    str(tmp), True), "退出码 2 → REVIEW 不阻断后续阶段")
    ok(m["stages"]["G6"] == "REVIEW", "记为 REVIEW（而非 FAIL）")
    ok("G6" in m.get("review_stages", []), "REVIEW 阶段被登记")

    m = {"stages": {}}
    ok(not RW.run_stage([py, "-c", "import sys; sys.exit(1)"], "fail", m, "G6",
                        str(tmp), True), "退出码 1 → FAIL 阻断")
    ok(m["stages"]["G6"] == "FAIL", "记为 FAIL")
    ok(m.get("failure_stage") == "G6", "登记失败阶段")


if __name__ == "__main__":
    print("=" * 60)
    print("G6 SI 门槛 / 退出码 测试")
    print("=" * 60)
    test_si_verification()
    test_backend_param_binding()
    test_runner_exit_codes()
    print("=" * 60)
    print(f"全部通过: {_n} 项断言")
