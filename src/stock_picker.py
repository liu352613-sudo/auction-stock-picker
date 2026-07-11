#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auction_picker_akshare.py
=========================

竞价选股器（AkShare 版）

每个交易日 09:26 自动运行，基于集合竞价数据筛选强势个股，输出 Markdown 报告。
包含：市场温度计、个股初筛、动能评分、板块效应加分、止盈止损计算、风控降级。

用法:
    python auction_picker_akshare.py [--output-dir DIR] [--demo]
    python auction_picker_akshare.py --backtest [--scope all] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--limit N]
    python auction_picker_akshare.py --backtest-demo        # 合成数据验证回测链路

    --output-dir      报告输出目录 (默认: ./auction_reports)
    --demo            使用内置样例数据跑通选股全流程(无需联网/盘中数据)
    --backtest        运行历史回测(需联网拉取日线, 全A股较重, 建议 --limit 先验证)
    --backtest-demo   用内置合成数据跑通回测流程(无需联网)
    --scope/--start/--end/--limit  回测范围 / 区间 / 抽样上限
"""

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# 统一数据服务层：本项目唯一允许访问 AkShare 的入口（页面/策略不再直接 import akshare）
try:
    from .data_service import data_service
except ImportError:  # 作为脚本 `python src/stock_picker.py` 运行时
    from data_service import data_service

# 统一评分引擎：首页 / 历史 / 回测 / API 四端共用同一套评分逻辑
try:
    from .scoring import score_stock, StockFeatures
except ImportError:
    from scoring import score_stock, StockFeatures

# ----------------------------------------------------------------------------
# 配置常量
# ----------------------------------------------------------------------------
VOL_RATIO_MIN = 3.0          # 竞价量比下限
AUCTION_AMOUNT_MIN = 5_000_000  # 竞价成交额下限 (500 万)
NEW_STOCK_DAYS = 60          # 上市不足该天数视为新股剔除
TAKE_PROFIT = 0.05           # 止盈 5%
STOP_LOSS = 0.03             # 止损 3%
SECTOR_BONUS = 5.0           # 板块效应加分

# 主选板块前缀 (沪市60/68, 深市00/30)
BOARD_PREFIX = ("60", "68", "00", "30")


# ----------------------------------------------------------------------------
# 策略参数（集中管理，支持自动调参与前端配置）
# ----------------------------------------------------------------------------
from dataclasses import dataclass, fields, asdict


@dataclass
class StrategyParams:
    """竞价选股策略的全部可调参数。

    默认值与上方历史常量一致；自动调参 / 前端配置通过 from_dict 构造。
    """

    # —— 初筛 ——
    vol_ratio_min: float = 3.0            # 竞价量比下限
    auction_amount_min: float = 5_000_000  # 竞价成交额下限 (元)
    new_stock_days: int = 60             # 上市不足该天数视为新股剔除
    # 动态开盘涨幅阈值: low=max(lo_base, market_pct+lo_offset); high=min(hi_base, market_pct+hi_offset)
    threshold_lo_base: float = 2.0
    threshold_hi_base: float = 6.0
    threshold_lo_offset: float = 1.5
    threshold_hi_offset: float = 6.0
    # —— 风控 ——
    take_profit: float = 0.05            # 止盈 5%
    stop_loss: float = 0.03              # 止损 3%
    sector_bonus: float = 5.0            # 板块效应加分
    # —— 评分权重 (合计 100) ——
    w_vol_ratio: float = 30.0            # 量比归一化权重
    w_rel_market: float = 20.0           # 相对大盘权重
    w_ma60_dev: float = 25.0             # 60日均线偏离权重
    w_vol_energy: float = 25.0           # 量能比权重
    vol_ratio_top: float = 5.0           # 量比归一化满分上限
    ma60_dev_sweet: float = 0.05         # 均线偏离甜区下界
    ma60_dev_max: float = 0.15           # 均线偏离甜区上界
    vol_energy_lo: float = 0.03          # 量能比下界
    vol_energy_hi: float = 0.10          # 量能比上界
    # —— 过滤开关 ——
    filter_st: bool = True               # 剔除 ST
    filter_new_stock: bool = True        # 剔除新股
    filter_suspended: bool = True        # 剔除停牌
    filter_limit_up: bool = True         # 剔除已封板涨停股(无法买入)
    # —— 买入程度阈值 ——
    level_strong: float = 80.0
    level_mid: float = 60.0
    level_cautious: float = 40.0

    @classmethod
    def from_dict(cls, d):
        if not d:
            return cls()
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})

    def to_dict(self):
        return asdict(self)


def get_default_params():
    """返回默认策略参数（dataclass 默认值）。"""
    return StrategyParams()


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def ensure_deps():
    """确保 akshare/pandas/numpy 可用，缺失时尝试自动安装（委托 DataService）。"""
    data_service.ensure_deps()


def _safe_num(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _clamp01(x):
    try:
        x = float(x)
        if x != x:
            return 0.0
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, x))


def _sector_heat_from_avg(sec_avg_pct, market_pct):
    """由板块平均涨幅相对大盘，映射到板块热度 [0,1]。

    板块平均涨幅 == 大盘 -> 0.5；高于大盘约 3% -> ~1.0；低于约 3% -> ~0。
    """
    return _clamp01(0.5 + (float(sec_avg_pct) - float(market_pct)) / 6.0)


def _to_detail(result):
    """把 score_stock 的结果转为与前端兼容的「评分明细」字典。

    既保留旧版的 4 个数值键（量比分/相对大盘分/均线偏离分/量能比分/偏离度%/量能比%），
    又附加新的 ``dimensions``（8 维度拆解）与 ``risk_factor``，供详情页「评分拆解」使用。
    """
    dims = {d["key"]: d for d in result.get("dimensions", [])}
    feat = result.get("features", {})
    price, ma60 = _safe_num(feat.get("price")), _safe_num(feat.get("ma60"))
    prev = _safe_num(feat.get("prev_volume"))
    dev = ((price - ma60) / ma60 * 100.0) if ma60 > 0 else 0.0
    ratio = (_safe_num(feat.get("auction_volume")) / prev * 100.0) if prev > 0 else 0.0
    return {
        "量比分": round(dims.get("vol_ratio", {}).get("score", 0.0), 2),
        "相对大盘分": round(dims.get("rel_market", {}).get("score", 0.0), 2),
        "均线偏离分": round(dims.get("ma60_dev", {}).get("score", 0.0), 2),
        "量能比分": round(dims.get("vol_energy", {}).get("score", 0.0), 2),
        "偏离度%": round(dev, 2),
        "量能比%": round(ratio, 2),
        "dimensions": result.get("dimensions", []),
        "risk_factor": result.get("risk_factor", 1.0),
        "total": result.get("total", 0.0),
    }


# ----------------------------------------------------------------------------
# 模块 1: 市场温度计
# ----------------------------------------------------------------------------
def get_market_temperature():
    """计算大盘综合温度 (0-100)。返回 dict。"""
    temp = {
        "index_score": 0.0, "breadth_score": 0.0, "north_score": 0.0,
        "total": 0.0, "level": "常温", "position": 60, "market_pct": 0.0,
        "up": 0, "down": 0, "north_flow": 0.0, "north_mean": 0.0,
        "index_avg": 0.0, "note": "",
    }
    try:
        # (1) 指数表现 (40 分)
        try:
            # 沪深重要指数 包含 沪深300/上证指数/深证成指/创业板指 等
            # 改用新浪财经接口（海外服务器对东方财富常被拒）
            idx = data_service.index_spot_sina()
            targets = {}
            for _, row in idx.iterrows():
                name = str(row.get("名称", ""))
                for key in ("沪深300", "上证指数", "深证成指", "创业板指"):
                    if key in name and key not in targets:
                        targets[key] = _safe_num(row.get("涨跌幅", 0))
            vals = [v for v in targets.values() if v is not None]
            if vals:
                index_avg = float(np.mean(vals))
                temp["index_avg"] = index_avg
                if index_avg >= 0.5:
                    temp["index_score"] = 40.0
                elif index_avg <= -1.0:
                    temp["index_score"] = 0.0
                else:
                    temp["index_score"] = 40.0 * (index_avg + 1.0) / 1.5
        except Exception as e:
            temp["note"] += f"指数数据获取失败: {e}; "

        # (2) 涨跌比 (35 分)
        try:
            spot = data_service.a_spot()
            pct = pd.to_numeric(spot["涨跌幅"], errors="coerce")
            up = int((pct > 0).sum())
            down = int((pct < 0).sum())
            temp["up"], temp["down"] = up, down
            ratio = (up / down) if down > 0 else (float(up) if up > 0 else 0.0)
            if ratio >= 2.0:
                temp["breadth_score"] = 35.0
            elif ratio <= 0.5:
                temp["breadth_score"] = 0.0
            else:
                temp["breadth_score"] = 35.0 * (ratio - 0.5) / (2.0 - 0.5)
        except Exception as e:
            temp["note"] += f"涨跌比数据获取失败: {e}; "

        # (3) 北向资金 (25 分)
        try:
            north = _get_north_flow(ak)
            today_flow, mean5 = _parse_north(north)
            temp["north_flow"] = today_flow
            temp["north_mean"] = mean5
            if mean5 <= 0:
                temp["north_score"] = 25.0 if today_flow > 0 else 0.0
            elif today_flow >= mean5:
                temp["north_score"] = 25.0
            elif today_flow <= 0:
                temp["north_score"] = 0.0
            else:
                temp["north_score"] = 25.0 * today_flow / mean5
        except Exception as e:
            temp["note"] += f"北向资金获取失败: {e}; "

        temp["total"] = temp["index_score"] + temp["breadth_score"] + temp["north_score"]
        temp["total"] = round(min(100.0, max(0.0, temp["total"])), 1)
        temp["market_pct"] = round(temp["index_avg"], 2)
        temp["index_score"] = round(temp["index_score"], 1)
        temp["breadth_score"] = round(temp["breadth_score"], 1)
        temp["north_score"] = round(temp["north_score"], 1)

        t = temp["total"]
        if t > 80:
            temp["level"], temp["position"] = "极热", 80
        elif t >= 60:
            temp["level"], temp["position"] = "温暖", 80
        elif t >= 40:
            temp["level"], temp["position"] = "常温", 60
        elif t >= 20:
            temp["level"], temp["position"] = "寒冷", 40
        else:
            temp["level"], temp["position"] = "极寒", 20
    except Exception as e:
        temp["note"] += f"温度计异常: {e}"
        temp["level"], temp["position"], temp["total"] = "常温", 60, 50.0

    return temp


def _get_north_flow(ak):
    """兼容多种北向资金接口名称，返回原始 DataFrame。"""
    for fn in ("stock_hsgt_north_net_flow_in_em", "stock_hsgt_north_cash_flow_summary_em",
               "stock_hsgt_fund_flow_summary_em"):
        if hasattr(ak, fn):
            try:
                return getattr(ak, fn)(symbol="北上")
            except Exception:
                try:
                    return getattr(ak, fn)()
                except Exception:
                    continue
    return None


def _parse_north(north):
    """从北向资金原始数据解析 (当日净流入, 过去5日均值)。

    兼容两种结构：
    - 长表 (stock_hsgt_fund_flow_summary_em)：含 资金方向/交易日/成交净买额，
      按 资金方向=北向 聚合到每日后取最新与近5日均值。
    - 简单时间序列：直接取末值与近5日均值。
    返回 (today, mean5)，失败返回 (0.0, 0.0)。
    """
    if north is None or len(north) == 0:
        return 0.0, 0.0
    try:
        if "资金方向" in north.columns:
            nb = north[north["资金方向"].astype(str).str.contains("北向", na=False)].copy()
            valcol = "成交净买额" if "成交净买额" in nb.columns else (
                "资金净流入" if "资金净流入" in nb.columns else None)
            if valcol is None:
                return 0.0, 0.0
            nb["交易日"] = pd.to_datetime(nb["交易日"], errors="coerce")
            nb[valcol] = pd.to_numeric(nb[valcol], errors="coerce")
            daily = nb.groupby("交易日")[valcol].sum().sort_index()
            if len(daily) == 0:
                return 0.0, 0.0
            today = float(daily.iloc[-1])
            window = daily.iloc[-6:-1]
            mean5 = float(window.mean()) if len(window) > 0 else 0.0
            return today, mean5
        # 简单时间序列兜底
        flow_col = None
        for col in north.columns:
            if "净" in str(col) or "flow" in str(col).lower():
                flow_col = col
                break
        if flow_col is None and len(north.columns) > 0:
            flow_col = north.columns[-1]
        series = pd.to_numeric(north[flow_col], errors="coerce").dropna()
        if len(series) == 0:
            return 0.0, 0.0
        today = float(series.iloc[-1])
        window = series.iloc[-6:-1]
        mean5 = float(window.mean()) if len(window) > 0 else 0.0
        return today, mean5
    except Exception:
        return 0.0, 0.0


# ----------------------------------------------------------------------------
# 模块 2: 动态阈值
# ----------------------------------------------------------------------------
def calc_dynamic_threshold(market_pct, params=None):
    """动态开盘涨幅阈值（可配置）。

    下限 = max(threshold_lo_base, 大盘涨幅 + threshold_lo_offset)
    上限 = min(threshold_hi_base, 大盘涨幅 + threshold_hi_offset)
    """
    p = params or StrategyParams()
    mp = market_pct or 0.0
    low = max(p.threshold_lo_base, mp + p.threshold_lo_offset)
    high = min(p.threshold_hi_base, mp + p.threshold_hi_offset)
    if low > high:  # 极端行情保护
        low, high = high, low
    return round(low, 2), round(high, 2)


# ----------------------------------------------------------------------------
# 模块 3: 股票池 & 初筛
# ----------------------------------------------------------------------------
def get_stock_pool():
    """获取全市场 A 股实时行情（剔除非主选板块）。

    使用 AkShare 的东方财富接口 stock_zh_a_spot_em（该接口包含「量比」字段，
    而新浪 stock_zh_a_spot 实际不返回量比列，故改回东方财富）。
    带重试：重试 3 次、每次间隔 3 秒、模拟浏览器 UA。
    若所有尝试均失败，打印警告并返回空 DataFrame。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    last_err = None
    for attempt in range(1, 4):  # 重试 3 次
        try:
            # stock_zh_a_spot_em 内部已带 UA；此处额外兜底设置环境变量 UA
            os.environ.setdefault("HTTP_USER_AGENT", headers["User-Agent"])
            df = data_service.a_spot_em()
            if df is None or len(df) == 0:
                raise ValueError("东方财富接口返回空数据")
            # 打印实际返回列名，便于核对接口字段（尤其量比）
            log(f"get_stock_pool 实际列名: {list(df.columns)}")
            # 东方财富列名：今开 -> 开盘（下游统一使用「开盘」）
            if "今开" in df.columns and "开盘" not in df.columns:
                df = df.rename(columns={"今开": "开盘"})
            df["__code"] = df["代码"].astype(str)
            df = df[df["__code"].str.startswith(BOARD_PREFIX)].copy()
            return df
        except Exception as e:
            last_err = e
            log(f"get_stock_pool 第 {attempt}/3 次尝试失败: {e}")
            if attempt < 3:
                time.sleep(3)

    log(f"警告: get_stock_pool 全部 3 次尝试失败，返回空列表。最后一次错误: {last_err}")
    return pd.DataFrame(columns=["代码", "名称", "最新价", "涨跌幅", "成交量", "成交额", "量比", "开盘", "__code"])


