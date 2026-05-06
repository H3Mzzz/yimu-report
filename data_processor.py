# data_processor.py
import io
import pandas as pd
from datetime import datetime, timedelta
from location_resolver import enrich_transactions, area_summary

MODE_DAYS_MAP = {"daily": 1, "weekly": 7, "monthly": 30}


def parse_transactions(excel_bytes: bytes, mode: str, reference_date: datetime = None) -> tuple[pd.DataFrame, str]:
    """
    解析 Excel，筛选指定时间范围的数据，返回 (DataFrame, 时间描述)
    自动定位列名，合并一级/二级分类，计算真实净支出。

    改动：新增 reference_date 参数，便于生成上一周期数据（测试或非当前时刻调用）。
    """
    df = pd.read_excel(io.BytesIO(excel_bytes))
    print(f"原始数据列：{df.columns.tolist()}  行数：{len(df)}")

    def find_col(keywords):
        for kw in keywords:
            match = next((c for c in df.columns if kw in str(c)), None)
            if match:
                return match
        return None

    # 关键列定位
    date_col = find_col(["日期", "时间", "Date"])
    amount_col = find_col(["金额", "Amount"])
    type_col = find_col(["类型", "收支", "Type"])
    cat_col = find_col(["类别", "分类", "Category"])
    sub_cat_col = find_col(["二级分类", "Subcategory"])
    account_col = find_col(["账户", "Account"])
    refund_col = find_col(["退款", "Refund"])
    disc_col = find_col(["优惠", "Discount"])
    reimb_col = find_col(["报销金额", "报销", "Reimbursement"])
    note_col = find_col(["备注", "摘要", "Note", "Remark"])
    tag_col = find_col(["标签", "Tag"])
    addr_col = find_col(["地址", "Address", "Location"])

    if not all([date_col, amount_col, type_col, cat_col]):
        raise ValueError(f"核心列名识别失败，实际列：{df.columns.tolist()}")

    # 日期处理 & 时间范围筛选
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])

    days = MODE_DAYS_MAP.get(mode, 7)

    # 改动：支持 reference_date，方便生成上一周期时段
    now = reference_date if reference_date else datetime.now()
    if mode.startswith("previous_"):  # 新增上一周期模式解析
        base_mode = mode.replace("previous_", "")
        base_days = MODE_DAYS_MAP.get(base_mode, 7)
        # 结束时间往前推 base_days
        end = now - timedelta(days=base_days)
        start = end - timedelta(days=base_days)
        period_label = f"过去 {base_days} 天（上一周期）"
        df = df[(df[date_col] >= start) & (df[date_col] < end)].copy()
    else:
        cutoff = now - timedelta(days=days)
        period_label = f"过去 {days} 天"
        df = df[df[date_col] >= cutoff].copy()

    # 重命名标准列名（核心列 + 存在的可选列）
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

    # 金额标准化（使用重命名后的列名）
    # 注意：不使用 abs()，保留原始符号——
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
    # 正数支出：扣除退款/优惠/报销，最低为 0
    positive_expense = is_expense & (df["原始金额"] > 0)
    df.loc[positive_expense, "实际金额"] = (
        df.loc[positive_expense, "原始金额"]
        - df.loc[positive_expense, "退款"]
        - df.loc[positive_expense, "优惠"]
        - df.loc[positive_expense, "报销"]
    ).clip(lower=0)
    # 负数支出（报销回血/AA 收款）：保留原值，用于冲抵同类支出

    # 最终分类：优先使用二级分类（若非空），否则使用一级分类
    sub_renamed = rename_map.get(sub_cat_col) if sub_cat_col else None
    df["最终分类"] = df["分类"]
    if sub_renamed and sub_renamed in df.columns:
        has_sub = df[sub_renamed].notna() & (df[sub_renamed].astype(str).str.strip() != "")
        df.loc[has_sub, "最终分类"] = df.loc[has_sub, sub_renamed]

    return df, period_label


