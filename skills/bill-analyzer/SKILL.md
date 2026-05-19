---
name: bill-analyzer
description: 基于本地 xlsx 账单数据进行筛选、统计和分析。适用于：(1) 查询指定时间段的收支明细；(2) 按分类/金额筛选账单；(3) 生成消费摘要报告；(4) 检测小额高频消费（拿铁因子）；(5) 排查大额消费 Top N。数据源来自 knowledge/finance/data/ 目录下的每日备份账单。
metadata:
  requires:
    bins: ["python3"]
    env: []
---

## 数据源

账单文件存放在 `knowledge/finance/data/`，每天 cron 备份时自动更新，滚动保留最近 5 份。

## 用法

所有命令通过 bash 执行，脚本位于本 skill 的 `scripts/` 目录下。

### 列出可用数据

```bash
python3 <base_dir>/scripts/analyze_bills.py --list-files
```

### 最近 N 天

```bash
python3 <base_dir>/scripts/analyze_bills.py --days 7 --json
```

### 指定日期范围

```bash
python3 <base_dir>/scripts/analyze_bills.py --from 2026-05-01 --to 2026-05-07 --json
```

### 本月 / 上月

```bash
python3 <base_dir>/scripts/analyze_bills.py --month current --json
python3 <base_dir>/scripts/analyze_bills.py --month last --json
```

### 按分类筛选

```bash
python3 <base_dir>/scripts/analyze_bills.py --days 30 --category 餐饮 --json
```

### 按金额筛选

```bash
python3 <base_dir>/scripts/analyze_bills.py --days 30 --min-amount 200 --json
```

### 小额高频检测

```bash
python3 <base_dir>/scripts/analyze_bills.py --days 30 --small-freq --json
```

### 日支出趋势

```bash
python3 <base_dir>/scripts/analyze_bills.py --days 7 --trend --json
```

### 完整报告（所有维度）

```bash
python3 <base_dir>/scripts/analyze_bills.py --days 7 --full
```

### 指定历史数据文件

```bash
python3 <base_dir>/scripts/analyze_bills.py --file bills_2026-05-06 --days 7 --json
```

### What-If 沙盘推演

```bash
# 假设现在要花 500 元，结合预算和历史模式分析影响
python3 <base_dir>/scripts/analyze_bills.py --whatif 500 --json

# 指定月预算（默认从数据库 budget 表读取）
python3 <base_dir>/scripts/analyze_bills.py --whatif 500 --budget 2050 --json
```

输出包含：本月已消费、剩余预算、购买后剩余/日均、风险评估、上月同期参照、月底预计消费趋势等。

### 本月 vs 上月同期对比

```bash
python3 <base_dir>/scripts/analyze_bills.py --compare --json
```

输出包含：本月/上月同期净支出笔数日均对比、各分类变化差额和百分比。

## 参数说明

| 参数 | 说明 |
|------|------|
| `--file` | 指定数据文件名（默认用最新） |
| `--list-files` | 列出可用数据 |
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
| `--json` | JSON 输出（推荐，默认用这个） |

## 输出格式 (JSON)

```json
{
  "文件": "bills_2026-05-07.xlsx",
  "时间范围": "最近 7 天",
  "summary": {
    "总收入": 0.0,
    "净支出": 1234.56,
    "净结余": -1234.56,
    "支出笔数": 45,
    "天数": 7,
    "日均支出": 176.37,
    "储蓄率": null,
    "支出分类": {"餐饮": 500, "交通": 200},
    "分类笔数": {"餐饮": 20, "交通": 10}
  }
}
```

## 使用建议

- **默认加 `--json`**，方便解析
- **完整分析用 `--full`**，生成人类可读的报告文本
- 金额筛选可叠加组合：`--min-amount 50 --max-amount 500 --category 娱乐`
