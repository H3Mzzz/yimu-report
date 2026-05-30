# refund 表结构与数据流

## 一木记账退款机制

App 处理退款的流程：
1. 用户在 App 发起退款（关联到原始账单）
2. App 将原始 `bill.cost` 设为 `0`（全额退款时）
3. 退款记录写入 `refund` 表
4. 退款详情 JSON 写入 `refund_refundinfos` 表

## 表结构

### refund

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| billid | INTEGER | 关联的原始账单 billid |
| refundnum | REAL | 退款金额（正数） |
| refundid | INTEGER | 退款业务 ID |
| updatetime | INTEGER | 退款时间（毫秒 epoch） |
| userid | INTEGER | 用户 ID |
| delete_lpcolumn | INTEGER | 软删除标记（0=有效） |

### refund_refundinfos

| 字段 | 类型 | 说明 |
|------|------|------|
| refund_id | INTEGER | 关联 refund.id |
| refundinfos | TEXT | JSON 字符串，包含退款详情 |

`refundinfos` JSON 结构：
```json
{
  "assetId": 550854230,       // 入账账户 ID
  "assetNum": 56.9,           // 入账金额
  "costNum": 56.9,            // 成本金额
  "currentNumber": -0.0,      // 账户当前余额变化
  "inTime": 0,                // 入账时间（0=未入账）
  "number": 56.9,             // 退款金额
  "relatedBillId": 0,         // 关联账单 ID
  "remark": "退款-来自名创**店",  // 退款备注
  "restoreCostNum": 0.0,      // 恢复成本
  "restoreNum": 0.0,          // 恢复数量
  "time": 1779519819000       // 退款时间（毫秒 epoch）
}
```

## 查询示例

```python
# 查看所有有效退款
SELECT r.id, r.billid, r.refundnum,
       datetime(r.updatetime/1000, 'unixepoch', 'localtime') as refund_time,
       ri.refundinfos
FROM refund r
LEFT JOIN refund_refundinfos ri ON ri.refund_id = r.id
WHERE r.delete_lpcolumn = 0
ORDER BY r.updatetime DESC

# 关联原始账单
SELECT r.billid, r.refundnum, b.remark, b.cost as current_cost
FROM refund r
JOIN bill b ON b.billid = r.billid
WHERE r.delete_lpcolumn = 0
```

## ⚠️ 已知问题

`analyze_bills.py` 的 `_BASE_SQL` 只查 `bill` 表且过滤 `cost != 0`，完全不查 `refund` 表。需要增加退款查询逻辑，将退款作为收入事件纳入分析。

修复方向：在 `load_from_db()` 中增加对 `refund` 表的 LEFT JOIN 或 UNION，将退款记录以正数收入形式加入结果集。注意：
- 退款时间用 `refund.updatetime`（不是 `bill.time`，后者是原始消费时间）
- 退款备注从 `refund_refundinfos` 的 JSON 中提取 `remark` 字段
- 退款分类应与原始消费分类一致（通过 billid 关联回 bill）
