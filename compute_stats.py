#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收益统计聚合脚本。

聚合两类数据，产出 data/stats.json，供前端「收益统计」视图直接展示：

1) 历史回测绩效（auction_reports/backtest_*.json）
   - 选取最具代表性的回测作为 primary（交易次数≥10 且累计收益最高者）
   - 汇总每期回测（周期/交易次数/胜率/累计收益）
   - 由 primary 的逐笔交易计算月度分解

2) 推荐活跃度（data/history/*.json 快照）
   - 推荐天数、累计推荐次数、平均评分、平均温度
   - 评分分布、温度分布
   - 高频推荐个股 Top、近期评分/温度趋势

3) 策略调参摘要（data/param_tuning.json）
   - 最优参数组合及其绩效、相对出厂默认的提升

运行:
  python compute_stats.py          # 聚合并写 data/stats.json
  python compute_stats.py --quiet  # 静默模式（供定时任务调用）

前端 index.html 通过 fetch 读取 data/stats.json 渲染收益统计。
"""
import argparse
import datetime
import glob
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
REPORTS_DIR = os.path.join(ROOT, "auction_reports")
PARAM_TUNING_PATH = os.path.join(DATA_DIR, "param_tuning.json")
STATS_PATH = os.path.join(DATA_DIR, "stats.json")

# 温度等级（用于分布统计）
TEMP_LEVELS = ["冰冷", "寒冷", "凉爽", "温暖", "炎热", "沸腾"]
# 评分分桶（10 分一档，0-100）
SCORE_BUCKETS = [(i * 10, i * 10 + 10) for i in range(10)]


def _num(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# 1) 历史回测绩效
# ---------------------------------------------------------------------------
def load_backtests():
    """读取所有回测报告，返回有效报告列表（含 meta/stats/trades）。"""
    out = []
    for p in glob.glob(os.path.join(REPORTS_DIR, "backtest_*.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        stats = d.get("stats") or {}
        trades = d.get("trades") or []
        n = _num(stats.get("交易次数"), len(trades))
        if n <= 0:
            continue  # 跳过无交易/结构不符的报告
        out.append({
            "file": os.path.basename(p),
            "meta": d.get("meta", {}),
            "stats": stats,
            "trades": trades,
        })
    return out


def monthly_breakdown(trades):
    """由逐笔交易按月份聚合（等权累计收益=该月收益率之和）。"""
    by_month = {}
    for t in trades:
        dt = str(t.get("日期", ""))[:7]  # YYYY-MM
        if not dt or "-" not in dt:
            continue
        r = _num(t.get("收益率%"))
        win = 1 if r > 0 else 0
        m = by_month.setdefault(dt, {"month": dt, "trades": 0, "wins": 0, "ret_sum": 0.0})
        m["trades"] += 1
        m["wins"] += win
        m["ret_sum"] += r
    rows = []
    for dt in sorted(by_month.keys()):
        m = by_month[dt]
        rows.append({
            "month": dt,
            "trades": m["trades"],
            "win_rate": round(100.0 * m["wins"] / m["trades"], 1),
            "cum_return": round(m["ret_sum"], 2),
        })
    return rows


def aggregate_backtests():
    reports = load_backtests()
    summaries = []
    for r in reports:
        s = r["stats"]
        summaries.append({
            "file": r["file"],
            "period": f"{r['meta'].get('start','?')} ~ {r['meta'].get('end','?')}",
            "scope": r["meta"].get("scope", "all"),
            "trades": int(_num(s.get("交易次数"))),
            "win_rate": round(_num(s.get("胜率%")), 2),
            "avg_return": round(_num(s.get("平均收益率%")), 2),
            "cum_return": round(_num(s.get("累计收益%(复利)")), 2),
            "max_drawdown_trade": round(_num(s.get("最大单笔亏损%")), 2),
            "touch_tp": int(_num(s.get("触达+5%次数"))),
            "touch_sl": int(_num(s.get("触达-3%次数"))),
        })

    # 选取 primary：交易次数≥10 且累计收益（复利）最高者
    candidates = [r for r in reports if _num(r["stats"].get("交易次数")) >= 10]
    pool = candidates if candidates else reports
    primary = None
    if pool:
        primary = max(pool, key=lambda r: _num(r["stats"].get("累计收益%(复利)")))
        pstats = primary["stats"]
        primary_block = {
            "file": primary["file"],
            "period": f"{primary['meta'].get('start','?')} ~ {primary['meta'].get('end','?')}",
            "scope": primary["meta"].get("scope", "all"),
            "exit_rule": primary["meta"].get("exit_rule", "T+1 次日开盘卖出"),
            "data_source": primary["meta"].get("data_source", ""),
            "stats": {k: _num(v) for k, v in pstats.items()},
            "monthly": monthly_breakdown(primary["trades"]),
            "is_primary": True,
        }
    else:
        primary_block = None

    return {"primary": primary_block, "reports": summaries}


# ---------------------------------------------------------------------------
# 2) 推荐活跃度（来自历史快照）
# ---------------------------------------------------------------------------
def aggregate_recommendations():
    snaps = []
    if os.path.isdir(HISTORY_DIR):
        for p in glob.glob(os.path.join(HISTORY_DIR, "*.json")):
            try:
                snaps.append(json.load(open(p, encoding="utf-8")))
            except Exception:
                continue
    snaps.sort(key=lambda s: s.get("date", ""))

    total_days = len(snaps)
    total_picks = 0
    score_sum = 0.0
    temp_sum = 0.0
    score_dist = {f"{lo}-{hi}": 0 for lo, hi in SCORE_BUCKETS}
    temp_dist = {lv: 0 for lv in TEMP_LEVELS}
    pick_counter = {}      # code -> {name, count, score_sum}
    trend = []

    for s in snaps:
        stocks = s.get("stocks", [])
        total_picks += len(stocks)
        temp = s.get("temperature") or {}
        tval = _num(temp.get("total"))
        temp_sum += tval
        tlevel = temp.get("level", "")
        if tlevel in temp_dist:
            temp_dist[tlevel] += 1
        day_score_sum = 0.0
        for st in stocks:
            sc = _num(st.get("评分"))
            score_sum += sc
            day_score_sum += sc
            # 分桶
            b = min(int(sc) // 10, 9)
            lo, hi = SCORE_BUCKETS[b]
            score_dist[f"{lo}-{hi}"] += 1
            code = str(st.get("代码", ""))
            if code:
                rec = pick_counter.setdefault(code, {"code": code, "name": st.get("名称", ""), "count": 0, "score_sum": 0.0})
                rec["count"] += 1
                rec["score_sum"] += sc
        avg_day = round(day_score_sum / len(stocks), 1) if stocks else 0.0
        trend.append({"date": s.get("date", ""), "avg_score": avg_day, "temperature": tval})

    avg_score = round(score_sum / total_picks, 1) if total_picks else 0.0
    avg_temp = round(temp_sum / total_days, 1) if total_days else 0.0

    top_picks = sorted(
        ({"code": v["code"], "name": v["name"], "count": v["count"],
          "avg_score": round(v["score_sum"] / v["count"], 1)} for v in pick_counter.values()),
        key=lambda x: (x["count"], x["avg_score"]), reverse=True
    )[:10]

    return {
        "total_days": total_days,
        "total_picks": total_picks,
        "avg_score": avg_score,
        "avg_temperature": avg_temp,
        "score_distribution": score_dist,
        "temperature_distribution": temp_dist,
        "top_picks": top_picks,
        "trend": trend[-30:],
    }


# ---------------------------------------------------------------------------
# 3) 策略调参摘要
# ---------------------------------------------------------------------------
def aggregate_tuning():
    if not os.path.exists(PARAM_TUNING_PATH):
        return None
    try:
        d = json.load(open(PARAM_TUNING_PATH, encoding="utf-8"))
    except Exception:
        return None
    results = d.get("results", [])
    best_key = d.get("best_key")
    best = None
    if best_key is not None and 0 <= best_key < len(results):
        best = results[best_key]
    return {
        "meta": d.get("meta", {}),
        "best_key": best_key,
        "best_params": (best or {}).get("combo"),
        "best_stats": (best or {}).get("stats"),
        "n_combos": len(results),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="收益统计聚合")
    ap.add_argument("--quiet", action="store_true", help="静默模式")
    args = ap.parse_args()
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a))

    backtest = aggregate_backtests()
    reco = aggregate_recommendations()
    tuning = aggregate_tuning()

    payload = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "backtest": backtest,
        "recommendation": reco,
        "tuning": tuning,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    p = backtest.get("primary")
    if p:
        log(f"回测 primary: {p['file']}  交易{p['stats'].get('交易次数')}笔  "
            f"胜率{p['stats'].get('胜率%')}%  累计{p['stats'].get('累计收益%(复利)')}%  "
            f"月度分解{len(p['monthly'])}项")
    else:
        log("回测: 未找到可用回测报告（运行 auto_tune.py / run_backtest 后生成）")
    log(f"推荐活跃度: {reco['total_days']}天 / {reco['total_picks']}次  "
        f"平均评分{reco['avg_score']}  平均温度{reco['avg_temperature']}")
    log(f"调参摘要: {'有(' + str(tuning['n_combos']) + '组)' if tuning else '无'}")
    log(f"已生成: {STATS_PATH}")


if __name__ == "__main__":
    main()
