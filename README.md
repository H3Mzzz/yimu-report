# 一木 Report 💰

自动账单分析 + AI 财务报告生成系统。从一木记账 App 导出数据，经地理编码和空间聚类处理后，由 DeepSeek 大模型生成专业财务分析报告，通过邮件定时推送。

## 架构

```
GitHub Actions (定时触发)
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  backup.py          独立备份通道                       │
│    download.py ─► 一木记账网页 ─► 坚果云 WebDAV        │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  main.py            主报告流程                         │
│    │                                                   │
│    ├─► webdav.py          坚果云下载最新账单 xlsx       │
│    ├─► data_processor.py  Excel 解析 + 时间筛选 + 摘要 │
│    │       └─► location_resolver.py                    │
│    │             地址 → 高德地理编码 → AOI/POI/DBSCAN  │
│    ├─► memory.py          持久化记忆（画像/洞察/快照）  │
│    ├─► prompts.py         分模式 Prompt 构建            │
│    ├─► DeepSeek API       AI 报告生成                  │
│    ├─► html_renderer.py   纯文本 → HTML 邮件渲染        │
│    └─► QQ 邮箱 SMTP       发送报告邮件                 │
└──────────────────────────────────────────────────────┘
```

## 文件说明

| 文件 | 职责 |
|:---|:---|
| `main.py` | 主入口：WebDAV 下载 → 解析 → 摘要 → AI 报告 → 记忆 → 邮件 |
| `data_processor.py` | Excel 解析、列名自动识别、金额标准化、分类合并、周期筛选、对比引擎 |
| `location_resolver.py` | 高德地图位置解析：地址→经纬度→AOI/POI/DBSCAN 三层标签→区域聚合 |
| `prompts.py` | 三模式 Prompt（日报=体检、周报=诊断、月报=战略）+ 对比章节模板 |
| `memory.py` | 持久化记忆系统：用户画像、滚动洞察、上次报告快照、Prompt 上下文注入 |
| `html_renderer.py` | 纯文本报告 → 内联 CSS HTML 邮件（兼容主流邮件客户端） |
| `webdav.py` | 坚果云 WebDAV 完整 CRUD：上传/下载/列表/删除/旧备份清理 |
| `download.py` | Playwright 无头浏览器：登录一木记账 → 导出 Excel |
| `backup.py` | 独立备份流程：一木记账 → 坚果云（与报告生成解耦） |
| `save_auth.py` | 本地工具：手动登录一木记账并保存登录状态 |


## 环境变量

### 必需

| 变量 | 说明 |
|:---|:---|
| `QQ_EMAIL` | 发件 QQ 邮箱地址 |
| `QQ_AUTH_CODE` | QQ 邮箱 SMTP 授权码 |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `AMAP_API_KEY` | 高德地图 Web 服务 API Key |

### 可选

| 变量 | 默认值 | 说明 |
|:---|:---|:---|
| `TO_EMAIL` | 同 `QQ_EMAIL` | 收件邮箱 |
| `REPORT_MODE` | `weekly` | 报告模式：`daily` / `weekly` / `monthly` |
| `MONTHLY_BUDGET` | `2000` | 月基准（元），自动换算日/周预算 |
| `DEFAULT_GEOCODE_CITY` | `` | 高德地理编码默认搜索城市 |
| `CITY_KW_MAP` | `{}` | 地址→城市名映射 JSON（防跨城误匹配） |
| `HARDCODED_LOCATIONS` | `{}` | 手动坐标映射 JSON（高德不收录的地点） |
| `MEMORY_DIR` | `/root/cow/memory/bill` | 记忆文件存储目录 |
| `WEBDAV_BASE_URL` | `https://dav.jianguoyun.com/dav/` | 坚果云 WebDAV 地址 |
| `WEBDAV_USERNAME` | — | 坚果云账号 |
| `WEBDAV_PASSWORD` | — | 坚果云应用密码 |
| `WEBDAV_BACKUP_FOLDER` | `账单备份` | WebDAV 备份文件夹名 |

