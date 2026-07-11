#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竞价选股策略 自动调参器（网格搜索 + 回测评估）。

背景：沙箱中东财被掐，强制走新浪（与 run_backtest_real.py 一致）。
对每个参数组合，复用 src.stock_picker 的回测逻辑跑一遍历史回测，
以「综合目标函数」(收益×胜率×样本量 − 风险惩罚) 评估，选出最优参数。

用法:
  python auto_tune.py --demo                 # 合成数据快速验证管线
  python auto_tune.py --limit 120 --start 2026-01-01 --end 2026-07-10   # 真实调参(需联网,建议后台)
  python auto_tune.py --quick                # 小网格(2组合)快速真实验证

输出:
  data/params.json        { default, best, best_stats, tuned_at, meta }
  data/param_tuning.json  { grid, results[], best_key, meta }  (参数-绩效映射/灵敏度)
  auction_reports/param_tuning.md            人读报告
"""
import argparse
import datetime
import glob
import itertools
import json
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import pandas as pd
from src import stock_picker as sp
from src.data_service import data_service

# ---------------------------------------------------------------------------
# 强制新浪数据源（沙箱东财被掐）：统一经 DataService，不再 monkeypatch akshare
# ---------------------------------------------------------------------------
data_service.force_sina(True)  # stock_hist 只走新浪；universe 用新浪代码表


def get_backtest_universe_sina(scope="all"):
    """用新浪代码表重建股票池（原 get_backtest_universe 只用东财，无回退）。"""
    df = data_service.universe_sina()
    if df.empty:
        return df
    df = df[df["代码"].str.startswith(sp.BOARD_PREFIX)].copy()
    return df.drop_duplicates("代码").reset_index(drop=True)


sp.get_backtest_universe = get_backtest_universe_sina

# ---------------------------------------------------------------------------
# 搜索空间
# ---------------------------------------------------------------------------
GRID = {
    "vol_ratio_min": [2.5, 3.0, 3.5],
    "auction_amount_min": [3_000_000, 5_000_000],
    "threshold_hi_base": [6.0, 8.0],
    "w_vol_ratio": [30.0],
}
QUICK_GRID = {
    "vol_ratio_min": [3.0],
    "auction_amount_min": [5_000_000],
    "threshold_hi_base": [6.0, 8.0],
    "w_vol_ratio": [30.0],
}


def objective(stats):
    """综合目标函数：收益×胜率×样本量因子 − 单笔最大亏损惩罚。

    样本量 < 5 视为不可信，直接打极低分。
    """
    if not stats:
        return -999.0
    n = stats.get("交易次数", 0)
    if n < 5:
        return -999.0 + n
    cum = stats.get("累计收益%(复利)", 0)
    wr = stats.get("胜率%", 0)
    maxdd = abs(stats.get("最大单笔亏损%", 0))
    score = (cum / 100.0) * (wr / 100.0) * (1.0 + min(n, 100) / 100.0)
    score -= (maxdd / 100.0) * 0.1
    return round(score, 4)


def main():
    ap = argparse.ArgumentParser(description="竞价选股策略自动调参")
    ap.add_argument("--output-dir", default="./data")
    ap.add_argument("--report-dir", default="./auction_reports")
    ap.add_argument("--scope", default="all")
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-07-10")
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--demo", action="store_true", help="合成数据快速验证管线")
    ap.add_argument("--quick", action="store_true", help="小网格(2组合)快速真实验证")
    args = ap.parse_args()

    grid = QUICK_GRID if args.quick else GRID
    keys = list(grid.keys())
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*[grid[k] for k in keys])]
    print(f"[auto_tune] 参数组合数量: {len(combos)}  区间={args.start}~{args.end} "
          f"抽样={args.limit} demo={args.demo}")

    tmp = Path(args.report_dir) / ".tune_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    results = []
    best, best_key, best_obj = None, None, -1e9
    for ci, combo in enumerate(combos, 1):
        params = sp.StrategyParams.from_dict(combo)
        # 固定输出名以便读取 stats
        sp.run_backtest(str(tmp), scope=args.scope, start=args.start, end=args.end,
                        limit=args.limit, demo=args.demo, params=params)
        jsons = sorted(glob.glob(str(tmp / "backtest_*.json")))
        stats = {}
        if jsons:
            try:
                stats = json.loads(Path(jsons[-1]).read_text(encoding="utf-8")).get("stats", {})
            except Exception:
                stats = {}
        obj = objective(stats)
        results.append({"combo": combo, "stats": stats, "objective": obj})
        print(f"  [{ci}/{len(combos)}] {combo} -> 胜率{stats.get('胜率%','-')}% "
              f"累计{stats.get('累计收益%(复利)','-')}% 目标={obj}")
        if obj > best_obj:
            best_obj, best, best_key = obj, dict(combo), ci - 1  # 0 基索引，与 results 列表对齐

    # 清理临时回测文件
    for f in glob.glob(str(tmp / "backtest_*")):
        try:
            os.remove(f)
        except Exception:
            pass

    default_params = sp.get_default_params().to_dict()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    best_params = sp.StrategyParams.from_dict(best).to_dict() if best else default_params
    best_stats = next((r["stats"] for r in results if r["combo"] == best), {})
    params_payload = {
        "default": default_params,
        "best": best_params,
        "best_stats": best_stats,
        "tuned_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "universe": args.scope, "start": args.start, "end": args.end, "limit": args.limit,
        "demo": args.demo,
        "note": "best 为自动调参目标函数最优组合；default 为出厂默认。样本有限，注意过拟合，实盘请审慎。",
    }
    (out_dir / "params.json").write_text(
        json.dumps(params_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    tuning_payload = {
        "meta": {
            "start": args.start, "end": args.end, "limit": args.limit, "demo": args.demo,
            "grid_keys": keys, "n_combos": len(combos),
            "tuned_at": params_payload["tuned_at"],
        },
        "results": results,
        "best_key": best_key,
    }
    (out_dir / "param_tuning.json").write_text(
        json.dumps(tuning_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 报告
    lines = ["# 竞价选股策略 自动调参报告\n",
             f"> 区间 **{args.start} ~ {args.end}** ｜ 抽样 **{args.limit}** 只 ｜ "
             f"demo={args.demo} ｜ 组合 {len(combos)}\n"]
    lines.append("## 目标函数排名 (综合: 累计收益×胜率×样本量 − 风险惩罚)\n")
    lines.append("| 排名 | 参数组合 | 胜率% | 累计(复利)% | 交易次数 | 目标函数 |")
    lines.append("|------|------|------|------|------|------|")
    for i, r in enumerate(sorted(results, key=lambda x: x["objective"], reverse=True), 1):
        c, s = r["combo"], r["stats"]
        combo_str = " ".join(f"{k}={v}" for k, v in c.items())
        lines.append(f"| {i} | {combo_str} | {s.get('胜率%','-')} | "
                     f"{s.get('累计收益%(复利)','-')} | {s.get('交易次数','-')} | {r['objective']} |")
    lines.append("\n## 最优参数\n")
    lines.append("```json\n" + json.dumps(best_params, ensure_ascii=False, indent=2) + "\n```\n")
    lines.append("\n> 以上为历史数据统计，不构成投资建议；样本有限，注意过拟合。\n")
    rep_dir = Path(args.report_dir)
    rep_dir.mkdir(parents=True, exist_ok=True)
    (rep_dir / "param_tuning.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"[auto_tune] 完成。最优组合 #{best_key}: {best} 目标={best_obj}")
    print(f"[auto_tune] 已写出 data/params.json, data/param_tuning.json, "
          f"auction_reports/param_tuning.md")


if __name__ == "__main__":
    main()
