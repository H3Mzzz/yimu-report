# Budget 表结构与数据

## 表结构

```sql
CREATE TABLE budget (
    id INTEGER PRIMARY KEY,
    delete_lpcolumn INTEGER DEFAULT 0,  -- 软删除标记
    year INTEGER,                        -- 年份
    num REAL,                            -- 预算金额
    endtime INTEGER,
    budgetid INTEGER,
    starttime INTEGER,
    type INTEGER,
    positionweight INTEGER,
    userid INTEGER,
    bookid INTEGER,                      -- 账本 ID
    addnum REAL,
    month INTEGER,                       -- 月份
    budgetname TEXT,
    updatetime INTEGER
);
```

## 数据示例

| id | year | month | num | bookid | 说明 |
|----|------|-------|-----|--------|------|
| 1 | 2026 | 3 | 2050.0 | 1 | 3月预算 |
| 2 | 2026 | 4 | 2000.0 | 1 | 4月预算 |
| 3 | 2026 | 4 | 0.0 | 272064873 | 另一账本（无预算） |

## 读取逻辑

`get_budget_from_db(year, month)` 函数：
1. 优先查询指定年月的预算（`num > 0`）
2. 若当前月无预算，回退到最近一个月（`ORDER BY year DESC, month DESC`）
3. 数据库不存在或无数据时，兜底返回 2050

## 相关表

- `categorybudget` — 分类预算（当前为空）
- `budgetsetting` — 预算设置（`autoreducebudget=1` 表示自动减少预算已开启）
- `budgethide` — 隐藏的预算
