# -*- coding: utf-8 -*-
"""离线刷新脚本：用当前统一评分引擎重算已存储数据的「评分拆解」。

用途：当 src/scoring.py 引擎结构变化（如维度数量、风险因子暴露方式）后，
把 data/results.json 与 data/history/*.json 中每只股票的「评分明细/dimensions/
risk_factor/评分」按 *当前引擎* 重新计算，保证静态文件与引擎、与 API 实时重算
口径完全一致。

要点：
- 仅重算「拆解」，不改动底层真实特征（features 来自此前真实行情/日线，原样保留）。
- 不联网，纯本地计算。
- 会就地覆盖对应 json；这些文件均已纳入 git 版本管理，可随时回滚。

用法：
    python scripts/refresh_scores.py            # 刷新 results.json + 全部 history 快照
    python scripts/refresh_scores.py data/results.json
"""
import sys, os, json, glob
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from src.scoring import score_stock, StockFeatures
from src.stock_picker import StrategyParams, get_default_params, _to_detail
from api import loaders

FIELDS = list(StockFeatures.__dataclass_fields__.keys())


def _params():
    try:
        p = loaders.params()
        best = (p.get("best") or p.get("default")) or get_default_params().to_dict()
        return StrategyParams.from_dict(best)
    except Exception:
        return get_default_params()


def refresh_file(path, params):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    stocks = d.get("stocks") or []
    if not stocks:
        return 0
    n = 0
    for s in stocks:
        feat_d = s.get("features") or {}
        if not feat_d:
            continue
        feat = StockFeatures(**{k: feat_d.get(k) for k in FIELDS})
        res = score_stock(feat, params)
        detail = _to_detail(res)
        detail["risk_note"] = res.get("risk_note", "风险中性")
        s["评分"] = res["total"]
        s["评分明细"] = detail
        n += 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return n


def main():
    params = _params()
    targets = sys.argv[1:] or ([loaders.RESULTS_PATH] if hasattr(loaders, "RESULTS_PATH") else [])
    if not targets:
        targets = ["data/results.json"]
        targets += sorted(glob.glob("data/history/*.json"))
    total = 0
    for p in targets:
        if os.path.exists(p):
            c = refresh_file(p, params)
            total += c
            print(f"  刷新 {p}: {c} 只")
    print(f"完成，共刷新 {total} 只股票评分拆解。")


if __name__ == "__main__":
    main()
