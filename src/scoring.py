# -*- coding: utf-8 -*-
"""统一评分引擎 (Canonical Scoring Engine)
=========================================
项目唯一真实的「个股评分」实现。

所有消费方都必须通过本模块的 ``score_stock()`` 计算评分，确保
**首页 / 历史推荐 / 回测 / API 四端数据完全一致**：

- ``generate_results.py``（每日静态生成）→ 用盘中真实行情 + 日线衍生特征；
- ``run_backtest``（历史回测）→ 用历史日线在每一个交易日还原同样的特征；
- ``api/routers/core.py``（盘中实时）→ 用 live quote 合并快照结构特征重算。

设计要点
--------
1. 输入是一个标准的「特征字典」(StockFeatures)，这些特征可由不同数据源产生
   （盘中实时行情 / 历史日线 / 快照缓存），但 **评分逻辑只有一份**。
2. 评分由 8 个连续、差异化的子分项构成，外加一个风险惩罚因子，最终落在 [0,100]。
3. **绝不出现「固定 100 分」或「测试假数据直通」**：每个子分项都是实值的连续
   函数，缺少数据时该项得 0（而非满分），最终分数必然呈现真实的差异化分布。
4. 输出 (总分, 明细) 中的明细既含各项得分，也含可读的中文解释，便于前端
   「评分拆解」展示，做到每只股票可解释。

权重（合计 100）：
    量比 18 · 竞价金额 12 · 相对大盘 12 · 均线偏离 15 · 量能比 12
  · 资金流 12 · 板块热度 10 · 趋势 9
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


# ----------------------------------------------------------------------------
# 特征字典：评分引擎的唯一输入
# ----------------------------------------------------------------------------
@dataclass
class StockFeatures:
    """一只股票在某一时点的「可评分特征」。

    这些字段可由不同上下文填充：
    - 盘中（generate_results）：量比/涨幅/竞价额 来自实时行情；
      ma60/趋势/波动率/资金流/板块热度 来自日线与 DataService。
    - 历史（run_backtest）：均由该交易日的日线还原。
    - 实时重算（api）：量比/涨幅/竞价额/当日资金流 来自 live quote，
      其余结构特征沿用快照中缓存的值。

    缺失（NaN / 0 / 未知）的字段只会导致对应子分项得 0，不会抬高总分。
    """

    code: str = ""
    name: str = ""
    sector: str = ""

    # —— 盘中/日内可得 ——
    price: float = 0.0           # 当前价
    vol_ratio: float = 0.0       # 量比
    pct_open: float = 0.0        # 开盘涨幅% / 盘中涨跌幅%
    auction_amount: float = 0.0  # 竞价成交额 (元)
    auction_volume: float = 0.0  # 竞价成交量 (股)
    fund_flow_today_net: float = 0.0   # 当日主力净流入 (元)

    # —— 结构特征（来自日线/基本面，相对稳定） ——
    ma60: float = 0.0
    ma20: float = 0.0
    ma10: float = 0.0
    ma5: float = 0.0
    prev_volume: float = 0.0     # 昨日全天成交量 (股)
    volatility: float = 0.0       # 近 20 日年化波动率 (0~1)
    fund_flow_5d_net: float = 0.0  # 近 5 日主力净流入均值 (元)
    sector_heat: float = 0.0      # 板块热度 (0~1，越高越热)
    float_mv: float = 0.0         # 流通市值 (元)

    # —— 风险标记 ——
    is_st: bool = False
    market_pct: float = 0.0       # 大盘当日平均涨幅% (相对大盘分项用)

    def to_dict(self) -> Dict:
        return asdict(self)


# ----------------------------------------------------------------------------
# 引擎默认阈值与权重
# ----------------------------------------------------------------------------
WEIGHTS: Dict[str, float] = {
    "vol_ratio": 18.0,
    "amount": 12.0,
    "rel_market": 12.0,
    "ma60_dev": 15.0,
    "vol_energy": 12.0,
    "fund_flow": 12.0,
    "sector": 10.0,
    "trend": 9.0,
}

# 量比归一化区间 [min, top] -> 0..满分
VR_MIN = 2.0
VR_TOP = 6.0
# 竞价金额对数归一化区间 (元)
AMT_LO = 5_000_000.0      # 5 百万
AMT_HI = 50_000_000.0     # 5 千万
# 相对大盘：超出大盘 diff% 达此值即满分
REL_TOP = 3.0
# 均线偏离甜区 [sweet_lo, sweet_hi]
DEV_SWEET_LO = 0.02
DEV_SWEET_HI = 0.10
# 量能比（竞价量/昨日量）归一化区间
VE_LO = 0.03
VE_HI = 0.10
# 资金流（近5日净流入，元）对数归一化区间
FF_LO = 1_000_000.0
FF_HI = 1_000_000_000.0
# 小市值阈值（元）：低于此值施加风险惩罚
SMALL_MV = 3_000_000_000.0


def _clamp(x, lo=0.0, hi=1.0):
    if x is None:
        return lo
    return max(lo, min(hi, x))


def _safe(x):
    try:
        if x is None:
            return 0.0
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return 0.0
        return f
    except (TypeError, ValueError):
        return 0.0


def _lognorm(v, lo, hi):
    """对正数做对数归一化到 [0,1]；v<=0 返回 0。"""
    v = _safe(v)
    if v <= 0:
        return 0.0
    lv = math.log10(v)
    llo, lhi = math.log10(lo), math.log10(hi)
    return _clamp((lv - llo) / (lhi - llo))


# ----------------------------------------------------------------------------
# 8 个子分项（每个返回 (得分, 说明)）
# ----------------------------------------------------------------------------
def _s_vol_ratio(f: StockFeatures, ctx):
    vr = _safe(f.vol_ratio)
    vmin, vtop = ctx["vr_min"], ctx["vr_top"]
    if vr >= vtop:
        s = WEIGHTS["vol_ratio"]
    elif vr >= vmin:
        s = WEIGHTS["vol_ratio"] * (vr - vmin) / (vtop - vmin)
    else:
        s = 0.0
    note = f"量比 {vr:.2f}" + ("，显著放量" if vr >= vtop else ("，高于阈值" if vr >= vmin else "，低于阈值"))
    return s, note


def _s_amount(f: StockFeatures, ctx):
    s = WEIGHTS["amount"] * _lognorm(f.auction_amount, ctx["amt_lo"], AMT_HI)
    amt_yi = _safe(f.auction_amount) / 1e8
    note = f"竞价额 {amt_yi:.2f}亿" + ("，强资金介入" if s >= WEIGHTS["amount"] * 0.8 else ("，中等" if s > 0 else "，偏低"))
    return s, note


def _s_rel_market(f: StockFeatures, ctx):
    diff = _safe(f.pct_open) - _safe(f.market_pct)
    if diff >= REL_TOP:
        s = WEIGHTS["rel_market"]
    elif diff > 0:
        s = WEIGHTS["rel_market"] * diff / REL_TOP
    else:
        s = 0.0
    note = f"相对大盘 {diff:+.2f}%" + ("，明显强于大盘" if diff >= REL_TOP else ("，强于大盘" if diff > 0 else "，弱于大盘"))
    return s, note


def _s_ma60_dev(f: StockFeatures, ctx):
    price, ma60 = _safe(f.price), _safe(f.ma60)
    if ma60 <= 0:
        return 0.0, "无均线数据"
    dev = (price - ma60) / ma60
    if dev >= DEV_SWEET_HI:
        # 偏离过远 -> 回吐惩罚，线性衰减到 0（dev=2×sweet_hi 处为 0）
        s = WEIGHTS["ma60_dev"] * max(0.0, 1.0 - (dev - DEV_SWEET_HI) / DEV_SWEET_HI)
    elif dev >= DEV_SWEET_LO:
        s = WEIGHTS["ma60_dev"]
    elif dev >= 0:
        s = WEIGHTS["ma60_dev"] * dev / DEV_SWEET_LO
    else:
        s = 0.0
    note = f"偏离60日线 {dev*100:+.1f}%" + ("，处于甜区" if DEV_SWEET_LO <= dev < DEV_SWEET_HI else ("，偏低" if dev >= 0 else "，跌破均线"))
    return s, note


def _s_vol_energy(f: StockFeatures, ctx):
    prev = _safe(f.prev_volume)
    ratio = (_safe(f.auction_volume) / prev) if prev > 0 else 0.0
    if ratio >= VE_HI:
        s = WEIGHTS["vol_energy"]
    elif ratio >= VE_LO:
        s = WEIGHTS["vol_energy"] * (ratio - VE_LO) / (VE_HI - VE_LO)
    else:
        s = 0.0
    note = f"量能比 {ratio*100:.1f}%" + ("，竞价量充沛" if ratio >= VE_HI else ("，良好" if ratio >= VE_LO else "，偏弱"))
    return s, note


def _s_fund_flow(f: StockFeatures, ctx):
    # 优先用近5日主力净流入均值（更稳定）；缺失则用当日净流入
    net = _safe(f.fund_flow_5d_net) if _safe(f.fund_flow_5d_net) != 0 else _safe(f.fund_flow_today_net)
    if net <= 0:
        return 0.0, "主力资金净流出/无数据"
    s = WEIGHTS["fund_flow"] * _lognorm(net, FF_LO, FF_HI)
    note = f"主力净流入 {net/1e8:+.2f}亿" + ("，持续吸筹" if s >= WEIGHTS["fund_flow"] * 0.8 else "，温和流入")
    return s, note


def _s_sector(f: StockFeatures, ctx):
    heat = _clamp(_safe(f.sector_heat))
    s = WEIGHTS["sector"] * heat
    note = f"板块热度 {heat:.2f}" + ("，行业领涨" if heat >= 0.7 else ("，板块偏强" if heat >= 0.4 else "，板块一般"))
    return s, note


def _s_trend(f: StockFeatures, ctx):
    price = _safe(f.price)
    ma5, ma10, ma20, ma60 = _safe(f.ma5), _safe(f.ma10), _safe(f.ma20), _safe(f.ma60)
    mas = [m for m in (ma5, ma10, ma20, ma60) if m > 0]
    if len(mas) < 2:
        return 0.0, "均线数据不足"
    # 多头排列计数：ma5>ma10>ma20>ma60
    order = [ma5, ma10, ma20, ma60]
    bull = 0
    for i in range(len(order) - 1):
        if order[i] > 0 and order[i + 1] > 0 and order[i] > order[i + 1]:
            bull += 1
    above = 1 if (price > ma60) else 0.5
    s = WEIGHTS["trend"] * (bull / 3.0) * above
    label = {3: "完全多头排列", 2: "偏多头", 1: "弱多头", 0: "空头排列"}.get(bull, "")
    note = f"趋势 {label}（{bull}/3）"
    return s, note


# ----------------------------------------------------------------------------
# 风险惩罚因子
# ----------------------------------------------------------------------------
def _risk_factor(f: StockFeatures) -> (float, str):
    factor = 1.0
    notes = []
    if f.is_st:
        factor *= 0.80
        notes.append("ST 风险 -20%")
    vol = _safe(f.volatility)
    if vol >= 1.0:
        factor *= 0.80
        notes.append("高波动 -20%")
    elif vol >= 0.6:
        factor *= 0.90
        notes.append("波动偏大 -10%")
    mv = _safe(f.float_mv)
    if 0 < mv < SMALL_MV:
        factor *= 0.92
        notes.append("小市值 -8%")
    if _safe(f.pct_open) >= 9.5:
        factor *= 0.90
        notes.append("近涨停难买入 -10%")
    factor = _clamp(factor, 0.8, 1.0)
    note = "风险中性" if not notes else "；".join(notes)
    return factor, note


# ----------------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------------
def ctx_from_params(params=None) -> Dict:
    """从策略参数构造评分上下文（阈值）。无参数时用引擎默认值。

    这样配置页里的 vol_ratio_min / vol_ratio_top / auction_amount_min
    会同时影响「初筛」与「评分」，保证各端口径一致。
    """
    if params is None:
        return {"vr_min": VR_MIN, "vr_top": VR_TOP, "amt_lo": AMT_LO}
    return {
        "vr_min": getattr(params, "vol_ratio_min", VR_MIN) or VR_MIN,
        "vr_top": getattr(params, "vol_ratio_top", VR_TOP) or VR_TOP,
        "amt_lo": getattr(params, "auction_amount_min", AMT_LO) or AMT_LO,
    }


def score_stock(f: StockFeatures, params=None) -> Dict:
    """对一只股票评分，返回结构化结果。

    params: 可选 StrategyParams，用于让 vol_ratio_min/top、auction_amount_min
            等阈值与初筛保持一致。

    返回::
        {
          "total": 82.3,                       # 最终得分 [0,100]
          "risk_factor": 0.95,                 # 风险惩罚因子
          "dimensions": [                      # 8 个可解释子分项
             {"key","label","score","max","note"}, ...
          ],
          "features": {...},                   # 回显的特征，便于核查
        }
    """
    ctx = ctx_from_params(params)
    subs = [
        ("vol_ratio", "量比", _s_vol_ratio(f, ctx)),
        ("amount", "竞价金额", _s_amount(f, ctx)),
        ("rel_market", "相对大盘", _s_rel_market(f, ctx)),
        ("ma60_dev", "均线偏离", _s_ma60_dev(f, ctx)),
        ("vol_energy", "量能比", _s_vol_energy(f, ctx)),
        ("fund_flow", "资金流", _s_fund_flow(f, ctx)),
        ("sector", "板块热度", _s_sector(f, ctx)),
        ("trend", "趋势", _s_trend(f, ctx)),
    ]
    dimensions = []
    raw = 0.0
    for key, label, (s, note) in subs:
        s = max(0.0, min(WEIGHTS[key], _safe(s)))
        raw += s
        dimensions.append({
            "key": key, "label": label,
            "score": round(s, 2), "max": WEIGHTS[key], "note": note,
        })
    factor, risk_note = _risk_factor(f)
    total = round(min(100.0, raw) * factor, 2)
    total = _clamp(total, 0.0, 100.0)
    dimensions.append({
        "key": "risk", "label": "风险调整",
        "score": round(factor * 100, 1), "max": 100.0,
        "note": risk_note, "is_factor": True,
    })
    return {
        "total": total,
        "raw": round(raw, 2),
        "risk_factor": round(factor, 3),
        "dimensions": dimensions,
        "features": f.to_dict(),
    }


def explain_text(result: Dict) -> List[str]:
    """把评分结果转成可读的中文解释列表（供详情/报告使用）。"""
    out = []
    for d in result.get("dimensions", []):
        if d.get("is_factor"):
            out.append(f"【风险调整】{d['note']}（因子 {d['score']/100:.2f}）")
        else:
            out.append(f"【{d['label']}】{d['note']}（{d['score']}/{d['max']}）")
    out.append(f"综合得分：{result['total']}")
    return out
