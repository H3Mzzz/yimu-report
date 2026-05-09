#!/usr/bin/env python3
"""桥接脚本：AI 生成的 Markdown 报告 → HTML 邮件发送。"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

# 确保脚本所在目录在 Python 路径中，避免 CWD 不同时导入失败
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from html_renderer import build_html_email
from send_mail import send_email
from data_processor import parse_transactions, _extract_metrics

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "cow", "knowledge", "finance", "data")

MODE_LABELS = {"daily": "日报", "weekly": "周报", "monthly": "月报"}


def _find_latest_xlsx():
    if not os.path.isdir(DATA_DIR):
        return None
    xlsx_files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".xlsx")], reverse=True)
    return os.path.join(DATA_DIR, xlsx_files[0]) if xlsx_files else None


def get_latest_metrics(mode):
    """从本地知识库读取最新账单，提取饼图所需的分类指标。"""
    try:
        china_tz = timezone(timedelta(hours=8))
        today_file = os.path.join(DATA_DIR, f"bills_{datetime.now(china_tz).strftime('%Y-%m-%d')}.xlsx")
        path = today_file if os.path.exists(today_file) else _find_latest_xlsx()
        if path is None:
            return {}
        with open(path, "rb") as f:
            excel_bytes = f.read()
        df, _ = parse_transactions(excel_bytes, mode)
        if df.empty:
            return {}
        return _extract_metrics(df)
    except Exception as e:
        print(f"获取指标数据失败: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser(description="发送财务报告邮件")
    parser.add_argument("--mode", required=True, choices=["daily", "weekly", "monthly"])
    parser.add_argument("--body", help="报告正文（Markdown）")
    parser.add_argument("--body-file", help="从文件读取报告正文")
    parser.add_argument("--summary", default="", help="数据摘要（可选）")
    parser.add_argument("--no-chart", action="store_true", help="不生成饼图")
    args = parser.parse_args()

    if args.body:
        report_md = args.body
    elif args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as f:
            report_md = f.read()
    else:
        print("必须指定 --body 或 --body-file")
        sys.exit(1)

    summary = args.summary or ""

    metrics = {}
    if not args.no_chart:
        metrics = get_latest_metrics(args.mode)

    china_tz = timezone(timedelta(hours=8))
    today_str = datetime.now(china_tz).strftime("%Y年%m月%d日")
    period_label = MODE_LABELS.get(args.mode, args.mode)

    html_body = build_html_email(
        summary=summary, report=report_md, period_label=period_label,
        today_str=today_str, metrics=metrics if metrics else None,
    )

    plain_body = f"{summary}\n\n{'='*50}\n\n{report_md}" if summary else report_md

    from_addr = os.environ.get("QQ_EMAIL", "")
    to_addr = os.environ.get("TO_EMAIL", from_addr)
    auth_code = os.environ.get("QQ_AUTH_CODE", "")

    if not from_addr or not auth_code:
        print("缺少 QQ_EMAIL 或 QQ_AUTH_CODE")
        sys.exit(1)

    send_email(
        subject=f"💰 {period_label}财务报告 · {today_str}",
        plain_body=plain_body, html_body=html_body,
        from_addr=from_addr, to_addr=to_addr, auth_code=auth_code,
    )


if __name__ == "__main__":
    main()
