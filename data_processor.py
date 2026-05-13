#!/usr/bin/env python3
"""一木记账数据结构化处理：解析 Excel、分类筛选、摘要生成、周期对比。"""

import io
import pandas as pd
from datetime import datetime, timedelta
from location_resolver import enrich_transactions, area_summary

MODE_DAYS_MAP = {"daily": 1, "weekly": 7, "monthly": 30}


def _find_col(columns, keywords):
    for kw in keywords:
        match = next((c for c in columns if kw in str(c)), None)
        if match:
            return match
    return None


def parse_transactions(excel_bytes, mode, reference_date=None):
    """解析 Excel，筛选指定时间范围，返回 (DataFrame, 时间描述)。"""
    df = pd.read_excel(io.BytesIO(excel_bytes))

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
        raise ValueError(f"核心列识别失败: {df.columns.tolist()}")

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])

    days = MODE_DAYS_MAP.get(mode, 7)
    now = reference_date if reference_date else datetime.now()

    if mode.startswith("previous_"):
        base_mode = mode.replace("previous_", "")
        base_days = MODE_DAYS_MAP.get(base_mode, 7)
        end = now - timedelta(days=base_days)
        start = end - timedelta(days=base_days)
        period_label = f"过去 {base_days} 天（上一周期）"
        df = df[(df[date_col] >= start) & (df[date_col] < end)].copy()
    else:
        cutoff = now - timedelta(days=days)
        period_label = f"过去 {days} 天"
        df = df[df[date_col] >= cutoff].copy()

    rename_map = {date_col: "日期", amount_col: "金额", type_col: "类型", cat_col: "分类"}
    if sub_cat_col:
        rename_map[sub_cat_col] = "二级分类"
    for col, name in [(account_col, "账户"), (note_col, "备注"), (tag_col, "标签"),
                       (disc_col, "优惠"), (refund_col, "退款"), (reimb_col, "报销"),
                       (addr_col, "地址")]:
        if col:
            rename_map[col] = name
    df = df.rename(columns=rename_map)

    df["原始金额"] = pd.to_numeric(df["金额"], errors="coerce").fillna(0)
    for col in ["退款", "优惠", "报销"]:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).abs()

    # 一木记账的"金额"列已经是实付金额（已扣除优惠/退款/报销后的净值）。
    # 优惠/退款/报销列仅作信息记录，不在计算中二次扣减。
    # 支出可为负（报销退款），保留符号让净支出求和自动核减。
    df["实际金额"] = df["原始金额"]

    sub_renamed = rename_map.get(sub_cat_col) if sub_cat_col else None
    df["最终分类"] = df["分类"]
    if sub_renamed and sub_renamed in df.columns:
        has_sub = df[sub_renamed].notna() & (df[sub_renamed].astype(str).str.strip() != "")
        df.loc[has_sub, "最终分类"] = df.loc[has_sub, sub_renamed]

    return df, period_label


def _format_clusters(clusters):
    lines = []
    if not clusters:
        return lines
    cluster_total = sum(c["total_amount"] for c in clusters)
    lines.append("## 🗺️ 高频活动区域")
    lines.append("| 区域 | 笔数 | 金额 | 占比 | 均值 | 主要消费 |")
    lines.append("|------|------|------|------|------|----------|")
    for c in clusters[:8]:
        pct = c["total_amount"] / cluster_total * 100 if cluster_total > 0 else 0
        top_cats = ", ".join(f"{k} ¥{v:.0f}" for k, v in list(c["top_categories"].items())[:3])
        lines.append(f"| {c['aoi_label']} | {c['count']} | ¥{c['total_amount']:,.2f} | "
                     f"{pct:.0f}% | ¥{c['avg_amount']:.2f} | {top_cats} |")
    return lines


