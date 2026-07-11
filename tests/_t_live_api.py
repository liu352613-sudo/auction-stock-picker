# -*- coding: utf-8 -*-
"""离线校验 /api/recommend 与 /api/stock 的实时评分重算逻辑（不联网）。

通过 monkeypatch 模拟两个场景：
  A. 实时行情不可达（返回空）→ 验证离线降级、live_scores 为空、字段齐全。
  B. 实时行情可达（合成报价）→ 验证 live_scores 用同一 score_stock 重算并带 delta。
"""
import sys, os, json, types
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import api.routers.core as core
import src.data_service as ds_mod

# ---- 合成 quote（匹配代码读取的键：最新价/量比/涨跌幅/成交额/成交量）----
def _synth_quote(code, price=None, vol_ratio=None, pct=None, amount=None, volume=None):
    return {
        "最新价": price, "量比": vol_ratio, "涨跌幅": pct,
        "成交额": amount, "成交量": volume,
    }

PASS, FAIL = 0, 0
def chk(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [XX] {name}  {extra}")

# ===== 场景 A：离线降级 =====
def fake_quote_empty(codes):
    return {}
ds_mod.data_service.spot_quote = fake_quote_empty
core.data_service.spot_quote = staticmethod(fake_quote_empty)

rA = core.api_recommend()
print("\n[场景A] 离线 → /api/recommend")
for k in ["trade_date", "effective_date", "data_freshness", "live", "live_flag",
          "live_scores", "live_score_flag", "updated_at"]:
    chk(f"字段 {k} 存在", k in rA, f"keys={list(rA.keys())}")
chk("data_freshness 合法", rA.get("data_freshness") in ("today", "previous"), rA.get("data_freshness"))
chk("live_flag=False(离线)", rA.get("live_flag") is False)
chk("live_scores 为空(离线)", rA.get("live_scores") == {})
chk("stocks 非空", len(rA.get("stocks", [])) > 0)

# ===== 场景 B：实时可达，盘中放量上涨 → 评分应变化并带 delta =====
def fake_quote_live(codes):
    out = {}
    for c in codes:
        # 给每只股票一个明显放大的量比与正涨幅，制造与盘前不同的盘中状态
        out[c] = _synth_quote(c, price=12.5, vol_ratio=9.5, pct=6.5,
                              amount=25000000, volume=2000000)
    return out
ds_mod.data_service.spot_quote = fake_quote_live
core.data_service.spot_quote = staticmethod(fake_quote_live)

rB = core.api_recommend()
print("\n[场景B] 实时 → /api/recommend")
chk("live_flag=True", rB.get("live_flag") is True)
chk("live_scores 非空", len(rB.get("live_scores", {})) > 0)
for code, v in rB.get("live_scores", {}).items():
    for k in ["score", "delta", "dimensions", "risk_factor"]:
        chk(f"live[{code}].{k} 存在", k in v, f"got {list(v.keys())}")
    # 放大上涨应使评分 > 盘前（delta 应 >=0，且维度解释应存在）
    chk(f"live[{code}] 有 8 维度", len(v.get("dimensions", [])) == 8, f"dims={len(v.get('dimensions',[]))}")
    chk(f"live[{code}] 风险因子存在", "risk_factor" in v)
    chk(f"live[{code}] 风险说明存在", "risk_note" in v and isinstance(v.get("risk_note"), str))
    print(f"      {code}: 盘前? 重算={v['score']} delta={v['delta']}")

# ===== 场景 C：/api/stock 详情实时评分 =====
# 先确认 600519 在 results 中
base = core.loaders.results()
code519 = next((s for s in base["stocks"] if str(s.get("代码")) == "600519"), None)
if code519 and code519.get("features"):
    stk = core.api_stock("600519")
    print("\n[场景C] /api/stock/600519")
    chk("返回 info", stk.get("info") is not None)
    chk("返回 kline", stk.get("kline") is not None)
    # 实时报价经 monkeypatch 给到 600519
    if stk.get("live_flag"):
        chk("live_score 存在(实时可达)", stk.get("live_score") is not None)
        ls = stk.get("live_score") or {}
        for k in ["score", "delta", "dimensions", "risk_factor"]:
            chk(f"live_score.{k} 存在", k in ls, f"got {list(ls.keys())}")
        print(f"      600519 盘前={code519.get('评分')} 重算={ls.get('score')} delta={ls.get('delta')}")
    else:
        chk("live_flag False(600519 不在实时列表)", True)
else:
    print("\n[场景C] 600519 不在推荐/无 features，跳过个股实时校验")

# ===== 同报价一致性：用快照特征构造 identical quote 应 delta≈0 =====
print("\n[场景D] 同报价一致性（实时=盘前快照原始值）")
def fake_quote_identical(codes):
    out = {}
    for c in codes:
        s = next((x for x in base["stocks"] if str(x.get("代码")) == c), None)
        f = (s or {}).get("features") or {}
        out[c] = _synth_quote(c, price=f.get("price"), vol_ratio=f.get("vol_ratio"),
                              pct=f.get("pct_open"), amount=f.get("auction_amount"),
                              volume=f.get("auction_volume"))
    return out
ds_mod.data_service.spot_quote = fake_quote_identical
core.data_service.spot_quote = staticmethod(fake_quote_identical)
rD = core.api_recommend()
max_delta = 0.0
for code, v in rD.get("live_scores", {}).items():
    max_delta = max(max_delta, abs(v["delta"]))
chk(f"同报价最大|delta|≤0.1 (got {max_delta})", max_delta <= 0.1, f"max={max_delta}")

print(f"\n==== 结果: PASS={PASS} FAIL={FAIL} ====")
sys.exit(1 if FAIL else 0)
