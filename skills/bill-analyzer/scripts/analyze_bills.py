#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账单筛选分析工具 — 从本地 xlsx 账单中按时间/分类/金额筛选并生成摘要

用法：
    # 最近 7 天
    python analyze_bills.py --days 7

    # 指定日期范围
    python analyze_bills.py --from 2026-05-01 --to 2026-05-07

    # 本月
    python analyze_bills.py --month current

    # 指定分类
    python analyze_bills.py --days 30 --category 餐饮

    # 大额消费
    python analyze_bills.py --days 30 --min-amount 200

    # 小额高频
    python analyze_bills.py --days 30 --small-freq

    # 完整模式（输出所有分析维度）
    python analyze_bills.py --days 7 --full

    # 指定数据文件
    python analyze_bills.py --file bills_2026-05-07.xlsx --days 7

    # 列出可用数据文件
    python analyze_bills.py --list-files

    # 输出 JSON（供程序消费）
    python analyze_bills.py --days 7 --json
"""

import io
import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "knowledge" / "finance" / "data"
if not DATA_DIR.is_dir():
    DATA_DIR = Path(os.path.expanduser("~/cow/knowledge/finance/data"))

DB_PATH = DATA_DIR / "Custom.db"


def get_budget_from_db(year: int = None, month: int = None) -> float:
    """从数据库读取月预算。如果指定月份没有预算，回退到最近一个月的预算。"""
    if not DB_PATH.exists():
        return 2050  # 数据库不存在时的兜底值

    now = datetime.now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # 先查当前月
    cursor.execute('''
        SELECT num FROM budget 
        WHERE year = ? AND month = ? AND delete_lpcolumn = 0 AND num > 0
        LIMIT 1
    ''', (year, month))
    result = cursor.fetchone()
    if result:
        conn.close()
        return result[0]

    # 当前月没有预算，找最近的预算
    cursor.execute('''
        SELECT num FROM budget 
        WHERE delete_lpcolumn = 0 AND num > 0
        ORDER BY year DESC, month DESC
        LIMIT 1
    ''')
    result = cursor.fetchone()
    conn.close()

    return result[0] if result else 2050


def _find_col(columns: list[str], keywords: list[str]) -> str | None:
    for kw in keywords:
        match = next((c for c in columns if kw in str(c)), None)
        if match:
            return match
    return None


def list_data_files() -> list[str]:
    if not DATA_DIR.is_dir():
        return []
    files = sorted(
        [f for f in os.listdir(DATA_DIR) if f.startswith("bills_") and f.endswith(".xlsx")],
        reverse=True,
    )
    return files


def load_latest_file() -> tuple[pd.DataFrame, str]:
    files = list_data_files()
    if not files:
        raise FileNotFoundError(f"无数据文件，请先执行备份: {DATA_DIR}")
    fpath = DATA_DIR / files[0]
    return pd.read_excel(fpath), str(fpath)


def load_file(filename: str) -> pd.DataFrame:
    fpath = DATA_DIR / filename
    if not fpath.exists():
        raise FileNotFoundError(f"文件不存在: {fpath}")
    return pd.read_excel(fpath)


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """标准化列名、解析日期、计算实际金额（含优惠/退款/报销扣除）"""
    cols = df.columns.tolist()

    date_col = _find_col(cols, ["日期", "时间", "Date"])
    amount_col = _find_col(cols, ["金额", "Amount"])
    type_col = _find_col(cols, ["类型", "收支", "Type"])
    cat_col = _find_col(cols, ["类别", "分类", "Category"])
    sub_cat_col = _find_col(cols, ["二级分类", "Subcategory"])
    account_col = _find_col(cols, ["账户", "Account"])
    refund_col = _find_col(cols, ["退款", "Refund"])
    disc_col = _find_col(cols, ["优惠", "Discount"])
    reimb_col = _find_col(cols, ["报销金额", "报销", "Reimbursement"])
    note_col = _find_col(cols, ["备注", "摘要", "Note", "Remark"])
    tag_col = _find_col(cols, ["标签", "Tag"])
    addr_col = _find_col(cols, ["地址", "Address", "Location"])

    if not all([date_col, amount_col, type_col, cat_col]):
        raise ValueError(f"核心列缺失: {cols}")

    rename_map = {
        date_col: "日期", amount_col: "金额", type_col: "类型", cat_col: "分类",
    }
    if sub_cat_col:
        rename_map[sub_cat_col] = "二级分类"
    for col, name in [(account_col, "账户"), (note_col, "备注"), (tag_col, "标签"),
                       (disc_col, "优惠"), (refund_col, "退款"), (reimb_col, "报销"),
                       (addr_col, "地址")]:
        if col:
            rename_map[col] = name
    df = df.rename(columns=rename_map)

    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df = df.dropna(subset=["日期"])

    df["原始金额"] = pd.to_numeric(df["金额"], errors="coerce").fillna(0)
    for col in ["退款", "优惠", "报销"]:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).abs()

    is_expense = df["类型"].str.contains("支出", na=False)
    df["实际金额"] = df["原始金额"]
    positive_expense = is_expense & (df["原始金额"] > 0)
    df.loc[positive_expense, "实际金额"] = (
        df.loc[positive_expense, "原始金额"]
        - df.loc[positive_expense, "退款"]
        - df.loc[positive_expense, "优惠"]
        - df.loc[positive_expense, "报销"]
    ).clip(lower=0)

    # 最终分类：优先二级分类
    df["最终分类"] = df["分类"]
    if "二级分类" in df.columns:
        has_sub = df["二级分类"].notna() & (df["二级分类"].astype(str).str.strip() != "")
        df.loc[has_sub, "最终分类"] = df.loc[has_sub, "二级分类"]

    return df


def filter_by_date(df: pd.DataFrame, date_from: datetime | None = None,
                   date_to: datetime | None = None, days: int | None = None) -> pd.DataFrame:
    if days and not date_from:
        date_from = datetime.now() - timedelta(days=days)
    if date_from:
        df = df[df["日期"] >= date_from]
    if date_to:
        df = df[df["日期"] <= date_to]
    return df.copy()


def filter_by_category(df: pd.DataFrame, category: str) -> pd.DataFrame:
    return df[df["最终分类"].str.contains(category, na=False)].copy()


def filter_by_amount(df: pd.DataFrame, min_amount: float = 0, max_amount: float = float("inf")) -> pd.DataFrame:
    return df[(df["实际金额"] >= min_amount) & (df["实际金额"] <= max_amount)].copy()


def compute_summary(df: pd.DataFrame) -> dict:
    """生成核心摘要指标"""
    income_df = df[df["类型"].str.contains("收入", na=False)]
    expense_df = df[df["类型"].str.contains("支出", na=False)]

    total_income = float(income_df["原始金额"].sum())
    total_expense = float(expense_df["实际金额"].sum())
    total_count = len(expense_df)
    net_balance = total_income - total_expense

    # 分类支出
    cat_expense = expense_df.groupby("最终分类")["实际金额"].sum()
    cat_expense = cat_expense[cat_expense > 0].sort_values(ascending=False)
    cat_dict = {k: round(v, 2) for k, v in cat_expense.items()}

    # 分类笔数
    cat_count = expense_df["最终分类"].value_counts().to_dict()

    # 日均
    if not expense_df.empty:
        date_range = (expense_df["日期"].max() - expense_df["日期"].min()).days + 1
        daily_avg = total_expense / max(date_range, 1)
    else:
        date_range = 0
        daily_avg = 0

    return {
        "总收入": round(total_income, 2),
        "净支出": round(total_expense, 2),
        "净结余": round(net_balance, 2),
        "支出笔数": total_count,
        "天数": date_range,
        "日均支出": round(daily_avg, 2),
        "储蓄率": round(net_balance / total_income * 100, 1) if total_income > 0 else None,
        "支出分类": cat_dict,
        "分类笔数": cat_count,
    }


def compute_small_freq(df: pd.DataFrame, threshold: float = 30, min_count: int = 5) -> list[dict]:
    """小额高频消费检测"""
    expense_df = df[df["类型"].str.contains("支出", na=False)]
    small = expense_df[expense_df["实际金额"] <= threshold]
    if small.empty:
        return []

    freq = small.groupby("最终分类").agg(
        次数=("实际金额", "count"),
        总额=("实际金额", "sum"),
        均值=("实际金额", "mean"),
    )
    freq = freq[freq["次数"] >= min_count].sort_values("次数", ascending=False)

    return [
        {"分类": cat, "次数": int(row["次数"]), "总额": round(row["总额"], 2),
         "均值": round(row["均值"], 2)}
        for cat, row in freq.iterrows()
    ]


def compute_top_expenses(df: pd.DataFrame, top_n: int = 10) -> list[dict]:
    """大额消费 Top N"""
    expense_df = df[df["类型"].str.contains("支出", na=False)]
    top = expense_df[expense_df["实际金额"] > 0].nlargest(top_n, "实际金额")

    results = []
    for _, row in top.iterrows():
        item = {
            "日期": row["日期"].strftime("%Y-%m-%d"),
            "分类": row["最终分类"],
            "金额": round(float(row["实际金额"]), 2),
        }
        if "备注" in df.columns and pd.notna(row.get("备注")) and str(row.get("备注")).strip():
            item["备注"] = str(row["备注"]).strip()
        if "标签" in df.columns and pd.notna(row.get("标签")) and str(row.get("标签")).strip():
            item["标签"] = str(row["标签"]).strip()
        results.append(item)
    return results


def compute_daily_trend(df: pd.DataFrame) -> list[dict]:
    """每日支出趋势"""
    expense_df = df[df["类型"].str.contains("支出", na=False)]
    daily = expense_df.groupby(expense_df["日期"].dt.date)["实际金额"].sum()
    return [{"日期": str(d), "金额": round(v, 2)} for d, v in daily.items()]


def compute_month_comparison(df: pd.DataFrame) -> dict:
    """本月 vs 上月同期对比（按已过天数对齐）"""
    now = datetime.now()
    day_of_month = now.day

    # 本月：1号到今天
    this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_end = now.replace(hour=23, minute=59, second=59)
    this_df = filter_by_date(df, date_from=this_start, date_to=this_end)

    # 上月：1号到同一天
    if now.month == 1:
        last_start = now.replace(year=now.year - 1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        last_start = now.replace(month=now.month - 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    last_end_day = min(day_of_month, (last_start.replace(month=last_start.month % 12 + 1, day=1) - timedelta(days=1)).day)
    last_end = last_start.replace(day=last_end_day, hour=23, minute=59, second=59)
    last_df = filter_by_date(df, date_from=last_start, date_to=last_end)

    this_summary = compute_summary(this_df)
    last_summary = compute_summary(last_df)

    # 分类对比
    this_cats = this_summary["支出分类"]
    last_cats = last_summary["支出分类"]
    all_cats = sorted(set(list(this_cats.keys()) + list(last_cats.keys())))
    cat_comparison = {}
    for cat in all_cats:
        t = this_cats.get(cat, 0)
        l = last_cats.get(cat, 0)
        diff = round(t - l, 2)
        pct = round(diff / l * 100, 1) if l > 0 else None
        cat_comparison[cat] = {"本月": t, "上月": l, "差额": diff, "变化%": pct}

    # 本月日均 vs 上月日均
    this_days = max(this_summary["天数"], 1)
    last_days = max(last_summary["天数"], 1)

    return {
        "对比天数": f"本月 1-{day_of_month}日 vs 上月 1-{last_end_day}日",
        "本月": {
            "净支出": this_summary["净支出"],
            "笔数": this_summary["支出笔数"],
            "日均": this_summary["日均支出"],
            "天数": this_summary["天数"],
        },
        "上月同期": {
            "净支出": last_summary["净支出"],
            "笔数": last_summary["支出笔数"],
            "日均": round(last_summary["净支出"] / last_days, 2),
            "天数": last_summary["天数"],
        },
        "差额": round(this_summary["净支出"] - last_summary["净支出"], 2),
        "分类对比": cat_comparison,
    }


def compute_whatif(df: pd.DataFrame, amount: float, budget: float = None) -> dict:
    """What-If 沙盘：假设现在花 amount 元，结合历史模式分析影响"""
    if budget is None:
        budget = get_budget_from_db()
    now = datetime.now()
    day_of_month = now.day
    days_in_month = 30  # 简化

    # 本月已消费
    this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_df = filter_by_date(df, date_from=this_start)
    this_summary = compute_summary(this_df)
    this_spent = this_summary["净支出"]

    # 上月同期消费（用于参考）
    if now.month == 1:
        last_start = now.replace(year=now.year - 1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        last_start = now.replace(month=now.month - 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    last_end_day = min(day_of_month, 28)
    last_end = last_start.replace(day=last_end_day, hour=23, minute=59, second=59)
    last_df = filter_by_date(df, date_from=last_start, date_to=last_end)
    last_summary = compute_summary(last_df)
    last_same_period_spent = last_summary["净支出"]

    # 上月整月消费（推算本月趋势）
    last_full_start = last_start
    if now.month == 1:
        last_full_end = now.replace(year=now.year - 1, month=12, day=31, hour=23, minute=59, second=59)
    else:
        last_full_end = now.replace(month=now.month, day=1) - timedelta(seconds=1)
    last_full_df = filter_by_date(df, date_from=last_full_start, date_to=last_full_end)
    last_full_summary = compute_summary(last_full_df)
    last_full_spent = last_full_summary["净支出"]

    remaining_days = days_in_month - day_of_month
    remaining_budget = budget - this_spent
    after_whatif_remaining = remaining_budget - amount
    after_whatif_daily = round(after_whatif_remaining / max(remaining_days, 1), 2) if after_whatif_remaining > 0 else 0

    # 趋势推算：按当前日均，月底预计总消费
    current_daily = this_summary["日均支出"]
    projected_total = round(this_spent + current_daily * remaining_days, 2)
    projected_total_with_whatif = round(this_spent + amount + current_daily * remaining_days, 2)

    # 历史参照
    trend_vs_last = round(this_spent - last_same_period_spent, 2)

    result = {
        "假设消费": amount,
        "本月已消费": this_spent,
        "月预算": budget,
        "剩余预算": round(remaining_budget, 2),
        "购买后剩余": round(after_whatif_remaining, 2),
        "购买后日均": after_whatif_daily,
        "剩余天数": remaining_days,
        "当前日均": current_daily,
        "月底预计总消费（不含假设）": projected_total,
        "月底预计总消费（含假设）": projected_total_with_whatif,
        "上月同期消费": last_same_period_spent,
        "上月整月消费": last_full_spent,
        "与上月同期差额": trend_vs_last,
    }

    # 风险评估
    if after_whatif_remaining < 0:
        result["风险"] = "🚨 直接超支"
        result["建议"] = f"超支 ¥{abs(after_whatif_remaining):.0f}，建议推迟或分期"
    elif after_whatif_daily < 20:
        result["风险"] = "⚠️ 日均预算极低"
        result["建议"] = f"剩余{remaining_days}天日均仅¥{after_whatif_daily:.0f}，生活将很紧张"
    elif after_whatif_daily < 40:
        result["风险"] = "⚠️ 偏紧"
        result["建议"] = f"日均¥{after_whatif_daily:.0f}，需要严格控制其他开支"
    elif projected_total_with_whatif > budget:
        result["风险"] = "⚠️ 按当前趋势将超支"
        result["建议"] = f"按当前日均月底预计¥{projected_total_with_whatif:.0f}，超出预算¥{projected_total_with_whatif - budget:.0f}"
    else:
        result["风险"] = "✅ 可承受"
        result["建议"] = f"日均¥{after_whatif_daily:.0f}，预算充足"

    # 历史模式建议
    if trend_vs_last > 200:
        result["历史提醒"] = f"本月同期已比上月多花¥{trend_vs_last:.0f}，再消费需谨慎"
    elif trend_vs_last < -200:
        result["历史提醒"] = f"本月同期比上月少花¥{abs(trend_vs_last):.0f}，有一定缓冲空间"

    return result


def build_text_report(df: pd.DataFrame, date_label: str) -> str:
    """生成可读的文本报告"""
    summary = compute_summary(df)
    small_freq = compute_small_freq(df)
    top_expenses = compute_top_expenses(df)

    lines = [f"📊 账单分析（{date_label}）", ""]

    # 核心指标
    lines.append("## 核心指标")
    lines.append(f"- 💰 总收入：¥{summary['总收入']:,.2f}")
    lines.append(f"- 💸 净支出：¥{summary['净支出']:,.2f}")
    lines.append(f"- 🏦 净结余：¥{summary['净结余']:,.2f}")
    lines.append(f"- 📝 支出笔数：{summary['支出笔数']}")
    lines.append(f"- 📅 覆盖天数：{summary['天数']}")
    lines.append(f"- 📈 日均支出：¥{summary['日均支出']:,.2f}")
    if summary['储蓄率'] is not None:
        lines.append(f"- 💰 储蓄率：{summary['储蓄率']}%")

    # 分类支出
    lines.append("")
    lines.append("## 支出分类")
    for cat, amt in summary["支出分类"].items():
        pct = amt / summary["净支出"] * 100 if summary["净支出"] else 0
        cnt = summary["分类笔数"].get(cat, 0)
        lines.append(f"- {cat}：¥{amt:,.2f}（{pct:.1f}%，{cnt}笔）")

    # 小额高频
    if small_freq:
        lines.append("")
        lines.append("## ☕ 小额高频（≤30元，≥5次）")
        for item in small_freq:
            lines.append(f"- {item['分类']}：{item['次数']}次，累计¥{item['总额']:,.2f}，均¥{item['均值']:.2f}")

    # 大额消费
    if top_expenses:
        lines.append("")
        lines.append("## 🚨 大额消费 Top 10")
        for item in top_expenses:
            extra = ""
            if item.get("备注"):
                extra += f" 📝{item['备注']}"
            if item.get("标签"):
                extra += f" 🏷️{item['标签']}"
            lines.append(f"- {item['日期']} | {item['分类']} | ¥{item['金额']:,.2f}{extra}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="账单筛选分析")
    parser.add_argument("--file", help="指定数据文件名（默认用最新）")
    parser.add_argument("--list-files", action="store_true", help="列出可用数据文件")
    parser.add_argument("--from", dest="date_from", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--days", type=int, help="最近 N 天")
    parser.add_argument("--month", choices=["current", "last"], help="本月/上月")
    parser.add_argument("--category", help="按分类筛选（模糊匹配）")
    parser.add_argument("--min-amount", type=float, help="最小金额")
    parser.add_argument("--max-amount", type=float, help="最大金额")
    parser.add_argument("--small-freq", action="store_true", help="输出小额高频")
    parser.add_argument("--top", type=int, default=0, help="大额消费 Top N")
    parser.add_argument("--trend", action="store_true", help="输出日趋势")
    parser.add_argument("--compare", action="store_true", help="本月 vs 上月同期对比")
    parser.add_argument("--whatif", type=float, help="What-If 沙盘：假设消费金额")
    parser.add_argument("--budget", type=float, default=None, help="月预算（默认从数据库读取）")
    parser.add_argument("--full", action="store_true", help="完整分析模式")
    parser.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()

    if args.list_files:
        files = list_data_files()
        if files:
            print("可用数据文件：")
            for f in files:
                fsize = (DATA_DIR / f).stat().st_size
                print(f"  {f}  ({fsize // 1024}KB)")
        else:
            print(f"无数据文件: {DATA_DIR}")
        return

    # 加载数据
    if args.file:
        df = load_file(args.file)
        file_label = args.file
    else:
        df, fpath = load_latest_file()
        file_label = Path(fpath).name

    df = normalize_df(df)

    # 时间范围
    now = datetime.now()
    date_from, date_to = None, None
    if args.month == "current":
        date_from = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif args.month == "last":
        first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        date_to = first_this_month - timedelta(seconds=1)
        date_from = date_to.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif args.date_from:
        date_from = datetime.strptime(args.date_from, "%Y-%m-%d")
    if args.date_to:
        date_to = datetime.strptime(args.date_to, "%Y-%m-%d")

    df = filter_by_date(df, date_from=date_from, date_to=date_to, days=args.days)

    if args.category:
        df = filter_by_category(df, args.category)
    if args.min_amount:
        df = filter_by_amount(df, min_amount=args.min_amount)
    if args.max_amount:
        df = filter_by_amount(df, max_amount=args.max_amount)

    # 构建日期标签
    if date_from and date_to:
        date_label = f"{date_from.strftime('%Y-%m-%d')} ~ {date_to.strftime('%Y-%m-%d')}"
    elif date_from:
        date_label = f"{date_from.strftime('%Y-%m-%d')} ~ 今"
    elif args.days:
        date_label = f"最近 {args.days} 天"
    else:
        date_label = f"全量数据 ({file_label})"

    # 对比/沙盘模式（独立于时间筛选，使用全量数据）
    if args.compare:
        result = compute_month_comparison(df)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.whatif is not None:
        result = compute_whatif(df, args.whatif, budget=args.budget)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.json:
        result = {
            "文件": file_label,
            "时间范围": date_label,
            "summary": compute_summary(df),
        }
        if args.full or args.small_freq:
            result["小额高频"] = compute_small_freq(df)
        if args.full or args.top > 0:
            result["大额Top"] = compute_top_expenses(df, args.top or 10)
        if args.full or args.trend:
            result["日趋势"] = compute_daily_trend(df)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if args.full:
            print(build_text_report(df, date_label))
        else:
            summary = compute_summary(df)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            if args.small_freq:
                print("\n## 小额高频")
                for item in compute_small_freq(df):
                    print(f"  {item['分类']}：{item['次数']}次 ¥{item['总额']:,.2f}")
            if args.top > 0:
                print(f"\n## 大额 Top {args.top}")
                for item in compute_top_expenses(df, args.top):
                    print(f"  {item['日期']} {item['分类']} ¥{item['金额']:,.2f}")
            if args.trend:
                print("\n## 日趋势")
                for item in compute_daily_trend(df):
                    print(f"  {item['日期']} ¥{item['金额']:,.2f}")


if __name__ == "__main__":
    main()
