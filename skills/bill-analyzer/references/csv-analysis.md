# CSV 原始数据分析

用户于 2026 年 5 月从旧记账软件切换到一木记账。旧 CSV 导出比 Custom.db 更完整。

## Schema 对照

| CSV 列名 | 含义 | 对应 Custom.db |
|-----------|------|---------------|
| 收支类型 | 支出/收入/其他 | `parentcategoryid=9` |
| 账单类型 | 普通收支/转账/退款 | `billtype` |
| 金额 | 正数 | `cost` |
| 退款状态 | 是/否 | `refund` 表 |
| 退款金额 | 实际退款额 | `refund_refundinfos` |
| 报销状态 | 是/否 | `reimbursement` 表 |
| 分类/子分类 | 中文分类名 | `parentcategory`/`childcategory` |
| 账户名称 | 支付方式 | `assetid` → `asset` 表 |
| 记账日期 | `YYYY-M-D H:MM` | `time` (epoch ms) |

**去重**：`(记账日期, 金额, 分类, 账户名称, 收支类型)` 五元组。

## CSV 分析 Pitfalls

1. **不能把分类支出等同于个人消费** — 演唱会含代购和退款票
2. **"职业收入"≠工资** — 整百金额（¥100/¥500/¥1000）是生活费
3. **"其他收益"包含贷款** — 农信社大额收入可能是助学贷款
4. **内部转账不是收支** — `收支类型=其他` + `账单类型=转账`
5. **贷款到账模式** — 贷款→交学费→剩余转微信/支付宝→日常消费

## 净额计算

```python
if r['退款状态'] == '是' and refund_amt > 0:
    net = max(0, amount - refund_amt)
elif r['退款状态'] == '是':
    net = 0
else:
    net = amount
```