## 数据处理流程

### 1. 数据获取

两个通道互不依赖：

- **备份通道**（`backup.py`）：Playwright 模拟登录一木记账 → 导出 Excel → 上传坚果云
- **报告通道**（`main.py`）：从坚果云下载最新备份 → 生成报告

### 2. Excel 解析（`data_processor.py`）

- **列名自动识别**：`_find_col()` 模糊匹配，兼容不同导出格式
- **金额标准化**：保留负数支出（报销/AA 回血），不盲目 `abs()`
- **净支出计算**：`实际金额 = 原始金额 - 退款 - 优惠 - 报销`
- **分类合并**：有二级分类时优先使用二级分类作为 `最终分类`
- **周期筛选**：支持 `daily` / `weekly` / `monthly` 及 `previous_*` 回溯模式

### 3. 地理编码（`location_resolver.py`）

```
地址文本 → geocode() → (经度, 纬度) → regeocode() → 结构化区域
                                                    │
                                    ┌───────────────┼───────────────┐
                                    ▼               ▼               ▼
                               AOI 标签        POI 标签      DBSCAN 聚类
                            (面状: 学校、商场)  (点状: 餐厅)   (r≈300m, ≥2点)
```

- **三层标签降级**：AOI → POI → DBSCAN 空间聚类
- **磁盘缓存**：30 天 TTL，MD5 key，失败结果也缓存避免重复消耗配额
- **纯 Python 回退**：sklearn 不可用时自动使用内置 DBSCAN 实现
- **区域聚合**：`area_summary()` 按标签分组，输出交易数、金额、品类分布

### 4. AI 报告生成（`prompts.py` + DeepSeek）

三种模式各有侧重：

| 模式 | 定位 | 关键词 |
|:---|:---|:---|
| `daily` | 即时体检 | 今天有没有值得注意的事？对照日均基准 |
| `weekly` | 行为诊断 | 这周的钱花出了什么习惯？必要/弹性划分 |
| `monthly` | 战略规划 | 财务结构是否健康？下月目标设定 |

每个模式会注入：
- **用户画像**（来自 `memory.py` 的长期记忆）
- **上次报告回顾**（结构化指标快照，非原文）
- **近期关键洞察**（滚动累积）
- **预算基准**（日/周/月自动换算）
- **周期对比数据**（周报/月报，日报不注入）

### 5. 记忆系统（`memory.py`）

```
memory/bill/
├── profile.json          用户画像（预算、身份、已知特征）
├── last_report.json      上次报告结构化快照（非原文，防认知惯性）
├── insights_daily.json   日报洞察（滚动 7 条）
├── insights_weekly.json  周报洞察（滚动 12 条）
└── insights_monthly.json 月报洞察（永久保留）
```

### 6. 邮件发送

- HTML + 纯文本双版本（`MIMEMultipart`）
- `html_renderer.py` 将 Markdown 报告转为内联 CSS HTML
- 核心指标渲染为卡片组，区域消费渲染为独立区块
- 兼容 QQ 邮箱、Gmail、Outlook 等主流客户端

## GitHub Actions

| Workflow | 触发方式 | 报告模式 |
|:---|:---|:---|
| `daily_report.yml` | cron 每天 8:00 | `daily` |
| `weekly_report.yml` | cron 每周一 8:00 | `weekly` |
| `monthly_report.yml` | cron 每月 1 日 8:00 | `monthly` |
| `backup.yml` | cron 每天 6:00 | — |

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量（或使用 .env）
export QQ_EMAIL="your@qq.com"
export QQ_AUTH_CODE="your_auth_code"
export DEEPSEEK_API_KEY="sk-xxx"
export AMAP_API_KEY="your_amap_key"

# 首次：保存一木记账登录状态
python save_auth.py

# 运行报告
python main.py
```

## 依赖

```
openai
playwright
pandas
openpyxl
requests
```

可选：`scikit-learn`（DBSCAN 聚类加速，不安装则使用纯 Python 回退）。
