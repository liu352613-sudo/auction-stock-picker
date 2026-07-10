#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竞价选股系统 Flask 入口（适配 EdgeOne Pages 部署）。

运行: python app_flask.py
复用 src/stock_picker.AuctionStockPicker 进行选股，并以 JSON 形式通过 /run 暴露结果。

路由:
  GET /       -> 简单 HTML 页面（含「运行选股」按钮，AJAX 请求 /run）
  GET /run    -> JSON 选股结果（市场温度 / Top3 / 全部候选）；支持 ?demo=1 使用内置样例
"""

import json
import sys
import datetime as _dt
from pathlib import Path

import numpy as np
import pandas as pd
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

# 将项目根目录加入导入路径，便于 `from src.stock_picker import ...`
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.stock_picker import AuctionStockPicker  # noqa: E402

app = Flask(__name__)
CORS(app)  # 允许跨域请求（flask_cors）

INDEX_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>📈 每日竞价选股推荐</title>
  <style>
    body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
           max-width: 880px; margin: 0 auto; padding: 24px; color: #1f2329; background: #f7f8fa; }
    h1 { font-size: 24px; margin-bottom: 4px; }
    .sub { color: #8a8f99; font-size: 13px; margin-bottom: 20px; }
    button { font-size: 16px; padding: 10px 22px; border: none; border-radius: 8px;
             background: #3370ff; color: #fff; cursor: pointer; }
    button:disabled { background: #b7c4e0; cursor: not-allowed; }
    .status { margin: 16px 0; font-size: 14px; min-height: 20px; }
    .err { color: #d54941; }
    .ok { color: #2a9d5c; }
    .card { background: #fff; border: 1px solid #e6e8eb; border-radius: 10px;
            padding: 14px 16px; margin: 10px 0; }
    .temp { display: flex; gap: 12px; }
    .temp .box { flex: 1; background: #fff; border: 1px solid #e6e8eb; border-radius: 10px;
                 padding: 12px; text-align: center; }
    .temp .box b { display: block; font-size: 22px; margin-top: 4px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 6px; }
    th, td { border: 1px solid #e6e8eb; padding: 6px 8px; text-align: center; }
    th { background: #f0f3f8; }
    .warn { background: #fff7e6; border: 1px solid #ffe1a8; color: #a05a00;
            padding: 10px 12px; border-radius: 8px; font-size: 13px; margin-top: 14px; }
  </style>
</head>
<body>
  <h1>📈 每日竞价选股推荐</h1>
  <div class="sub">基于 AkShare 集合竞价数据的 A 股竞价选股器 · 每日 09:26 口径</div>

  <button id="runBtn" onclick="runSelection()">运行选股</button>
  <div class="status" id="status"></div>

  <div id="tempArea"></div>
  <div id="top3Area"></div>
  <div id="allArea"></div>

  <div class="warn">
    ⚠️ 风险提示：以上推荐仅基于竞价数据筛选，不构成任何投资建议。市场有风险，投资需谨慎。
  </div>

  <script>
    function escapeHtml(s) {
      return ('' + s).replace(/[&<>"']/g, c => (
        {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    function runSelection() {
      const btn = document.getElementById('runBtn');
      const status = document.getElementById('status');
      btn.disabled = true;
      status.className = 'status';
      status.textContent = '正在获取集合竞价数据并计算，请稍候…';
      document.getElementById('tempArea').innerHTML = '';
      document.getElementById('top3Area').innerHTML = '';
      document.getElementById('allArea').innerHTML = '';

      fetch('/run').then(r => r.json()).then(data => {
        if (!data.success) {
          status.className = 'status err';
          status.textContent = data.message || '无法获取实时数据，请检查网络或稍后重试';
          return;
        }
        status.className = 'status ok';
        status.textContent = '数据来源：' + (data.data_source || '') + ' ｜ 生成时间：' + (data.generated_at || '');
        renderTemperature(data.temperature);
        renderTop3(data.top3);
        renderAll(data.all);
      }).catch(err => {
        status.className = 'status err';
        status.textContent = '请求失败：' + err;
      }).finally(() => { btn.disabled = false; });
    }

    function renderTemperature(t) {
      if (!t) return;
      const total = (t.total != null) ? Number(t.total).toFixed(1) : '-';
      const level = t.level || '-';
      const pos = (t.position != null) ? t.position + '%' : '-';
      document.getElementById('tempArea').innerHTML =
        '<h3>🌡️ 市场温度</h3><div class="temp">' +
        '<div class="box">综合温度（分数）<b>' + total + '</b></div>' +
        '<div class="box">温度等级<b>' + escapeHtml(level) + '</b></div>' +
        '<div class="box">建议仓位<b>' + pos + '</b></div></div>';
    }

    function renderTop3(top3) {
      if (!top3 || !top3.length) { return; }
      let html = '<h3>📊 Top 3 精选股票</h3>';
      top3.forEach((r, i) => {
        const open = Number(r['买入价'] || 0).toFixed(2);
        const tp = (Number(r['买入价'] || 0) * 1.05).toFixed(2);
        const sl = (Number(r['买入价'] || 0) * 0.97).toFixed(2);
        html += '<div class="card"><b>' + (i + 1) + '. ' + escapeHtml(r['代码']) +
          ' · ' + escapeHtml(r['名称']) + '</b><br>' +
          '开盘价 ' + open + ' ｜ 止盈价(+5%) ' + tp + ' ｜ 止损价(-3%) ' + sl +
          ' ｜ 动能评分 ' + Number(r['动能评分'] || 0).toFixed(2) +
          ' ｜ 量比 ' + Number(r['量比'] || 0).toFixed(2) +
          ' ｜ 买入程度 ' + escapeHtml(r['买入程度'] || '-') + '</div>';
      });
      document.getElementById('top3Area').innerHTML = html;
    }

    function renderAll(all) {
      if (!all || !all.length) { return; }
      let html = '<h3>📋 全部初筛股票列表（' + all.length + ' 只）</h3><div class="card"><table><thead><tr>' +
        '<th>代码</th><th>名称</th><th>开盘价</th><th>评分</th><th>量比</th><th>涨幅%</th></tr></thead><tbody>';
      all.forEach(r => {
        html += '<tr><td>' + escapeHtml(r['代码']) + '</td><td>' + escapeHtml(r['名称']) +
          '</td><td>' + Number(r['买入价'] || 0).toFixed(2) +
          '</td><td>' + Number(r['动能评分'] || 0).toFixed(2) +
          '</td><td>' + Number(r['量比'] || 0).toFixed(2) +
          '</td><td>' + Number(r['开盘涨幅%'] || 0).toFixed(2) + '</td></tr>';
      });
      html += '</tbody></table></div>';
      document.getElementById('allArea').innerHTML = html;
    }
  </script>
</body>
</html>'''


def to_jsonable(obj):
    """递归将 numpy / pandas / datetime 类型转换为原生 Python 类型，确保可 JSON 序列化。"""
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (pd.Timestamp, _dt.datetime, _dt.date)):
        return str(obj)
    return obj


def df_to_records(df):
    """将 DataFrame 转为 JSON 友好的 records（NaN -> null，数值保持数值类型）。"""
    if df is None or len(df) == 0:
        return []
    return json.loads(df.to_json(orient="records", force_ascii=False, date_format="iso"))


def run_selection(demo=False):
    """执行一次选股，返回 (success: bool, payload: dict)。"""
    try:
        import akshare as ak

        # ---------- 交易日判断 ----------
        today = _dt.date.today()
        is_trade_day = True
        try:
            cal = ak.tool_trade_date_hist_sina()
            col = "trade_date" if "trade_date" in cal.columns else cal.columns[0]
            trade_dates = [str(d)[:10] for d in cal[col].tolist()]
            is_trade_day = today.strftime("%Y-%m-%d") in trade_dates
        except Exception:
            pass  # 日历接口异常时不误杀，按交易日继续

        if not is_trade_day:
            return False, {"message": "今日非交易日，无竞价数据"}

        # ---------- 选股（底层已带网络重试）----------
        picker = AuctionStockPicker()
        try:
            result = picker.pick_stocks(demo=demo)
        except Exception as e:
            return False, {"message": f"数据获取失败：{e}"}

        stocks = result.get("stocks")
        if stocks is None or len(stocks) == 0:
            return False, {"message": "无法获取实时数据，请检查网络或稍后重试"}

        all_recs = df_to_records(stocks)
        return True, {
            "temperature": to_jsonable(result.get("temperature", {})),
            "top3": all_recs[:3],
            "all": all_recs,
            "count": len(all_recs),
            "generated_at": result.get("generated_at"),
            "data_source": result.get("data_source"),
        }
    except Exception as e:
        return False, {"message": f"服务器内部错误：{e}"}


@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html; charset=utf-8")


@app.route("/run")
def run():
    # 支持 ?demo=1 使用内置样例数据（便于海外/无网络环境下验证页面与接口）
    demo = request.args.get("demo") in ("1", "true", "yes")
    success, payload = run_selection(demo=demo)
    return jsonify({"success": success, **payload})


if __name__ == "__main__":
    port = int(sys.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
