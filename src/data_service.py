# -*- coding: utf-8 -*-
"""统一数据服务层 (DataService)
================================

**这是整个项目唯一允许 import akshare 的模块。**

- 策略引擎 (src/stock_picker.py)、数据生成 (generate_results.py)、自动调参
  (auto_tune.py) 以及 FastAPI 后端 (api/) 都必须通过本模块的 DataService 实例
  获取行情 / 指数 / 个股 / 日线 / 板块 / 资金流，禁止直接调用 akshare。
- 内置：懒加载 akshare、自动安装依赖、调用缓存、数据源回退 (东财 → 新浪)、重试。
- 预留扩展点：热点板块 hot_sectors()、个股资金流 fund_flow()、批量实时报价
  spot_quote()，为实时 API / AI 分析 / 实盘交易 / 消息推送打基础。

架构定位：
    AkShare ──> DataService ──> [策略引擎 | 数据生成 | FastAPI API]
                                        │
                                        └─> 前端 SPA (静态优先 + API 实时刷新)
"""
from __future__ import annotations

import os
import sys
import time
import subprocess
from typing import Optional

import pandas as pd


class DataServiceError(Exception):
    """数据服务层统一异常。"""


class DataService:
    """集中封装所有外部行情数据源（当前为 AkShare）。

    设计原则
    --------
    - 延迟导入 akshare，仅在首次需要时 import，且全局只此一处。
    - 缓存：默认 15s TTL，避免盘中高频刷新重复打接口。
    - 回退：单数据源失败时自动切换到备用源（东财 ↔ 新浪）。
    - force_sina()：供自动调参在沙箱/受限网络下强制走新浪。
    """

    def __init__(self, log=print, cache_ttl: int = 15):
        self._ak = None
        self._prefer = "auto"          # auto | em | sina
        self._cache_ttl = cache_ttl    # 秒
        self._cache: dict = {}
        self._log = log or print

    # ------------------------------------------------------------------ #
    # 依赖与源管理
    # ------------------------------------------------------------------ #
    def ensure_deps(self):
        """确保 akshare 可用，缺失时尝试自动安装。"""
        if self._ak is not None:
            return
        try:
            import akshare  # noqa: F401
        except ImportError:
            self._log("未检测到 akshare，尝试自动安装依赖 (akshare pandas numpy)...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "--quiet", "akshare"]
                )
                self._log("依赖安装完成。")
            except Exception as e:  # pragma: no cover
                self._log(f"自动安装失败: {e}；请手动执行: pip install akshare")
                raise DataServiceError("akshare 未安装且自动安装失败") from e
        # 真正导入并缓存模块引用
        import akshare as ak
        self._ak = ak

    @property
    def ak(self):
        """暴露 akshare 模块（仅内部/调试用）。"""
        self.ensure_deps()
        return self._ak

    def set_prefer(self, prefer: str):
        """设置数据源偏好：'auto'（默认，东财优先回退新浪）/ 'em' / 'sina'。"""
        if prefer not in ("auto", "em", "sina"):
            raise ValueError("prefer 必须是 auto|em|sina")
        self._prefer = prefer

    def force_sina(self, on: bool = True):
        """强制全部走新浪数据源。供自动调参在受限网络下使用。"""
        self._prefer = "sina" if on else "auto"

    def _cached(self, key, fn, ttl: Optional[int] = None):
        ttl = self._cache_ttl if ttl is None else ttl
        now = time.time()
        item = self._cache.get(key)
        if item and (now - item[0]) < ttl:
            return item[1]
        val = fn()
        self._cache[key] = (now, val)
        return val

    def invalidate(self, key_prefix: Optional[str] = None):
        if key_prefix is None:
            self._cache.clear()
        else:
            for k in list(self._cache.keys()):
                if k.startswith(key_prefix):
                    self._cache.pop(k, None)

    # ------------------------------------------------------------------ #
    # 指数
    # ------------------------------------------------------------------ #
    def index_spot_sina(self):
        """实时指数行情（新浪）。列含 名称/最新价/涨跌额/涨跌幅 等。"""
        ak = self.ak
        df = ak.stock_zh_index_spot_sina()
        return df

    def index_spot_em(self):
        """实时指数行情（东方财富）。列含 指数名称/指数代码/最新价/涨跌额/涨跌幅 等。"""
        ak = self.ak
        return ak.stock_zh_index_spot_em()

    def index_daily(self, sym: str):
        """指数日线 stock_zh_index_daily(symbol)。返回 DataFrame。"""
        ak = self.ak
        return ak.stock_zh_index_daily(symbol=sym)

    # ------------------------------------------------------------------ #
    # 全市场实时
    # ------------------------------------------------------------------ #
    def a_spot_em(self):
        """全 A 实时行情（东方财富，含「量比」列）。带重试。"""
        ak = self.ak
        last_err = None
        for attempt in range(1, 4):
            try:
                df = ak.stock_zh_a_spot_em()
                if df is None or len(df) == 0:
                    raise ValueError("东方财富接口返回空数据")
                return df
            except Exception as e:
                last_err = e
                self._log(f"[DataService] a_spot_em 第 {attempt}/3 次失败: {e}")
                if attempt < 3:
                    time.sleep(3)
        raise DataServiceError(f"a_spot_em 失败: {last_err}")

    def a_spot(self):
        """全 A 实时行情（新浪，不含量比）。"""
        ak = self.ak
        return ak.stock_zh_a_spot()

    def new_stock(self):
        """新股列表 stock_zh_a_new()。"""
        ak = self.ak
        return ak.stock_zh_a_new()

    # ------------------------------------------------------------------ #
    # 个股
    # ------------------------------------------------------------------ #
    def individual_info(self, code: str):
        """个股基础信息 stock_individual_info_em(symbol=code)。返回 DataFrame。"""
        ak = self.ak
        return ak.stock_individual_info_em(symbol=str(code))

    def stock_hist(self, code: str, start: str, end: str, adjust: str = "qfq"):
        """个股日线。优先东财 stock_zh_a_hist，失败回退新浪 stock_zh_a_daily。

        返回标准列 DataFrame(日期,开盘,收盘,最高,最低,成交量,成交额) 升序。
        force_sina=True 时只走新浪。
        """
        ak = self.ak
        cols = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]
        sd_f, ed_f = start.replace("-", ""), end.replace("-", "")
        use_em = self._prefer in ("auto", "em")
        # 1) 东财
        if use_em:
            try:
                h = ak.stock_zh_a_hist(symbol=str(code), period="daily",
                                       start_date=sd_f, end_date=ed_f, adjust=adjust)
                if h is not None and len(h):
                    h = h[cols].copy()
                    h["日期"] = pd.to_datetime(h["日期"])
                    for c in ("开盘", "收盘", "最高", "最低", "成交量", "成交额"):
                        h[c] = pd.to_numeric(h[c], errors="coerce")
                    return h.sort_values("日期").reset_index(drop=True)
            except Exception as e:
                self._log(f"  [DataService] eastmoney hist 失败, 回退 sina: {code} ({e})")
        # 2) 新浪
        try:
            prefix = "sh" if str(code).startswith(("60", "68", "90", "88")) else "sz"
            sym = prefix + str(code).zfill(6)
            d = ak.stock_zh_a_daily(symbol=sym, adjust=adjust)
            if d is None or len(d) == 0:
                return pd.DataFrame(columns=cols)
            d = d.rename(columns={"date": "日期", "open": "开盘", "high": "最高",
                                  "low": "最低", "close": "收盘",
                                  "volume": "成交量", "amount": "成交额"})
            d["日期"] = pd.to_datetime(d["日期"])
            for c in ("开盘", "收盘", "最高", "最低", "成交量", "成交额"):
                d[c] = pd.to_numeric(d[c], errors="coerce")
            d = d.sort_values("日期")
            st, en = pd.Timestamp(start), pd.Timestamp(end)
            d = d[(d["日期"] >= st) & (d["日期"] <= en)]
            return d.reset_index(drop=True)
        except Exception as e:
            self._log(f"  [DataService] sina daily 失败: {code} ({e})")
            return pd.DataFrame(columns=cols)

    # ------------------------------------------------------------------ #
    # 代码表 / 股票池
    # ------------------------------------------------------------------ #
    def info_a_code_name(self):
        """全 A 代码表 stock_info_a_code_name()。"""
        ak = self.ak
        return ak.stock_info_a_code_name()

    def info_sh_name_code(self):
        ak = self.ak
        return ak.stock_info_sh_name_code()

    def info_sz_name_code(self):
        ak = self.ak
        return ak.stock_info_sz_name_code()

    def universe_sina(self):
        """用新浪沪/深代码表重建股票池（东财受限时的回退）。

        返回 DataFrame(代码, 名称)（仅主选板块前缀）。
        """
        parts = []
        try:
            sh = self.info_sh_name_code()[["证券代码", "证券简称"]].rename(
                columns={"证券代码": "代码", "证券简称": "名称"})
            parts.append(sh)
        except Exception as e:
            self._log(f"  [warn] sh_name_code 失败: {e}")
        try:
            sz = self.info_sz_name_code()[["A股代码", "A股简称"]].rename(
                columns={"A股代码": "代码", "A股简称": "名称"})
            parts.append(sz)
        except Exception as e:
            self._log(f"  [warn] sz_name_code 失败: {e}")
        if not parts:
            return pd.DataFrame(columns=["代码", "名称"])
        df = pd.concat(parts, ignore_index=True)
        df["代码"] = df["代码"].astype(str).str.zfill(6)
        return df

    # ------------------------------------------------------------------ #
    # 扩展：热点板块 / 资金流 / 批量报价（供 FastAPI 实时接口使用）
    # ------------------------------------------------------------------ #
    def hot_sectors(self, top: int = 20):
        """热点行业板块排行（东方财富）。返回按涨跌幅降序的列表。

        字段：板块名称/涨跌幅/总市值/换手率/领涨股/领涨股-涨跌幅。
        """
        ak = self.ak
        try:
            df = ak.stock_board_industry_name_em()
            want = ["板块名称", "涨跌幅", "总市值", "换手率", "领涨股", "领涨股-涨跌幅"]
            have = [c for c in want if c in df.columns]
            df = df[have].copy()
            for c in df.columns:
                if c != "板块名称":
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.sort_values("涨跌幅", ascending=False).head(top)
            return df.to_dict(orient="records")
        except Exception as e:
            self._log(f"  [DataService] hot_sectors 失败: {e}")
            raise DataServiceError(str(e))

    def fund_flow(self, code: str):
        """个股资金流（东方财富）。返回最近若干交易日的主力净流入等。"""
        ak = self.ak
        try:
            market = "sh" if str(code).startswith(("60", "68", "90", "88")) else "sz"
            df = ak.stock_individual_fund_flow(stock=str(code), market=market)
            if df is None or len(df) == 0:
                return []
            cols = [c for c in ("日期", "主力净流入-净额", "主力净流入-净占比",
                                "超大单净流入-净额", "大单净流入-净额",
                                "收盘价") if c in df.columns]
            df = df[cols].copy()
            df = df.tail(10)
            return df.to_dict(orient="records")
        except Exception as e:
            self._log(f"  [DataService] fund_flow 失败: {code} ({e})")
            raise DataServiceError(str(e))

    def spot_quote(self, codes):
        """批量实时报价：从全 A 实时行情中筛选给定代码。

        codes: iterable of 6 位代码字符串。
        返回 {code: {最新价, 涨跌幅, 成交量, 成交额, 量比}}。
        失败时抛出 DataServiceError（由调用方决定降级）。
        """
        codes = [str(c).zfill(6) for c in codes]
        # 优先东财（含量比），失败用新浪
        try:
            df = self.a_spot_em()
        except Exception:
            df = self.a_spot()
        key = "代码"
        if key not in df.columns:
            key = df.columns[0]
        df["__code"] = df[key].astype(str).str.zfill(6)
        sub = df[df["__code"].isin(codes)]
        out = {}
        pct_c = "涨跌幅" if "涨跌幅" in sub.columns else (sub.columns[3] if len(sub.columns) > 3 else None)
        price_c = "最新价" if "最新价" in sub.columns else "收盘价"
        vol_c = "成交量" if "成交量" in sub.columns else None
        amt_c = "成交额" if "成交额" in sub.columns else None
        vr_c = "量比" if "量比" in sub.columns else None
        for _, r in sub.iterrows():
            code = str(r["__code"])
            out[code] = {
                "最新价": _num(r.get(price_c)),
                "涨跌幅": _num(r.get(pct_c)),
                "成交量": _num(r.get(vol_c)),
                "成交额": _num(r.get(amt_c)),
                "量比": _num(r.get(vr_c)),
            }
        return out


def _num(v):
    try:
        f = float(v)
        return f if f == f else None  # NaN -> None
    except (TypeError, ValueError):
        return None


# 模块级单例：整个进程共享同一缓存与数据源偏好
data_service = DataService()
