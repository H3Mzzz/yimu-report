# yimu-report 数据源迁移：XLSX → SQLite ✅

**状态：已完成** — 2026-05-17

## 背景

当前 yimu-report 从坚果云下载 xlsx 备份文件作为数据源，xlsx 是通过 playwright 模拟登录一木记账网页版导出的。现切换为使用一木记账 App 的原始 SQLite 数据库 (`Custom.db`)，数据更完整、更稳定。

## 实际数据验证结论

通过对 `Custom.db`（5934 条账单，2023-09 ~ 2026-05-16）的分析，确认以下关键事实：

### 1. 收支判断：靠 parentcategoryid，不靠 billtype

| billtype | 数量 | 含义 | 收支混合？ |
|----------|------|------|-----------|
| 3 | 5716 (96%) | 主要类型 | ✅ 混合 |
| 5 | 107 (1.8%) | 自动识别类（共享单车等） | ✅ 混合 |
| 1 | 83 (1.4%) | 手动/特殊（信用卡利息、手续费等） | ✅ 混合 |
| 2 | 28 (0.5%) | 早期/导入数据 | ✅ 混合 |

**正确判断**：`parentcategoryid = 9`（categoryname = '收入'）→ 收入，其余 → 支出。

### 2. cost 保留原值，不取 ABS

费用类账单的 cost **正负并存**：
- 正数 cost = 正常支出（如 ¥1834 演唱会门票）
- 负数 cost = 报销/退款/调整（如 ¥-917 报销差额）
- 两者自动抵消：¥1834 + ¥-917 = ¥917（实际自付）
- 全额退款 cost=0 → 过滤排除

⚠️ **绝对不能用 `ABS(cost)`**：全局 5082 笔负数 cost，ABS 会多算 ¥338,833。

验证：5/16 `SUM(cost)` = ¥84.69，与 XLSX 完全吻合。

**结论**：`实际金额 = cost`（保留原值），refund 表仅作信息展示，不参与计算。

### 3. 数据库基础信息

| 维度 | 数值 |
|------|------|
| 总账单 | 5934 条 |
| 时间跨度 | 2023-09-24 ~ 2026-05-16 |
| 一级分类 | 15 个 |
| 二级分类 | 75 个 |
| 资产账户 | 25 个 |
| 退款记录 | 143 条（¥27,310） |
| 有地址数据 | 132 条（2.2%） |
| zip 密码 | 2895285 |
| zip 路径 | 坚果云 /一木记账/6.4.8_auto_04290236.zip |

---

## 改动文件清单

### 文件 1: `webdav.py` — 新增 zip 下载函数

**新增 2 个函数，现有函数不动：**

```python
def list_zip_files(folder="一木记账"):
    """列出指定文件夹中的 .zip 文件，按名称降序。"""

def download_custom_db():
    """从坚果云 一木记账/ 下载最新 zip → 7z 解密 → 返回 Custom.db bytes。
    
    流程：
    1. list_zip_files() 获取最新 zip 文件名
    2. requests.get() 下载 zip 到临时文件
    3. subprocess: 7z x -p2895285 -o/tmp/ <zip> -y
    4. 读取 /tmp/Custom.db → return bytes
    5. 清理临时文件
    """
```

**依赖**：系统需安装 `p7zip-full`（已安装）。

---

### 文件 2: `data_processor.py` — 重写数据加载层

**删除：**
- `_find_col()` 函数（L12-17）

**新增 `load_from_sqlite(db_path, mode, reference_date=None)`：**

```python
def load_from_sqlite(db_path, mode, reference_date=None):
    """从 SQLite 数据库加载账单，返回 (DataFrame, period_label)。
    
    SQL 核心：
    SELECT
        datetime(b.time/1000, 'unixepoch', 'localtime') as 日期,
        b.cost,
        CASE WHEN pc.categoryid = 9 THEN '收入' ELSE '支出' END as 类型,
        pc.categoryname as 分类,
        cc.categoryname as 二级分类,
        a.assetname as 账户,
        b.remark as 备注,
        b.poiaddress as 地址
    FROM bill b
    LEFT JOIN parentcategory pc ON b.parentcategoryid = pc.categoryid
    LEFT JOIN childcategory cc ON b.childcategoryid = cc.categoryid
        AND b.childcategoryid != -1
    LEFT JOIN asset a ON b.assetid = a.assetid
    WHERE b.delete_lpcolumn = 0
      AND b.cost != 0
    ORDER BY b.time DESC
    
    后处理：
    - 金额 = cost（保留原值，正数=支出/收入，负数=报销/退款抵消）
    - 时间过滤逻辑与现有 parse_transactions 一致（daily/weekly/monthly/previous_*）
    - childcategoryid = -1 时二级分类为 NULL → 用一级分类
    """
```

