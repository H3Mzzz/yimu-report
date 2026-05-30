# 一木记账 SQLite 数据库 (Custom.db) Schema 参考

一木记账 App 的原始数据库是 SQLite 格式，存放在加密 zip 中并同步到坚果云。
比 XLSX 导出包含**远更丰富**的数据维度。

> ⚠️ 本文档基于 2026-05-17 对实际数据库的分析验证。之前的版本有多处错误，已修正。

## 数据库获取

坚果云 `一木记账/` 文件夹存放 App 自动备份的加密 zip（如 `6.4.8_auto_04290236.zip`）。

**解密要求：** zip 使用 AES 加密（PK compat v5.1），Python `zipfile` 模块和系统 `unzip` **均不支持**。必须用 `7z`：
```bash
# 安装（如未安装）
apt-get install -y p7zip-full

# 解密提取
7z x -p"$ZIP_PASSWORD" -o/tmp/ /path/to/backup.zip -y
```
密码存储在环境变量 `ZIP_PASSWORD`（`~/.hermes/.env`）。

## 核心表

### `bill` — 账单主表（5934 条，2026-05-17 验证）

| 字段 | 类型 | 说明 |
|------|------|------|
| `billid` | INTEGER | 唯一账单 ID |
| `time` | INTEGER | 毫秒级 Unix 时间戳 |
| `recordtime` | INTEGER | 记录时间（毫秒） |
| `cost` | REAL | 金额（见 Pitfall #1 复杂语义） |
| `discountnumber` | REAL | 优惠金额 |
| `billtype` | INTEGER | 账单类型（见 Pitfall #2） |
| `parentcategoryid` | INTEGER | → `parentcategory.categoryid` |
| `childcategoryid` | INTEGER | → `childcategory.categoryid`（-1 表示无子分类） |
| `assetid` | INTEGER | → `asset.assetid`（关联账户） |
| `remark` | TEXT | 备注 |
| `totaladdress` | TEXT | 完整地址（省/市/区+POI），覆盖率约 2.2% |
| `poiaddress` | TEXT | POI 名称，覆盖率约 2.2% |
| `reimbursement` | INTEGER | 报销标记 |
| `notintobudget` | INTEGER | 不计入预算 |
| `notintototal` | INTEGER | 不计入总额 |
| `currencyassetnumber` | REAL | 外币金额 |
| `currencydiscountnumber` | REAL | 外币优惠 |
| `delete_lpcolumn` | INTEGER | 软删除标记（0=有效） |

### `parentcategory` — 一级分类（15 条）

| categoryid | categoryname | categorytype |
|-----------|-------------|-------------|
| 1 | 医疗 | 1 (系统) |
| 2 | 人情 | 1 |
| 3 | 学习 | 1 |
| 5 | 娱乐 | 1 |
| 6 | 交通 | 1 |
| 7 | 餐饮 | 1 |
| 8 | 购物 | 1 |
| **9** | **收入** | 1 |
| 99 | 其他 | 1 |
| 1287035358 | 会员租用 | 2 (自定义) |
| 1375551510 | 三餐 | 2 |
| 1505081119 | 旅游 | 2 |
| 1667731997 | 住宿 | 2 |
| 1921963153 | 通讯 | 2 |
| 2122136670 | 日常 | 2 |

`categorytype`: 1=系统预设, 2=用户自定义

### `childcategory` — 二级分类（75 条）

通过 `parentcategoryid` 关联父分类。`childcategoryid = -1` 在 bill 表中表示"未选择子分类"。

### `asset` — 账户（25 个）

`assettype` 枚举：
- 1 = 普通资产（微信钱包、支付宝、现金、银行卡）
- 2 = 信用账户（花呗、白条、信用卡）
- 3 = 预付卡（校园卡、超市卡）
- 4 = 流转账户（转账流转）
- 7 = 其他/特殊（学费、贷款、证券）

### `refund` — 退款（143 条）

| 字段 | 说明 |
|------|------|
| `billid` | 关联原账单 |
| `refundnum` | 退款金额 |

### `reimbursement` — 报销（1 条，2026-05 验证）

| 字段 | 类型 | 说明 |
|------|------|------|
| `reimbursementid` | INTEGER | 报销记录 ID |
| `billid` | INTEGER | 关联原账单 |
| `reimbursementnum` | REAL | 报销金额 |
| `assetid` | INTEGER | 报销入账的账户 |
| `end_lpcolumn` | INTEGER | 是否完成 |
| `delete_lpcolumn` | INTEGER | 软删除 |

关联表 `reimbursement_reimbursementnumbers` 存报销明细，格式：
`原账单billid:金额:时间戳:描述:总额`（如 `1596872776:917.0:...:小欣AA薛之谦南京演唱会门票:917.0`）

bill 表有两个报销标记字段：
- `reimbursement` (INTEGER): 1=该笔账单有报销
- `reimbursementend` (INTEGER): 1=报销已完成

**交互机制**：原账单 cost 保留全价（如演唱会票 cost=¥1834），报销金额在 reimbursement 表中（¥917）。XLSX 导出的「报销」列 = reimbursementnum。实际用户自付 = cost - reimbursementnum。仅 1 条正式报销记录（薛之谦演唱会门票 AA），其余非正式报销通过单独的账单条目处理（如 cost=-917 的"报销差额"记录）。

### `transfer` — 转账（795 条）

账户间资金流转，XLSX 导出中完全没有。

