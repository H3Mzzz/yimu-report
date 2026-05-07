# html_renderer.py — 将纯文本报告转换为 HTML 邮件
# 负责：文本解析 → HTML 结构化 → 内联 CSS 样式（兼容各邮件客户端）

import re
import io
import base64

# ═══════════════════════════════════════════════════════════
# CSS 样式（全部内联，确保邮件客户端兼容性）
# ═══════════════════════════════════════════════════════════

_CSS_RESET = "margin:0;padding:0;"
_CSS_BODY = (
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',"
    "Arial,'PingFang SC','Microsoft YaHei',sans-serif;"
    "font-size:15px;line-height:1.7;color:#1a1a2e;background:#f0f2f5;padding:20px 0;"
)
_CSS_CONTAINER = (
    "max-width:640px;margin:0 auto;background:#ffffff;"
    "border-radius:12px;overflow:hidden;"
    "box-shadow:0 2px 12px rgba(0,0,0,0.08);"
)
_CSS_HEADER = (
    "background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);"
    "color:#ffffff;padding:28px 32px;text-align:center;"
)
_CSS_HEADER_TITLE = "font-size:22px;font-weight:700;margin-bottom:4px;letter-spacing:0.5px;"
_CSS_HEADER_SUB = "font-size:13px;opacity:0.85;"
_CSS_CONTENT = "padding:28px 32px;"
_CSS_SECTION = "margin-bottom:24px;"
_CSS_H2 = (
    "font-size:17px;font-weight:700;color:#2d3748;"
    "margin:28px 0 12px 0;padding-bottom:8px;"
    "border-bottom:2px solid #e2e8f0;"
)
_CSS_H2_FIRST = (
    "font-size:17px;font-weight:700;color:#2d3748;"
    "margin:0 0 12px 0;padding-bottom:8px;"
    "border-bottom:2px solid #e2e8f0;"
)
_CSS_METRIC_CARD = (
    "display:inline-block;background:#f7fafc;border:1px solid #e2e8f0;"
    "border-radius:8px;padding:12px 16px;margin:4px 6px 4px 0;min-width:120px;"
    "text-align:center;"
)
_CSS_METRIC_VALUE = "font-size:20px;font-weight:700;color:#5a67d8;display:block;"
_CSS_METRIC_LABEL = "font-size:12px;color:#718096;display:block;margin-top:2px;"
_CSS_P = "margin:8px 0;color:#4a5568;font-size:14.5px;"
_CSS_UL = "margin:8px 0 8px 0;padding-left:0;list-style:none;"
_CSS_OL = "margin:8px 0 8px 20px;padding-left:0;"
_CSS_LI = "margin:5px 0;color:#4a5568;font-size:14px;"
_CSS_LI_UL = "margin:5px 0;color:#4a5568;font-size:14px;padding-left:16px;"
_CSS_STRONG = "color:#2d3748;font-weight:600;"

_CSS_TABLE = (
    "width:100%;border-collapse:collapse;margin:12px 0;"
    "font-size:13px;color:#4a5568;"
)
_CSS_TH = (
    "background:#f7fafc;border:1px solid #e2e8f0;"
    "padding:8px 12px;text-align:left;font-weight:600;color:#2d3748;"
)
_CSS_TD = (
    "border:1px solid #e2e8f0;padding:8px 12px;"
)

_CSS_FOOTER = (
    "padding:16px 32px;background:#f7fafc;border-top:1px solid #e2e8f0;"
    "text-align:center;font-size:12px;color:#a0aec0;"
)
_CSS_DIVIDER = "border:none;border-top:1px solid #e2e8f0;margin:20px 0;"


# ═══════════════════════════════════════════════════════════
# 饼图生成（matplotlib → base64 PNG）
# ═══════════════════════════════════════════════════════════