def summarize(df: pd.DataFrame, period_label: str) -> str:
    """根据筛选后的 DataFrame 生成详细的文本摘要（供 AI 分析使用）"""
    income_df = df[df["类型"].str.contains("收入", na=False)]
    expense_df = df[df["类型"].str.contains("支出", na=False)]

    total_income = income_df["原始金额"].sum()
    raw_expense = expense_df["原始金额"].sum()
    total_refund = expense_df["退款"].sum() if "退款" in expense_df.columns else 0
    total_disc = expense_df["优惠"].sum() if "优惠" in expense_df.columns else 0
    total_reimb = expense_df["报销"].sum() if "报销" in expense_df.columns else 0
    real_expense = expense_df["实际金额"].sum()
    net_balance = total_income - real_expense

    lines = [
        f"📊 财务数据摘要（{period_label}）",
        f"本周期账面原始总支出 ¥{raw_expense:,.2f}，"
        f"经优惠(¥{total_disc:,.2f})、退款(¥{total_refund:,.2f})、报销抵扣(¥{total_reimb:,.2f})后，"
        f"个人真实净支出为 ¥{real_expense:,.2f}。",
        "",
        "1. 核心指标（真实现金流）",
        f"- 💰总收入：¥{total_income:,.2f}",
        f"- 💸 真实净支出：¥{real_expense:,.2f}",
        f"- 🏦净结余：¥{net_balance:,.2f}",
        f"- 📈储蓄率：{net_balance/total_income*100:.1f}%" if total_income > 0 else "- 储蓄率：无收入数据"
    ]

    # 收入来源明细
    if total_income > 0:
        lines += ["", "2. 收入来源明细"]
        income_by_cat = income_df.groupby("最终分类")["原始金额"].sum().sort_values(ascending=False)
        for cat, amt in income_by_cat.items():
            lines.append(f"- {cat}：¥{amt:,.2f}（{amt/total_income*100:.1f}%）")

    # 支出分类全景（按实际净支出）
    lines += ["", "3. 支出分类全景（按实际净支出）"]
    expense_by_cat = expense_df.groupby("最终分类")["实际金额"].sum().sort_values(ascending=False)
    expense_by_cat = expense_by_cat[expense_by_cat > 0]
    for cat, amt in expense_by_cat.items():
        pct = amt / real_expense * 100 if real_expense else 0
        lines.append(f"- {cat}：¥{amt:,.2f}（{pct:.1f}%）")

    # 频繁小额支出（单笔≤30元，出现≥5次）
    small_expenses = expense_df[expense_df["实际金额"] <= 30]
    if not small_expenses.empty:
        freq_small = small_expenses.groupby("最终分类").agg(
            次数=("实际金额", "count"),
            总计=("实际金额", "sum")
        ).sort_values(by="次数", ascending=False)
        freq_small = freq_small[freq_small["次数"] >= 5]
        if not freq_small.empty:
            lines += ["", "☕ 频繁小额支出（单笔≤30元，出现5次及以上）"]
            for cat, row in freq_small.iterrows():
                lines.append(f"- {cat}：共 {row['次数']} 次，累计 ¥{row['总计']:,.2f}")

    # 区域消费聚合（粗粒度：地址→经纬度→空间聚类 / 行政区划）
    if "地址" in df.columns:
        addr_expense = expense_df[expense_df["地址"].notna() & (expense_df["地址"].astype(str).str.strip() != "")]
        if not addr_expense.empty:
            # 转为 dict 列表传给 location_resolver
            addr_records = addr_expense[["地址", "最终分类", "实际金额"]].copy()
            addr_records.columns = ["address", "category", "amount"]
            records = addr_records.to_dict("records")

            # enrich：附加经纬度 + 行政区划
            enriched = enrich_transactions(records)

            # 空间聚类摘要
            area = area_summary(enriched, eps_meters=300)

            # 空间聚类输出（自动发现高频活动区域，AOI 四级降级标签）
            if area.get("clusters"):
                lines += ["", "🗺️ 高频活动区域（空间聚类，半径300m，AOI标签）"]
                # 计算全局总额用于金额占比
                cluster_total = sum(c["total_amount"] for c in area["clusters"])
                # AOI 类型码映射（高德 POI 大分类编码）
                AOI_TYPE_MAP = {
                    "141201": "🏫 高等院校", "141200": "🏫 学校",
                    "141100": "🏫 学校", "141400": "🏫 学校",
                    "060100": "🛒 购物中心", "060400": "🛒 超市",
                    "050000": "🍽️ 餐饮", "070000": "🍽️ 餐饮",
                    "080000": "🏥 医疗", "100000": "🏨 住宿",
                    "110000": "🏢 写字楼", "120000": "🏠 住宅区",
                }
                SOURCE_CN = {
                    "aoi": "AOI", "business_area": "商圈", "street": "街巷",
                    "township": "乡镇", "keyword_match": "地址提取",
                }
                for c in area["clusters"][:8]:
                    label = c.get("aoi_label", "未知区域")
                    source = SOURCE_CN.get(c.get("label_source", "?"), c.get("label_source", "?"))
                    pct = c["total_amount"] / cluster_total * 100 if cluster_total > 0 else 0
                    aoi_type = c.get("aoi_type", "")
                    type_str = AOI_TYPE_MAP.get(aoi_type[:6], aoi_type) if aoi_type else ""
                    lines.append(
                        f"- {label}（{source}）：{c['count']}笔 / ¥{c['total_amount']:,.2f}"
                        f"（占聚类总额 {pct:.0f}%）| "
                        f"均值 ¥{c['avg_amount']:.2f}"
                        f"{' | ' + type_str if type_str else ''} | "
                        f"主要: {', '.join(f'{k} ¥{v:.0f}' for k, v in list(c.get('top_categories', {}).items())[:3])}"
                    )

            # 孤立点详情（半径300m内不足3笔，逐个展示）
            if area.get("noise"):
                noise_sum = sum(n["total_amount"] for n in area["noise"])
                lines.append("")
                lines.append(f"📍 孤立散点（{len(area['noise'])} 笔，合计 ¥{noise_sum:,.2f}，半径300m内未形成聚簇）")
                # 按金额降序展示
                for n in sorted(area["noise"], key=lambda x: x["total_amount"], reverse=True):
                    p = n["points"][0]
                    addr = p.get("address", "")[:50] or n.get("aoi_label", "?")
                    cat = list(n.get("top_categories", {}).keys())[0] if n.get("top_categories") else "?"
                    lines.append(f"  - {n['aoi_label']} | {cat} | ¥{n['total_amount']:,.2f}（{addr}）")

            # 有地址但无法解析坐标的提示
            if area["stats"]["total_without_location"] > 0:
                lines.append(f"（{area['stats']['total_without_location']}条地址无法解析坐标，未纳入区域分析）")

    # 单笔大额支出 Top 10（仅统计正数支出，排除报销回血等负数条目）
    lines += ["", "🚨 单笔大额支出 Top 10"]
    has_note = "备注" in df.columns
    has_tag = "标签" in df.columns
    top_expenses = expense_df[expense_df["实际金额"] > 0].nlargest(10, "实际金额")
    for _, row in top_expenses.iterrows():
        extras = []
        if has_tag and pd.notna(row.get("标签")) and str(row.get("标签")).strip():
            extras.append(f"🏷️ {row['标签']}")
        if has_note and pd.notna(row.get("备注")) and str(row.get("备注")).strip():
            extras.append(f"📝 {row['备注']}")
        extra_str = f"（{' | '.join(extras)}）" if extras else ""
        lines.append(f"- {row['日期'].strftime('%m/%d')} | {row['最终分类']} | ¥{row['实际金额']:,.2f} {extra_str}")

    return "\n".join(lines)


