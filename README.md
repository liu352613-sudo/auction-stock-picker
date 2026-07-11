# 竞价选股 · A 股集合竞价量化策略

基于集合竞价量价特征的 A 股量化选股系统。前端为纯静态站点（EdgeOne Pages 托管），所有数据由 Python 脚本在**本机 / CI** 预生成 JSON，浏览器只负责渲染——无后端、无客户端重计算、首屏即数据。

> ⚠️ 数据来源于公开行情，仅供研究学习，不构成任何投资建议。

---

## 功能

| 模块 | 说明 |
| --- | --- |
| 精选选股 | 大盘温度仪表盘 + 实时指数 + 今日 Top3 + 全部候选（评分/建议/买卖点） |
| 股票详情 | 个股关键指标、动能评分四维明细、**Canvas K 线图**（红涨绿跌，含成交量） |
| 历史推荐 | 每日快照存档（`data/history/YYYY-MM-DD.json`），可回看任意一期候选 |
| 收益统计 | 回测绩效（胜率/累计收益/月度分解）、推荐活跃度、评分与温度分布、高频个股 |
| 参数配置 | 26 项策略参数可视化编辑（本地保存 / 导出 JSON） |
| 策略优化 | 网格搜索灵敏度表 + 目标函数对比，自动选出最优参数组合 |
| 自动调参 | `auto_tune.py` 网格搜索，以「收益×胜率×样本量 − 风险惩罚」为目标选出最优参数 |
| 性能优化 | 全程预生成静态 JSON、前端 fetch 缓存、图表按需 rAF 绘制、单资源单请求 |

---

## 架构

```
Python 生成层（本机/CI，不跑服务）          静态托管层（EdgeOne Pages）
┌──────────────────────────┐              ┌──────────────────────────┐
│ auto_tune.py   → params   │              │  index.html              │
│ generate_results.py       │  生成 JSON   │  assets/css/style.css    │
│   → results.json          │ ───────────▶ │  assets/js/{util,       │
│   → klines/*.json         │   提交仓库   │            charts,app}.js │
│   → history/YYYY-MM-DD    │              │  data/*.json  ◀── fetch  │
│ generate_snapshot.py      │              └──────────────────────────┘
│ compute_stats.py → stats  │
└──────────────────────────┘
```

浏览器读取的数据契约：
- `data/results.json` — 当日选股（温度/指数/候选/参数版本）
- `data/klines/{code}.json` — 个股 K 线 `{bars:[{d,o,c,h,l,v}]}`
- `data/history_index.json` + `data/history/YYYY-MM-DD.json` — 历史推荐
- `data/stats.json` — 收益统计聚合
- `data/params.json` — 当前生效策略参数（default / best）
- `data/param_tuning.json` — 调参网格结果

---

## 本地运行

```bash
# 安装依赖（akshare 等）
pip install -r requirements.txt

# 一键构建全部静态数据（真实行情）
python build_site.py
# 或内置样例（无需联网，用于验证/首次部署种子）
python build_site.py --demo
# 附带自动调参（较慢，需数据源可达）
python build_site.py --with-tune --limit 120 --start 2026-01-01 --end 2026-07-10
```

分步运行也支持：

```bash
python generate_results.py [--demo]     # 选股 + K线 + 当日快照
python generate_snapshot.py [--date D]  # 手动补存档某日推荐
python compute_stats.py                 # 聚合收益统计
python auto_tune.py [--demo|--quick]    # 自动调参
python run_backtest_real.py             # 生成回测报告（stats 视图依赖）
```

本地预览：用任意静态服务器根目录指向仓库根，例如 `python -m http.server 8080`，访问 `http://localhost:8080/`。

---

## 部署到 EdgeOne Pages

仓库已包含 `edgeone.json`（静态站，构建命令为空 `echo`，不安装 Python 依赖）。推送仓库后：
1. EdgeOne Pages 导入该仓库；
2. 框架识别为 `static`，产物目录为仓库根 `.`；
3. 由于 Python 生成的数据已随仓库提交，站点直接生效。

> 若需「每日自动更新」，在 CI（GitHub Actions / 云函数）中定时执行 `python build_site.py` 并推送 `data/` 即可；EdgeOne 重新构建即更新。

---

## 策略说明

初筛：集合竞价**量比 ≥ 阈值** + **开盘涨幅动态区间（随大盘温度浮动）** + **竞价成交额下限**，并按开关剔除 ST / 次新 / 停牌 / 涨停。
评分：量比、相对大盘、60 日均线偏离、量能比四维加权（权重可在参数配置中调整）。
退出：T+1 次日开盘卖出（回测与建议一致）。

参数通过 `StrategyParams` 集中管理，自动调参与前端配置共用同一套定义。

---

## 目录结构

```
auction-stock-picker/
├── index.html                # SPA 入口
├── assets/
│   ├── css/style.css         # 深蓝金融主题（涨红跌绿）
│   └── js/{util,charts,app}.js
├── src/stock_picker.py       # 核心策略引擎（参数化）
├── auto_tune.py              # 自动调参
├── generate_results.py       # 选股 + K线 + 快照生成
├── generate_snapshot.py      # 历史推荐快照
├── compute_stats.py          # 收益统计聚合
├── build_site.py             # 一键构建编排
├── run_backtest_real.py      # 回测报告生成
├── data/                     # 预生成 JSON（站点数据源）
├── auction_reports/          # 回测 / 调参报告（md + json）
└── edgeone.json              # 静态站部署配置
```

---

*数据仅供参考，投资有风险，决策需谨慎。*
