# -*- coding: utf-8 -*-
"""核心 API 路由（7 个端点）。

设计原则：「静态优先，实时补充」。
- 所有端点都先返回由 Python 脚本预生成的静态数据（data/*.json），保证秒开与离线可用。
- 实时部分（行情/个股盘中数据/板块热度）经统一 DataService 拉取；
  一旦数据源不可达，自动降级为静态并标注 live=false，不影响前端渲染。
"""
import datetime
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api import loaders
from src.data_service import data_service
from src.stock_picker import StrategyParams, get_default_params

router = APIRouter()


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# /api/market  实时指数
# ---------------------------------------------------------------------------
@router.get("/api/market")
def api_market():
    """实时指数行情。优先 DataService（东财→新浪），失败降级为静态 indices。"""
    static = loaders.results().get("indices", []) or []
    try:
        # 优先东财，失败走新浪
        try:
            df = data_service.index_spot_em()
            name_col = "指数名称" if "指数名称" in df.columns else df.columns[1]
        except Exception:
            df = data_service.index_spot_sina()
            name_col = "名称" if "名称" in df.columns else df.columns[1]
        pool = {}
        for _, r in df.iterrows():
            nm = str(r[name_col])
            pool[nm] = loaders.normalize_index_row(
                nm, str(r.get("指数代码", r.get("代码", ""))),
                r.get("最新价"), r.get("涨跌额"), r.get("涨跌幅"))
        rows = [v for v in pool.values()]
        if rows:
            return {"indices": rows, "live": True, "source": "akshare", "updated_at": _now()}
    except Exception as e:
        pass
    return {"indices": static, "live": False, "source": "static",
            "updated_at": _now(), "note": "实时指数不可达，返回静态回退数据"}


# ---------------------------------------------------------------------------
# /api/recommend  今日推荐（静态 + 实时盘中补充）
# ---------------------------------------------------------------------------
@router.get("/api/recommend")
def api_recommend():
    """今日推荐。返回静态选股结果，并附带实时盘中报价（涨跌幅/最新价/成交量/成交额/量比）。"""
    base = loaders.results()
    codes = [str(s.get("代码")) for s in base.get("stocks", []) or []]
    live = None
    live_flag = False
    try:
        quotes = data_service.spot_quote(codes) if codes else {}
        if quotes:
            live = {"by_code": quotes}
            live_flag = True
    except Exception:
        live = None
    out = dict(base)
    out["live"] = live
    out["live_flag"] = live_flag
    out["updated_at"] = _now()
    return out


# ---------------------------------------------------------------------------
# /api/history  历史推荐
# ---------------------------------------------------------------------------
@router.get("/api/history")
def api_history(limit: int = 60, date: Optional[str] = None):
    """历史推荐索引；?date=YYYY-MM-DD 返回该期快照。"""
    if date:
        snap = loaders.history_snapshot(date)
        if snap is None:
            raise HTTPException(status_code=404, detail=f"未找到 {date} 的历史推荐")
        return {"date": date, "snapshot": snap}
    idx = loaders.history_index()
    return {"count": len(idx), "items": idx[:limit], "updated_at": _now()}


# ---------------------------------------------------------------------------
# /api/backtest  回测结果
# ---------------------------------------------------------------------------
@router.get("/api/backtest")
def api_backtest():
    """回测统计（来自 data/stats.json）。"""
    s = loaders.stats()
    return {"stats": s, "updated_at": _now()}


# ---------------------------------------------------------------------------
# /api/hot-sector  热点板块
# ---------------------------------------------------------------------------
@router.get("/api/hot-sector")
def api_hot_sector(top: int = 20):
    """热点行业板块排行（实时）。失败返回空列表并标注 live=false。"""
    try:
        rows = data_service.hot_sectors(top=top)
        return {"sectors": rows, "live": True, "source": "akshare", "updated_at": _now()}
    except Exception:
        return {"sectors": [], "live": False, "source": "static",
                "updated_at": _now(), "note": "实时板块数据不可达"}


# ---------------------------------------------------------------------------
# /api/stock/{code}  股票详情
# ---------------------------------------------------------------------------
@router.get("/api/stock/{code}")
def api_stock(code: str):
    """股票详情：静态信息 + K线 + 实时报价 + 资金流。"""
    code = code.zfill(6)
    info = loaders.stock_in_results(code)
    kl = loaders.kline(code)
    live = None
    fund = None
    live_flag = False
    try:
        quotes = data_service.spot_quote([code])
        if quotes.get(code):
            live = quotes[code]
            live_flag = True
    except Exception:
        pass
    try:
        fund = data_service.fund_flow(code)
    except Exception:
        fund = None
    if info is None and kl is None:
        raise HTTPException(status_code=404, detail=f"未找到股票 {code} 的静态数据")
    return {
        "code": code,
        "info": info,
        "kline": kl,
        "live": live,
        "fund_flow": fund,
        "live_flag": live_flag,
        "updated_at": _now(),
    }


# ---------------------------------------------------------------------------
# /api/config  策略配置
# ---------------------------------------------------------------------------
class ConfigIn(BaseModel):
    params: dict


@router.get("/api/config")
def api_config_get():
    """当前策略参数（default/best/best_stats/tuned_at）。"""
    return loaders.params()


@router.post("/api/config")
def api_config_post(body: ConfigIn):
    """保存用户策略参数到 data/user_params.json（不覆盖自动调参 best）。

    返回校验后的完整参数（与默认合并）。应用需重新运行生成脚本。
    """
    default = get_default_params().to_dict()
    merged = dict(default)
    merged.update({k: v for k, v in (body.params or {}).items() if k in default})
    try:
        StrategyParams.from_dict(merged)  # 校验字段/类型
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"参数校验失败: {e}")
    payload = {
        "params": merged,
        "saved_at": _now(),
        "note": "已保存到 data/user_params.json；运行 python build_site.py --with-tune 可应用并重新生成数据",
    }
    out_path = os.path.join(loaders.DATA_DIR, "user_params.json")
    with open(out_path, "w", encoding="utf-8") as f:
        import json
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload
