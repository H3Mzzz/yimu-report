# html_renderer.py — 将纯文本报告转换为 HTML 邮件
# 负责：文本解析 → HTML 结构化 → 内联 CSS 样式（兼容各邮件客户端）

import re

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
_CSS_AREA_CARD = (
    "background:#f0fff4;border:1px solid #c6f6d5;border-radius:8px;"
    "padding:12px 16px;margin:8px 0;"
)
_CSS_AREA_TITLE = "font-size:14px;font-weight:600;color:#276749;margin-bottom:4px;"
_CSS_AREA_DETAIL = "font-size:13px;color:#4a5568;"
_CSS_NOISE_CARD = (
    "background:#fffaf0;border:1px solid #feebc8;border-radius:8px;"
    "padding:12px 16px;margin:8px 0;"
)
_CSS_EXPENSE_CARD = (
    "background:#fed7d7;border:1px solid #feb2b2;border-radius:6px;"
    "padding:8px 12px;margin:4px 0;font-size:13px;color:#9b2c2c;"
)
_CSS_FOOTER = (
    "padding:16px 32px;background:#f7fafc;border-top:1px solid #e2e8f0;"
    "text-align:center;font-size:12px;color:#a0aec0;"
)
_CSS_DIVIDER = "border:none;border-top:1px solid #e2e8f0;margin:20px 0;"


def _escape(text: str) -> str:
    """HTML 转义"""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _apply_inline_formatting(text: str) -> str:
    """处理行内格式：加粗、emoji 保留"""
    # 加粗 **text**
    text = re.sub(r'\*\*(.+?)\*\*', rf'<strong style="{_CSS_STRONG}">\1</strong>', text)
    return text


def _is_data_section(text: str) -> bool:
    """判断是否为数据摘要区（summary）"""
    return "📊 财务数据摘要" in text


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


def _render_area_block(title_line: str, detail_lines: list[str], is_noise: bool = False) -> str:
    """渲染高频活动区域或孤立散点卡片"""
    card_style = _CSS_NOISE_CARD if is_noise else _CSS_AREA_CARD
    title_style = _CSS_AREA_TITLE
    html = f'<div style="{card_style}">'
    html += f'<div style="{title_style}">{_escape(title_line)}</div>'
    for line in detail_lines:
        line = _apply_inline_formatting(_escape(line))
        html += f'<div style="{_CSS_AREA_DETAIL}">{line}</div>'
    html += '</div>'
    return html


def _parse_report_text(text: str) -> str:
    """
    将纯文本报告解析为 HTML 片段。
    
    处理逻辑：
    1. 中文数字标题（一、二、三…）→ h2
    2. emoji 开头的区块标题（📊 🗺️ 📍 🚨 ☕）→ 特殊渲染
    3. 数字列表（1. 2. 3.）→ ol
    4. 破折号列表（- xxx）→ ul
    5. 分隔线（---）→ hr
    6. 普通段落 → p
    """
    lines = text.split('\n')
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

        # Markdown 标题 ## xxx 或 ### xxx
        h_match = re.match(r'^(#{2,3})\s+(.+)', line.strip())
        if h_match:
            level = len(h_match.group(1))
            if level == 2:
                style = _CSS_H2_FIRST if first_h2 else _CSS_H2
                html_parts.append(f'<h2 style="{style}">{_escape(h_match.group(2).strip())}</h2>')
            else:
                html_parts.append(f'<h3 style="font-size:15px;font-weight:600;color:#4a5568;margin:16px 0 8px;">{_escape(h_match.group(2).strip())}</h3>')
            first_h2 = False
            i += 1
            continue

        # 中文数字标题：一、二、三、... 或 一、
        m = re.match(r'^[一二三四五六七八九十]+[、.．]\s*(.+)', line.strip())
        if m:
            style = _CSS_H2_FIRST if first_h2 else _CSS_H2
            html_parts.append(f'<h2 style="{style}">{_escape(m.group(1).strip())}</h2>')
            first_h2 = False
            i += 1
            continue

        # 📊 数据摘要标题
        if line.strip().startswith('📊'):
            html_parts.append(f'<h2 style="{_CSS_H2_FIRST}">{_escape(line.strip())}</h2>')
            first_h2 = False
            i += 1
            # 收集紧跟的描述段落（非列表）
            desc_lines = []
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(('-', '•', '1', '2', '3', '4', '5', '6', '7', '8', '9', '📊', '🗺', '📍', '🚨', '☕')):
                desc_lines.append(lines[i].strip())
                i += 1
            if desc_lines:
                p_text = ' '.join(desc_lines)
                html_parts.append(f'<p style="{_CSS_P}">{_apply_inline_formatting(_escape(p_text))}</p>')
            continue

        # 🗺️ 高频活动区域
        if line.strip().startswith('🗺️'):
            title = line.strip()
            i += 1
            detail_lines = []
            while i < len(lines) and lines[i].strip().startswith('-'):
                detail_lines.append(lines[i].strip().lstrip('- ').strip())
                i += 1
            html_parts.append(_render_area_block(title, detail_lines, is_noise=False))
            continue

        # 📍 孤立散点
        if line.strip().startswith('📍'):
            title = line.strip()
            i += 1
            detail_lines = []
            while i < len(lines) and (lines[i].strip().startswith('-') or lines[i].strip().startswith('  -')):
                detail_lines.append(lines[i].strip().lstrip(' -').strip())
                i += 1
            html_parts.append(_render_area_block(title, detail_lines, is_noise=True))
            continue

        # 🚨 大额支出标题
        if line.strip().startswith('🚨'):
            html_parts.append(f'<h3 style="font-size:15px;font-weight:600;color:#e53e3e;margin:16px 0 8px;">{_escape(line.strip())}</h3>')
            i += 1
            continue

        # ☕ 频繁小额支出
        if line.strip().startswith('☕'):
            html_parts.append(f'<h3 style="font-size:15px;font-weight:600;color:#975a16;margin:16px 0 8px;">{_escape(line.strip())}</h3>')
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

        # 数字列表项：1. 2. 3. ...
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
            items_html = ''.join(f'<li style="{_CSS_LI}">{item}</li>' for item in ol_items)
            html_parts.append(f'<ol style="{_CSS_OL}">{items_html}</ol>')
            continue

        # 破折号或星号列表项：- xxx 或 * xxx（缩进的子项也算）
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
                elif lines[i].strip() == '':
                    i += 1
                    continue
                else:
                    break
            html_parts.append(f'<ul style="{_CSS_UL}">{"".join(ul_items)}</ul>')
            continue

        # 普通段落
        para_lines = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r'^[-•*]\s', lines[i]) and not re.match(r'^\d+\.\s', lines[i]) and not re.match(r'^[一二三四五六七八九十]+[、.]', lines[i]) and not lines[i].strip().startswith(('📊', '🗺', '📍', '🚨', '☕', '---', '##')):
            para_lines.append(lines[i].strip())
            i += 1
        p_text = ' '.join(para_lines)
        html_parts.append(f'<p style="{_CSS_P}">{_apply_inline_formatting(_escape(p_text))}</p>')

    return '\n'.join(html_parts)


def build_html_email(summary: str, report: str, period_label: str, today_str: str) -> str:
    """
    将数据摘要 + AI 报告组装成完整 HTML 邮件。

    参数：
        summary: 数据摘要纯文本
        report: AI 生成的报告纯文本
        period_label: 周期标签，如 "过去 1 天"
        today_str: 日期字符串，如 "2026年05月07日"
    """
    # 分别渲染摘要和报告
    summary_html = _parse_report_text(summary)
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