def get_new_stock_codes(days=NEW_STOCK_DAYS):
    """返回上市不足 days 日的新股代码集合。"""
    try:
        new_df = data_service.new_stock()
        new_df["上市日期"] = pd.to_datetime(new_df["上市日期"], errors="coerce")
        cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
        mask = new_df["上市日期"] >= cutoff
        return set(new_df.loc[mask, "代码"].astype(str).tolist())
    except Exception:
        return set()


def filter_stocks(df, params, market_pct):
    """初筛：量比、开盘涨幅(动态阈值)、竞价成交额，剔除 ST/停牌/涨停板。

    params: StrategyParams 实例（None 取默认）。
    """
    p = params or StrategyParams()
    low, high = calc_dynamic_threshold(market_pct, p)
    df = df.copy()
    for col in ("涨跌幅", "量比", "成交额", "成交量", "最新价"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    name = df["名称"].astype(str)
    if p.filter_st:
        df = df[~name.str.contains("ST", case=False, na=False)]
    if p.filter_suspended:
        df = df[df["涨跌幅"].notna()]
        df = df[df["成交量"].fillna(0) > 0]
    if p.filter_limit_up:
        # 开盘即涨停 / 接近涨停(>=9.5%) 无法买入，剔除
        df = df[df["涨跌幅"] < 9.5]
    cond = (
        (df["量比"] >= p.vol_ratio_min)
        & (df["涨跌幅"] >= low)
        & (df["涨跌幅"] <= high)
        & (df["成交额"] >= p.auction_amount_min)
    )
    return df[cond].copy()


# ----------------------------------------------------------------------------
# 模块 4: 动能评分
# ----------------------------------------------------------------------------
def get_stock_hist(code):
    """返回 (ma60, 昨日全天成交量, ma5, ma10, ma20, 年化波动率)。

    优先东财，失败回退新浪。任何失败均返回 0 元组（由评分引擎按缺失处理，
    对应子分项得 0，绝不会因此拿到满分）。
    """
    try:
        hist = _fetch_stock_hist_robust(code, adjust="qfq")
        if hist is None or len(hist) == 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        closes = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
        vols = pd.to_numeric(hist["成交量"], errors="coerce").dropna()
        n = len(closes)
        ma60 = float(closes.iloc[-60:].mean()) if n >= 60 else (float(closes.mean()) if n else 0.0)
        ma20 = float(closes.iloc[-20:].mean()) if n >= 20 else ma60
        ma10 = float(closes.iloc[-10:].mean()) if n >= 10 else ma20
        ma5 = float(closes.iloc[-5:].mean()) if n >= 5 else ma10
        prev_vol = float(vols.iloc[-2]) if n >= 2 else 0.0
        # 年化波动率：近 20 日对数收益标准差 * sqrt(252)
        if n >= 21:
            rets = np.diff(np.log(closes.iloc[-21:].to_numpy(dtype=float)))
            vol = float(np.std(rets) * np.sqrt(252))
        else:
            vol = 0.0
        return ma60, prev_vol, ma5, ma10, ma20, vol
    except Exception:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0


def calc_momentum_score(price, vol_ratio, pct_change, ma60, market_pct,
                        auction_volume, prev_volume, params=None):
    """动能评分（向后兼容包装）。

    直接委托统一评分引擎 score_stock，仅用传入的 4 个原始维度构造特征，
    其余维度（竞价金额/资金流/板块热度/趋势）因缺少输入得 0。返回 (总分, 明细dict)，
    明细保留旧版 4 个数值键以保持外部调用兼容。
    """
    p = params or StrategyParams()
    feat = StockFeatures(
        price=_safe_num(price), vol_ratio=_safe_num(vol_ratio),
        pct_open=_safe_num(pct_change), ma60=_safe_num(ma60),
        auction_volume=_safe_num(auction_volume), prev_volume=_safe_num(prev_volume),
        market_pct=_safe_num(market_pct),
    )
    result = score_stock(feat, p)
    dims = {d["key"]: d["score"] for d in result["dimensions"]}
    dev = ((price - ma60) / ma60 * 100.0) if ma60 else 0.0
    ratio = (auction_volume / prev_volume * 100.0) if prev_volume else 0.0
    detail = {
        "量比分": round(dims.get("vol_ratio", 0.0), 2),
        "相对大盘分": round(dims.get("rel_market", 0.0), 2),
        "均线偏离分": round(dims.get("ma60_dev", 0.0), 2),
        "量能比分": round(dims.get("vol_energy", 0.0), 2),
        "偏离度%": round(dev, 2), "量能比%": round(ratio, 2),
    }
    return round(result["total"], 2), detail


# ----------------------------------------------------------------------------
# 模块 5: 板块 / 行业
# ----------------------------------------------------------------------------
def get_industry(code):
    """获取个股所属行业板块。"""
    try:
        info = data_service.individual_info(code)
        d = {}
        for _, r in info.iterrows():
            d[str(r.iloc[0])] = r.iloc[1]
        return d.get("行业", "未知")
    except Exception:
        return "未知"


def get_stock_profile(code):
    """获取个股行业与总市值。返回 (行业, 总市值元)。失败返回 ('未知', 0.0)。

    总市值单位与 AkShare 一致（元）。
    """
    try:
        info = data_service.individual_info(code)
        d = {}
        for _, r in info.iterrows():
            d[str(r.iloc[0])] = r.iloc[1]
        return d.get("行业", "未知"), _safe_num(d.get("总市值", 0))
    except Exception:
        return "未知", 0.0


# ----------------------------------------------------------------------------
# 模块 6: 板块效应加分
# ----------------------------------------------------------------------------
def add_sector_bonus(df, params=None):
    """同一板块 >=2 只进入初筛，则该板块所有股票统一加分（可配置）。"""
    p = params or StrategyParams()
    df = df.copy()
    counts = df["行业"].value_counts()
    multi = set(counts[counts >= 2].index.tolist())
    df["板块加分"] = 0.0
    df.loc[df["行业"].isin(multi), "板块加分"] = p.sector_bonus
    df["动能评分"] = (df["动能评分"] + df["板块加分"]).clip(upper=100.0)
    return df, multi


# ----------------------------------------------------------------------------
# 买入程度 & 风控降级
# ----------------------------------------------------------------------------
def recommend_level(score, params=None):
    p = params or StrategyParams()
    if score >= p.level_strong:
        return "强烈推荐"
    elif score >= p.level_mid:
        return "中等"
    elif score >= p.level_cautious:
        return "谨慎"
    return "不推荐"


DOWNGRADE = {"强烈推荐": "中等", "中等": "谨慎", "谨慎": "不推荐", "不推荐": "不推荐"}


# ----------------------------------------------------------------------------
# 模块 7: 生成 Markdown 报告
# ----------------------------------------------------------------------------
def generate_report(temp, res_df, low, high, today, multi_sectors):
    lines = []
    lines.append(f"# 竞价选股日报 · {today.isoformat()}\n")
    lines.append(f"> 数据时间口径：集合竞价（约 09:26）· 数据源：AkShare\n")

    # 一、市场温度计
    lines.append("## 一、🌡️ 市场温度计\n")
    lines.append(f"- **综合温度**：{temp['total']}/100")
    lines.append(f"- **温度等级**：{temp['level']}")
    lines.append(f"- **建议仓位**：{temp['position']}%")
    lines.append("")
    lines.append("| 维度 | 得分 | 说明 |")
    lines.append("|------|------|------|")
    lines.append(f"| 指数表现 (40) | {temp['index_score']} | 四大指数平均涨跌 {temp['index_avg']:.2f}% |")
    lines.append(f"| 涨跌比 (35) | {temp['breadth_score']} | 上涨 {temp['up']} / 下跌 {temp['down']} |")
    lines.append(f"| 北向资金 (25) | {temp['north_score']} | 当日净流入 {temp['north_flow']:.2f} / 5日均 {temp['north_mean']:.2f} |")
    if temp.get("note"):
        lines.append(f"\n> ⚠️ 温度计提示：{temp['note']}")
    lines.append("")

    # 二、今日精选个股（前3名）
    lines.append("## 二、📊 今日精选个股（前 3 名）\n")
    top3 = res_df.head(3)
    lines.append("| 排名 | 代码 | 名称 | 动能评分 | 买入价 | 止盈价 | 止损价 | 买入程度 | 所属板块 |")
    lines.append("|------|------|------|---------|--------|--------|--------|----------|----------|")
    if len(top3) == 0:
        lines.append("| - | - | 今日无符合条件的个股 | - | - | - | - | - | - |")
    else:
        for i, (_, r) in enumerate(top3.iterrows(), 1):
            lines.append(
                f"| {i} | {r['代码']} | {r['名称']} | {r['动能评分']} | "
                f"{r['买入价']} | {r['止盈价']} | {r['止损价']} | {r['买入程度']} | {r['行业']} |"
            )
    lines.append("")

    # 三、全部初筛股票列表
    lines.append("## 三、📋 全部初筛股票列表（供参考）\n")
    lines.append(f"*共 {len(res_df)} 只通过初筛，按动能评分降序。动态开盘涨幅阈值：{low}% ~ {high}%*\n")
    lines.append("| 排名 | 代码 | 名称 | 动能评分 | 买入价 | 止盈价 | 止损价 | 买入程度 | 所属板块 |")
    lines.append("|------|------|------|---------|--------|--------|--------|----------|----------|")
    if len(res_df) == 0:
        lines.append("| - | - | 无 | - | - | - | - | - | - |")
    else:
        for i, (_, r) in enumerate(res_df.iterrows(), 1):
            lines.append(
                f"| {i} | {r['代码']} | {r['名称']} | {r['动能评分']} | "
                f"{r['买入价']} | {r['止盈价']} | {r['止损价']} | {r['买入程度']} | {r['行业']} |"
            )
    if multi_sectors:
        lines.append("")
        lines.append(f"> 板块效应：{', '.join(sorted(multi_sectors))} 板块有 2 只及以上入选，已统一 +{int(SECTOR_BONUS)} 分。")
    lines.append("")

    # 四、风险提示
    lines.append("## 四、⚠️ 风险提示\n")
    lines.append("以上推荐仅基于竞价数据筛选，不构成投资建议，请结合市场环境和个人风险承受能力审慎决策。")
    lines.append("")

    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def _enrich_and_score(filtered, market_pct, params=None):
    p = params or StrategyParams()
    # 板块平均涨幅（用于板块热度），与初筛/评分同源
    if "行业" in filtered.columns and "涨跌幅" in filtered.columns:
        sec_avg = filtered.groupby("行业")["涨跌幅"].transform("mean")
        filtered = filtered.assign(__sec_avg=sec_avg)
    else:
        filtered = filtered.assign(__sec_avg=float(market_pct))

    records = []
    cache = {}
    for _, row in filtered.iterrows():
        code = str(row["代码"])
        name = str(row["名称"])
        price = _safe_num(row.get("最新价", 0))
        vol_ratio = _safe_num(row.get("量比", 0))
        pct = _safe_num(row.get("涨跌幅", 0))
        auction_vol = _safe_num(row.get("成交量", 0))
        auction_amt = _safe_num(row.get("成交额", 0))

        if code not in cache:
            cache[code] = get_stock_hist(code)
            time.sleep(0.02)
        ma60, prev_vol, ma5, ma10, ma20, vol = cache[code]

        industry, mv = get_stock_profile(code)
        if not industry or str(industry).strip() in ("", "未知", "nan"):
            industry = row.get("行业", "未知")
            time.sleep(0.02)

        sec_avg_pct = _safe_num(row.get("__sec_avg", market_pct))
        feat = StockFeatures(
            code=code, name=name, sector=industry,
            price=price, vol_ratio=vol_ratio, pct_open=pct,
            auction_amount=auction_amt, auction_volume=auction_vol,
            ma60=ma60, ma20=ma20, ma10=ma10, ma5=ma5,
            prev_volume=prev_vol, volatility=vol,
            sector_heat=_sector_heat_from_avg(sec_avg_pct, market_pct),
            float_mv=float(mv), is_st=("ST" in str(name).upper()),
            market_pct=float(market_pct),
        )
        result = score_stock(feat, p)
        score = result["total"]

        # 涨停价（用于前端提示买入难度）：主板 10%、创业板/科创板 20%
        limit_pct = 0.20 if code.startswith(("30", "68")) else 0.10
        prev_close = price / (1 + pct / 100.0) if pct != 0 else price
        limit_up_price = round(prev_close * (1 + limit_pct), 2)

        buy = round(price, 2)
        tp = round(price * (1 + p.take_profit), 2)
        sl = round(price * (1 - p.stop_loss), 2)
        records.append({
            "代码": code, "名称": name, "动能评分": score,
            "买入价": buy, "止盈价": tp, "止损价": sl,
            "行业": industry, "市值": round(float(mv), 2), "涨停价": limit_up_price,
            "量比": round(vol_ratio, 2),
            "开盘涨幅%": round(pct, 2),
            "成交额": auction_amt,
            "最新价": round(price, 2),
            "明细": _to_detail(result),
        })
    return pd.DataFrame(records)


_EMPTY_COLS = ["代码", "名称", "动能评分", "买入价", "止盈价", "止损价",
              "行业", "市值", "涨停价", "买入程度"]


def run(output_dir, demo=False, params=None):
    ensure_deps()
    params = params or StrategyParams()
    today = datetime.date.today()
    log("开始竞价选股流程...")

    multi = set()
    res_df = pd.DataFrame(columns=_EMPTY_COLS)
    try:
        temp = get_market_temperature()
        log(f"市场温度: {temp['total']}/100 ({temp['level']})，建议仓位 {temp['position']}%")
        market_pct = temp["market_pct"]
        low, high = calc_dynamic_threshold(market_pct, params)
        log(f"动态开盘涨幅阈值: {low}% ~ {high}%")

        if demo:
            filtered = _demo_pool()
            log("DEMO 模式：使用内置样例数据。")
        else:
            pool = get_stock_pool()
            new_codes = get_new_stock_codes(params.new_stock_days)
            pool = pool[~pool["代码"].astype(str).isin(new_codes)]
            filtered = filter_stocks(pool, params, market_pct)
            log(f"初筛通过: {len(filtered)} 只")

        res_df = _enrich_and_score(filtered, market_pct, params) if len(filtered) > 0 else pd.DataFrame()

        if len(res_df) > 0:
            res_df, multi = add_sector_bonus(res_df, params)
            res_df = res_df.sort_values("动能评分", ascending=False).reset_index(drop=True)
            res_df["买入程度"] = res_df["动能评分"].apply(lambda s: recommend_level(s, params))
            if temp["level"] in ("寒冷", "极寒"):
                res_df["买入程度"] = res_df["买入程度"].replace(DOWNGRADE)
                log("温度寒冷/极寒：买入程度已统一降级。")
        else:
            res_df = pd.DataFrame(columns=_EMPTY_COLS)
    except Exception as e:
        log(f"选股流程异常，生成降级报告: {e}")
        temp = {
            "index_score": 0.0, "breadth_score": 0.0, "north_score": 0.0,
            "total": 50.0, "level": "常温", "position": 60, "market_pct": 0.0,
            "up": 0, "down": 0, "north_flow": 0.0, "north_mean": 0.0,
            "index_avg": 0.0, "note": f"实时数据获取失败: {e}",
        }
        low, high = calc_dynamic_threshold(0.0)
        multi = set()
        res_df = pd.DataFrame(columns=_EMPTY_COLS)

    report = generate_report(temp, res_df, low, high, today, multi)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"auction_recommend_{today.isoformat()}.md"
    out_path.write_text(report, encoding="utf-8")
    log(f"报告已保存: {out_path}")

    count = min(3, len(res_df))
    print(f"今日市场温度{temp['total']}，精选{count}只股票，详见报告")
    return report, out_path


def _demo_pool():
    """内置样例数据，用于离线验证全流程。"""
    data = [
        {"代码": "000001", "名称": "平安银行", "最新价": 12.30, "涨跌幅": 4.2, "量比": 5.8, "成交额": 8_000_000, "成交量": 650_000, "行业": "银行"},
        {"代码": "600519", "名称": "贵州茅台", "最新价": 1680.0, "涨跌幅": 3.1, "量比": 4.2, "成交额": 9_500_000, "成交量": 600, "行业": "白酒"},
        {"代码": "300750", "名称": "宁德时代", "最新价": 185.5, "涨跌幅": 5.0, "量比": 6.1, "成交额": 12_000_000, "成交量": 70_000, "行业": "电池"},
        {"代码": "601318", "名称": "中国平安", "最新价": 48.2, "涨跌幅": 2.8, "量比": 3.4, "成交额": 6_000_000, "成交量": 120_000, "行业": "保险"},
        {"代码": "000858", "名称": "五粮液", "最新价": 150.0, "涨跌幅": 3.6, "量比": 4.6, "成交额": 7_200_000, "成交量": 48_000, "行业": "白酒"},
        {"代码": "002594", "名称": "比亚迪", "最新价": 240.0, "涨跌幅": 4.9, "量比": 5.2, "成交额": 10_000_000, "成交量": 42_000, "行业": "汽车"},
    ]
    df = pd.DataFrame(data)
    # 给样例补充 60 日均线/昨日量 (demo 里直接注入到 get_stock_hist 的缓存)
    return df


def _demo_temp():
    return {
        "index_score": 30.0, "breadth_score": 28.0, "north_score": 20.0,
        "total": 78.0, "level": "温暖", "position": 80, "market_pct": 0.6,
        "up": 3200, "down": 800, "north_flow": 35.0, "north_mean": 20.0,
        "index_avg": 0.6, "note": "DEMO 样例数据(非真实行情)",
    }


_DEMO_HIST_MAP = {
    "000001": (11.5, 1_200_000), "600519": (1600.0, 400),
    "300750": (165.0, 90_000), "601318": (46.0, 200_000),
    "000858": (140.0, 60_000), "002594": (215.0, 55_000),
}


def _enrich_demo(filtered, market_pct, params=None):
    """离线 enrich（demo 用，不触网）。返回基础 res_df（不含板块加分/买入程度）。

    仍走统一评分引擎 score_stock，只是特征来自内置样例（清晰标注 DEMO）。
    """
    p = params or StrategyParams()
    mp = float(market_pct)
    recs = []
    for _, row in filtered.iterrows():
        code = str(row["代码"])
        price = _safe_num(row["最新价"]); vr = _safe_num(row["量比"])
        pct = _safe_num(row["涨跌幅"]); av = _safe_num(row["成交量"])
        ma60, pv = _DEMO_HIST_MAP.get(code, (price * 0.95, av * 2))
        # demo 下构造一个温和多头排列（ma5>ma10>ma20>ma60）与中等波动率
        ma5, ma10, ma20 = ma60 * 1.06, ma60 * 1.04, ma60 * 1.02
        vol = 0.35
        sec_avg_pct = mp + 1.5  # demo 假设所属板块略强于大盘
        feat = StockFeatures(
            code=code, name=row["名称"], sector=row.get("行业", "未知"),
            price=price, vol_ratio=vr, pct_open=pct,
            auction_amount=_safe_num(row.get("成交额", 0)), auction_volume=av,
            ma60=ma60, ma20=ma20, ma10=ma10, ma5=ma5, prev_volume=pv,
            volatility=vol, sector_heat=_sector_heat_from_avg(sec_avg_pct, mp),
            float_mv=5e10, is_st=False, market_pct=mp,
        )
        result = score_stock(feat, p)
        recs.append({
            "代码": code, "名称": row["名称"], "动能评分": result["total"],
            "买入价": round(price, 2), "止盈价": round(price * (1 + p.take_profit), 2),
            "止损价": round(price * (1 - p.stop_loss), 2), "行业": row["行业"],
            "市值": round(float(row.get("市值", 0)), 2), "涨停价": round(price * 1.1, 2),
            "成交额": _safe_num(row.get("成交额", 0)),
            "最新价": round(price, 2), "明细": _to_detail(result),
        })
    return pd.DataFrame(recs)


def run_demo(output_dir, params=None):
    """使用内置样例数据跑通全流程，便于离线验证。"""
    p = params or StrategyParams()
    today = datetime.date.today()
    temp = _demo_temp()
    market_pct = temp["market_pct"]
    low, high = calc_dynamic_threshold(market_pct, p)
    demo_df = _demo_pool()
    res_df = _enrich_demo(demo_df, market_pct, p)
    res_df, multi = add_sector_bonus(res_df, p)
    res_df = res_df.sort_values("动能评分", ascending=False).reset_index(drop=True)
    res_df["买入程度"] = res_df["动能评分"].apply(lambda s: recommend_level(s, p))
    report = generate_report(temp, res_df, low, high, today, multi)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"auction_recommend_{today.isoformat()}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"今日市场温度{temp['total']}，精选{min(3, len(res_df))}只股票，详见报告")
    return report, out_path


# ----------------------------------------------------------------------------
# 模块 8: 历史回测 (Backtest)
# ----------------------------------------------------------------------------
BT_CACHE_SUBDIR = ".bt_cache"


def get_backtest_universe(scope="all"):
    """返回回测股票池 DataFrame(代码, 名称)。scope='all' 取全A主板/创业板/科创板。"""
    try:
        df = data_service.info_a_code_name()
        df = df.rename(columns={df.columns[0]: "代码", df.columns[1]: "名称"})
    except Exception:
        df = data_service.a_spot()[["代码", "名称"]]
    df["代码"] = df["代码"].astype(str)
    df = df[df["代码"].str.startswith(BOARD_PREFIX)].copy()
    return df.reset_index(drop=True)


def _fetch_stock_hist_robust(code, adjust="qfq", start=None, end=None):
    """获取个股日线，经统一 DataService（东财优先，失败回退新浪）。

    返回标准列 DataFrame(日期,开盘,收盘,最高,最低,成交量,成交额) 升序；失败返回空 DataFrame。
    start/end 为 'YYYY-MM-DD' 字符串或 None。
    """
    cols = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]
    sd = start or (datetime.date.today() - datetime.timedelta(days=400)).isoformat()
    ed = end or datetime.date.today().isoformat()
    return data_service.stock_hist(code, sd, ed, adjust)


