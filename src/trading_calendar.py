# -*- coding: utf-8 -*-
"""交易日历与「生效交易日」逻辑
=================================
解决「该展示哪一天的推荐」问题，统一一套口径，避免各端自行判断导致不一致：

- 周末 / 法定节假日  → 展示「最近一个交易日」的推荐
- 交易日 09:26 之前   → 展示「上一交易日」的推荐（当日竞价数据尚未生成）
- 交易日 09:26 之后   → 展示「当天」的推荐

对外只暴露一个函数 ``effective_trade_date(now=None)``，返回「当前应当展示的
交易日(date)」。首页 / 历史 / 回测 / API 全部调用它，保证四端一致。

数据来源
--------
优先经统一 DataService 拉取交易所官方交易日历（akshare），并缓存到
``data/.trade_calendar.json``（7 天有效），便于离线 / 沙箱复用；网络与缓存
均不可用时，回退到「工作日 − 已知节假日」的启发式近似。
"""
from __future__ import annotations

import datetime
import json
import os
from typing import List, Optional, Set

try:
    from .data_service import data_service
except ImportError:  # 作为脚本 `python src/trading_calendar.py` 运行时
    from data_service import data_service

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(ROOT, "data", ".trade_calendar.json")
CACHE_TTL_DAYS = 7

# 竞价切换时间点（09:26 生成当日推荐）
CUTOVER_HOUR = 9
CUTOVER_MINUTE = 26

# 已知法定节假日（仅作离线回退的兜底；网络可用时以官方日历为准）
# 格式：YYYY-MM-DD。覆盖 2025~2026 主要长假。
KNOWN_HOLIDAYS: Set[str] = {
    # 2025
    "2025-01-01", "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
    "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",
    "2025-04-04", "2025-04-05", "2025-04-06",
    "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
    "2025-06-02",
    "2025-09-03",
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04", "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
    "2025-12-31",
    # 2026
    "2026-01-01", "2026-01-02",
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22",
    "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19",
    "2026-09-25", "2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07",
    "2026-12-31",
}


def _load_cache() -> Optional[dict]:
    try:
        if not os.path.exists(CACHE_PATH):
            return None
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        updated = datetime.datetime.fromisoformat(d.get("updated", "2000-01-01T00:00:00"))
        if (datetime.datetime.now() - updated).days > CACHE_TTL_DAYS:
            return None
        return d
    except Exception:
        return None


def _save_cache(days: List[str]):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"updated": datetime.datetime.now().isoformat(), "days": days}, f, ensure_ascii=False)
    except Exception:
        pass


def fetch_official_calendar() -> List[str]:
    """经 DataService 拉取官方交易日历（东财/新浪）。失败抛异常。"""
    ak = data_service.ak
    last_err = None
    for fn in ("tool_trade_date_hist_sina", "tool_trade_date_hist_sh"):
        if not hasattr(ak, fn):
            continue
        try:
            df = getattr(ak, fn)()
            col = "trade_date" if "trade_date" in df.columns else df.columns[0]
            vals = df[col].tolist()
            out = []
            for v in vals:
                if isinstance(v, datetime.datetime):
                    out.append(v.strftime("%Y-%m-%d"))
                elif isinstance(v, datetime.date):
                    out.append(v.isoformat())
                else:
                    s = str(v)[:10]
                    if len(s) == 10 and s[4] == "-":
                        out.append(s)
            if out:
                return out
        except Exception as e:
            last_err = e
    if last_err:
        raise RuntimeError(f"官方交易日历拉取失败: {last_err}")
    raise RuntimeError("未找到可用的交易日历接口")


def heuristic_calendar() -> List[str]:
    """离线回退：最近 730 天的工作日，剔除已知节假日。"""
    out = []
    end = datetime.date.today() + datetime.timedelta(days=10)
    d = end - datetime.timedelta(days=730)
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in KNOWN_HOLIDAYS:
            out.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return out


def get_trade_calendar(force_refresh: bool = False) -> Set[str]:
    """返回交易日集合（'YYYY-MM-DD'）。优先缓存→官方→启发式。"""
    if not force_refresh:
        c = _load_cache()
        if c and c.get("days"):
            return set(c["days"])
    try:
        days = fetch_official_calendar()
        _save_cache(days)
        return set(days)
    except Exception:
        c = _load_cache()
        if c and c.get("days"):
            return set(c["days"])
        return set(heuristic_calendar())


def is_trading_day(date: datetime.date, calendar: Optional[Set[str]] = None) -> bool:
    if calendar is None:
        calendar = get_trade_calendar()
    return date.isoformat() in calendar


def previous_trading_day(date: datetime.date, calendar: Optional[Set[str]] = None) -> datetime.date:
    if calendar is None:
        calendar = get_trade_calendar()
    d = date - datetime.timedelta(days=1)
    for _ in range(400):  # 安全上限（约 1.5 年）
        if d.isoformat() in calendar:
            return d
        d -= datetime.timedelta(days=1)
    # 兜底：返回 7 天前（极端情况下不至于死循环）
    return date - datetime.timedelta(days=7)


def effective_trade_date(now: Optional[datetime.datetime] = None,
                         calendar: Optional[Set[str]] = None) -> datetime.date:
    """当前应当展示的「交易日」。

    规则：
    - 非交易日（周末/节假日）→ 最近一个交易日
    - 交易日 09:26 之前       → 上一交易日
    - 交易日 09:26 及之后     → 当天
    """
    now = now or datetime.datetime.now()
    if calendar is None:
        calendar = get_trade_calendar()
    today = now.date()
    if not is_trading_day(today, calendar):
        return previous_trading_day(today, calendar)
    if now.hour < CUTOVER_HOUR or (now.hour == CUTOVER_HOUR and now.minute < CUTOVER_MINUTE):
        return previous_trading_day(today, calendar)
    return today


def freshness_label(trade_date: str, now: Optional[datetime.datetime] = None) -> str:
    """根据推荐所属交易日与当前时间，给出展示文案。"""
    now = now or datetime.datetime.now()
    eff = effective_trade_date(now)
    if trade_date == eff.isoformat():
        return "today"
    return "previous"
