# Asset 表结构（账户余额）

## 表结构

```sql
CREATE TABLE asset (
    id INTEGER PRIMARY KEY,
    assetname TEXT,          -- 账户名称（如"微信钱包"、"工商银行"）
    assetnumber REAL,        -- ★ 余额（不是 balance！）
    assettype INTEGER,       -- 1=资金账户, 3=充值账户, 4=信贷账户, 4=投资理财
    groupname TEXT,          -- 分组（资金账户/充值账户/信贷账户/应付款/借入）
    assetid INTEGER,         -- 账户 ID（bill 表关联用）
    bookid INTEGER,
    hide INTEGER,
    delete_lpcolumn INTEGER,
    currency TEXT,
    updatetime INTEGER
);
```

> ⚠️ **字段名是 `assetnumber`，不是 `balance`**。查询时用 `SELECT assetname, assetnumber FROM asset`。

## 查询流动现金

```sql
SELECT assetname, assetnumber, groupname
FROM asset
WHERE delete_lpcolumn = 0 AND assetnumber != 0
ORDER BY assetnumber DESC
```

## 数据示例（2026-05-19）

| 账户 | 金额 | 分组 |
|------|------|------|
| 微信钱包 | ¥1,424 | 资金账户 |
| 亲情卡 | ¥100 | 资金账户 |
| 工商银行 | ¥91 | 资金账户 |
| 现金 | ¥54 | 资金账户 |
| 校园卡 | ¥29 | 充值账户 |
| 花呗 | -¥954 | 信贷账户 |
| 美团月付 | -¥553 | 信贷账户 |

**净流动** = 资金账户 + 充值账户 - 信贷账户（不含应付款/借入类负债）

## 资产变动历史

```sql
SELECT datetime(ah.time/1000, 'unixepoch', 'localtime'),
       ah.change, a.assetname, ah.remark
FROM assethistory ah
LEFT JOIN asset a ON ah.assetid = a.assetid
WHERE ah.delete_lpcolumn = 0
ORDER BY ah.time DESC
LIMIT 10
```

## assettype 参考

| 值 | 类型 | 说明 |
|----|------|------|
| 1 | 资金账户 | 银行卡、微信、支付宝、现金 |
| 3 | 充值账户 | 校园卡、超市卡 |
| 4 | 信贷账户 | 花呗、信用卡、美团月付 |
| 4 | 投资理财 | 证券等 |