def _bt_fetch_hist(code, cache_dir, start, end, adjust="qfq"):
    """带缓存的日线获取（经 _fetch_stock_hist_robust）。"""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cpath = cache_dir / f"{code}.csv"
    if cpath.exists():
        try:
            h = pd.read_csv(cpath, parse_dates=["日期"])
            if len(h) > 0:
                return h
        except Exception:
            pass
    h = _fetch_stock_hist_robust(code, adjust=adjust, start=start, end=end)
    if h is not None and len(h) > 0:
        try:
            h.to_csv(cpath, index=False)
        except Exception:
            pass
    return h


def get_daily_market_pct(start, end):
    """大盘每日平均涨跌幅(%)序列，作为动态阈值的 market_pct。失败返回空 Series。"""
    try:
        syms = ["sh000300", "sh000001", "sz399001", "sz399006"]
        frames = []
        for sym in syms:
            d = data_service.index_daily(sym)
            d = d.rename(columns={"date": "日期", "close": "收盘"})
            d["日期"] = pd.to_datetime(d["日期"])
            d["ret"] = pd.to_numeric(d["收盘"], errors="coerce").pct_change() * 100
            d = d[(d["日期"] >= start) & (d["日期"] <= end)]
            frames.append(d.set_index("日期")["ret"].rename(sym))
        m = pd.concat(frames, axis=1)
        s = m.mean(axis=1).dropna()
        s.index = s.index.strftime("%Y-%m-%d")
        return s
    except Exception as e:
        log(f"大盘温度序列获取失败(回测将以静态阈值2%~6%进行): {e}")
        return pd.Series(dtype=float)


