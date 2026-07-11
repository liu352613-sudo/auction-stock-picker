# 竞价选股系统 · 实时 API 文档

后端：`api/`（FastAPI）。所有行情经统一 `DataService` 封装，禁止直接调用 AkShare。
启动：`python -m uvicorn api.main:app --host 0.0.0.0 --port 8000`（同源托管前端+API）。
CORS 已全开，可独立部署后由 EdgeOne 静态站跨域调用（设 `window.API_BASE`）。

> 设计原则：**静态优先，实时补充**。所有端点先返回预生成的静态 `data/*.json`（秒开/离线可用）；
> 实时部分（指数/盘中报价/板块/资金流）经 DataService 拉取，失败时自动降级为静态并标注 `live=false`。

---

## 1. 核心端点

### GET `/api/health`
健康检查。
```json
{ "status": "ok", "service": "auction-stock-picker-api", "time": "2026-07-11 15:14:48" }
```

### GET `/api/market`
实时指数行情。优先东财 `stock_zh_index_spot_em`，失败回退新浪 `stock_zh_index_spot_sina`；不可达时返回静态 `indices` 并 `live=false`。
```json
{
  "indices": [ { "name": "上证指数", "code": "sh000001", "val": 3996.16, "diff": -40.43, "pct": "-1.00%" } ],
  "live": true, "source": "akshare", "updated_at": "2026-07-11 15:15:00"
}
```

### GET `/api/recommend`
今日推荐。返回静态选股结果 `data/results.json`，并附带实时盘中报价。
```json
{
  "count": 6,
  "temperature": { "total": 78.0, "level": "温暖", "position": 60 },
  "stocks": [ { "代码": "000001", "名称": "平安银行", "现价": 12.34, "涨跌幅": 1.23, "评分": 94.5, "买入程度": "强烈推荐", ... } ],
  "live": { "by_code": { "000001": { "最新价": 12.40, "涨跌幅": 1.50, "成交量": 1234567, "成交额": 1.5e8, "量比": 3.1 } } },
  "live_flag": true, "updated_at": "2026-07-11 15:15:00"
}
```
前端据此定点刷新候选列表的现价/涨跌幅（每 20s）。

### GET `/api/history`
历史推荐索引；`?date=YYYY-MM-DD` 返回该期快照。
- `GET /api/history?limit=60` → `{ "count": 1, "items": [ { "date":"2026-07-11", "count":6, "temperature":78.0, "level":"温暖", "avg_score":94.5, "top1":"平安银行", "top1_code":"000001", ... } ] }`
- `GET /api/history?date=2026-07-11` → `{ "date":"2026-07-11", "snapshot": { ...当日完整存档... } }`（404 若不存在）

### GET `/api/backtest`
回测统计（来自 `data/stats.json`）。
```json
{ "stats": { "generated_at": "...", "backtest": { "primary": { "period":"2026-01-01 ~ 2026-07-10", "stats": { "胜率%":52.0, "累计收益%(复利)":20.63, ... }, "monthly":[...] }, "recommendation": {...}, "tuning": {...} } } }
```

### GET `/api/hot-sector?top=20`
热点行业板块排行（实时，东方财富）。不可达时 `sectors:[]`、`live=false`。
```json
{ "sectors": [ { "板块名称":"半导体", "涨跌幅":3.2, "领涨股":"中芯国际", "主力净流入-净额": 1.2e8 } ], "live": true, "source":"akshare" }
```

### GET `/api/stock/{code}`
股票详情：静态信息 + K线 + 实时报价 + 资金流。
```json
{
  "code": "000001",
  "info": { "代码":"000001", "名称":"平安银行", "现价":12.34, "涨跌幅":1.23, "评分":94.5, "板块":"银行", "市值":..., "涨停价":..., "评分明细":{...} },
  "kline": { "code":"000001", "name":"平安银行", "bars":[ { "d":"2026-07-10", "o":12.1, "c":12.34, "h":12.4, "l":12.05, "v":1234567 } ] },
  "live": { "最新价":12.40, "涨跌幅":1.50, "成交量":..., "成交额":..., "量比":3.1 },
  "fund_flow": [ { "日期":"2026-07-10", "主力净流入-净额":1.2e8, "主力净流入-净占比":5.3 } ],
  "live_flag": true
}
```
`{code}` 自动 `zfill(6)`；404 当静态与 K线均无该股票。

### GET `/api/config`
当前策略参数（来自 `data/params.json`：`default` / `best` / `best_stats` / `tuned_at`）。

### POST `/api/config`
保存用户策略参数到 `data/user_params.json`（不覆盖自动调参 `best`）。
请求体：`{ "params": { "vol_ratio_min": 4.0 } }`
- 经 `StrategyParams` 校验字段/类型，仅保留已知字段并与默认合并；
- 返回完整合并后参数；应用需重新运行 `build_site.py --with-tune` 生效。
- 校验失败返回 `400`。

---

## 2. 预留扩展接口（模块化，已返回 reserved 结构）

| 端点 | 用途 | 状态 |
|------|------|------|
| `GET /api/strategies` | 多策略引擎：列出已注册策略（当前 `auction_default`） | `ok` |
| `GET /api/analysis/{code}` | AI 分析：个股智能解读/风险提示/舆情 | `reserved` |
| `POST /api/signals/push` | 消息推送：推荐/预警推送到微信/邮件/Webhook | `reserved` |
| `POST /api/trade` | 实盘交易：下单/撤单（需券商账户与风控授权） | `reserved` |

新增能力只需在 `api/routers/` 内追加路由，前端按统一 `status` 字段对接。

---

## 3. 数据契约（静态 JSON）
| 文件 | 用途 |
|------|------|
| `data/results.json` | 今日选股（温度/候选/Top3/指数/参数版本） |
| `data/stats.json` | 回测绩效/推荐活跃度/调参摘要 |
| `data/history_index.json` | 历史推荐索引（降序） |
| `data/history/YYYY-MM-DD.json` | 每日推荐快照 |
| `data/klines/{code}.json` | 个股 K 线（供详情页） |
| `data/params.json` | 策略参数（default/best） |
| `data/param_tuning.json` | 自动调参灵敏度表 |

---

## 4. 错误与降级
- 实时接口异常 → 返回静态兜底 + `live=false` + `note`，HTTP 仍 `200`（前端不报错）。
- 静态文件缺失 → `404` + 说明。
- `POST /api/config` 参数非法 → `400`。