# ===================== 新增对比功能 =====================

def _extract_metrics(df: pd.DataFrame) -> dict:
    """
    从处理后的 DataFrame 提取核心指标，供对比使用。
    返回字典包含：总收入、净支出、净结余、支出分类、小额高频统计。
    """
    income_df = df[df["类型"].str.contains("收入", na=False)]
    expense_df = df[df["类型"].str.contains("支出", na=False)]

    total_income = income_df["原始金额"].sum()
    real_expense = expense_df["实际金额"].sum()
    net_balance = total_income - real_expense

    # 分类支出字典
    expense_by_cat = expense_df.groupby("最终分类")["实际金额"].sum().to_dict()

    # 小额高频统计
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
        "小额高频": freq_small,
    }


def generate_comparison_summary(df_current, df_previous,
                                period_label_current: str,
                                period_label_previous: str) -> str:
    """
    对比两个周期的财务数据，生成文本摘要（AI 可直接解读）。

    参数：
        df_current:  当前周期的 DataFrame（已 parse 处理）
        df_previous: 上一周期的 DataFrame（已 parse 处理）
        period_label_current:  当前周期描述，如 '本周'
        period_label_previous: 上一周期描述，如 '上周'
    """
    cur = _extract_metrics(df_current)
    prev = _extract_metrics(df_previous)

    lines = [f"同期对比：{period_label_previous} → {period_label_current}"]

    # 1. 核心指标变动
    lines.append("\n【核心指标变动】")
    # 净支出
    exp_cur = cur["净支出"]
    exp_prev = prev["净支出"]
    exp_change = exp_cur - exp_prev
    exp_pct = (exp_change / exp_prev * 100) if exp_prev else 0
    lines.append(f"净支出：¥{exp_prev:.2f} → ¥{exp_cur:.2f}，{'+' if exp_change>0 else ''}¥{exp_change:.2f}（{exp_pct:+.1f}%）")

    # 净结余
    bal_cur = cur["净结余"]
    bal_prev = prev["净结余"]
    bal_change = bal_cur - bal_prev
    lines.append(f"净结余：¥{bal_prev:.2f} → ¥{bal_cur:.2f}，{'+' if bal_change>0 else ''}¥{bal_change:.2f}")

    # 总收入（如果存在）
    inc_cur = cur["总收入"]
    inc_prev = prev["总收入"]
    if inc_prev > 0 or inc_cur > 0:
        lines.append(f"总收入：¥{inc_prev:.2f} → ¥{inc_cur:.2f}")

    # 2. 分类支出变动
    lines.append("\n【分类支出变动（按真实净支出）】")
    cat_cur = cur["支出分类"]
    cat_prev = prev["支出分类"]
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
            lines.append(f"  {cat}：¥{prev_val:.2f} → ¥{cur_val:.2f}，{'+' if change>0 else ''}¥{change:.2f}（{pct:+.1f}%）")

    # 3. 高频小额变动（简要）
    small_cur = cur["小额高频"]
    small_prev = prev["小额高频"]
    all_small_cats = set(small_cur.keys()) | set(small_prev.keys())
    if all_small_cats:
        lines.append("\n【高频小额变动（单笔≤30元，出现≥5次的类别）】")
        for cat in all_small_cats:
            p_cnt = small_prev.get(cat, {"次数": 0, "总额": 0.0})
            c_cnt = small_cur.get(cat, {"次数": 0, "总额": 0.0})
            lines.append(f"  {cat}：{p_cnt['次数']}次 ¥{p_cnt['总额']:.2f} → {c_cnt['次数']}次 ¥{c_cnt['总额']:.2f}")

    return "\n".join(lines)