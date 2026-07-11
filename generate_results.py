#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成选股结果 JSON，供 EdgeOne Pages 静态前端读取。

运行: python generate_results.py            # 真实数据（需联网 + 东财接口可达）
运行: python generate_results.py --demo     # 内置样例（无需联网，用于验证/首次部署）

输出: data/results.json
前端 index.html 通过 fetch('./data/results.json') 读取并渲染。

说明: EdgeOne Pages 是静态站 + JS 边缘函数平台，无法运行 Python 服务，
因此选股逻辑在「有 Python 的环境」(本机 / GitHub Actions / 其他 Python 主机)
定时或手动运行本脚本，把结果写入仓库，EdgeOne 重新部署后即可展示最新数据。
"""

import os
import sys
import json
import datetime
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.stock_picker import AuctionStockPicker


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


def build_payload(result):
    stocks = result["stocks"]

    # npcs1983 风格主表字段：排名/名称代码/板块/现价/涨跌幅/评分/建议/交易额
    stocks_list = []
    for i, (_, r) in enumerate(stocks.iterrows()):
        buy_degree = to_native(r.get("买入程度", "-"))
        price = to_native(r.get("最新价", r.get("买入价", 0)) or 0)
        pct = to_native(r.get("开盘涨幅%", 0) or 0)
        turnover = to_native(r.get("成交额", 0) or 0)
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
            "买入价": round(float(to_native(r.get("买入价", 0)) or 0), 2),
            "止盈价": round(float(to_native(r.get("止盈价", 0)) or 0), 2),
            "止损价": round(float(to_native(r.get("止损价", 0)) or 0), 2),
            "量比": round(float(to_native(r.get("量比", 0)) or 0), 2),
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
        "temperature": temperature,
        "stocks": stocks_list,
        "top3": top3,
        "all": stocks_list,
        "count": len(stocks_list),
    }


def main():
    parser = argparse.ArgumentParser(description="生成选股结果 JSON")
    parser.add_argument("--demo", action="store_true", help="使用内置样例数据（不触网）")
    args = parser.parse_args()

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "results.json")

    picker = AuctionStockPicker()
    result = picker.pick_stocks(demo=args.demo)
    payload = build_payload(result)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"已生成: {out_path}")
    print(f"  数据来源: {payload['data_source']}")
    print(f"  生成时间: {payload['generated_at']}")
    print(f"  候选数量: {payload['count']}  | Top3: {len(payload['top3'])}")


if __name__ == "__main__":
    main()
