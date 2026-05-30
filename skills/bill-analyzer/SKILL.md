---
name: bill-analyzer
description: 基于本地 SQLite (Custom.db) 账单数据进行筛选、统计和分析。适用于：(1) 查询指定时间段的收支明细；(2) 按分类/金额筛选账单；(3) 生成消费摘要报告；(4) 检测小额高频消费（拿铁因子）；(5) 排查大额消费 Top N。数据源为一木记账 App 原始数据库，通过 sync_db.py 从坚果云同步。
metadata:
  requires:
    bins: ["python3", "7z"]
    env: []
---

## 数据源

账单数据库 `Custom.db` 存放在 `~/cow/knowledge/finance/data/`，通过 `sync_db.py` 从坚果云同步。

## 用法

所有命令通过 bash 执行，脚本位于 `~/.hermes/skills/bill-analyzer/scripts/` 下。

```bash
# 最近 N 天
python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --days 7 --json

# 指定日期范围
python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --from 2026-05-01 --to 2026-05-07 --json

# 本月 / 上月
python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --month current --json
python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --month last --json

# 按分类筛选
python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --days 30 --category 餐饮 --json

# 按金额筛选
python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --days 30 --min-amount 200 --json

# 小额高频检测
python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --days 30 --small-freq --json

# 日支出趋势
python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --days 7 --trend --json

# 完整报告（所有维度）
python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --days 7 --full

# What-If 沙盘（预算从数据库读取）
python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --whatif 500 --json

# 本月 vs 上月同期对比
python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --compare --json
```

> ⚠️ `--to` 参数包含当天全部交易（23:59:59）。查全天用 `--from 2026-05-16 --to 2026-05-16`。

## 参数说明

| 参数 | 说明 |
|------|------|
| `--from` / `--to` | 日期范围 YYYY-MM-DD |
| `--days` | 最近 N 天 |
| `--month` | current(本月) / last(上月) |
| `--category` | 分类筛选（模糊） |
| `--min-amount` / `--max-amount` | 金额范围 |
| `--small-freq` | 小额高频检测 |
| `--top N` | 大额消费 Top N |
| `--trend` | 日支出趋势 |
| `--compare` | 本月 vs 上月同期对比 |
| `--whatif N` | What-If 沙盘（假设消费 N 元） |
| `--budget N` | 月预算（配合 --whatif，默认从数据库读取） |
| `--full` | 完整报告（文本格式） |
| `--json` | JSON 输出（推荐） |

## 使用建议

- **默认加 `--json`**，方便解析
- **完整分析用 `--full`**，生成人类可读的报告文本
- 金额筛选可叠加组合：`--min-amount 50 --max-amount 500 --category 娱乐`

## 查询账户余额

余额在 `asset` 表的 `assetnumber` 字段（不是 `balance`）：

```python
import sqlite3
conn = sqlite3.connect('/root/cow/knowledge/finance/data/Custom.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT assetname, assetnumber, groupname
    FROM asset
    WHERE delete_lpcolumn = 0 AND assetnumber != 0
    ORDER BY assetnumber DESC
''')
```

## 知识库文件管理

| 文件 | 用途 | 生命周期 |
|------|------|---------|
| `daily-insights.md` | 每日关键信息 | 滚动 30 条 |
| `weekly-insights.md` | 每周关键信息 | 滚动 12 条 |
| `monthly-insights.md` | 月度汇总 | 永久 |
| `consumption-profile.md` | 长期消费画像 | 永久 |
| `budget-config.md` | 预算配置 | 永久 |
| `agent-evolution.md` | 分析策略演进 | 永久 |

**日报/周报记录原则**：只记值得 30 天后回看的关键信息。详见 `references/daily-recording-principles.md`。

**文件结构**：`##` = ISO 周标题，`###` = 日期，`---` = 分隔线。裁剪脚本按 `---` 分割。

## 项目结构

统一仓库 `H3Mzzz/yimu-report`（`~/yimu-report/`）。修改后需同步运行时副本，详见 `references/hermes-config-pitfalls.md`。

## Pitfalls 参考

详细的历史问题排查手册在 `references/` 目录，按需读取：

| 文件 | 内容 |
|------|------|
| `references/report-pitfalls.md` | 饼图注入、发送脚本选择、地点聚类丢失、幽灵监控、晚补数据 |
| `references/data-pitfalls.md` | cost 语义、退款表、SQLite 时间过滤、预算来源、毛额vs净额 |
| `references/csv-analysis.md` | CSV Schema 对照、分析 pitfalls、净额计算 |
| `references/hermes-config-pitfalls.md` | Provider 命名、配置污染、双副本、pipe-to-interpreter |
| `references/privacy-pitfalls.md` | templates/ 真实数据泄露 |
| `references/refund-table.md` | 退款表结构和查询 |
| `references/budget-schema.md` | 预算表结构 |
| `references/asset-schema.md` | 资产表结构 |
