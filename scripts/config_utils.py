#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""配置读取与 SI 硬门槛的唯一来源（shared configuration helpers）

为什么必须强制依赖 PyYAML
--------------------------
早期版本在没有 PyYAML 时回退到手写解析，把每个值都当字符串：
    enabled: false  ->  "false"  （真值！）
于是 `bool(cfg["enabled"])` 得到 True，`if not cfg["enabled"]` 得到 False ——
**配置写 false 却被当成 true**：阶段不会跳过、异构体守卫被静默打开、
TMAH 副产物被静默保留。科研流程里这种静默错误比直接报错危险得多。
因此本模块要求真实 PyYAML，缺失即抛错。

SI 硬门槛
---------
算子必须在看结果之前定死。'>=' 与 '>' 在本项目数据集上相差 53 个峰（3.34%），
会静默改变论文里的每一个百分比。本项目采用 '>='（与历史 SI80 工作簿口径一致）。
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_SI_THRESHOLD = 80.0
SI_OPERATORS = (">=", ">")


def load_config(path: str) -> dict:
    """读取 config.yaml。强制依赖 PyYAML（缺失即抛错，绝不静默回退）。"""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PyYAML 是必需依赖。请先安装（pip install pyyaml）再运行；"
            "本流程不使用手写 YAML 回退，因为 'false' 会被误当真值。"
        ) from exc

    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if cfg is None:
        return {}
    if not isinstance(cfg, dict):
        raise ValueError("config.yaml 根节点必须是映射（mapping）")
    return cfg


def project_root(config_path: str) -> Path:
    """相对路径的解析基准。

    若配置位于 <project>/config/ 下，则从 <project> 解析；否则从配置所在目录解析。
    """
    cp = Path(config_path).resolve()
    parent = cp.parent
    return parent.parent if parent.name.lower() == "config" else parent


def resolve_path(config_path: str, value) -> str:
    """把配置里的路径解析为绝对路径（支持 ~ 与环境变量）。"""
    if value is None or str(value).strip() == "":
        return ""
    p = Path(os.path.expandvars(os.path.expanduser(str(value))))
    if p.is_absolute():
        return str(p)
    return str((project_root(config_path) / p).resolve())


def si_passes(value, threshold: float | None, operator: str = ">=") -> bool:
    """判断单个 SI 是否满足硬门槛。threshold=None 表示不设门槛。

    无 SI（None / 空 / 非数值）一律视为不满足：未鉴定不能进入候选。
    """
    if threshold is None:
        return True
    if operator not in SI_OPERATORS:
        raise ValueError(f"filters.si_operator 必须为 {SI_OPERATORS} 之一，收到 {operator!r}")
    try:
        si = float(value)
    except (TypeError, ValueError):
        return False
    return si >= float(threshold) if operator == ">=" else si > float(threshold)


def get_si_rule(cfg: dict) -> tuple[float | None, str]:
    """从配置取出 SI 口径 (threshold, operator)，带默认值与合法性校验。"""
    flt = cfg.get("filters", {}) or {}
    raw = flt.get("si_threshold", DEFAULT_SI_THRESHOLD)
    operator = str(flt.get("si_operator", ">=")).strip()
    if operator not in SI_OPERATORS:
        raise ValueError(f"filters.si_operator 必须为 {SI_OPERATORS} 之一，收到 {operator!r}")
    if raw is None or str(raw).strip() == "":
        return None, operator
    return float(raw), operator


def si_rule_text(threshold: float | None, operator: str) -> str:
    """人类可读的 SI 口径描述（写进报告与 manifest）。"""
    if threshold is None:
        return "无 SI 门槛（保留全部峰）"
    return f"SI {operator} {threshold:g}"
