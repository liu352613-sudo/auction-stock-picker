"""真实历史回测运行器：强制全部数据走可用的新浪端点，复用本项目的竞价策略逻辑。

背景：当前沙箱/受限网络下东财 stock_zh_a_hist / stock_info_a_code_name 被断流，
但新浪 stock_zh_a_daily / stock_info_sh_name_code / stock_info_sz_name_code 通常可用。
本脚本通过统一 DataService 的 force_sina() 让回测模块只走新浪，从而对真实历史数据跑回测。
所有 AkShare 访问均经 src/data_service.DataService，本文件不再直接 import akshare。

用法:
  python run_backtest_real.py --limit 150 --start 2024-01-01 --end 2024-12-31
  python run_backtest_real.py --limit 10     # 快速验证
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from src import stock_picker as sp
from src.data_service import data_service


def main():
    ap = argparse.ArgumentParser(description="竞价策略真实历史回测（新浪数据源）")
    ap.add_argument("--output-dir", default="./auction_reports")
    ap.add_argument("--scope", default="all")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--limit", type=int, default=150)
    args = ap.parse_args()

    # 经统一 DataService 强制新浪：stock_hist 走新浪，universe 用新浪代码表
    data_service.force_sina(True)

    os.makedirs(args.output_dir, exist_ok=True)
    print(f"[runner] 真实回测 窗口={args.start}~{args.end} 抽样limit={args.limit} 数据源=新浪")
    sp.run_backtest(
        output_dir=args.output_dir,
        scope=args.scope,
        start=args.start,
        end=args.end,
        limit=args.limit,
        demo=False,
    )


if __name__ == "__main__":
    main()
