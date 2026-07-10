#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竞价选股系统 Web 界面（Streamlit）。

运行: streamlit run app.py
数据源: AkShare 集合竞价（约 09:26）数据。
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
st.title("竞价选股系统")

st.caption("基于 AkShare 集合竞价数据的 A 股竞价选股器 · 每日 09:26 口径")

if st.button("运行选股", type="primary", use_container_width=False):
    with st.spinner("正在获取集合竞价数据并计算，请稍候…"):
        picker = AuctionStockPicker()
        # 真实数据走 AkShare；如需离线演示可改为 picker.pick_stocks(demo=True)
        result = picker.pick_stocks(demo=False)

    temp = result["temperature"]
    stocks = result["stocks"]

    # ---------- 市场温度 ----------
    st.header("🌡️ 市场温度")
    t1, t2, t3 = st.columns(3)
    t1.metric("综合温度（分数）", f"{temp.get('total', 0):.1f}")
    t2.metric("温度等级", temp.get("level", "未知"))
    t3.metric("建议仓位", f"{temp.get('position', 0)}%")

    # ---------- Top3 精选 ----------
    st.header("📊 Top 3 精选股票")
    if len(stocks) > 0:
        top3 = stocks.head(3)
        for i, (_, r) in enumerate(top3.iterrows(), 1):
            open_price = float(r["买入价"])
            tp = round(open_price * 1.05, 2)   # 止盈价 = 开盘价 * 1.05
            sl = round(open_price * 0.97, 2)   # 止损价 = 开盘价 * 0.97
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

    # ---------- 全部初筛列表 ----------
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

    # ---------- 底部信息 ----------
    st.divider()
    st.caption(f"数据来源：{result['data_source']} ｜ 生成时间：{result['generated_at']}")
    st.warning(
        "⚠️ 风险提示：以上推荐仅基于竞价数据筛选，不构成任何投资建议。"
        "市场有风险，投资需谨慎，请结合市场环境与个人风险承受能力审慎决策。"
    )
else:
    st.info("点击上方「运行选股」按钮开始筛选。")
