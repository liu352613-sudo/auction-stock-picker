#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成选股结果与配套数据 JSON，供 EdgeOne Pages 静态前端读取。

运行:
  python generate_results.py            # 真实数据（需联网 + 新浪/东财可达）
  python generate_results.py --demo     # 内置样例（无需联网，用于验证/首次部署）

输出:
  data/results.json        当日选股结果（增强字段：参数版本/市值/涨停价/评分明细）
  data/klines/{code}.json  入选股票 K 线（约120交易日，供详情页绘制）
  data/params.json         当前生效策略参数（若不存在则写默认，含 best/default）
  data/history_index.json  历史推荐索引（追加本次快照摘要）

前端 index.html 通过 fetch 读取并渲染。EdgeOne 是静态站，Python 只在本机/CI 运行本脚本。
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.stock_picker import (
    AuctionStockPicker,
    get_default_params,
    _fetch_stock_hist_robust,
    _bt_demo_hist,
)
from src.data_service import data_service
from src.trading_calendar import effective_trade_date
from generate_snapshot import snapshot

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
KLINES_DIR = os.path.join(DATA_DIR, "klines")
HISTORY_DIR = os.path.join(DATA_DIR, "history")


def to_native(v):
    """把 numpy / pandas 标量转成 JSON 原生类型。"""
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    if isinstance(v, (list, tuple)):
        return [to_native(x) for x in v]
    if isinstance(v, dict):
        return {k: to_native(val) for k, val in v.items()}
    return v


# 买入程度 → npcs1983 风格「建议」文案
RECO_MAP = {
    "强烈推荐": "积极关注",
    "中等": "小仓试错",
    "谨慎": "极小仓观察",
    "不推荐": "暂不参与",
}

# 主要指数（用于顶部指数栏），顺序即展示顺序
INDEX_WANTED = ["上证指数", "深证成指", "创业板指", "科创50", "沪深300"]
# 联网失败时的回退数据（仅保证页面不空，标记 live=False）
INDEX_FALLBACK = [
    {"name": "上证指数", "code": "000001", "val": 3996.16, "diff": -40.43, "pct": "-1.00%"},
    {"name": "深证成指", "code": "399001", "val": 15046.67, "diff": -352.06, "pct": "-2.29%"},
    {"name": "创业板指", "code": "399006", "val": 3842.73, "diff": -175.44, "pct": "-4.37%"},
    {"name": "科创50", "code": "000688", "val": 2064.98, "diff": -120.85, "pct": "-5.53%"},
    {"name": "沪深300", "code": "000300", "val": 4780.79, "diff": -95.52, "pct": "-1.96%"},
]


def fetch_indices():
    """实时拉取主要指数行情（经统一 DataService）。返回 (list, live)。"""
    try:
        df = data_service.index_spot_em()
        name_col = "指数名称" if "指数名称" in df.columns else df.columns[1]
        pool = {}
        for _, r in df.iterrows():
            nm = str(r[name_col])
            if nm in INDEX_WANTED:
                pool[nm] = {
                    "name": nm,
                    "code": str(r.get("指数代码", "")),
                    "val": round(float(r.get("最新价", 0)), 2),
                    "diff": round(float(r.get("涨跌额", 0)), 2),
                    "pct": f"{float(r.get('涨跌幅', 0)):+.2f}%",
                }
        rows = [pool[n] for n in INDEX_WANTED if n in pool]
        if rows:
            return rows, True
        print("  [warn] 未匹配到目标指数，使用内置回退数据。")
    except Exception as e:
        print(f"  [warn] 指数行情拉取失败，使用内置回退数据: {e}")
    return [dict(x) for x in INDEX_FALLBACK], False


