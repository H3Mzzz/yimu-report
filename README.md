# 一木 Report 💰

自动账单分析 + AI 财务报告系统。从一木记账导出数据，经空间聚类处理后，由 AI 助手生成深度分析报告，通过邮件推送。

## 架构

```
┌──────────────────────────────────────────────────────┐
│  backup.py          独立备份通道                       │
│    download.py ─► 一木记账网页 ─► 坚果云 WebDAV       │
│                     └─► knowledge/finance/data/       │
└──────────────────────────────────────────────────────┘
    │
    ▼  (scheduler 触发 AI 助手)
┌──────────────────────────────────────────────────────┐
│  AI 助手分析流程                                      │
│    ├─► main.py --data-only    从坚果云获取 JSON 摘要   │
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
| `main.py` | 数据入口：WebDAV 下载 → 解析 → JSON 摘要输出（`--data-only` 模式） |
| `data_processor.py` | Excel 解析、列名自动识别、金额标准化、分类合并、周期筛选、对比引擎 |
| `location_resolver.py` | 高德地图位置解析：地址→经纬度→AOI/POI/DBSCAN 三层标签→区域聚合 |
| `html_renderer.py` | Markdown 报告 → 内联 CSS HTML 邮件 + matplotlib 饼图（引线标注） |
| `send_report.py` | 桥接脚本：读取 Markdown 报告 + 本地账单 → HTML 邮件发送 |
| `send_mail.py` | QQ 邮箱 SMTP 发送（HTML + 纯文本双版本） |
| `webdav.py` | 坚果云 WebDAV 客户端：上传/下载/列表/清理 |
| `download.py` | Playwright 无头浏览器：登录一木记账 → 导出 Excel |
| `backup.py` | 独立备份：一木记账 → 坚果云 + knowledge/finance/data/ |
| `save_auth.py` | 本地工具：手动登录一木记账并保存 auth_state.json |

## 定时任务（scheduler）

| 任务 | 时间 | 内容 |
|------|------|------|
| 账单备份 | 每天 23:50 | `backup.py` 从一木下载 → 上传坚果云 + 同步知识库 |
| 财务日报 | 每天 00:00 | AI 助手分析当日数据 → 发送邮件 |
| 财务周报 | 每周一 00:05 | AI 助手分析周数据 + Agent 进化报告 |
| 财务月报 | 每月1号 00:10 | AI 助手深度月报 + 战略级分析 |

## 数据处理流程

### 数据获取

- **备份通道**（`backup.py`）：Playwright 模拟登录一木 → 导出 Excel → 上传坚果云 + 存本地 `knowledge/finance/data/`
- **报告通道**：AI 助手调用 `main.py --data-only` → 从坚果云下载最新备份 → JSON 摘要

### Excel 解析（`data_processor.py`）

- 列名自动识别（`_find_col` 模糊匹配，兼容不同导出格式）
- 净支出计算：`实际金额 = 原始金额 - 退款 - 优惠 - 报销`
- 分类合并：有二级分类优先二级分类，无则使用一级分类
- 周期筛选：支持 `daily` / `weekly` / `monthly` 及 `previous_*` 回溯模式

### 地理编码（`location_resolver.py`）

三层标签降级：AOI（面状区域）→ POI（点状地标）→ DBSCAN 空间聚类（r≈300m）
- 30 天磁盘缓存（MD5 key），失败结果也缓存避免重复消耗配额
- sklearn 不可用时自动回退纯 Python DBSCAN 实现

### 邮件渲染（`html_renderer.py` + `send_report.py`）

- Markdown → 内联 CSS HTML（兼容 QQ 邮箱/Gmail/Outlook）
- matplotlib 饼图：引线标注 + 按章节注入（支出图在"支出结构"、收入图在"收入结构"）
- 支出/收入无数据时自动跳过饼图

## 环境变量

### 必需

| 变量 | 说明 |
|------|------|
| `QQ_EMAIL` | 发件 QQ 邮箱 |
| `QQ_AUTH_CODE` | QQ 邮箱 SMTP 授权码 |
| `AMAP_API_KEY` | 高德地图 Web 服务 API Key |
| `YIMU_AUTH_STATE` | 一木记账登录状态 JSON（或 `auth_state.json` 文件） |

### 可选

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TO_EMAIL` | 同 `QQ_EMAIL` | 收件邮箱 |
| `MONTHLY_BUDGET` | `2000` | 月基准（元） |
| `DEFAULT_GEOCODE_CITY` | — | 高德地理编码默认城市 |
| `WEBDAV_BASE_URL` | `https://dav.jianguoyun.com/dav/` | 坚果云 WebDAV |
| `WEBDAV_USERNAME` | — | 坚果云账号 |
| `WEBDAV_PASSWORD` | — | 坚果云应用密码 |
| `WEBDAV_BACKUP_FOLDER` | `账单备份` | 备份文件夹名 |

## 本地运行

```bash
pip install -r requirements.txt

# 配置环境变量
export QQ_EMAIL="your@qq.com"
export QQ_AUTH_CODE="your_auth_code"
export AMAP_API_KEY="your_key"
export YIMU_AUTH_STATE='{...}'

# 首次：保存登录状态
python save_auth.py

# 备份
python backup.py

# 获取数据（JSON 摘要）
python main.py --data-only --mode daily

# 发送报告（需要有 Markdown 报告文件）
python send_report.py --mode daily --body-file /tmp/daily_report.md
```

## 依赖

```
openpyxl
pandas
playwright
requests
matplotlib
numpy
```

可选：`scikit-learn`（DBSCAN 聚类加速，不安装则使用纯 Python 回退）。