def _bt_trades_for_stock(hist, code, name, mkt_pct, params=None, start=None, end=None):
    """对单只股票遍历每个交易日，套用初筛+评分，T+1次日开盘卖出。返回 trade dict 列表。"""
    p = params or StrategyParams()
    if hist is None or len(hist) < 62:
        return []
    o = hist["开盘"].to_numpy(dtype=float)
    c = hist["收盘"].to_numpy(dtype=float)
    hi = hist["最高"].to_numpy(dtype=float)
    lo = hist["最低"].to_numpy(dtype=float)
    v = hist["成交量"].to_numpy(dtype=float)
    amt = hist["成交额"].to_numpy(dtype=float)
    dates = hist["日期"].dt.strftime("%Y-%m-%d").to_numpy()
    n = len(hist)
    trades = []
    is_st = ("ST" in str(name).upper())
    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    for i in range(60, n - 1):
        dstr = dates[i]
        if start_ts is not None and pd.Timestamp(dstr) < start_ts:
            continue
        if end_ts is not None and pd.Timestamp(dstr) > end_ts:
            continue
        prev_close = c[i - 1]
        if not np.isfinite(prev_close) or prev_close <= 0:
            continue
        open_i = o[i]
        if not np.isfinite(open_i) or open_i <= 0:
            continue
        pct_open = (open_i - prev_close) / prev_close * 100.0
        vol_i = v[i]
        if not np.isfinite(vol_i) or vol_i <= 0:
            continue
        vol5 = np.mean(v[i - 5:i]) if i >= 5 else vol_i
        vol_ratio = vol_i / vol5 if vol5 > 0 else 0.0
        amount_i = amt[i] if np.isfinite(amt[i]) else 0.0
        if amount_i < p.auction_amount_min:
            continue
        if is_st:
            continue
        mp = float(mkt_pct.get(dstr, 0.0)) if (mkt_pct is not None and len(mkt_pct)) else 0.0
        low, high = calc_dynamic_threshold(mp, p)
        if not (low <= pct_open <= high):
            continue
        if vol_ratio < p.vol_ratio_min:
            continue
        ma60_win = c[i - 60:i]
        ma60 = float(np.mean(ma60_win)) if len(ma60_win) else 0.0
        ma20 = float(np.mean(c[i - 20:i])) if i >= 20 else ma60
        ma10 = float(np.mean(c[i - 10:i])) if i >= 10 else ma20
        ma5 = float(np.mean(c[i - 5:i])) if i >= 5 else ma10
        prev_vol = float(v[i - 1]) if np.isfinite(v[i - 1]) else 0.0
        # 年化波动率：截至当日的近 20 日对数收益标准差
        if i >= 20:
            rets = np.diff(np.log(c[i - 20:i + 1].astype(float)))
            vol = float(np.std(rets) * np.sqrt(252))
        else:
            vol = 0.0
        # 板块热度（回测代理）：该股开盘涨幅相对大盘的强弱
        sector_heat = _clamp01(0.5 + (pct_open - mp) / 6.0)
        feat = StockFeatures(
            code=code, name=name, sector=name,
            price=open_i, vol_ratio=vol_ratio, pct_open=pct_open,
            auction_amount=amount_i, auction_volume=vol_i,
            ma60=ma60, ma20=ma20, ma10=ma10, ma5=ma5, prev_volume=prev_vol,
            volatility=vol, sector_heat=sector_heat,
            float_mv=0.0, is_st=is_st, market_pct=mp,
        )
        result = score_stock(feat, p)
        score = result["total"]
        next_open = o[i + 1]
        if not np.isfinite(next_open) or next_open <= 0:
            continue
        ret = (next_open - open_i) / open_i * 100.0
        max_up = (hi[i] - open_i) / open_i * 100.0 if np.isfinite(hi[i]) else 0.0
        max_down = (lo[i] - open_i) / open_i * 100.0 if np.isfinite(lo[i]) else 0.0
        hit_tp = max_up >= p.take_profit * 100
        hit_sl = max_down <= -p.stop_loss * 100
        level = recommend_level(score, p)
        cold = mp <= -1.0
        if cold:
            level = DOWNGRADE.get(level, level)
        trades.append({
            "日期": dstr, "代码": code, "名称": name,
            "开盘涨幅%": round(pct_open, 2), "量比(近似)": round(vol_ratio, 2),
            "动能评分": score, "买入价": round(open_i, 2), "次日开盘卖出价": round(next_open, 2),
            "收益率%": round(ret, 2), "盘中最高%": round(max_up, 2), "盘中最低%": round(max_down, 2),
            "触达止盈": bool(hit_tp), "触达止损": bool(hit_sl),
            "买入程度": level, "温度偏冷": bool(cold),
        })
    return trades


