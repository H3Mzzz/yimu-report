#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财务助手记忆模块 —— 持久化关键洞察，让 AI 有"人设"和"长期记忆"。

每次报告生成后：
1. 从生成的报告中提取关键信息，持久化到 memory/ 目录
2. 下次报告时，读取历史记忆，注入到 prompt 中
"""

import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

MEMORY_DIR = Path(os.environ.get("MEMORY_DIR", "/root/cow/memory/bill"))

# ── 记忆文件结构 ──────────────────────────────────────────
# memory/
#   insights.json       # 长期累积的关键洞察（滚动，最多保留 20 条）
#   last_report.json    # 最近一次报告的指标快照（用于下次对比）
#   profile.json        # 用户财务画像（缓慢变化的长期特征）
#   advice_log.json     # 历史建议执行追踪

def _now():
    return datetime.now(timezone(timedelta(hours=8)))

def _ensure_dir():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════
# 1. 财务画像 — 长期缓慢变化的用户特征
# ═══════════════════════════════════════════════════════════

DEFAULT_PROFILE = {
    "monthly_budget": int(os.environ.get("MONTHLY_BUDGET", "2000")),
    "identity": os.environ.get("USER_IDENTITY", ""),
    "known_behavior": [],
    "financial_goals": [],
    "context_notes": [],
    "updated_at": None,
}

def load_profile() -> dict:
    _ensure_dir()
    path = MEMORY_DIR / "profile.json"
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    return DEFAULT_PROFILE.copy()

def save_profile(profile: dict):
    _ensure_dir()
    profile["updated_at"] = _now().isoformat()
    (MEMORY_DIR / "profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), "utf-8"
    )

# ═══════════════════════════════════════════════════════════
# 2. 关键洞察 — 滚动累积（最多 20 条）
# ═══════════════════════════════════════════════════════════


def add_insight_from_report(mode: str, report_text: str, summary_data: dict):
    """
    从报告文本中提取关键洞察并持久化。
    - 日报/周报/月报分开管理，各有独立容量
    - 日报仅保留最近 7 天（有周报覆盖）
    - 周报保留最近 12 期（约 3 个月）
    - 月报永久保留（重要）
    """
    insight = {
        "mode": mode,
        "date": _now().strftime("%Y-%m-%d"),
        "summary": report_text[:300],
        "metrics": {
            "净支出": round(summary_data.get("净支出", 0), 2),
            "净结余": round(summary_data.get("净结余", 0), 2),
            "总收入": round(summary_data.get("总收入", 0), 2),
        },
    }
    _append_mode_insight(mode, insight)


def _append_mode_insight(mode: str, insight: dict):
    """各模式独立文件，避免日报挤掉月报"""
    _ensure_dir()
    path = MEMORY_DIR / f"insights_{mode}.json"
    existing = []
    if path.exists():
        existing = json.loads(path.read_text("utf-8"))

    insight["recorded_at"] = _now().isoformat()
    existing.append(insight)

    # 各模式不同容量
    limits = {"daily": 7, "weekly": 12, "monthly": 99}
    cap = limits.get(mode, 12)
    if len(existing) > cap:
        existing = existing[-cap:]

    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), "utf-8")


def load_insights(mode: str = None, max_count: int = 10) -> list[dict]:
    _ensure_dir()
    if mode:
        path = MEMORY_DIR / f"insights_{mode}.json"
        if path.exists():
            return json.loads(path.read_text("utf-8"))[-max_count:]
        return []

    # 汇总所有模式
    all_insights = []
    for m in ["daily", "weekly", "monthly"]:
        p = MEMORY_DIR / f"insights_{m}.json"
        if p.exists():
            all_insights.extend(json.loads(p.read_text("utf-8")))
    all_insights.sort(key=lambda x: x.get("recorded_at", ""))
    return all_insights[-max_count:]

# ═══════════════════════════════════════════════════════════
# 3. 上次报告快照
# ═══════════════════════════════════════════════════════════

def load_last_report() -> dict | None:
    _ensure_dir()
    path = MEMORY_DIR / "last_report.json"
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    return None

def save_last_report(mode: str, summary_text: str, metrics: dict, report_text: str):
    """
    保存上次报告的「结构化快照」——不存报告原文。

    为什么只存结构化数据：
    - 原文是 AI 的写作风格，注入下次 prompt 会导致语言趋同和认知惯性
    - 结构化指标（金额、类别排行）足够让下次 AI 感知历史趋势
    """
    _ensure_dir()

    # 从 summary 中提取关键结构化信息（不存原文）
    expense_cats = metrics.get("支出分类", {})

    snapshot = {
        "mode": mode,
        "date": _now().strftime("%Y-%m-%d %H:%M"),
        "metrics": {
            "净支出": round(metrics.get("净支出", 0), 2),
            "净结余": round(metrics.get("净结余", 0), 2),
            "总收入": round(metrics.get("总收入", 0), 2),
        },
        "top_expense_categories": dict(
            sorted(expense_cats.items(), key=lambda x: x[1], reverse=True)[:5]
        ),
        "small_item_highlights": {
            cat: {"次数": info["次数"], "总额": round(info["总额"], 2)}
            for cat, info in metrics.get("小额高频", {}).items()
        },
    }
    (MEMORY_DIR / "last_report.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), "utf-8"
    )

# ═══════════════════════════════════════════════════════════
# 4. 建议追踪
# ═══════════════════════════════════════════════════════════

def load_advice_log() -> list[dict]:
    _ensure_dir()
    path = MEMORY_DIR / "advice_log.json"
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    return []

def log_advice(mode: str, advice_text: str):
    """记录本次报告中 AI 给出的建议，供下次追踪"""
    _ensure_dir()
    path = MEMORY_DIR / "advice_log.json"
    existing = load_advice_log()
    # 新建议替换旧建议（同一模式）
    existing = [a for a in existing if a.get("mode") != mode]
    existing.append({
        "mode": mode,
        "date": _now().strftime("%Y-%m-%d"),
        "advice": advice_text,
    })
    # 最多保留 10 条
    path.write_text(json.dumps(existing[-10:], ensure_ascii=False, indent=2), "utf-8")

# ═══════════════════════════════════════════════════════════
# 5. 组装「记忆上下文」— 注入到 Prompt
# ═══════════════════════════════════════════════════════════

def build_memory_context(mode: str) -> str:
    """构建记忆上下文，嵌入到 prompt 的用户背景部分。返回纯文本字符串。"""
    parts = [_profile_context(), _last_report_context(mode), _advice_context(mode), _insights_context(mode)]
    return "\n".join(filter(None, parts))


def _profile_context() -> str:
    profile = load_profile()
    lines = [f"用户画像：{profile['identity']}，月生活费基准约 {profile['monthly_budget']} 元。"]
    if profile.get("known_behavior"):
        lines.append(f"已知消费特征：{'；'.join(profile['known_behavior'])}")
    if profile.get("context_notes"):
        lines.append(f"背景说明：{'；'.join(profile['context_notes'])}")
    return "\n".join(lines)


def _last_report_context(mode: str) -> str:
    last = load_last_report()
    if not last or last.get("mode") != mode:
        return ""
    m = last.get("metrics", {})
    top = last.get("top_expense_categories", {})
    cats_str = "、".join(f"{c}¥{v:.0f}" for c, v in list(top.items())[:3])
    return (
        f"\n上次{mode}报告回顾（{last['date']}）："
        f"净支出¥{m.get('净支出', 0):.0f}，净结余¥{m.get('净结余', 0):.0f}；"
        f"支出前三：{cats_str or '无数据'}。"
    )


def _advice_context(mode: str) -> str:
    advice_log = load_advice_log()
    relevant = [a for a in advice_log if a.get("mode") == mode]
    if not relevant:
        return ""
    return f"\n你上次给出的建议：{relevant[-1]['advice'][:200]}"


def _insights_context(mode: str) -> str:
    insights = load_insights(mode=mode, max_count=5)
    if not insights:
        return ""
    lines = ["\n近期关键洞察（按时间倒序）："]
    for i, ins in enumerate(reversed(insights)):
        lines.append(f"{i+1}. [{ins['date']}] {ins['mode']}报告 — {ins['summary'][:150]}")
    return "\n".join(lines)
