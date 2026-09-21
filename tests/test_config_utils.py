#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""config_utils 测试：配置读取、布尔正确性、路径解析、SI 口径。

运行: python tests/test_config_utils.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from config_utils import (DEFAULT_SI_THRESHOLD, get_si_rule, load_config,  # noqa: E402
                          project_root, resolve_path, si_passes, si_rule_text)

_n = 0


def ok(cond, msg):
    global _n
    _n += 1
    if not cond:
        raise AssertionError(f"FAIL: {msg}")
    print(f"  ok {_n:02d} {msg}")


def write_cfg(text: str, name: str = "config.yaml") -> Path:
    d = Path(tempfile.mkdtemp(prefix="pygcms_cfg_"))
    (d / "config").mkdir()
    p = d / "config" / name
    p.write_text(text, encoding="utf-8")
    return p


def test_boolean_types():
    """回归：手写回退曾把 'false' 解析成字符串（真值），静默打开异构体切换。"""
    print("布尔类型（回归：'false' 曾被误当真值）:")
    p = write_cfg(
        "filters:\n"
        "  si_threshold: 80\n"
        "  si_operator: \">=\"\n"
        "adjudicate:\n"
        "  enabled: false\n"
        "  allow_isomer_switch: false\n"
        "  keep_artifacts: false\n"
        "  rt_win: 0.6\n"
    )
    cfg = load_config(str(p))
    adj = cfg["adjudicate"]
    ok(adj["enabled"] is False, "enabled: false 解析为 Python False（不是字符串）")
    ok(adj["allow_isomer_switch"] is False, "allow_isomer_switch: false 解析为 False")
    ok(adj["keep_artifacts"] is False, "keep_artifacts: false 解析为 False")
    ok(not adj["enabled"], "`if not enabled` 为真 → 阶段会正确跳过")
    ok(not bool(adj["allow_isomer_switch"]), "异构体守卫保持关闭（不会被静默打开）")
    ok(isinstance(adj["rt_win"], float) and abs(adj["rt_win"] - 0.6) < 1e-9,
       "rt_win 解析为 float 而非字符串")
    ok(isinstance(cfg["filters"]["si_threshold"], int)
       and cfg["filters"]["si_threshold"] == 80, "si_threshold 解析为 int")


def test_pyyaml_required():
    print("PyYAML 为硬依赖:")
    p = write_cfg("filters:\n  si_threshold: 80\n")
    cfg = load_config(str(p))
    ok(isinstance(cfg, dict), "正常读取返回 dict")
    ok(load_config(str(p)) is not None, "load_config 不返回 None")


def test_paths():
    print("路径解析:")
    p = write_cfg("project:\n  name: t\n")
    root = project_root(str(p))
    ok(root.name == p.parent.parent.name, "config/ 下的配置：基准为项目根")
    ok(resolve_path(str(p), "data/raw") == str((root / "data" / "raw").resolve()),
       "相对路径从项目根解析")
    absd = str(Path(tempfile.gettempdir()).resolve())
    ok(resolve_path(str(p), absd) == absd, "绝对路径原样返回")
    ok(resolve_path(str(p), "") == "", "空值返回空串")
    ok(resolve_path(str(p), None) == "", "None 返回空串")


def test_si_rule():
    print("SI 口径:")
    ok(DEFAULT_SI_THRESHOLD == 80.0, "默认门槛 80")
    p = write_cfg("filters:\n  si_threshold: 80\n  si_operator: \">=\"\n")
    thr, op = get_si_rule(load_config(str(p)))
    ok(thr == 80.0 and op == ">=", "读取 SI >= 80")

    p2 = write_cfg("filters:\n  si_threshold: 80\n  si_operator: \">\"\n")
    thr2, op2 = get_si_rule(load_config(str(p2)))
    ok(thr2 == 80.0 and op2 == ">", "读取严格 SI > 80")

    p3 = write_cfg("project:\n  name: t\n")
    thr3, op3 = get_si_rule(load_config(str(p3)))
    ok(thr3 == 80.0 and op3 == ">=", "缺省时为 SI >= 80（本项目口径）")

    p4 = write_cfg("filters:\n  si_threshold: 80\n  si_operator: \"==\"\n")
    try:
        get_si_rule(load_config(str(p4)))
        ok(False, "非法算子应抛错")
    except ValueError:
        ok(True, "非法算子抛 ValueError")

    p5 = write_cfg("filters:\n  si_threshold:\n  si_operator: \">=\"\n")
    thr5, _ = get_si_rule(load_config(str(p5)))
    ok(thr5 is None, "空门槛 → None（表示不设门槛）")

    ok(si_rule_text(None, ">=") == "无 SI 门槛（保留全部峰）", "口径描述：无门槛")
    ok(si_rule_text(80, ">=") == "SI >= 80", "口径描述：SI >= 80")

    print("SI 判据:")
    ok(si_passes(80, 80, ">="), "'>='  保留 80")
    ok(not si_passes(80, 80, ">"), "'>'   剔除 80")
    ok(si_passes(80.5, 80, ">"), "'>'   保留 80.5")
    ok(not si_passes(79, 80, ">="), "79 不达标")
    ok(si_passes(None, None, ">="), "无门槛时 None 也通过")
    ok(not si_passes(None, 80, ">="), "有门槛时无 SI 不通过")
    ok(not si_passes("abc", 80, ">="), "非数值不通过")


if __name__ == "__main__":
    print("=" * 60)
    print("config_utils 测试")
    print("=" * 60)
    test_boolean_types()
    test_pyyaml_required()
    test_paths()
    test_si_rule()
    print("=" * 60)
    print(f"全部通过: {_n} 项断言")