def compute_backtest_stats(df):
    if df is None or len(df) == 0:
        return {}
    rets = df["收益率%"].to_numpy(dtype=float)
    win = int((rets > 0).sum())
    total = len(rets)
    avg = float(np.mean(rets))
    avg_win = float(np.mean(rets[rets > 0])) if (rets > 0).any() else 0.0
    avg_loss = float(np.mean(rets[rets < 0])) if (rets < 0).any() else 0.0
    cum = float(np.sum(rets))
    cum_comp = (float(np.prod(1 + rets / 100.0)) - 1) * 100.0
    tp = int(df["触达止盈"].sum())
    sl = int(df["触达止损"].sum())
    return {
        "交易次数": total, "盈利次数": win,
        "胜率%": round(win / total * 100, 2) if total else 0,
        "平均收益率%": round(avg, 3), "平均盈利%": round(avg_win, 3), "平均亏损%": round(avg_loss, 3),
        "累计收益%(等权)": round(cum, 2), "累计收益%(复利)": round(cum_comp, 2),
        "最大单笔收益%": round(float(rets.max()), 2), "最大单笔亏损%": round(float(rets.min()), 2),
        "触达+5%次数": tp, "触达-3%次数": sl,
    }


def generate_backtest_report(stats, df, scope, start, end, limit):
    L = []
    L.append("# 竞价选股策略回测报告\n")
    L.append(f"> 回测范围：**{scope}** ｜ 区间：**{start} ~ {end}**"
             + (f" ｜ 抽样上限：**{limit}** 只" if limit else "")
             + " ｜ 退出规则：**T+1 次日开盘卖出** ｜ 数据源：AkShare\n")
    L.append("")
    if stats:
        L.append("## 一、📈 总体绩效\n")
        L.append("| 指标 | 数值 |")
        L.append("|------|------|")
        for k, val in stats.items():
            L.append(f"| {k} | {val} |")
        L.append("")
    if df is not None and len(df):
        L.append("## 二、🏆 收益最高的 15 笔交易\n")
        cols = ["日期", "代码", "名称", "开盘涨幅%", "量比(近似)", "动能评分",
                "买入价", "次日开盘卖出价", "收益率%", "买入程度"]
        L.append("| " + " | ".join(cols) + " |")
        L.append("|" + "|".join(["------"] * len(cols)) + "|")
        for _, r in df.sort_values("收益率%", ascending=False).head(15).iterrows():
            L.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
        L.append("")
        L.append("## 三、📉 收益最低的 15 笔交易\n")
        L.append("| " + " | ".join(cols) + " |")
        L.append("|" + "|".join(["------"] * len(cols)) + "|")
        for _, r in df.sort_values("收益率%", ascending=True).head(15).iterrows():
            L.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
        L.append("")
    L.append("## 四、⚠️ 方法论与局限\n")
    L.append("- **买入价** = 当日开盘价（集合竞价成交口径）；**卖出价** = 次日开盘价（A股 T+1）。")
    L.append("- **量比(近似)**：日线无集合竞价量比，用 `当日成交量 / 近5日均量` 近似；**量能比**：用 `当日成交量 / 前一日成交量` 近似。")
    L.append("- **动态阈值** 的 market_pct 取四大指数当日平均涨跌幅；北向资金/涨跌家数历史序列较重，回测温度仅用指数维度，且仅在指数平均 ≤ -1% 时触发买入程度降级。")
    L.append("- 回测不含交易成本（佣金/印花税/滑点），实盘收益会更低。")
    L.append("- 以上为历史数据统计，不构成投资建议。")
    L.append("")
    return "\n".join(L)


