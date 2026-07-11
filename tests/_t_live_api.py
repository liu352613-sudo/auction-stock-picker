# -*- coding: utf-8 -*-
"""离线校验 API 数据流：首页推荐端点不重算评分 + 个股详情仍维持盘中重算。

场景：
  A. 离线降级 → /api/recommend 有 live quote 但**无 live_scores**
  B. 实时报价 → /api/recommend 仍无 live_scores；/api/stock/{code} 有 live_score
  C. 一致性   → 同报价下 /api/stock live_score delta≈0
  D. 前端验证 → verify_reco.py 输出来源/数量
"""
import sys, os, json, subprocess
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import api.routers.core as core
import src.data_service as ds_mod

def _synth_quote(code, price=None, vol_ratio=None, pct=None, amount=None, volume=None):
    return {
        "最新价": price, "量比": vol_ratio, "涨跌幅": pct,
        "成交额": amount, "成交量": volume,
    }

PASS, FAIL = 0, 0
def chk(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  [OK] {name}")
    else:
        FAIL += 1; print(f"  [XX] {name}  {extra}")

# ===== 基础加载 =====
base = core.loaders.results()
codes = [str(s.get("代码")) for s in base.get("stocks", []) or []]
has_stocks = len(codes) > 0
if not has_stocks:
    print("\n[skip] results.json 为空（真实接口未生成数据）；仅运行结构校验.")

# ===== 场景 A：离线降级 → /api/recommend =====
def fake_quote_empty(codes):
    return {}
ds_mod.data_service.spot_quote = fake_quote_empty
core.data_service.spot_quote = staticmethod(fake_quote_empty)

rA = core.api_recommend()
print("\n[场景A] 离线 → /api/recommend")
for k in ["trade_date", "effective_date", "data_freshness", "live", "live_flag", "updated_at"]:
    chk(f"字段 {k} 存在", k in rA)
# 首页不再重算评分：禁止 live_scores / live_score_flag
chk("live_scores 不存在（首页不重算评分）", "live_scores" not in rA, "live_scores" in rA)
chk("live_score_flag 不存在", "live_score_flag" not in rA)
chk("data_freshness 合法", rA.get("data_freshness") in ("today", "previous"))
chk("live_flag=False(离线)", rA.get("live_flag") is False)
if has_stocks:
    chk("stocks 非空", len(rA.get("stocks", [])) > 0)

# 验证 freshness 字段内容
print(f"      effective_date={rA.get('effective_date')} trade_date={rA.get('trade_date')} freshness={rA.get('data_freshness')}")

# ===== 场景 B：实时报价可达，首页仍无评分重算 =====
print("\n[场景B] 实时报价 → /api/recommend 与 /api/stock")

def fake_quote_live(codes):
    out = {}
    for c in codes:
        out[c] = _synth_quote(c, price=12.5, vol_ratio=9.5, pct=6.5,
                              amount=25000000, volume=2000000)
    return out
ds_mod.data_service.spot_quote = fake_quote_live
core.data_service.spot_quote = staticmethod(fake_quote_live)

rB = core.api_recommend()
# 当 stocks 非空时实时报价可达 → live_flag=True；0 stocks 时无法报价 → False
if has_stocks:
    chk("/api/recommend live_flag=True(报价可达)", rB.get("live_flag") is True)
else:
    chk("/api/recommend 无 stocks 不报价", rB.get("live_flag") is False)
chk("/api/recommend 仍无 live_scores", "live_scores" not in rB)
if has_stocks:
    # /api/stock/{code} 仍维持详情页盘中重算
    first_code = codes[0]
    stk = core.api_stock(first_code)
    print(f"\n  /api/stock/{first_code} :")
    chk("live_flag=True", stk.get("live_flag") is True)
    chk("live_score 存在(详情页面盘中重算)", stk.get("live_score") is not None)
    if stk.get("live_score"):
        ls = stk["live_score"]
        for k in ["score", "delta", "dimensions", "risk_factor"]:
            chk(f"live_score.{k} 存在", k in ls)
        dim_count = len(ls.get("dimensions", []))
        chk(f"dimensions 8 个", dim_count == 8, f"got {dim_count}")
        print(f"      score={ls.get('score')} delta={ls.get('delta')} risk_factor={ls.get('risk_factor')}")

# ===== 场景 C：同报价一致性（/api/stock 路径）=====
print("\n[场景C] 同报价一致性")
if has_stocks and all(s.get("features") for s in base.get("stocks", [])):
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
    max_delta = 0.0
    worst = ""
    for code in codes:
        stk = core.api_stock(code)
        if stk.get("live_score"):
            d = abs(stk["live_score"]["delta"])
            if d > max_delta:
                max_delta = d
                worst = code
    chk(f"同报价最大|delta|≤0.1 (worst={worst}@{max_delta})", max_delta <= 0.1, f"max={max_delta}")
    print(f"      max_delta={max_delta}")
else:
    print("  (跳过后端一致性 — 无 features 数据)")

# ===== 场景 D：verify_reco.py 验证脚本 =====
print("\n[场景D] verify_reco.py 输出")
try:
    r = subprocess.run(
        [sys.executable, "scripts/verify_reco.py"],
        capture_output=True, text=True, timeout=30, cwd=os.path.dirname(os.path.abspath(__file__)) + "/.."
    )
    out_lines = r.stdout.strip().split("\n")
    for line in out_lines[-8:]:
        print(f"  {line}")
    chk("verify_reco 运行成功", r.returncode == 0, f"exit={r.returncode}")
except Exception as e:
    print(f"  [skip] verify_reco 异常: {e}")
    chk("verify_reco 可运行", False, str(e))

print(f"\n==== 结果: PASS={PASS} FAIL={FAIL} ====")
sys.exit(1 if FAIL else 0)