def _generate_pie_chart_html(data: dict, title: str) -> str:
    """将分类数据渲染为饼图，返回含 base64 图片的 HTML 片段"""
    if not data:
        return ""

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "SimHei", "PingFang SC",
            "WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans",
        ]
        plt.rcParams["axes.unicode_minus"] = False

        sorted_data = sorted(data.items(), key=lambda x: x[1], reverse=True)
        labels = [d[0] for d in sorted_data]
        values = [d[1] for d in sorted_data]

        if not any(v > 0 for v in values):
            return ""

        colors = [
            "#667eea", "#764ba2", "#f093fb", "#f5576c", "#4facfe",
            "#00f2fe", "#43e97b", "#38f9d7", "#fa709a", "#fee140",
            "#a18cd1", "#fbc2eb", "#8fd3f4", "#84fab0", "#cfd9df",
        ]

        fig, ax = plt.subplots(figsize=(5.5, 3.5), dpi=150)
        fig.patch.set_facecolor("white")

        wedges, texts, autotexts = ax.pie(
            values, labels=None, autopct="",
            colors=colors[: len(values)], startangle=90,
            wedgeprops={"linewidth": 1, "edgecolor": "white"},
        )

        # 图例放在右侧
        legend_labels = [f"{l}  ¥{v:,.0f}" for l, v in zip(labels, values)]
        legend = ax.legend(
            wedges, legend_labels, loc="center left",
            bbox_to_anchor=(1.02, 0.5), fontsize=8, frameon=False,
        )

        # 百分比标签叠在扇区上（仅占比 > 5% 的显示）
        total = sum(values)
        for i, (w, v) in enumerate(zip(wedges, values)):
            pct = v / total * 100
            if pct >= 5:
                ang = (w.theta2 + w.theta1) / 2.0
                x = 0.65 * __import__("math").cos(__import__("math").radians(ang))
                y = 0.65 * __import__("math").sin(__import__("math").radians(ang))
                ax.text(x, y, f"{pct:.0f}%", ha="center", va="center",
                        fontsize=8, color="white", fontweight="bold")

        ax.set_title(title, fontsize=12, fontweight="bold", pad=12)
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("ascii")

        return (
            f'<div style="text-align:center;margin:16px 0;">'
            f'<img src="data:image/png;base64,{b64}" '
            f'style="max-width:100%;height:auto;" alt="{title}">'
            f"</div>"
        )

    except Exception as e:
        print(f"⚠️ 饼图生成失败: {e}")
        return ""


# ═══════════════════════════════════════════════════════════
# 文本解析辅助
# ═══════════════════════════════════════════════════════════