def _bt_demo_universe():
    return pd.DataFrame([
        {"代码": "000001", "名称": "平安银行"},
        {"代码": "600519", "名称": "贵州茅台"},
        {"代码": "300750", "名称": "宁德时代"},
        {"代码": "601318", "名称": "中国平安"},
        {"代码": "000858", "名称": "五粮液"},
        {"代码": "002594", "名称": "比亚迪"},
    ])


def _bt_demo_market_pct():
    dates = pd.date_range("2026-01-01", periods=200, freq="B")
    rng = np.random.default_rng(42)
    return pd.Series(rng.normal(0.3, 0.8, len(dates)), index=dates.strftime("%Y-%m-%d"))


def _bt_demo_hist(code):
    rng = np.random.default_rng(abs(hash(code)) % (2 ** 32))
    n = 200
    # 锚定到「今日」结束，避免演示 K 线出现未来日期
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    base = rng.uniform(10, 100)
    rets = rng.normal(0.0005, 0.02, n)
    close = base * np.cumprod(1 + rets)
    prev = np.concatenate([[close[0]], close[:-1]])
    openp = prev * (1 + rng.normal(0, 0.01, n))
    high = np.maximum(close, openp) * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = np.minimum(close, openp) * (1 - np.abs(rng.normal(0, 0.008, n)))
    vol = rng.uniform(1e5, 5e6, n)
    amount = close * vol * rng.uniform(0.9, 1.1, n)
    for i in range(60, n - 1, 7):  # 注入若干"通过初筛"的信号日
        gap = rng.uniform(0.02, 0.05)
        openp[i] = close[i - 1] * (1 + gap)
        vol[i] = vol[i - 1] * rng.uniform(3.2, 6.0)
        amount[i] = max(amount[i], AUCTION_AMOUNT_MIN * 1.2)
    return pd.DataFrame({
        "日期": dates, "开盘": openp, "收盘": close, "最高": high, "最低": low,
        "成交量": vol, "成交额": amount,
    })


