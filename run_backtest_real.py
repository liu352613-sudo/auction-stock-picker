"""真实历史回测运行器：强制全部数据走可用的新浪端点，复用 skill 的竞价策略逻辑。

背景：当前沙箱网络下东财 stock_zh_a_hist / stock_info_a_code_name 被断流，
但新浪 stock_zh_a_daily / stock_info_sh_name_code / stock_info_sz_name_code 完全可用。
本脚本通过 monkeypatch 让 skill 回测模块只走新浪，从而对真实历史数据跑回测。

用法:
  python run_backtest_real.py --limit 150 --start 2024-01-01 --end 2024-12-31
  python run_backtest_real.py --limit 10     # 快速验证
"""
import argparse, importlib.util, sys, os
import pandas as pd
import akshare as ak

SKILL_SCRIPT = r"C:\Users\PC\.workbuddy\skills\auction-stock-picker-akshare\scripts\auction_picker_akshare.py"

# ---- 1) 加载 skill 脚本为模块 ----
spec = importlib.util.spec_from_file_location("auction_skill", SKILL_SCRIPT)
skill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill)

# ---- 2) 强制东财 hist 直接抛错 -> skill 内置新浪回退立即生效（避免东财挂起）----
def _em_hist_raise(*a, **k):
    raise RuntimeError("eastmoney blocked in sandbox -> force sina fallback")
ak.stock_zh_a_hist = _em_hist_raise

# ---- 3) 用新浪代码表替换股票池（原 get_backtest_universe 只用东财，无回退）----
def get_backtest_universe_sina(scope="all"):
    parts = []
    try:
        sh = ak.stock_info_sh_name_code()[["证券代码", "证券简称"]].rename(
            columns={"证券代码": "代码", "证券简称": "名称"})
        parts.append(sh)
    except Exception as e:
        print("  [warn] sh_name_code 失败:", e)
    try:
        sz = ak.stock_info_sz_name_code()[["A股代码", "A股简称"]].rename(
            columns={"A股代码": "代码", "A股简称": "名称"})
        parts.append(sz)
    except Exception as e:
        print("  [warn] sz_name_code 失败:", e)
    if not parts:
        return pd.DataFrame(columns=["代码", "名称"])
    df = pd.concat(parts, ignore_index=True)
    df["代码"] = df["代码"].astype(str).str.zfill(6)
    df = df[df["代码"].str.startswith(skill.BOARD_PREFIX)].copy()
    df = df.drop_duplicates("代码").reset_index(drop=True)
    # 随机抽样，使 --limit 截断后是跨市场代表性样本（而非仅沪市大盘）
    return df.sample(frac=1, random_state=20260711).reset_index(drop=True)

skill.get_backtest_universe = get_backtest_universe_sina

# ---- 4) 大盘温度序列也走新浪（stock_zh_index_daily 本就是新浪源）----
#  skill.get_daily_market_pct 已用 stock_zh_index_daily，无需改。

# ---- 5) 运行回测 ----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="./auction_reports")
    ap.add_argument("--scope", default="all")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--limit", type=int, default=150)
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    print(f"[runner] 真实回测 窗口={args.start}~{args.end} 抽样limit={args.limit} 数据源=新浪")
    skill.run_backtest(
        output_dir=args.output_dir,
        scope=args.scope,
        start=args.start,
        end=args.end,
        limit=args.limit,
        demo=False,
    )

if __name__ == "__main__":
    main()
