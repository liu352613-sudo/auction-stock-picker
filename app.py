#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竞价选股系统 Web 界面（Streamlit）。

运行: streamlit run app.py
数据源: AkShare（新浪财经实时行情）集合竞价（约 09:26）数据。
"""

import sys
from pathlib import Path

import streamlit as st

# 将项目根目录加入导入路径，便于 `from src.stock_picker import ...`
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.stock_picker import AuctionStockPicker  # noqa: E402

st.set_page_config(page_title="竞价选股系统", layout="wide")
st.title("📈 每日竞价选股推荐")
st.info("👆 点击下方「运行选股」按钮获取今日推荐")

st.caption("基于 AkShare（新浪财经实时行情）集合竞价数据的 A 股竞价选股器 · 每日 09:26 口径")

if "fetch_failed" not in st.session_state:
    st.session_state.fetch_failed = False
if "ran" not in st.session_state:
    st.session_state.ran = False


def render_result(result):
    """渲染选股结果：市场温度 / Top3 / 全部初筛列表 / 数据来源与风险提示。"""
    temp = result["temperature"]
    stocks = result["stocks"]

    st.header("🌡️ 市场温度")
    t1, t2, t3 = st.columns(3)
    t1.metric("综合温度（分数）", f"{temp.get('total', 0):.1f}")
    t2.metric("温度等级", temp.get("level", "未知"))
    t3.metric("建议仓位", f"{temp.get('position', 0)}%")

    st.header("📊 Top 3 精选股票")
    if len(stocks) > 0:
        top3 = stocks.head(3)
        for i, (_, r) in enumerate(top3.iterrows(), 1):
            open_price = float(r["买入价"])
            tp = round(open_price * 1.05, 2)
            sl = round(open_price * 0.97, 2)
            with st.container():
                st.subheader(f"{i}. {r['代码']} · {r['名称']}")
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric("开盘价", f"{open_price:.2f}")
                c2.metric("止盈价 (+5%)", f"{tp:.2f}")
                c3.metric("止损价 (-3%)", f"{sl:.2f}")
                c4.metric("动能评分", f"{r['动能评分']:.2f}")
                c5.metric("量比", f"{r['量比']:.2f}")
                c6.metric("买入程度", r.get("买入程度", "-"))
    else:
        st.info("今日暂无符合初筛条件的个股。")

    st.header("📋 全部初筛股票列表")
    with st.expander(f"展开查看全部 {len(stocks)} 只初筛股票", expanded=False):
        if len(stocks) > 0:
            disp = stocks[["代码", "名称", "买入价", "动能评分", "量比", "开盘涨幅%"]].copy()
            disp = disp.rename(columns={
                "买入价": "开盘价",
                "动能评分": "评分",
                "开盘涨幅%": "涨幅%",
            })
            st.dataframe(disp, use_container_width=True, hide_index=True)
        else:
            st.write("无")

    st.divider()
    st.caption(f"数据来源：{result['data_source']} ｜ 生成时间：{result['generated_at']}")
    st.warning(
        "⚠️ 风险提示：以上推荐仅基于竞价数据筛选，不构成任何投资建议。"
        "市场有风险，投资需谨慎，请结合市场环境与个人风险承受能力审慎决策。"
    )


def run_selection():
    """执行一次选股并渲染结果；数据获取失败或结果为空时显示警告 + 重试按钮，不停止页面。"""
    import akshare as ak
    import datetime as _dt

    # ---------- 交易日判断 ----------
    today = _dt.date.today()
    is_trade_day = True
    try:
        cal = ak.tool_trade_date_hist_sina()
        col = "trade_date" if "trade_date" in cal.columns else cal.columns[0]
        trade_dates = [str(d)[:10] for d in cal[col].tolist()]
        is_trade_day = today.strftime("%Y-%m-%d") in trade_dates
    except Exception:
        pass

    if not is_trade_day:
        st.warning("今日非交易日，无竞价数据")
        st.session_state.ran = True
        return

    # ---------- 选股（底层已带网络重试）----------
    with st.spinner("正在获取集合竞价数据并计算，请稍候…"):
        picker = AuctionStockPicker()
        try:
            result = picker.pick_stocks(demo=False)
        except Exception as e:
            st.session_state.fetch_failed = True
            st.error(f"数据获取失败：{e}")
            st.warning("无法获取实时数据，请检查网络或稍后重试")
            return

    # 结果为空（未取到任何股票）也视为数据获取失败
    if result is None or result.get("stocks") is None or len(result.get("stocks", [])) == 0:
        st.session_state.fetch_failed = True
        st.warning("无法获取实时数据，请检查网络或稍后重试")
        return

    st.session_state.fetch_failed = False
    st.session_state.ran = True
    render_result(result)


if st.button("运行选股", type="primary", use_container_width=False):
    run_selection()

# 数据获取失败时：显示提示并提供「重试」按钮（重新执行选股逻辑，页面不停止）
if st.session_state.fetch_failed:
    st.warning("无法获取实时数据，请检查网络或稍后重试")
    if st.button("🔄 重试"):
        run_selection()
elif not st.session_state.ran:
    st.info("点击上方「运行选股」按钮开始筛选。")