def run_backtest(output_dir, scope="all", start=None, end=None, limit=None, demo=False, params=None):
    ensure_deps()
    params = params or StrategyParams()
    today = datetime.date.today()
    if not end:
        end = today.isoformat()
    if not start:
        start = (today - datetime.timedelta(days=200)).isoformat()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / BT_CACHE_SUBDIR
    log(f"回测启动: 范围={scope} 区间={start}~{end}" + (f" 抽样={limit}" if limit else ""))

    if demo:
        uni = _bt_demo_universe()
        mkt = _bt_demo_market_pct()
    else:
        uni = get_backtest_universe(scope)
        if limit:
            uni = uni.head(int(limit))
        mkt = get_daily_market_pct(pd.Timestamp(start), pd.Timestamp(end))

    all_trades = []
    for idx, row in uni.iterrows():
        code, name = str(row["代码"]), str(row["名称"])
        if demo:
            hist = _bt_demo_hist(code)
        else:
            hist = _bt_fetch_hist(code, cache_dir, start, end)
            time.sleep(0.05)
        if hist is None or len(hist) == 0:
            continue
        ts = _bt_trades_for_stock(hist, code, name, mkt, params, start, end)
        all_trades.extend(ts)
        if (idx + 1) % 50 == 0:
            log(f"已处理 {idx + 1}/{len(uni)} 只，命中 {len(all_trades)} 笔交易")

    df = pd.DataFrame(all_trades)
    stats = compute_backtest_stats(df)
    report = generate_backtest_report(stats, df, scope, start, end, limit)
    fname = f"backtest_{scope}_{start}_{end}" + (f"_top{limit}" if limit else "") + ".md"
    out_path = out_dir / fname
    out_path.write_text(report, encoding="utf-8")
    log(f"回测报告已保存: {out_path}")

    # 导出全量 JSON（含每一笔交易），供 Web 仪表盘读取
    json_path = out_dir / (fname.rsplit(".md", 1)[0] + ".json")
    try:
        trades_records = df.to_dict(orient="records") if len(df) else []
        payload = {
            "meta": {
                "scope": scope, "start": start, "end": end,
                "limit": limit, "exit_rule": "T+1 次日开盘卖出",
                "data_source": "AkShare",
                "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "stats": stats,
            "trades": trades_records,
        }
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"回测 JSON 已保存: {json_path}")
    except Exception as e:
        log(f"JSON 导出失败(不影响 md 报告): {e}")
    if stats:
        print(f"回测完成：范围{scope}，共{stats['交易次数']}笔交易，胜率{stats['胜率%']}%，"
              f"平均收益率{stats['平均收益率%']}%，累计(复利){stats['累计收益%(复利)']}%，详见报告")
    else:
        print(f"回测完成：范围{scope}，区间内无符合条件的交易，详见报告")
    return report, out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="竞价选股器 (AkShare)")
    ap.add_argument("--output-dir", default="./auction_reports", help="报告输出目录")
    ap.add_argument("--demo", action="store_true", help="使用内置样例数据跑通选股全流程")
    ap.add_argument("--backtest", action="store_true", help="运行历史回测(全A股/指定范围, 需联网)")
    ap.add_argument("--scope", default="all", help="回测范围: all=全A股(主选板块)")
    ap.add_argument("--start", default=None, help="回测开始日期 YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="回测结束日期 YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=None, help="回测股票抽样上限(用于快速验证, 如 --limit 30)")
    ap.add_argument("--backtest-demo", action="store_true", help="用内置合成数据跑通回测流程(无需联网)")
    ap.add_argument("--params", default=None,
                    help="策略参数 JSON 文件路径 或 inline JSON 字符串，覆盖默认参数(自动调参/前端配置用)")
    args = ap.parse_args()

    params = None
    if args.params:
        import json as _json
        raw = args.params.strip()
        try:
            if raw.startswith("{"):
                params = StrategyParams.from_dict(_json.loads(raw))
            else:
                with open(raw, "r", encoding="utf-8") as _f:
                    params = StrategyParams.from_dict(_json.load(_f))
            log(f"已加载自定义策略参数: {params.to_dict()}")
        except Exception as e:
            log(f"参数解析失败，使用默认参数: {e}")

    if args.backtest_demo:
        run_backtest(args.output_dir, scope=args.scope, start=args.start, end=args.end,
                     limit=args.limit, demo=True, params=params)
    elif args.backtest:
        run_backtest(args.output_dir, scope=args.scope, start=args.start, end=args.end,
                     limit=args.limit, demo=False, params=params)
    elif args.demo:
        run_demo(args.output_dir, params=params)
    else:
        run(args.output_dir, params=params)


