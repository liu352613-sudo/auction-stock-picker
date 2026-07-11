#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""历史推荐快照脚本。

把 data/results.json（当日选股结果）按日期写入 data/history/YYYY-MM-DD.json，
并为「历史推荐」系统维护 data/history_index.json（日期降序索引 + 每期摘要）。

可独立运行（每日定时/手动存档「当日推荐」）：
  python generate_snapshot.py                    # 以今日日期快照 data/results.json
  python generate_snapshot.py --date 2026-07-11 # 指定日期
  python generate_snapshot.py --source path      # 指定读取的 results 路径
  python generate_snapshot.py --force            # 覆盖已存在的同日快照

generate_results.py 在生成 results.json 后会自动调用本模块的 snapshot()，
因此每次跑 generate_results 都会同时存档当日推荐，无需额外步骤。
"""
import argparse
import datetime
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
HISTORY_INDEX = os.path.join(DATA_DIR, "history_index.json")
PARAMS_PATH = os.path.join(DATA_DIR, "params.json")


def read_results(path):
    """读取 results.json（或任意等价结构的 JSON）。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_params_meta():
    """读取 data/params.json 的元信息（tuned_at）。返回 dict 或 None。"""
    if not os.path.exists(PARAMS_PATH):
        return None
    try:
        d = json.load(open(PARAMS_PATH, encoding="utf-8"))
        return d
    except Exception:
        return None


def make_index_entry(payload, date_str, params_tuned):
    """根据 results 载荷构造 history_index 的一条摘要。"""
    stocks = payload.get("stocks", [])
    scores = [float(s.get("评分", 0) or 0) for s in stocks]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    max_score = round(max(scores), 1) if scores else 0.0
    temp = payload.get("temperature", {}) or {}
    top1 = stocks[0] if stocks else {}
    return {
        "date": date_str,
        "count": payload.get("count", len(stocks)),
        "temperature": temp.get("total"),
        "level": temp.get("level"),
        "avg_score": avg_score,
        "max_score": max_score,
        "top1": top1.get("名称", ""),
        "top1_code": top1.get("代码", ""),
        "data_source": payload.get("data_source", ""),
        "params_tuned": bool(params_tuned),
    }


def update_history_index(entry):
    """维护 data/history_index.json：按日期降序，同日去重。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    idx = []
    if os.path.exists(HISTORY_INDEX):
        try:
            idx = json.load(open(HISTORY_INDEX, encoding="utf-8"))
        except Exception:
            idx = []
    idx = [e for e in idx if e.get("date") != entry["date"]]
    idx.append(entry)
    # 日期降序（格式 YYYY-MM-DD 可直接字符串比较）
    idx.sort(key=lambda e: e.get("date", ""), reverse=True)
    json.dump(idx, open(HISTORY_INDEX, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return idx


def snapshot(results_path=None, date_str=None, force=False):
    """把 results.json 存档为 data/history/YYYY-MM-DD.json，并更新索引。

    返回 (entry, written: bool)。written=True 表示确实写入了新的快照文件。
    """
    results_path = results_path or os.path.join(DATA_DIR, "results.json")
    if not os.path.exists(results_path):
        raise FileNotFoundError(f"未找到结果文件: {results_path}")

    payload = read_results(results_path)
    params_meta = load_params_meta()
    tuned_at = (params_meta or {}).get("tuned_at")
    params_tuned = bool(tuned_at)

    date_str = date_str or datetime.date.today().isoformat()
    os.makedirs(HISTORY_DIR, exist_ok=True)
    snap_path = os.path.join(HISTORY_DIR, f"{date_str}.json")

    if os.path.exists(snap_path) and not force:
        print(f"  [skip] 快照已存在（{snap_path}），使用 --force 覆盖。")
        # 仍确保索引有该条目（可能由旧版生成，缺字段）
        entry = make_index_entry(payload, date_str, params_tuned)
        update_history_index(entry)
        return entry, False

    snap = {
        "date": date_str,
        "generated_at": payload.get("generated_at"),
        "snapshot_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": payload.get("data_source", ""),
        "params": payload.get("params"),
        "params_tuned": params_tuned,
        "tuned_at": tuned_at,
        "temperature": payload.get("temperature"),
        "count": payload.get("count", len(payload.get("stocks", []))),
        "stocks": payload.get("stocks", []),
        "top3": payload.get("top3", []),
        "indices": payload.get("indices"),
    }
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)

    entry = make_index_entry(payload, date_str, params_tuned)
    update_history_index(entry)
    print(f"  已写入快照: {snap_path}")
    return entry, True


def main():
    parser = argparse.ArgumentParser(description="历史推荐快照")
    parser.add_argument("--date", default=None, help="快照日期（默认今日，格式 YYYY-MM-DD）")
    parser.add_argument("--source", default=None, help="读取的 results 路径（默认 data/results.json）")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的同日快照")
    args = parser.parse_args()

    entry, written = snapshot(args.source, args.date, args.force)
    print(f"快照日期: {entry['date']}  | 候选数: {entry['count']}  "
          f"| 温度: {entry['temperature']}({entry['level']})  "
          f"| 平均评分: {entry['avg_score']}  | Top1: {entry['top1']}({entry['top1_code']})")
    print(f"参数已调优: {'是' if entry['params_tuned'] else '否'}  | 写入新快照: {'是' if written else '否'}")


if __name__ == "__main__":
    main()