def load_params():
    """读取 data/params.json（若存在），返回 (best_params_dict, full_dict)。否则写默认。"""
    p = os.path.join(DATA_DIR, "params.json")
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            best = d.get("best") or d.get("default") or get_default_params().to_dict()
            return best, d
        except Exception:
            pass
    default = get_default_params().to_dict()
    payload = {
        "default": default, "best": default, "best_stats": {},
        "tuned_at": None, "universe": "all", "start": None, "end": None,
        "limit": None, "demo": True,
        "note": "出厂默认参数（尚未运行自动调参 auto_tune.py）",
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(payload, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return default, payload


def gen_kline(code, demo):
    """生成单只股票 K 线 JSON（约120交易日）。返回 dict 或 None。"""
    try:
        if demo:
            hist = _bt_demo_hist(code)
        else:
            end = datetime.date.today().isoformat()
            start = (datetime.date.today() - datetime.timedelta(days=220)).isoformat()
            hist = _fetch_stock_hist_robust(code, adjust="qfq", start=start, end=end)
        if hist is None or len(hist) == 0:
            return None
        hist = hist.tail(120)
        rows = []
        for _, r in hist.iterrows():
            dt = r["日期"]
            dstr = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)
            rows.append({
                "d": dstr,
                "o": round(float(r["开盘"]), 2),
                "c": round(float(r["收盘"]), 2),
                "h": round(float(r["最高"]), 2),
                "l": round(float(r["最低"]), 2),
                "v": round(float(r["成交量"]), 0),
            })
        return {"code": str(code), "bars": rows}
    except Exception as e:
        print(f"  [warn] K线生成失败 {code}: {e}")
        return None


def build_payload(result, params_dict):
    stocks = result["stocks"]
    stocks_list = []
    for i, (_, r) in enumerate(stocks.iterrows()):
        buy_degree = to_native(r.get("买入程度", "-"))
        price = to_native(r.get("最新价", r.get("买入价", 0)) or 0)
        pct = to_native(r.get("开盘涨幅%", 0) or 0)
        turnover = to_native(r.get("成交额", 0) or 0)
        mv = to_native(r.get("市值", 0) or 0)
        limit_up = to_native(r.get("涨停价", 0) or 0)
        detail = to_native(r.get("明细", {})) or {}
        stocks_list.append({
            "排名": i + 1,
            "代码": str(to_native(r.get("代码", ""))),
            "名称": to_native(r.get("名称", "")),
            "板块": to_native(r.get("行业", "未知")),
            "现价": round(float(price), 2),
            "涨跌幅": round(float(pct), 2),
            "评分": round(float(to_native(r.get("动能评分", 0)) or 0), 1),
            "建议": RECO_MAP.get(buy_degree, "极小仓观察"),
            "买入程度": buy_degree,
            "交易额": float(turnover),
            "市值": round(float(mv) / 1e8, 2),        # 亿元
            "涨停价": round(float(limit_up), 2),
            "买入价": round(float(to_native(r.get("买入价", 0)) or 0), 2),
            "止盈价": round(float(to_native(r.get("止盈价", 0)) or 0), 2),
            "止损价": round(float(to_native(r.get("止损价", 0)) or 0), 2),
            "量比": round(float(to_native(r.get("量比", 0)) or 0), 2),
            "评分明细": detail,
            # 结构特征：供 API 实时重算盘中评分（日内字段会被 live quote 覆盖）
            "features": to_native(r.get("features")) or {},
        })
    stocks_list.sort(key=lambda x: x["评分"], reverse=True)
    for i, s in enumerate(stocks_list):
        s["排名"] = i + 1

    top3 = stocks_list[:3]
    temp = result["temperature"]
    temperature = {
        "total": to_native(temp.get("total")),
        "level": to_native(temp.get("level")),
        "position": to_native(temp.get("position")),
        "market_pct": to_native(temp.get("market_pct")),
    }

    return {
        "generated_at": result["generated_at"],
        "data_source": result["data_source"],
        "update_time": datetime.datetime.now().strftime("%H:%M"),
        "trade_date": effective_trade_date().isoformat(),
        "params": params_dict,
        "temperature": temperature,
        "stocks": stocks_list,
        # 规范推荐列表字段：首页严格以此为准（优先 recommendations，回退 stocks）。
        # 这是「真实推荐列表」的唯一来源，绝不与 Mock/Demo/Fallback 混用。
        "recommendations": stocks_list,
        "top3": top3,
        "all": stocks_list,
        "count": len(stocks_list),
    }


def main():
    parser = argparse.ArgumentParser(description="生成选股结果及配套数据 JSON")
    parser.add_argument("--demo", action="store_true", help="使用内置样例数据（不触网）")
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(KLINES_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, "results.json")

    params_dict, params_full = load_params()
    # 生成时即采用与数据一同下发的「生效参数」，确保静态评分与 API 实时重算
    # 使用完全相同的策略参数（避免 best/default 口径不一致）。
    from src.stock_picker import StrategyParams
    params_obj = StrategyParams.from_dict(params_dict)
    picker = AuctionStockPicker(params=params_obj)
    result = picker.pick_stocks(demo=args.demo, params=params_obj)
    payload = build_payload(result, params_dict)

    # 实时拉取指数行情
    indices, idx_live = fetch_indices()
    payload["indices"] = indices
    payload["indices_live"] = idx_live

    # 为入选股票生成 K 线
    kl_count = 0
    for s in payload["stocks"]:
        kl = gen_kline(s["代码"], args.demo)
        if kl:
            kp = os.path.join(KLINES_DIR, f"{s['代码']}.json")
            json.dump(kl, open(kp, "w", encoding="utf-8"), ensure_ascii=False)
            kl_count += 1

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 历史推荐快照：写入 data/history/<生效交易日>.json 并维护 history_index.json
    # 每次生成结果都刷新该交易日快照（force），无论是否已存在；
    # 周末/节假日/9:26 前会自动落到「最近/上一交易日」，与展示口径一致。
    eff_date = effective_trade_date().isoformat()
    snapshot(out_path, eff_date, force=True)

    print(f"已生成: {out_path}")
    print(f"  ── 数据来源与数量校验 ──")
    src = payload["data_source"]
    is_demo = ("DEMO" in src) or bool(params_full.get("demo"))
    print(f"  数据来源        : {src}")
    print(f"  是否示例/DEMO   : {'是 ⚠️（非真实推荐，请勿用于生产展示）' if is_demo else '否（真实数据）'}")
    print(f"  推荐数量        : {payload['count']} 只（recommendations 字段）")
    print(f"  生效交易日      : {payload['trade_date']}")
    print(f"  生成时间        : {payload['generated_at']}")
    if payload["count"]:
        print(f"  推荐列表        : " + "、".join(
            f"{s['名称']}({s['代码']})·{s['评分']}" for s in payload["recommendations"]))
    else:
        print(f"  推荐列表        : （空）将在首页明确提示「当前推荐数据为空」")
    print(f"  K线生成         : {kl_count} 只")
    print(f"  指数行情        : {'实时(akshare)' if idx_live else '回退(内置)'}  | {len(indices)} 个")
    print(f"  生效参数        : {'已调参(' + str(params_full.get('tuned_at')) + ')' if params_full.get('tuned_at') else '出厂默认'}")


if __name__ == "__main__":
    main()
