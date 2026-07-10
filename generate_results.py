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


def build_payload(result):
    stocks = result["stocks"]
    cols = ["代码", "名称", "动能评分", "买入价", "止盈价", "止损价", "量比", "开盘涨幅%", "买入程度"]
    avail = [c for c in cols if c in stocks.columns]

    def row_to_dict(r):
        d = {}
        for c in avail:
            d[c] = to_native(r[c])
        return d

    all_rows = [row_to_dict(r) for _, r in stocks.iterrows()]

    top3 = []
    for _, r in stocks.head(3).iterrows():
        open_price = float(r.get("买入价", 0) or 0)
        top3.append({
            "代码": to_native(r.get("代码")),
            "名称": to_native(r.get("名称")),
            "开盘价": round(open_price, 2),
            "止盈价": round(open_price * 1.05, 2),
            "止损价": round(open_price * 0.97, 2),
            "动能评分": to_native(r.get("动能评分")),
            "量比": to_native(r.get("量比")),
            "买入程度": to_native(r.get("买入程度", "-")),
        })

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
        "temperature": temperature,
        "top3": top3,
        "all": all_rows,
        "count": len(all_rows),
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
