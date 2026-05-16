# 一木 Report 💰

自动账单分析 + AI 财务报告系统。从一木记账 SQLite 数据库读取数据，经空间聚类处理后，由 AI 助手生成深度分析报告，通过邮件推送。

## 架构

```
┌──────────────────────────────────────────────────────┐
│  sync_db.py         DB 同步通道                       │
│    坚果云 zip ─► 7z 解密 ─► Custom.db                │
│                     └─► knowledge/finance/data/       │
└──────────────────────────────────────────────────────┘
    │
    ▼  (scheduler 触发 AI 助手)
┌──────────────────────────────────────────────────────┐
│  AI 助手分析流程                                      │
│    ├─► main.py --data-only    从 SQLite 读取 JSON 摘要 │
│    │       └─► data_processor.py 解析/筛选/对比        │
│    │              └─► location_resolver.py             │
│    │                    高德地理编码 → AOI/POI/DBSCAN  │
│    ├─► AI 深度分析（读取 knowledge/finance/ 历史知识）  │
│    ├─► 更新知识库（消费画像/洞察/预算追踪）            │
│    └─► send_report.py         Markdown → HTML → 邮件   │
│           ├─► html_renderer.py  内联 CSS + 饼图渲染    │
│           └─► send_mail.py      QQ 邮箱 SMTP           │
└──────────────────────────────────────────────────────┘
```

## 文件说明

| 文件 | 职责 |
|------|------|
| `sync_db.py` | DB 同步：从坚果云下载加密 zip → 7z 解密 → 保存 Custom.db |
| `main.py` | 数据入口：从 SQLite 读取 → JSON 摘要输出（`--data-only` 模式） |
| `data_processor.py` | SQLite 加载、收支分类、金额处理、周期筛选、对比引擎 |
| `location_resolver.py` | 高德地图位置解析：地址→经纬度→AOI/POI/DBSCAN 三层标签→区域聚合 |
| `html_renderer.py` | Markdown 报告 → 内联 CSS HTML 邮件 + matplotlib 饼图（引线标注） |
| `send_report.py` | 桥接脚本：读取 Markdown 报告 + SQLite 指标 → HTML 邮件发送 |
| `send_mail.py` | QQ 邮箱 SMTP 发送（HTML + 纯文本双版本） |
| `backup.py` | [旧] Playwright 备份通道：一木记账网页 → Excel → 坚果云（保留备用） |
| `webdav.py` | 坚果云 WebDAV 客户端：上传/下载/列表/清理 |
| `download.py` | [旧] Playwright 无头浏览器：登录一木记账 → 导出 Excel（保留备用） |
| `save_auth.py` | 本地工具：手动登录一木记账并保存 auth_state.json |

## 定时任务（scheduler）

| 任务 | 时间 | 内容 |
|------|------|------|
| DB 同步 | 每天 23:50 | `sync_db.py` 从坚果云下载 zip → 解密 → 保存 Custom.db |
| 财务日报 | 每天 00:00 | AI 助手分析当日数据 → 发送邮件 |
| 财务周报 | 每周一 00:05 | AI 助手分析周数据 + Agent 进化报告 |
| 财务月报 | 每月1号 00:10 | AI 助手深度月报 + 战略级分析 |

## 数据源

### SQLite 数据库（`Custom.db`）

一木记账 App 的原始数据库，以加密 zip 形式同步到坚果云 `一木记账/` 文件夹。

**关键数据语义**：

- **收支判断**：`parentcategoryid = 9`（收入类），其余为支出
- **金额**：`cost` 已是 App 处理后的净值。正数 = 正常支出/收入，负数 = 报销/退款抵消
- **全额退款**：`cost` 已被 App 清零（cost=0），refund 表仅记录历史
- ⚠️ **不要取 ABS(cost)**：负数 cost 是报销/调整，取绝对值会多算
- ⚠️ **不要从 cost 扣减 refund 表**：refund 表仅作信息展示

**时间戳**：`time` 字段为毫秒级 Unix 时间戳，`datetime(time/1000, 'unixepoch', 'localtime')`

**分类**：一级分类 `parentcategory` + 二级分类 `childcategory`（`childcategoryid = -1` 表示无子分类）

### 旧 Excel 通道（保留备用）

`backup.py` + `download.py` 通过 Playwright 模拟登录一木记账网页版导出 Excel，上传坚果云。已不再作为主数据源，保留供紧急回退。

## 地理编码（`location_resolver.py`）

三层标签降级：AOI（面状区域）→ POI（点状地标）→ DBSCAN 空间聚类（r≈300m）
- 30 天磁盘缓存（MD5 key），失败结果也缓存避免重复消耗配额
- sklearn 不可用时自动回退纯 Python DBSCAN 实现

## 邮件渲染（`html_renderer.py` + `send_report.py`）

- Markdown → 内联 CSS HTML（兼容 QQ 邮箱/Gmail/Outlook）
- matplotlib 饼图：引线标注 + 按章节注入（支出图在"支出分类全景"、收入图在"收入来源明细"）
- 支出/收入无数据时自动跳过饼图

## 环境变量

### 必需

| 变量 | 说明 |
|------|------|
| `QQ_EMAIL` | 发件 QQ 邮箱 |
| `QQ_AUTH_CODE` | QQ 邮箱 SMTP 授权码 |
| `AMAP_API_KEY` | 高德地图 Web 服务 API Key |
| `WEBDAV_USERNAME` | 坚果云账号 |
| `WEBDAV_PASSWORD` | 坚果云应用密码 |

### 可选

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TO_EMAIL` | 同 `QQ_EMAIL` | 收件邮箱 |
| `MONTHLY_BUDGET` | `2000` | 月基准（元） |
| `DEFAULT_GEOCODE_CITY` | — | 高德地理编码默认城市 |
| `WEBDAV_BASE_URL` | `https://dav.jianguoyun.com/dav/` | 坚果云 WebDAV |
| `WEBDAV_BACKUP_FOLDER` | `账单备份` | 旧备份文件夹名 |
| `WEBDAV_ZIP_FOLDER` | `一木记账` | DB zip 文件夹名 |
| `ZIP_PASSWORD` | — | 加密 zip 密码 |

## 本地运行

```bash
pip install -r requirements.txt

# 配置环境变量（或写入 .env）
export QQ_EMAIL="your@qq.com"
export QQ_AUTH_CODE="***"
export AMAP_API_KEY="***"
export WEBDAV_USERNAME="***"
export WEBDAV_PASSWORD="***"

# 同步数据库
python sync_db.py

# 获取数据（JSON 摘要）
python main.py --data-only --mode daily

# 发送报告（需要有 Markdown 报告文件）
python send_report.py --mode daily --body-file /tmp/daily_report.md
```

## 依赖

```
pandas
requests
matplotlib
numpy
python-dotenv
```

系统依赖：`7z`（`apt install p7zip-full`，用于解密坚果云 zip）

可选：`scikit-learn`（DBSCAN 聚类加速，不安装则使用纯 Python 回退）
