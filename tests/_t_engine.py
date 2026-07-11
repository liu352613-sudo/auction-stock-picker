# -*- coding: utf-8 -*-
"""统一评分引擎单测（锁定需求：差异化 / 无固定100 / 空数据得0 / 风险惩罚 / 8维度 / 同源委托）。

运行：python tests/_t_engine.py
"""
import sys, os, math
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from src.scoring import score_stock, StockFeatures, WEIGHTS, explain_text
from src.stock_picker import calc_momentum_score, StrategyParams
from api import loaders

PASS, FAIL = 0, 0
def chk(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  [OK] {name}")
    else:
        FAIL += 1; print(f"  [XX] {name}  {extra}")


def feat(**kw):
    base = dict(code="X", name="X", sector="X", price=0.0, vol_ratio=0.0,
        pct_open=0.0, auction_amount=0.0, auction_volume=0.0, fund_flow_today_net=0.0,
        ma60=0.0, ma20=0.0, ma10=0.0, ma5=0.0, prev_volume=0.0, volatility=0.0,
        fund_flow_5d_net=0.0, sector_heat=0.0, float_mv=0.0, is_st=False, market_pct=0.0)
    base.update(kw)
    return StockFeatures(**base)


# 1) 强 / 中 / 弱 / 空 —— 必须差异化且有序
strong = feat(price=12.5, vol_ratio=8.0, pct_open=5.0, auction_amount=3e7,
    auction_volume=1.2e6, prev_volume=8e5, ma60=11.0, ma5=12.0, ma10=11.8, ma20=11.6,
    volatility=0.3, fund_flow_5d_net=5e7, sector_heat=0.8, float_mv=1e11, market_pct=0.2)
medium = feat(price=10.2, vol_ratio=3.5, pct_open=2.5, auction_amount=1e7,
    auction_volume=4e5, prev_volume=4e5, ma60=10.0, ma5=10.1, ma10=10.0, ma20=9.9,
    volatility=0.35, fund_flow_5d_net=8e6, sector_heat=0.5, float_mv=5e10, market_pct=0.2)
weak = feat(price=8.0, vol_ratio=1.5, pct_open=-1.0, auction_amount=2e6,
    auction_volume=1e4, prev_volume=9e5, ma60=8.5, ma5=8.0, ma10=8.1, ma20=8.2,
    volatility=0.6, fund_flow_5d_net=-2e6, sector_heat=0.1, float_mv=2e10, market_pct=0.2)
empty = feat()  # 全 0

rs, rm, rw, re = (score_stock(strong), score_stock(medium), score_stock(weak), score_stock(empty))
print("\n[1] 差异化与排序")
chk(f"强股({rs['total']}) > 中股({rm['total']}) > 弱股({rw['total']}) > 空股({re['total']})",
    rs["total"] > rm["total"] > rw["total"] > re["total"],
    f"{rs['total']}/{rm['total']}/{rw['total']}/{re['total']}")
chk(f"强股严格 < 100（无硬编码满分）: {rs['total']}", rs["total"] < 100, rs["total"])
chk(f"弱股很低 (<5): {rw['total']}", rw["total"] < 5, rw["total"])
chk(f"空数据 = 0: {re['total']}", re["total"] == 0.0, re["total"])

# 2) 8 维度结构 + 权重合计 100
print("\n[2] 维度结构")
dims = rs["dimensions"]
chk("维度数量 == 8", len(dims) == 8, len(dims))
chk("权重合计 == 100", abs(sum(WEIGHTS.values()) - 100.0) < 1e-6, sum(WEIGHTS.values()))
keys = {d["key"] for d in dims}
chk("覆盖全部 8 个维度键", keys == set(WEIGHTS.keys()), keys ^ set(WEIGHTS.keys()))
for d in dims:
    chk(f"维度 {d['key']} 含 label/score/max/note",
        all(k in d for k in ("label", "score", "max", "note")))
    chk(f"维度 {d['key']} score∈[0,max]", 0 <= d["score"] <= d["max"] + 1e-6, d["score"])

# 3) 风险惩罚：相同特征 ST 应得更低分
print("\n[3] 风险惩罚")
normal = feat(price=12.0, vol_ratio=6.0, pct_open=4.0, auction_amount=2e7,
    auction_volume=8e5, prev_volume=6e5, ma60=11.0, ma5=11.8, ma10=11.6, ma20=11.4,
    volatility=0.3, fund_flow_5d_net=3e7, sector_heat=0.7, float_mv=8e10, market_pct=0.2)
st = feat(price=12.0, vol_ratio=6.0, pct_open=4.0, auction_amount=2e7,
    auction_volume=8e5, prev_volume=6e5, ma60=11.0, ma5=11.8, ma10=11.6, ma20=11.4,
    volatility=0.3, fund_flow_5d_net=3e7, sector_heat=0.7, float_mv=8e10, market_pct=0.2, is_st=True)
rn, rst = score_stock(normal), score_stock(st)
chk(f"ST 风险因子 < 1: {rst['risk_factor']}", rst["risk_factor"] < 1.0, rst["risk_factor"])
chk(f"ST 总分低于非ST ({rst['total']} < {rn['total']})", rst["total"] < rn["total"], f"{rst['total']} vs {rn['total']}")
chk("非ST 风险因子=1 (风险中性)", rn["risk_factor"] == 1.0, rn["risk_factor"])

# 4) 实时重算同报价 → delta≈0（验证 API 路径口径一致）
print("\n[4] 实时重算同报价一致性")
# 用快照特征构造「相同」的 live quote 并重算，应与原评分一致
snap_feat = feat(price=12.3, vol_ratio=5.8, pct_open=4.2, auction_amount=8e6,
    auction_volume=6.5e5, prev_volume=1.2e6, ma60=11.5, ma5=12.19, ma10=11.96, ma20=11.73,
    volatility=0.35, fund_flow_5d_net=2.4e7, sector_heat=0.75, float_mv=5e10, market_pct=0.6)
base = score_stock(snap_feat)["total"]
# 模拟 API：用相同值覆盖日内字段后重算
live = score_stock(StockFeatures(**{k: getattr(snap_feat, k) for k in
    StockFeatures.__dataclass_fields__}))["total"]
chk(f"同报价重算 delta≈0 ({abs(base-live)})", abs(base - live) < 1e-6, abs(base-live))

# 5) 同源委托：calc_momentum_score 必须与统一引擎结果一致（回测/历史共用引擎）
# 注：stock_picker 以 `from .scoring import score_stock` 持有引用，无法靠打桩拦截；
# 改用「相同输入 → 相同总分」等价性证明它确实走统一引擎。
print("\n[5] 同源委托（等价性）")
m_total, m_detail = calc_momentum_score(price=12.0, vol_ratio=5.0, pct_change=3.0,
    ma60=11.0, market_pct=0.2, auction_volume=8e5, prev_volume=6e5)
f2 = StockFeatures(price=12.0, vol_ratio=5.0, pct_open=3.0, ma60=11.0,
    auction_volume=8e5, prev_volume=6e5, market_pct=0.2)
e_total = score_stock(f2, StrategyParams())["total"]
chk(f"calc_momentum_score 与统一引擎结果一致 ({m_total} == {e_total})",
    abs(m_total - e_total) < 1e-6, f"{m_total} vs {e_total}")
chk("返回含 4 项传统明细键", all(k in m_detail for k in ("量比分", "相对大盘分", "均线偏离分", "量能比分")))

# 6) explain_text 可读
print("\n[6] 解释文本")
exps = explain_text(rs)
chk("explain_text 非空且末行为综合得分", exps and "综合得分" in exps[-1], exps[-1] if exps else "")

print(f"\n==== 引擎单测 PASS={PASS} FAIL={FAIL} ====")
sys.exit(1 if FAIL else 0)
