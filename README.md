# 竞价选股 · A 股集合竞价量化策略

基于集合竞价量价特征的 A 股量化选股系统，采用**「静态数据 + 实时 API」双模式架构**：

- **静态层**：Python 脚本在**本机 / CI** 每日 09:26 预生成 JSON，EdgeOne Pages 托管，前端**秒开**。
- **实时层**：FastAPI 后端经统一 `DataService` 拉取盘中行情/板块/资金流，前端**静态优先加载、再每 20s 经 `/api` 实时刷新**。
- **统一数据服务**：所有 AkShare 调用集中封装于 `src/data_service.py`，页面与策略**不再直接调用 AkShare**。

> ⚠️ 数据来源于公开行情，仅供研究学习，不构成任何投资建议。

---

## 功能

| 模块 | 说明 |
| --- | --- |
| 精选选股 | 大盘温度仪表盘 + 指数 + 今日 Top3 + 全部候选；**实时刷新**指数/报价/热点板块 |
| 股票详情 | 个股关键指标、动能评分四维明细、Canvas K 线图（红涨绿跌）+ **实时报价/主力资金流** |
| 历史推荐 | 每日快照存档（`data/history/YYYY-MM-DD.json`），可回看任意一期候选 |
| 收益统计 | 回测绩效（胜率/累计收益/月度分解）、推荐活跃度、评分与温度分布、高频个股 |
| 参数配置 | 26 项策略参数可视化编辑（本地保存 / 导出 JSON / 经 `/api/config` 保存） |
| 策略优化 | 网格搜索灵敏度表 + 目标函数对比，自动选出最优参数组合 |
| 自动调参 | `auto_tune.py` 网格搜索，以「收益×胜率×样本量 − 风险惩罚」为目标选出最优参数 |
| 实时 API | FastAPI 7 端点（市场/推荐/历史/回测/板块/个股/配置）+ 预留扩展（AI/多策略/推送/交易） |
| 性能优化 | 预生成静态 JSON、前端 fetch 缓存、图表按需 rAF、单资源单请求、实时降级不报错 |

---

## 架构

详见 **[系统架构图](docs/architecture.svg)** 与 **[API 文档](docs/API.md)**。

```
                 AkShare（东财/新浪）
                        │
                  DataService  ◀── 全项目唯一 import akshare（缓存/回退/重试）
                        │
          ┌─────────────┴──────────────┐
   生成管线（本机/CI）               FastAPI 实时 API
   generate_results/auto_tune/        /api/market /recommend
   run_backtest/snapshot/compute      /history /backtest /hot-sector
          │ 预生成静态 JSON            /stock/{code} /config
          ▼                            + 预留: strategies/analysis/push/trade
   data/*.json  ──▶  EdgeOne 静态站  ──┐        │
   (每日 09:26)      index.html        │ 静态优先│ 每20s 实时刷新
                          │            │ 加载    │ (行情/报价/板块/资金流)
                          ▼            ▼        ▼
                       前端 SPA（双模式；API 不可达时自动降级为静态并标注状态）
```

数据契约（静态 JSON）：
- `data/results.json` — 当日选股（温度/指数/候选/参数版本）
- `data/klines/{code}.json` — 个股 K 线 `{bars:[{d,o,c,h,l,v}]}`
- `data/history_index.json` + `data/history/YYYY-MM-DD.json` — 历史推荐
- `data/stats.json` — 收益统计聚合
- `data/params.json` — 当前生效策略参数（default / best）
- `data/param_tuning.json` — 调参网格结果

---

## 本地运行

```bash
# 安装依赖（akshare / fastapi 等）
pip install -r requirements.txt

# 一键构建全部静态数据（真实行情）
python build_site.py
# 或内置样例（无需联网，用于验证/首次部署种子）
python build_site.py --demo
# 附带自动调参（较慢，需数据源可达）
python build_site.py --with-tune --limit 120 --start 2026-01-01 --end 2026-07-10
```

**启动实时后端（双模式联调）**——单进程同时托管 API 与前端：

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
# 访问 http://localhost:8000/  （前端经同源 /api 自动实时刷新）
# API 文档：http://localhost:8000/docs
```

分步运行也支持：

```bash
python generate_results.py [--demo]     # 选股 + K线 + 当日快照
python generate_snapshot.py [--date D]  # 手动补存档某日推荐
python compute_stats.py                 # 聚合收益统计
python auto_tune.py [--demo|--quick]    # 自动调参
python run_backtest_real.py             # 生成回测报告（stats 视图依赖）
```

> 仅前端预览（纯静态，无实时 API）：`python -m http.server 8080`，访问 `http://localhost:8080/`，页面自动以「仅静态数据」模式运行。

---

## 部署

### EdgeOne Pages（静态前端）
仓库含 `edgeone.json`（静态站，构建命令为空 `echo`）。推送后 EdgeOne 识别为 `static`，产物目录为仓库根 `.`，站点直接生效。
> 每日自动更新：CI 定时执行 `python build_site.py` 并推送 `data/`。

### FastAPI 实时后端（可选，独立部署）
```bash
pip install -r api/requirements.txt
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```
前端跨域调用时，在 `index.html` 前设置 `window.API_BASE = "https://your-api-domain"`；同源部署（如上）则无需配置。API 不可达时前端自动降级为纯静态。

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
├── index.html                # SPA 入口（双模式：静态优先 + /api 实时刷新）
├── assets/
│   ├── css/style.css         # 深蓝金融主题（涨红跌绿）+ 实时指示灯
│   └── js/{util,charts,app}.js   # util 含 API 层(fetchAPI/setLive)
├── src/
│   ├── stock_picker.py       # 核心策略引擎（经 DataService 取数）
│   └── data_service.py       # 统一数据服务层（唯一 import akshare）
├── api/                      # FastAPI 实时后端
│   ├── main.py               # 应用入口（CORS + 静态托管 + 路由）
│   ├── loaders.py            # 静态 JSON 加载
│   ├── routers/core.py       # 7 个核心端点
│   ├── routers/extensions.py # 预留扩展（AI/多策略/推送/交易）
│   └── requirements.txt
├── auto_tune.py              # 自动调参（经 DataService 强制新浪）
├── generate_results.py       # 选股 + K线 + 快照生成（经 DataService）
├── generate_snapshot.py      # 历史推荐快照
├── compute_stats.py          # 收益统计聚合
├── build_site.py             # 一键构建编排
├── run_backtest_real.py      # 回测报告生成（经 DataService）
├── docs/                     # architecture.svg + API.md
├── data/                     # 预生成 JSON（站点数据源）
├── auction_reports/          # 回测 / 调参报告（md + json）
└── edgeone.json              # 静态站部署配置
```

---

*数据仅供参考，投资有风险，决策需谨慎。*
