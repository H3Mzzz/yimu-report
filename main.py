#!/usr/bin/env python3
"""一木记账数据获取模块。

数据流：坚果云 Custom.db → 解析筛选 → JSON 摘要输出。
供 AI 助手通过 --data-only 模式调用，不调 AI、不发邮件。
"""

import argparse
import json
import os
import sys
from datetime import datetime

# 确保脚本所在目录在 Python 路径中，避免 CWD 不同时导入失败
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_processor import parse_transactions, summarize, generate_comparison_summary, _extract_metrics

MODE_DAYS_MAP = {"daily": 1, "weekly": 7, "monthly": 30}
KNOWLEDGE_DB_PATH = os.path.expanduser("~/cow/knowledge/finance/data/Custom.db")


def fetch_data(mode: str = "weekly") -> dict:
    """从本地 Custom.db 获取账单，返回结构化摘要（不调 AI、不发邮件）。"""
    if not os.path.exists(KNOWLEDGE_DB_PATH):
        raise RuntimeError(f"数据库不存在: {KNOWLEDGE_DB_PATH}，请先运行 sync_db.py")

    print(f"数据源: {KNOWLEDGE_DB_PATH}")

    df, period_label = parse_transactions(KNOWLEDGE_DB_PATH, mode)
    if df.empty:
        return {"mode": mode, "period_label": period_label, "empty": True}

    summary = summarize(df, period_label)
    metrics = _extract_metrics(df)

    comparison_summary = None
    previous_label = None
    try:
        df_prev, prev_label = parse_transactions(KNOWLEDGE_DB_PATH, f"previous_{mode}")
        if not df_prev.empty:
            previous_label = prev_label
            comparison_summary = generate_comparison_summary(df, df_prev, period_label, previous_label)
    except Exception:
        pass

    return {
        "mode": mode,
        "period_label": period_label,
        "summary": summary,
        "metrics": metrics,
        "comparison_summary": comparison_summary,
        "previous_label": previous_label,
    }


def _serialize_metrics(data: dict) -> dict:
    """将 numpy 类型转为 JSON 可序列化类型。"""
    import numpy as np
    for key in ("metrics",):
        if key not in data or not data[key]:
            continue
        for sub_k, sub_v in data[key].items():
            if isinstance(sub_v, dict):
                for kk in sub_v:
                    if hasattr(sub_v[kk], "item"):
                        sub_v[kk] = sub_v[kk].item()
            elif hasattr(sub_v, "item"):
                data[key][sub_k] = sub_v.item()
    return data


def main():
    parser = argparse.ArgumentParser(description="一木记账数据获取")
    parser.add_argument("--data-only", action="store_true",
                        help="输出 JSON 数据摘要（供 AI 助手消费）")
    parser.add_argument("--mode", default=os.environ.get("REPORT_MODE", "daily"),
                        choices=["daily", "weekly", "monthly"],
                        help="报告模式")
    args = parser.parse_args()

    if not args.data_only:
        print("此脚本仅支持 --data-only 模式。AI 报告由 AI 助手独立生成。")
        return

    data = fetch_data(args.mode)
    if data.get("empty"):
        print(json.dumps({"error": "该时间段无数据"}, ensure_ascii=False))
        return

    data = _serialize_metrics(data)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