def summarize(df, period_label):
    """根据筛选后的 DataFrame 生成文本摘要（供 AI 分析）。"""
    income_df = df[df["类型"].str.contains("收入", na=False)]
    expense_df = df[df["类型"].str.contains("支出", na=False)]

    metrics = _extract_metrics(df)
    total_income = metrics["总收入"]
    real_expense = metrics["净支出"]
    net_balance = metrics["净结余"]

    # 一木记账的"金额"列已是实付净值，无需再扣减。
    # 优惠/退款/报销列仅作信息展示（显示本期累计享受到的优惠额度）。
    total_disc = expense_df["优惠"].sum() if "优惠" in expense_df.columns else 0
    total_refund = expense_df["退款"].sum() if "退款" in expense_df.columns else 0
    total_reimb = expense_df["报销"].sum() if "报销" in expense_df.columns else 0

    lines = [
        f"📊 财务数据摘要（{period_label}）",
        f"本周期净支出 ¥{real_expense:,.2f}",
    ]
    extras = []
    if total_disc > 0:
        extras.append(f"优惠 ¥{total_disc:,.2f}")
    if total_refund > 0:
        extras.append(f"退款 ¥{total_refund:,.2f}")
    if total_reimb > 0:
        extras.append(f"报销 ¥{total_reimb:,.2f}")
    if extras:
        lines.append(f"（期间累计享受：{'，'.join(extras)}）")
    lines += [
        "## 核心指标",
        f"- 💰总收入：¥{total_income:,.2f}",
        f"- 💸 真实净支出：¥{real_expense:,.2f}",
        f"- 🏦净结余：¥{net_balance:,.2f}",
    ]
    if total_income > 0:
        lines.append(f"- 📈储蓄率：{net_balance/total_income*100:.1f}%")
    else:
        lines.append("- 储蓄率：无收入数据")

    if total_income > 0:
        lines += ["## 收入来源明细"]
        income_by_cat = income_df.groupby("最终分类")["原始金额"].sum().sort_values(ascending=False)
        for cat, amt in income_by_cat.items():
            lines.append(f"- {cat}：¥{amt:,.2f}（{amt/total_income*100:.1f}%）")

    lines += ["## 支出分类全景"]
    expense_by_cat = {k: v for k, v in metrics["支出分类"].items() if v > 0}
    for cat, amt in sorted(expense_by_cat.items(), key=lambda x: x[1], reverse=True):
        pct = amt / real_expense * 100 if real_expense else 0
        lines.append(f"- {cat}：¥{amt:,.2f}（{pct:.1f}%）")

    freq_small = metrics["小额高频"]
    if freq_small:
        lines += ["☕ 频繁小额支出（单笔≤30元，出现5次及以上）"]
        for cat in sorted(freq_small, key=lambda c: freq_small[c]["次数"], reverse=True):
            lines.append(f"- {cat}：共 {freq_small[cat]['次数']} 次，累计 ¥{freq_small[cat]['总额']:,.2f}")

    if "地址" in df.columns:
        addr_expense = expense_df[expense_df["地址"].notna() & (expense_df["地址"].astype(str).str.strip() != "")]
        if not addr_expense.empty:
            addr_records = addr_expense[["地址", "最终分类", "实际金额"]].copy()
            addr_records.columns = ["address", "category", "amount"]
            records = addr_records.to_dict("records")
            enriched = enrich_transactions(records)
            area = area_summary(enriched)
            lines += _format_clusters(area["clusters"])

    has_note, has_tag = "备注" in expense_df.columns, "标签" in expense_df.columns
    lines.append("🚨 单笔大额支出 Top 10")
    top = expense_df[expense_df["实际金额"] > 0].nlargest(10, "实际金额")
    for _, row in top.iterrows():
        extras = []
        if has_tag and pd.notna(row.get("标签")) and str(row.get("标签")).strip():
            extras.append(f"🏷️ {row['标签']}")
        if has_note and pd.notna(row.get("备注")) and str(row.get("备注")).strip():
            extras.append(f"📝 {row['备注']}")
        extra_str = f"（{' | '.join(extras)}）" if extras else ""
        lines.append(f"- {row['日期'].strftime('%m/%d')} | {row['最终分类']} | ¥{row['实际金额']:,.2f} {extra_str}")

    return "\n".join(lines)