# ----------------------------------------------------------------------------
# Web 接口封装：供 Streamlit 等调用
# ----------------------------------------------------------------------------
class AuctionStockPicker:
    """竞价选股器 Web 接口封装。

    复用本模块已有的市场温度计 / 初筛 / 动能评分逻辑，
    对外暴露 pick_stocks() 返回结构化结果(dict)，便于 Web 层渲染。
    """

    def __init__(self, output_dir="./auction_reports", params=None):
        self.output_dir = output_dir
        self.params = params or StrategyParams()

    def pick_stocks(self, demo=False, params=None):
        """执行一次选股，返回结构化 dict。

        返回:
            {
              "temperature": {...},            # 市场温度计(含 total/level/position 等)
              "low": float, "high": float,    # 动态开盘涨幅阈值
              "stocks": DataFrame,            # 初筛+评分结果(按动能评分降序)
              "generated_at": str,            # 生成时间戳
              "data_source": str,             # 数据来源说明
            }
        """
        import datetime as _dt
        today = _dt.date.today()

        params = params or self.params
        if demo:
            temp = _demo_temp()
            market_pct = temp["market_pct"]
            low, high = calc_dynamic_threshold(market_pct, params)
            filtered = _demo_pool()
        else:
            temp = get_market_temperature()
            market_pct = temp["market_pct"]
            low, high = calc_dynamic_threshold(market_pct, params)
            pool = get_stock_pool()
            new_codes = get_new_stock_codes(params.new_stock_days)
            pool = pool[~pool["代码"].astype(str).isin(new_codes)]
            filtered = filter_stocks(pool, params, market_pct)

        if len(filtered) > 0:
            res_df = (_enrich_demo if demo else _enrich_and_score)(filtered, market_pct, params)
            res_df, _ = add_sector_bonus(res_df, params)
            res_df = res_df.sort_values("动能评分", ascending=False).reset_index(drop=True)
            res_df["买入程度"] = res_df["动能评分"].apply(lambda s: recommend_level(s, params))
            if temp["level"] in ("寒冷", "极寒"):
                res_df["买入程度"] = res_df["买入程度"].replace(DOWNGRADE)
        else:
            res_df = pd.DataFrame(columns=[
                "代码", "名称", "动能评分", "买入价", "止盈价", "止损价",
                "行业", "量比", "开盘涨幅%", "买入程度",
            ])

        return {
            "temperature": temp,
            "low": low,
            "high": high,
            "stocks": res_df,
            "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_source": "AkShare（集合竞价 ~09:26）" if not demo else "内置样例数据(DEMO)",
        }
