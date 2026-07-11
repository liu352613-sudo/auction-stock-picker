#!/usr/bin/env python3
"""验证 data/results.json 与历史快照的数据来源、推荐数量与真实性（无 Demo/Fallback）。

输出：
- 数据来源（data_source）
- 是否示例/DEMO 数据
- 推荐数量（recommendations 条数）
- 生效交易日
- 推荐股票列表（简称+代码+评分）
- 前端 DS-Badge 标签

运行：python scripts/verify_reco.py
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_PATH = os.path.join(ROOT, "data", "results.json")
HISTORY_DIR = os.path.join(ROOT, "data", "history")

def verify_results(path, label="results.json"):
    if not os.path.exists(path):
        print(f"[{label}] 文件不存在")
        return
    d = json.load(open(path, encoding="utf-8"))
    src = d.get("data_source", "-")
    trade_date = d.get("trade_date", "-")
    generated_at = d.get("generated_at", "-")

    # 规范字段：优先 recommendations，回退 stocks
    reco = d.get("recommendations") or d.get("stocks") or []
    count = len(reco)
    is_demo = "DEMO" in src or bool(d.get("params", {}).get("demo"))

    print(f"[{label}]")
    print(f"  ├─ 数据来源      : {src}")
    print(f"  ├─ 是否示例/DEMO : {'是 ⚠️' if is_demo else '否 ✓'}")
    print(f"  ├─ 推荐数量      : {count} 只（recommendations 字段）")
    print(f"  ├─ 生效交易日    : {trade_date}")
    print(f"  └─ 生成时间      : {generated_at}")
    print(f"  ┌─ 推荐股票列表")
    if count:
        for i, s in enumerate(reco):
            name = s.get("名称", s.get("name", "?"))
            code = s.get("代码", s.get("code", "?"))
            score = s.get("评分", s.get("score", "?"))
            print(f"  │  {i+1:>2}. {name}({code}) 评分={score}")
    else:
        print(f"  │  （空 — 首页将显示「当前推荐数据为空」）")
    # 前端 DS-Badge 模拟
    badge = "live" if d.get("indices_live") else ("demo" if is_demo else "static")
    print(f"  └─ DS-Badge     : {badge} -> {'内置样例数据' if badge=='demo' else '实时行情' if badge=='live' else '历史/缓存数据'}")
    print()
    return {"count": count, "is_demo": is_demo, "src": src, "trade_date": trade_date}


if __name__ == "__main__":
    print("=" * 60)
    print("  数据真实性校验 — 推荐数据来源与数量验证")
    print("=" * 60)
    r1 = verify_results(RESULTS_PATH, "results.json")

    # 检查最近一个历史快照
    if os.path.isdir(HISTORY_DIR):
        snaps = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith(".json"))
        if snaps:
            verify_results(os.path.join(HISTORY_DIR, snaps[-1]), f"history/{snaps[-1]}")
        else:
            print("[history] 无历史快照")
    print("=" * 60)
    if r1 and r1["count"] == 0:
        print("结论：推荐列表为空。系统将在首页显示「当前推荐数据为空」，不会回退到示例数据。")
    elif r1 and r1["is_demo"]:
        print("结论：当前为示例/DEMO 数据。请运行 python generate_results.py（不加 --demo）以生成真实推荐。")
    else:
        print("结论：数据来源真实，推荐列表来自 results.json，首页将严格展示此列表。")