def _extract_metrics(df):
    """从 DataFrame 提取核心指标：总收入、净支出、净结余、分类汇总、小额高频。"""
    income_df = df[df["类型"].str.contains("收入", na=False)]
    expense_df = df[df["类型"].str.contains("支出", na=False)]

    total_income = income_df["原始金额"].sum()
    real_expense = expense_df["实际金额"].sum()
    net_balance = total_income - real_expense

    expense_by_cat = expense_df.groupby("最终分类")["实际金额"].sum().to_dict()
    income_by_cat = income_df.groupby("最终分类")["原始金额"].sum().to_dict()

    small_expenses = expense_df[expense_df["实际金额"] <= 30]
    freq_small = {}
    if not small_expenses.empty:
        freq = small_expenses.groupby("最终分类").agg(
            次数=("实际金额", "count"), 总计=("实际金额", "sum"))
        freq = freq[freq["次数"] >= 5]
        for cat, row in freq.iterrows():
            freq_small[cat] = {"次数": int(row["次数"]), "总额": row["总计"]}

    return {
        "总收入": total_income, "净支出": real_expense, "净结余": net_balance,
        "支出分类": expense_by_cat, "收入分类": income_by_cat, "小额高频": freq_small,
    }


def generate_comparison_summary(df_current, df_previous, label_cur, label_prev):
    """对比两个周期的财务数据，生成文本摘要。"""
    cur = _extract_metrics(df_current)
    prev = _extract_metrics(df_previous)

    lines = [f"同期对比：{label_prev} → {label_cur}"]

    lines.append("【核心指标变动】")
    exp_c, exp_p = cur["净支出"], prev["净支出"]
    exp_chg = exp_c - exp_p
    pct = exp_chg / exp_p * 100 if exp_p else 0
    lines.append(f"净支出：¥{exp_p:.2f} → ¥{exp_c:.2f}，{exp_chg:+.2f}元（{pct:+.1f}%）")

    bal_c, bal_p = cur["净结余"], prev["净结余"]
    lines.append(f"净结余：¥{bal_p:.2f} → ¥{bal_c:.2f}，{bal_c - bal_p:+.2f}元")

    inc_c, inc_p = cur["总收入"], prev["总收入"]
    if inc_p > 0 or inc_c > 0:
        lines.append(f"总收入：¥{inc_p:.2f} → ¥{inc_c:.2f}")

    lines.append("【分类支出变动】")
    cat_cur, cat_prev = cur["支出分类"], prev["支出分类"]
    all_cats = sorted(set(cat_cur.keys()) | set(cat_prev.keys()),
                      key=lambda c: cat_cur.get(c, 0) + cat_prev.get(c, 0), reverse=True)
    for cat in all_cats:
        pv, cv = cat_prev.get(cat, 0), cat_cur.get(cat, 0)
        chg = cv - pv
        if pv == 0:
            lines.append(f"  {cat}：¥{pv:.2f} → ¥{cv:.2f}（新增）")
        else:
            lines.append(f"  {cat}：¥{pv:.2f} → ¥{cv:.2f}，{chg:+.2f}元（{chg/pv*100:+.1f}%）")

    small_cur, small_prev = cur["小额高频"], prev["小额高频"]
    all_small = set(small_cur.keys()) | set(small_prev.keys())
    if all_small:
        lines.append("【高频小额变动】")
        for cat in all_small:
            pc = small_prev.get(cat, {"次数": 0, "总额": 0.0})
            cc = small_cur.get(cat, {"次数": 0, "总额": 0.0})
            lines.append(f"  {cat}：{pc['次数']}次 ¥{pc['总额']:.2f} → {cc['次数']}次 ¥{cc['总额']:.2f}")

    return "\n".join(lines)
