# data_processor.py
import io
import pandas as pd
from datetime import datetime, timedelta
from location_resolver import enrich_transactions, area_summary

MODE_DAYS_MAP = {"daily": 1, "weekly": 7, "monthly": 30}


def _find_col(columns: list[str], keywords: list[str]) -> str | None:
    """从列名列表中匹配关键词，返回首个匹配的列名"""
    for kw in keywords:
        match = next((c for c in columns if kw in str(c)), None)
        if match:
            return match
    return None


def parse_transactions(excel_bytes: bytes, mode: str, reference_date: datetime | None = None) -> tuple[pd.DataFrame, str]:
    """
    解析 Excel，筛选指定时间范围的数据，返回 (DataFrame, 时间描述)。
    """
    df = pd.read_excel(io.BytesIO(excel_bytes))
    print(f"原始数据列：{df.columns.tolist()}  行数：{len(df)}")

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
        raise ValueError(f"核心列名识别失败，实际列：{df.columns.tolist()}")

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

    rename_map = {
        date_col:   "日期",
        amount_col: "金额",
        type_col:   "类型",
        cat_col:    "分类",
    }
    if sub_cat_col:
        rename_map[sub_cat_col] = "二级分类"

    for col, name in [(account_col, "账户"), (note_col, "备注"), (tag_col, "标签"),
                       (disc_col, "优惠"), (refund_col, "退款"), (reimb_col, "报销"),
                       (addr_col, "地址")]:
        if col:
            rename_map[col] = name
    df = df.rename(columns=rename_map)

    # 负数支出表示报销/AA 回血，不应被取绝对值后错误累加
    df["原始金额"] = pd.to_numeric(df["金额"], errors="coerce").fillna(0)
    for col in ["退款", "优惠", "报销"]:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).abs()

    # 计算实际净支出
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
    sub_renamed = rename_map.get(sub_cat_col) if sub_cat_col else None
    df["最终分类"] = df["分类"]
    if sub_renamed and sub_renamed in df.columns:
        has_sub = df[sub_renamed].notna() & (df[sub_renamed].astype(str).str.strip() != "")
        df.loc[has_sub, "最终分类"] = df.loc[has_sub, sub_renamed]

    return df, period_label


def _format_clusters(clusters: list[dict]) -> list[str]:
    """将区域聚合结果格式化为文本行列表"""
    lines = []
    if not clusters:
        return lines
    cluster_total = sum(c["total_amount"] for c in clusters)
    lines.append("## 🗺️ 高频活动区域")
    lines.append("")
    lines.append("| 区域 | 笔数 | 金额 | 占比 | 均值 | 主要消费 |")
    lines.append("|------|------|------|------|------|----------|")
    for c in clusters[:8]:
        pct = c["total_amount"] / cluster_total * 100 if cluster_total > 0 else 0
        top_cats = ", ".join(f"{k} ¥{v:.0f}" for k, v in list(c["top_categories"].items())[:3])
        lines.append(
            f"| {c['aoi_label']} | {c['count']} | ¥{c['total_amount']:,.2f} | {pct:.0f}% | ¥{c['avg_amount']:.2f} | {top_cats} |"
        )
    return lines


def summarize(df: pd.DataFrame, period_label: str) -> str:
    """根据筛选后的 DataFrame 生成详细的文本摘要（供 AI 分析使用）"""
    income_df = df[df["类型"].str.contains("收入", na=False)]
    expense_df = df[df["类型"].str.contains("支出", na=False)]

    metrics = _extract_metrics(df)
    total_income = metrics["总收入"]
    real_expense = metrics["净支出"]
    net_balance = metrics["净结余"]

    raw_expense = expense_df["原始金额"].sum()
    total_refund = expense_df["退款"].sum() if "退款" in expense_df.columns else 0
    total_disc = expense_df["优惠"].sum() if "优惠" in expense_df.columns else 0
    total_reimb = expense_df["报销"].sum() if "报销" in expense_df.columns else 0

    lines = [
        f"📊 财务数据摘要（{period_label}）",
        f"本周期账面原始总支出 ¥{raw_expense:,.2f}，"
        f"经优惠(¥{total_disc:,.2f})、退款(¥{total_refund:,.2f})、报销抵扣(¥{total_reimb:,.2f})后，"
        f"个人真实净支出为 ¥{real_expense:,.2f}。",
        "",
        "## 核心指标",
        f"- 💰总收入：¥{total_income:,.2f}",
        f"- 💸 真实净支出：¥{real_expense:,.2f}",
        f"- 🏦净结余：¥{net_balance:,.2f}",
    ]
    if total_income > 0:
        lines.append(f"- 📈储蓄率：{net_balance/total_income*100:.1f}%")
    else:
        lines.append("- 储蓄率：无收入数据")

    # 收入来源明细
    if total_income > 0:
        lines += ["", "## 收入来源明细"]
        income_by_cat = income_df.groupby("最终分类")["原始金额"].sum().sort_values(ascending=False)
        for cat, amt in income_by_cat.items():
            lines.append(f"- {cat}：¥{amt:,.2f}（{amt/total_income*100:.1f}%）")

    # 支出分类全景
    lines += ["", "## 支出分类全景"]
    expense_by_cat = {k: v for k, v in metrics["支出分类"].items() if v > 0}
    for cat, amt in sorted(expense_by_cat.items(), key=lambda x: x[1], reverse=True):
        pct = amt / real_expense * 100 if real_expense else 0
        lines.append(f"- {cat}：¥{amt:,.2f}（{pct:.1f}%）")

    # 频繁小额支出
    freq_small = metrics["小额高频"]
    if freq_small:
        lines += ["", "☕ 频繁小额支出（单笔≤30元，出现5次及以上）"]
        for cat in sorted(freq_small, key=lambda c: freq_small[c]["次数"], reverse=True):
            lines.append(f"- {cat}：共 {freq_small[cat]['次数']} 次，累计 ¥{freq_small[cat]['总额']:,.2f}")

    # 区域消费聚合
    if "地址" in df.columns:
        addr_expense = expense_df[expense_df["地址"].notna() & (expense_df["地址"].astype(str).str.strip() != "")]
        if not addr_expense.empty:
            addr_records = addr_expense[["地址", "最终分类", "实际金额"]].copy()
            addr_records.columns = ["address", "category", "amount"]
            records = addr_records.to_dict("records")
            enriched = enrich_transactions(records)
            area = area_summary(enriched)
            lines += _format_clusters(area["clusters"])
            if area["stats"]["total_without_location"] > 0:
                lines.append(f"（{area['stats']['total_without_location']}条地址无法解析坐标，未纳入区域分析）")

    # 单笔大额支出 Top 10
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


