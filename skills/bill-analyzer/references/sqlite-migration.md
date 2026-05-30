# SQLite 迁移实战经验 (2026-05-17)

## 改动文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `sync_db.py` | 新增 | 坚果云 zip → 7z 解密 → Custom.db |
| `data_processor.py` | 重写 | 删 `_find_col()`，新增 `load_from_sqlite()` |
| `main.py` | 重写 | `fetch_data()` 切换到 SQLite |
| `send_report.py` | 修复 | `get_latest_metrics()` 改读 SQLite |
| `html_renderer.py` | 修复 | 饼图注入关键词匹配 |
| `MIGRATION_PLAN.md` | 新增 | 迁移方案文档 |

**保留不动**：`backup.py`、`download.py`、`webdav.py`（原 xlsx 流程作为备用）

## 踩过的坑

### 1. cost 不能取 ABS（多算 ¥338,833）

初始方案用 `ABS(cost)` 统一正负，被用户发现报销场景会重复计算：

```
原账单 cost=1834（演唱会门票）
报销   cost=-917（朋友AA）
SUM(cost)      = 917   ✅ 正确
SUM(ABS(cost)) = 2751  ❌ 多算了 1834
```

**结论**：`cost` 保留原值，负数 cost 自动抵消对应支出。

### 2. strftime 返回 TEXT 导致时间过滤失效

```sql
-- SQLite: strftime('%s', ...) 返回 TEXT，INTEGER >= TEXT 走字符串比较
-- 结果：1778941508 >= '1778918400' → FALSE（字符串 '1' == '1'，然后 '7' < '7'... 实际是 '4' > '1' 但整体比较规则不同）
SELECT typeof(strftime('%s', '2026-05-16', 'localtime'))  -- → 'text'
SELECT 1778941508 >= '1778918400'  -- → 0 (FALSE!)
```

**修复**：用 Python `int(dt.timestamp())` 计算 epoch，直接注入 SQL 整数字面量。

### 3. 饼图不显示——关键词不匹配（两轮修复）

**第一轮（05/17）**：`html_renderer.py` 注入关键词是 `支出结构`，但 `summarize()` 输出标题是 `支出分类全景`。改为匹配 summarize 输出。

**第二轮（05/18）**：发现 cron AI 重写报告时把标题改成 `## 支出结构` / `## 收入结构`，导致改后的关键词 `支出分类全景` 反而匹配不上。

**最终方案**：renderer 关键词统一为 `支出结构` / `收入结构`，与 AI 生成的报告标题一致。`summarize()` 的输出标题（`支出分类全景`/`收入来源明细`）仅用于数据层，不参与 HTML 注入。

**教训**：饼图注入关键词必须与 AI 最终输出的 Markdown 标题匹配，不能假设 AI 会原样保留 `summarize()` 的标题。

### 4. send_report.py 的隐藏 xlsx 依赖

迁移了 `data_processor.py` 和 `main.py` 后，以为端到端就通了。但 `send_report.py` 里还有 `get_latest_metrics()` 独立读 xlsx 文件提取饼图数据。这个函数不走 `main.py` 的数据流，所以不会自动切换。

**教训**：迁移数据源时，全局搜索所有 `xlsx`、`read_excel`、`.xlsx` 引用。

### 5. 一木记账 billtype 不区分收支

136 个 billtype 值（1/2/3/5）全混杂收支，正确判断靠 `parentcategoryid=9`。

## Cron 切换

旧: `bill_backup.sh` (playwright 导出 xlsx) → 新: `sync_bill_db.sh` (zip 下载 + 7z 解密)
旧脚本保留，可随时切回。