def _escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _apply_inline_formatting(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', rf'<strong style="{_CSS_STRONG}">\1</strong>', text)
    return text


def _render_metric_cards(lines: list[str]) -> str:
    """将核心指标行渲染为卡片组"""
    cards = []
    for line in lines:
        m = re.match(r'^[-•]\s*(.+?)[：:]\s*(.+)$', line.strip())
        if m:
            label = m.group(1).strip()
            value = m.group(2).strip()
            cards.append(
                f'<div style="{_CSS_METRIC_CARD}">'
                f'<span style="{_CSS_METRIC_VALUE}">{_escape(value)}</span>'
                f'<span style="{_CSS_METRIC_LABEL}">{_escape(label)}</span>'
                f'</div>'
            )
    if cards:
        return f'<div style="margin:12px 0;text-align:center;">{"".join(cards)}</div>'
    return ""


def _render_table(header: list[str], rows: list[list[str]]) -> str:
    """将 Markdown 表格渲染为 HTML table"""
    html = f'<table style="{_CSS_TABLE}"><thead><tr>'
    for cell in header:
        html += f'<th style="{_CSS_TH}">{_apply_inline_formatting(_escape(cell))}</th>'
    html += "</tr></thead><tbody>"
    for row in rows:
        html += "<tr>"
        for cell in row:
            html += f'<td style="{_CSS_TD}">{_apply_inline_formatting(_escape(cell))}</td>'
        html += "</tr>"
    html += "</tbody></table>"
    return html


# ═══════════════════════════════════════════════════════════
# 主解析器
# ═══════════════════════════════════════════════════════════

def _parse_report_text(text: str, charts: dict = None) -> str:
    """
    将纯文本报告解析为 HTML 片段。

    charts: {标题文本: chart_html} — 在对应 ## 标题的列表后注入图表
    """
    lines = text.split("\n")
    html_parts = []
    i = 0
    first_h2 = True

    while i < len(lines):
        line = lines[i].rstrip()

        # 空行跳过
        if not line.strip():
            i += 1
            continue

        # --- 分隔线 ---
        if re.match(r'^-{3,}$', line.strip()):
            html_parts.append(f'<hr style="{_CSS_DIVIDER}">')
            i += 1
            continue

        # Markdown 表格（连续的 | 开头行）
        if line.strip().startswith("|") and line.strip().endswith("|"):
            table_rows = []
            while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                table_rows.append(cells)
                i += 1
            if len(table_rows) >= 2 and all(re.match(r'^[-:]+$', c.strip()) for c in table_rows[1]):
                html_parts.append(_render_table(table_rows[0], table_rows[2:]))
            elif table_rows:
                html_parts.append(_render_table(table_rows[0], table_rows[1:]))
            continue

        # Markdown 标题 ## xxx 或 ### xxx
        h_match = re.match(r'^(#{2,3})\s+(.+)', line.strip())
        if h_match:
            level = len(h_match.group(1))
            heading_text = h_match.group(2).strip()
            if level == 2:
                style = _CSS_H2_FIRST if first_h2 else _CSS_H2
                html_parts.append(f'<h2 style="{style}">{_escape(heading_text)}</h2>')
            else:
                html_parts.append(
                    f'<h3 style="font-size:15px;font-weight:600;color:#4a5568;margin:16px 0 8px;">'
                    f'{_escape(heading_text)}</h3>'
                )
            first_h2 = False
            i += 1

            # 如果此标题有对应图表：先收集后续列表项，再注入图表
            if charts and level == 2 and heading_text in charts:
                ul_items = []
                while i < len(lines):
                    m = re.match(r'^[-•*]\s+(.+)', lines[i].strip())
                    if m:
                        content = _apply_inline_formatting(_escape(m.group(1)))
                        ul_items.append(f'<li style="{_CSS_LI}">{content}</li>')
                        i += 1
                    elif lines[i].strip() == "":
                        i += 1
                        continue
                    else:
                        break
                if ul_items:
                    html_parts.append(f'<ul style="{_CSS_UL}">{"".join(ul_items)}</ul>')
                html_parts.append(charts[heading_text])
            continue

        # 中文数字标题
        m = re.match(r'^[一二三四五六七八九十]+[、.．]\s*(.+)', line.strip())
        if m:
            style = _CSS_H2_FIRST if first_h2 else _CSS_H2
            html_parts.append(f'<h2 style="{style}">{_escape(m.group(1).strip())}</h2>')
            first_h2 = False
            i += 1
            continue

        # 📊 数据摘要标题
        if line.strip().startswith("📊"):
            html_parts.append(f'<h2 style="{_CSS_H2_FIRST}">{_escape(line.strip())}</h2>')
            first_h2 = False
            i += 1
            desc_lines = []
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(
                ("-", "•", "1", "2", "3", "4", "5", "6", "7", "8", "9",
                 "📊", "🗺", "📍", "🚨", "☕", "#", "|")
            ):
                desc_lines.append(lines[i].strip())
                i += 1
            if desc_lines:
                p_text = " ".join(desc_lines)
                html_parts.append(f'<p style="{_CSS_P}">{_apply_inline_formatting(_escape(p_text))}</p>')
            continue

        # 🗺️ / 📍 区域区块（旧格式兼容：破折号列表）
        if line.strip().startswith(("🗺️", "📍")):
            title = line.strip()
            is_noise = line.strip().startswith("📍")
            i += 1
            detail_lines = []
            while i < len(lines) and lines[i].strip().startswith("-"):
                detail_lines.append(lines[i].strip().lstrip("- ").strip())
                i += 1
            # 如果紧跟的是表格，不收集（表格已由表格处理器处理）
            card_style = (
                "background:#fffaf0;border:1px solid #feebc8;border-radius:8px;"
                "padding:12px 16px;margin:8px 0;"
            ) if is_noise else (
                "background:#f0fff4;border:1px solid #c6f6d5;border-radius:8px;"
                "padding:12px 16px;margin:8px 0;"
            )
            html = f'<div style="{card_style}">'
            html += f'<div style="font-size:14px;font-weight:600;color:#276749;margin-bottom:4px;">{_escape(title)}</div>'
            for dl in detail_lines:
                html += f'<div style="font-size:13px;color:#4a5568;">{_apply_inline_formatting(_escape(dl))}</div>'
            html += "</div>"
            html_parts.append(html)
            continue

        # 🚨 大额支出标题
        if line.strip().startswith("🚨"):
            html_parts.append(
                f'<h3 style="font-size:15px;font-weight:600;color:#e53e3e;margin:16px 0 8px;">'
                f'{_escape(line.strip())}</h3>'
            )
            i += 1
            continue

        # ☕ 频繁小额支出
        if line.strip().startswith("☕"):
            html_parts.append(
                f'<h3 style="font-size:15px;font-weight:600;color:#975a16;margin:16px 0 8px;">'
                f'{_escape(line.strip())}</h3>'
            )
            i += 1
            continue

        # 核心指标区块：连续的 "- 💰/💸/🏦/📈 ..." 行
        metric_pat = re.compile(r'^[-•]\s*[💰💸🏦📈]')
        if metric_pat.match(line.strip()):
            metric_lines = []
            while i < len(lines) and metric_pat.match(lines[i].strip()):
                metric_lines.append(lines[i].strip())
                i += 1
            html_parts.append(_render_metric_cards(metric_lines))
            continue

        # 数字列表项
        ol_match = re.match(r'^(\d+)\.\s+(.+)', line.strip())
        if ol_match:
            ol_items = []
            while i < len(lines):
                m = re.match(r'^(\d+)\.\s+(.+)', lines[i].strip())
                if m:
                    ol_items.append(_apply_inline_formatting(_escape(m.group(2))))
                    i += 1
                else:
                    break
            items_html = "".join(f'<li style="{_CSS_LI}">{item}</li>' for item in ol_items)
            html_parts.append(f'<ol style="{_CSS_OL}">{items_html}</ol>')
            continue

        # 破折号/星号列表项
        ul_match = re.match(r'^(\s*)[-•*]\s+(.+)', line)
        if ul_match:
            ul_items = []
            while i < len(lines):
                m = re.match(r'^(\s*)[-•*]\s+(.+)', lines[i])
                if m:
                    indent = len(m.group(1))
                    content = _apply_inline_formatting(_escape(m.group(2)))
                    style = _CSS_LI_UL if indent > 0 else _CSS_LI
                    ul_items.append(f'<li style="{style}">{content}</li>')
                    i += 1
                elif lines[i].strip() == "":
                    i += 1
                    continue
                else:
                    break
            html_parts.append(f'<ul style="{_CSS_UL}">{"".join(ul_items)}</ul>')
            continue

        # 普通段落
        para_lines = [line.strip()]
        i += 1
        while (i < len(lines) and lines[i].strip()
               and not re.match(r'^[-•*]\s', lines[i])
               and not re.match(r'^\d+\.\s', lines[i])
               and not re.match(r'^[一二三四五六七八九十]+[、.]', lines[i])
               and not lines[i].strip().startswith(("📊", "🗺", "📍", "🚨", "☕", "---", "##", "|"))):
            para_lines.append(lines[i].strip())
            i += 1
        p_text = " ".join(para_lines)
        html_parts.append(f'<p style="{_CSS_P}">{_apply_inline_formatting(_escape(p_text))}</p>')

    return "\n".join(html_parts)


# ═══════════════════════════════════════════════════════════
# 邮件组装
# ═══════════════════════════════════════════════════════════

def build_html_email(
    summary: str, report: str, period_label: str, today_str: str,
    metrics: dict = None,
) -> str:
    """
    将数据摘要 + AI 报告组装成完整 HTML 邮件。

    metrics: 可选，包含 收入分类/支出分类 等字段，用于生成饼图
    """
    # 生成饼图
    charts = {}
    if metrics:
        income_chart = _generate_pie_chart_html(metrics.get("收入分类", {}), "收入构成")
        expense_chart = _generate_pie_chart_html(metrics.get("支出分类", {}), "支出构成")
        if income_chart:
            charts["收入来源明细"] = income_chart
        if expense_chart:
            charts["支出分类全景"] = expense_chart

    summary_html = _parse_report_text(summary, charts=charts)
    report_html = _parse_report_text(report)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="{_CSS_RESET}{_CSS_BODY}">
<div style="{_CSS_CONTAINER}">

  <!-- 头部 -->
  <div style="{_CSS_HEADER}">
    <div style="{_CSS_HEADER_TITLE}">💰 财务报告</div>
    <div style="{_CSS_HEADER_SUB}">{_escape(period_label)} · {_escape(today_str)}</div>
  </div>

  <!-- 数据摘要 -->
  <div style="{_CSS_CONTENT}">
    <div style="{_CSS_SECTION}">
      {summary_html}
    </div>

    <hr style="{_CSS_DIVIDER}">

    <!-- AI 分析报告 -->
    <div style="{_CSS_SECTION}">
      {report_html}
    </div>
  </div>

  <!-- 页脚 -->
  <div style="{_CSS_FOOTER}">
    一木 Report · 自动生成 · Powered by DeepSeek
  </div>

</div>
</body>
</html>'''
