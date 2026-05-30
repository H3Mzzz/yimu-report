# 数据分析 Pitfalls

## cost 语义

`cost` 已是 App 处理后的值。正数=支出/收入，负数=报销/退款抵消。全额退款 cost 已被 App 清零。**不要取 ABS(cost)**。

## 收支判断

靠 `parentcategoryid=9`（收入类），不靠 billtype 或 cost 符号。

## 退款表

全额退款后 `bill.cost` 被清零，退款详情在 `refund` 表（关联 `refund_refundinfos`）。`data_processor.py` 已修复（`_REFUND_SQL`）。

⚠️ `analyze_bills.py` 独立分析（`--days`/`--from`）不查 refund 表。cron 路径不受影响（走 `data_processor.py`）。

### 退款 SQL 常见错误

**① `LIMIT 1` 丢备注**：`refund_refundinfos` 可能有多条记录，应用 `GROUP_CONCAT`：
```sql
-- ✅ 取全部非空备注
NULLIF(
    (SELECT GROUP_CONCAT(json_extract(ri.refundinfos, '$.remark'), '; ')
     FROM refund_refundinfos ri
     WHERE ri.refund_id = r.id
       AND json_extract(ri.refundinfos, '$.remark') != ''),
    ''
)
```

**② `cutoff_ts` 和 `start_ts` 用 `elif` 而非独立 `if`**。

详见 `references/refund-table.md`。

## SQLite 时间过滤陷阱

`strftime('%s', ...)` 返回 TEXT 类型，与 INTEGER 比较走字符串规则，静默丢数据：
```sql
-- ❌ 返回 0 行
WHERE b.time / 1000 >= strftime('%s', '2026-05-16', 'localtime')

-- ✅ 用 Python 计算 epoch
cutoff_ts = int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
```

## 预算来源

月预算从 `budget` 表读取（`num` 字段），`get_budget_from_db()` 优先查当前月，若无回退到最近月。兜底值 2050。

⚠️ 知识库文件（`budget-config.md` 等）不应硬编码预算值——cron AI 读知识库而非调脚本。已修复：`budget-config.md` 改为"从数据库动态读取"。

## 毛额 vs 净额

分析时**绝不能只看毛支出**，必须扣除退款/报销。

| 数据源 | 退款标识 | 处理方式 |
|--------|---------|---------|
| Custom.db | `refund` 表 | `data_processor.py` |
| CSV 导出 | `退款状态=是` + `退款金额` | `net = max(0, amount - refund)` |

## 分类标签 ≠ 实际消费

- 退款/退货：分类保留但钱已退
- 代购/帮朋友买：不是自己消费
- 报销：净额远低于毛额

**规则**：高价值分类先展示数据，再请用户确认。

## 领域术语核实

- `信息费` → 家教中介费
- `日常` → 可能含电子产品
- `其他收益` → 贷款/二手/助学金

遇到不明确分类，**先问用户**。
