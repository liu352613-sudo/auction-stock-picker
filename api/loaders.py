# -*- coding: utf-8 -*-
"""静态数据加载器 + DataService 入口。

负责从 data/ 目录读取预生成的 JSON（前端静态模式的同一批数据），
供各 API 路由「静态优先、实时补充」地组装响应。所有 AkShare 访问都经
src.data_service.data_service 单例。
"""
import json
import os
import sys
from typing import Any, Dict, List, Optional

# 项目根目录（api/ 的上级）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
KLINES_DIR = os.path.join(DATA_DIR, "klines")
HISTORY_DIR = os.path.join(DATA_DIR, "history")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.data_service import data_service  # noqa: E402


def load_json(path: str, default: Any = None) -> Any:
    """读取 JSON，失败返回 default。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def results() -> Dict:
    return load_json(os.path.join(DATA_DIR, "results.json"), {}) or {}


def stats() -> Dict:
    return load_json(os.path.join(DATA_DIR, "stats.json"), {}) or {}


def params() -> Dict:
    return load_json(os.path.join(DATA_DIR, "params.json"), {}) or {}


def history_index() -> List[Dict]:
    return load_json(os.path.join(DATA_DIR, "history_index.json"), []) or []


def history_snapshot(date_str: str) -> Optional[Dict]:
    p = os.path.join(HISTORY_DIR, f"{date_str}.json")
    return load_json(p)


def kline(code: str) -> Optional[Dict]:
    name = f"{str(code).zfill(6)}.json"
    return load_json(os.path.join(KLINES_DIR, name))


def stock_in_results(code: str) -> Optional[Dict]:
    """从当日 results.json 中查找某只股票的静态信息。"""
    payload = results()
    for s in payload.get("stocks", []) or []:
        if str(s.get("代码")) == str(code):
            return s
    return None


def normalize_index_row(name, code, val, diff, pct) -> Dict:
    return {
        "name": name,
        "code": code,
        "val": _num(val),
        "diff": _num(diff),
        "pct": pct if isinstance(pct, str) else (f"{float(pct):+.2f}%" if _num(pct) is not None else "-"),
    }


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None