### `tag` — 标签（3 个：退款/借款/赔付）

通过 `bill_tags` 表关联（157 条关联记录）。

### 其他表

- `budget` — 预算（2026年3月：¥2020）
- `lend` — 借出记录（8 条）
- `stockasset` / `stockinfo` / `stockprice` — 股票投资
- `currency` — 160 种汇率
- `goldprice` — 黄金价格
- `cycle` — 周期性账单

---

## ⚠️ 关键 Pitfalls

### 1. cost 已是 App 处理后的净值，不要取 ABS 或扣减 refund

- 正数 cost = 正常支出/收入
- 负数 cost = 报销/退款/调整（如 ¥1834 门票 + ¥-917 报销 = ¥917 自付）
- 全额退款的账单 cost 已被 App 清零（cost=0）
- **不要用 `ABS(cost)`**：全局 5082 笔负数 cost，ABS 会多算 ¥338,833
- **不要从 cost 扣减 refund 表**：refund 表仅记录退款历史，不参与金额计算
### 2. billtype 不区分收支！

**之前的错误说法：** "1=支出, 2=收入, 5=特殊" — **错误。**

实际分布（5934 条）：
| billtype | 数量 | 说明 |
|----------|------|------|
| 3 | 5716 (96%) | 主体类型，包含支出和收入 |
| 5 | 107 (1.8%) | 混合，含支出和收入 |
| 1 | 83 (1.4%) | 混合，含信用卡利息、转账手续费、退款差额等 |
| 2 | 28 (0.5%) | 混合，含支出和收入 |

**正确判断收支：** 用 `parentcategoryid`：
```sql
CASE WHEN b.parentcategoryid = 9 THEN '收入' ELSE '支出' END as 类型
```

### 3. cost 正负混用

- **85% 的费用记录** cost 为负数（如 -11.0 三餐、-0.99 交通）——这是报销/退款/调整记录
- **近期数据（含2026年5月）** cost 为正数（如 71.0 交通、11.2 三餐）
- **收入** 始终为正数
- 负数 cost 与对应正数 cost 自动抵消：¥1834 + (-¥917) = ¥917（实际自付）

**不可依赖 cost 符号判断收支。** 用 `parentcategoryid=9` 判断。
**不可用 `ABS(cost)` 统一**：全局 5082 笔负数 cost，ABS 会多算 ¥338,833。
**直接 `SUM(cost)` 即可得到正确净值。**

### 4. 时间戳是毫秒级

`time` 和 `recordtime` 都是毫秒 Unix 时间戳，转换时需 `/1000`：
```python
datetime.fromtimestamp(row['time'] / 1000)
```
SQL 中用 `datetime(b.time/1000, 'unixepoch', 'localtime')` 转本地时间。

### 5. 地址数据覆盖率低

`totaladdress` 和 `poiaddress` 覆盖率约 2.2%（132/5934 条），集中在最近 3 周。短期分析有一定参考价值，但不足以支撑全量地理分析。`totaladdress` 含省/市/区前缀可提取 city 参数。

### 6. 分类是 ID 不是文本

bill 表存的是 `parentcategoryid` / `childcategoryid`，必须 JOIN 才能得到中文名。

### 7. childcategoryid = -1 表示无子分类

不是 NULL，是 -1。

### 8. strftime('%s') 返回 TEXT，与整数比较会静默失败

SQLite 的 `strftime('%s', '2026-05-16', 'localtime')` 返回 **TEXT** 类型（如 `'1778918400'`）。
与 INTEGER 类型的 `b.time/1000` 比较时，SQLite 走字符串比较规则，导致结果错误（多数行被静默过滤掉）。

```sql
-- ❌ 错误：strftime 返回 TEXT，与 INTEGER 比较结果不可靠
WHERE b.time / 1000 >= strftime('%s', '2026-05-16', 'localtime')

-- ✅ 正确方案：用 Python 算好 epoch 直接传入（推荐）
-- Python: cutoff_ts = int(datetime(2026, 5, 16).timestamp())
-- SQL:    WHERE b.time / 1000 >= {cutoff_ts}

-- ✅ 正确方案：CAST 转类型（备选）
WHERE b.time / 1000 >= CAST(strftime('%s', '2026-05-16', 'localtime') AS INTEGER)
```

**推荐用 Python 算 epoch**：`datetime.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()`，避免 SQLite 时区处理的不确定性。

---

## 推荐查询模板

```sql
SELECT 
    datetime(b.time/1000, 'unixepoch', 'localtime') as 日期,
    b.cost as 金额,
    CASE WHEN b.parentcategoryid = 9 THEN '收入' ELSE '支出' END as 类型,
    pc.categoryname as 分类,
    cc.categoryname as 二级分类,
    a.assetname as 账户,
    b.remark as 备注,
    b.poiaddress as 地址,
    COALESCE(r.total_refund, 0) as 退款金额
FROM bill b
LEFT JOIN parentcategory pc ON b.parentcategoryid = pc.categoryid
LEFT JOIN childcategory cc ON b.childcategoryid = cc.categoryid
LEFT JOIN asset a ON b.assetid = a.assetid
LEFT JOIN (
    SELECT billid, SUM(refundnum) as total_refund 
    FROM refund GROUP BY billid
) r ON b.billid = r.billid
WHERE b.delete_lpcolumn = 0
  AND b.cost != 0
ORDER BY b.time DESC
```