# ===================== 对比功能 =====================

def _extract_metrics(df: pd.DataFrame) -> dict:
    """
    从处理后的 DataFrame 提取核心指标。
    返回：总收入、净支出、净结余、支出分类、小额高频统计。
    """
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
            次数=("实际金额", "count"),
            总计=("实际金额", "sum")
        )
        freq = freq[freq["次数"] >= 5]
        for cat, row in freq.iterrows():
            freq_small[cat] = {"次数": int(row["次数"]), "总额": row["总计"]}

    return {
        "总收入": total_income,
        "净支出": real_expense,
        "净结余": net_balance,
        "支出分类": expense_by_cat,
        "收入分类": income_by_cat,
        "小额高频": freq_small,
    }


def generate_comparison_summary(df_current, df_previous,
                                period_label_current: str,
                                period_label_previous: str) -> str:
    """对比两个周期的财务数据，生成文本摘要"""
    cur = _extract_metrics(df_current)
    prev = _extract_metrics(df_previous)

    lines = [f"同期对比：{period_label_previous} → {period_label_current}"]

    # 核心指标变动
    lines.append("\n【核心指标变动】")
    exp_cur, exp_prev = cur["净支出"], prev["净支出"]
    exp_change = exp_cur - exp_prev
    exp_pct = exp_change / exp_prev * 100 if exp_prev else 0
    lines.append(f"净支出：¥{exp_prev:.2f} → ¥{exp_cur:.2f}，{exp_change:+.2f}元（{exp_pct:+.1f}%）")

    bal_cur, bal_prev = cur["净结余"], prev["净结余"]
    bal_change = bal_cur - bal_prev
    lines.append(f"净结余：¥{bal_prev:.2f} → ¥{bal_cur:.2f}，{bal_change:+.2f}元")

    inc_cur, inc_prev = cur["总收入"], prev["总收入"]
    if inc_prev > 0 or inc_cur > 0:
        lines.append(f"总收入：¥{inc_prev:.2f} → ¥{inc_cur:.2f}")

    # 分类支出变动
    lines.append("\n【分类支出变动（按真实净支出）】")
    cat_cur, cat_prev = cur["支出分类"], prev["支出分类"]
    all_cats = sorted(set(cat_cur.keys()) | set(cat_prev.keys()),
                      key=lambda c: cat_cur.get(c, 0) + cat_prev.get(c, 0), reverse=True)
    for cat in all_cats:
        prev_val = cat_prev.get(cat, 0)
        cur_val = cat_cur.get(cat, 0)
        change = cur_val - prev_val
        if prev_val == 0:
            lines.append(f"  {cat}：¥{prev_val:.2f} → ¥{cur_val:.2f}（新增）")
        else:
            pct = change / prev_val * 100
            lines.append(f"  {cat}：¥{prev_val:.2f} → ¥{cur_val:.2f}，{change:+.2f}元（{pct:+.1f}%）")

    # 高频小额变动
    small_cur, small_prev = cur["小额高频"], prev["小额高频"]
    all_small_cats = set(small_cur.keys()) | set(small_prev.keys())
    if all_small_cats:
        lines.append("\n【高频小额变动（单笔≤30元，出现≥5次的类别）】")
        for cat in all_small_cats:
            p_cnt = small_prev.get(cat, {"次数": 0, "总额": 0.0})
            c_cnt = small_cur.get(cat, {"次数": 0, "总额": 0.0})
            lines.append(f"  {cat}：{p_cnt['次数']}次 ¥{p_cnt['总额']:.2f} → {c_cnt['次数']}次 ¥{c_cnt['总额']:.2f}")

    return "\n".join(lines)
