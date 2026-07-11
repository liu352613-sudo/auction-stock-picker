#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""站点构建编排：一键生成前端所需的全部静态数据。

生产数据流（Python 仅在本机/CI 运行，EdgeOne 只托管静态产物）：
  1) generate_results.py  → data/results.json + data/klines/*.json + data/history/YYYY-MM-DD.json(快照)
  2) compute_stats.py     → data/stats.json（收益统计/推荐活跃度/调参摘要）
  可选：auto_tune.py       → 重算最优参数（写入 data/params.json），通常按周/按月运行

用法：
  python build_site.py                # 真实数据
  python build_site.py --demo         # 内置样例（无网验证 / 首次部署种子数据）
  python build_site.py --with-tune    # 真实数据 + 先跑自动调参（较慢，需联网且数据源可达）
  python build_site.py --with-tune --limit 120 --start 2026-01-01 --end 2026-07-10
"""
import argparse
import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(script, extra):
    cmd = [PY, os.path.join(ROOT, script)] + extra
    print("\n>>> " + " ".join(cmd))
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser(description="竞价选股站点数据构建")
    ap.add_argument("--demo", action="store_true", help="内置样例数据")
    ap.add_argument("--with-tune", action="store_true", help="先运行自动调参")
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-07-10")
    args = ap.parse_args()

    if args.with_tune:
        tune_extra = ["--limit", str(args.limit), "--start", args.start, "--end", args.end]
        if args.demo:
            tune_extra.append("--demo")
        rc = run("auto_tune.py", tune_extra)
        if rc != 0:
            print("[warn] auto_tune 返回非零，将沿用现有 data/params.json 继续。")

    gen_extra = ["--demo"] if args.demo else []
    if run("generate_results.py", gen_extra) != 0:
        print("[error] generate_results.py 失败"); sys.exit(1)

    if run("compute_stats.py", []) != 0:
        print("[error] compute_stats.py 失败"); sys.exit(1)

    print("\n✅ 站点数据已生成：data/results.json, data/klines/, data/history/, data/stats.json")
    print("   部署：将本仓库推送到 EdgeOne Pages（edgeone.json 已配置为静态站）。")


if __name__ == "__main__":
    main()
