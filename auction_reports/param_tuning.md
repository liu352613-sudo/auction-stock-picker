# 竞价选股策略 自动调参报告

> 区间 **2026-01-01 ~ 2026-07-10** ｜ 抽样 **120** 只 ｜ demo=False ｜ 组合 12

## 目标函数排名 (综合: 累计收益×胜率×样本量 − 风险惩罚)

| 排名 | 参数组合 | 胜率% | 累计(复利)% | 交易次数 | 目标函数 |
|------|------|------|------|------|------|
| 1 | vol_ratio_min=3.5 auction_amount_min=3000000 threshold_hi_base=8.0 w_vol_ratio=30.0 | 60.0 | -1.28 | 5 | -0.0133 |
| 2 | vol_ratio_min=3.5 auction_amount_min=5000000 threshold_hi_base=8.0 w_vol_ratio=30.0 | 60.0 | -1.28 | 5 | -0.0133 |
| 3 | vol_ratio_min=2.5 auction_amount_min=3000000 threshold_hi_base=6.0 w_vol_ratio=30.0 | 40.0 | -22.94 | 10 | -0.1163 |
| 4 | vol_ratio_min=3.0 auction_amount_min=3000000 threshold_hi_base=6.0 w_vol_ratio=30.0 | 55.56 | -19.53 | 9 | -0.1336 |
| 5 | vol_ratio_min=3.0 auction_amount_min=5000000 threshold_hi_base=6.0 w_vol_ratio=30.0 | 55.56 | -19.53 | 9 | -0.1336 |
| 6 | vol_ratio_min=2.5 auction_amount_min=3000000 threshold_hi_base=8.0 w_vol_ratio=30.0 | 33.33 | -33.13 | 12 | -0.139 |
| 7 | vol_ratio_min=3.0 auction_amount_min=3000000 threshold_hi_base=8.0 w_vol_ratio=30.0 | 50.0 | -23.73 | 10 | -0.1458 |
| 8 | vol_ratio_min=3.0 auction_amount_min=5000000 threshold_hi_base=8.0 w_vol_ratio=30.0 | 50.0 | -23.73 | 10 | -0.1458 |
| 9 | vol_ratio_min=2.5 auction_amount_min=5000000 threshold_hi_base=6.0 w_vol_ratio=30.0 | 41.67 | -28.39 | 12 | -0.1478 |
| 10 | vol_ratio_min=2.5 auction_amount_min=5000000 threshold_hi_base=8.0 w_vol_ratio=30.0 | 38.46 | -32.13 | 13 | -0.155 |
| 11 | vol_ratio_min=3.5 auction_amount_min=3000000 threshold_hi_base=6.0 w_vol_ratio=30.0 | 75.0 | 4.16 | 4 | -995.0 |
| 12 | vol_ratio_min=3.5 auction_amount_min=5000000 threshold_hi_base=6.0 w_vol_ratio=30.0 | 75.0 | 4.16 | 4 | -995.0 |

## 最优参数

```json
{
  "vol_ratio_min": 3.5,
  "auction_amount_min": 3000000,
  "new_stock_days": 60,
  "threshold_lo_base": 2.0,
  "threshold_hi_base": 8.0,
  "threshold_lo_offset": 1.5,
  "threshold_hi_offset": 6.0,
  "take_profit": 0.05,
  "stop_loss": 0.03,
  "sector_bonus": 5.0,
  "w_vol_ratio": 30.0,
  "w_rel_market": 20.0,
  "w_ma60_dev": 25.0,
  "w_vol_energy": 25.0,
  "vol_ratio_top": 5.0,
  "ma60_dev_sweet": 0.05,
  "ma60_dev_max": 0.15,
  "vol_energy_lo": 0.03,
  "vol_energy_hi": 0.1,
  "filter_st": true,
  "filter_new_stock": true,
  "filter_suspended": true,
  "filter_limit_up": true,
  "level_strong": 80.0,
  "level_mid": 60.0,
  "level_cautious": 40.0
}
```


> 以上为历史数据统计，不构成投资建议；样本有限，注意过拟合。