**修改 `parse_transactions()`：**

原签名 `parse_transactions(excel_bytes, mode, reference_date)` 改为 `parse_transactions(db_path, mode, reference_date)`，内部调用 `load_from_sqlite()`。返回值不变：`(DataFrame, period_label)`。

**不动的部分：**
- `summarize()` — 接收 DataFrame，不关心数据来源
- `_extract_metrics()` — 同上
- `generate_comparison_summary()` — 同上
- `_format_clusters()` — 同上

---

### 文件 3: `main.py` — 切换数据获取源

**修改 `fetch_data()`：**

```python
# 旧
excel_bytes, filename = download_latest_backup()  # webdav xlsx
df, period_label = parse_transactions(excel_bytes, mode)

# 新
from webdav import download_custom_db
db_bytes = download_custom_db()
db_path = "/tmp/Custom.db"  # 由 download_custom_db 写入
df, period_label = parse_transactions(db_path, mode)
```

**不动的部分：**
- CLI 参数（`--data-only`, `--mode`）
- `_serialize_metrics()`
- JSON 输出格式

---

### 文件 4: `backup.py` — 重写备份流程

**旧流程（删除）：**
1. playwright 登录一木记账网页版
2. 导出 xlsx
3. 上传坚果云 `账单备份/`
4. 同步知识库（滚动保留5份 xlsx）

**新流程：**
1. 从坚果云 `一木记账/` 下载最新 zip
2. 7z 解密提取 `Custom.db`
3. 保存到知识库 `~/cow/knowledge/finance/data/Custom.db`（单文件覆盖）
4. 无需上传（zip 是手机 App 自动同步的）

```python
async def main():
    print("=== 一木记账 DB 同步 ===")
    db_bytes = download_custom_db()
    
    os.makedirs(KNOWLEDGE_DATA_DIR, exist_ok=True)
    db_path = os.path.join(KNOWLEDGE_DATA_DIR, "Custom.db")
    with open(db_path, "wb") as f:
        f.write(db_bytes)
    print(f"已同步: {db_path} ({len(db_bytes)} bytes)")
```

**删除导入：**
- `from download import download_excel`（不再需要 playwright）

**不动的部分：**
- `download.py` 暂保留不删除（历史参考）

---

## 联动改动

### Cron Job: 账单备份 (`f01b2ec794a6`)

当前脚本 `~/.hermes/scripts/bill_backup.sh` 调用 `backup.py`，**脚本本身无需修改**（backup.py 内部逻辑已变）。

### Cron Job: 日报/周报/月报

当前调用 `main.py --data-only --mode daily/weekly/monthly`，**命令行接口不变**，内部数据源切换后透明生效。

### Skill: `bill-analyzer`

需更新文档和 `analyze_bills.py`：

| 变更 | 说明 |
|------|------|
| `SKILL.md` | 数据源描述从 xlsx 改为 SQLite |
| `analyze_bills.py` L48-84 | 数据加载从 xlsx 改为 SQLite |
| `analyze_bills.py` `_find_col()` | 删除 |
| `analyze_bills.py` `list_data_files()` | 改为检测 `Custom.db` 是否存在 |
| `references/sqlite-schema.md` | 更新 cost 语义说明 |

### 知识库文件

知识库中旧的 xlsx 数据文件 (`bills_*.xlsx`) 可保留作为历史参考，不再更新。新数据源为 `Custom.db`。

---

## 不在本次范围

- 新分析能力（资产仪表盘、资金流向、标签分析等）→ 后续迭代
- `download.py` 删除 → 暂保留
- 坚果云 `账单备份/` 目录清理 → 保留历史备份

---

## 验证结果

1. ✅ `sync_db.py` 下载解密 Custom.db → 1.8MB
2. ✅ `main.py --data-only --mode daily` → 净支出 ¥84.69，与 XLSX 一致
3. ✅ `main.py --data-only --mode weekly` → 净支出 ¥2,049.79
4. ✅ `analyze_bills.py --days 7 --json` → 正常输出
5. ✅ 饼图正常渲染（收入构成 + 支出构成）
6. ✅ 端到端 HTML 邮件生成通过
