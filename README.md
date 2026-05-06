# 一木记账 · 自动财务报告

从坚果云 WebDAV 自动拉取一木记账备份账单，AI 生成财务分析报告，发送 QQ 邮箱。

核心能力：
- **🍜 位置智能**：高德地图地理编码 + DBSCAN 空间聚类，自动发现高频消费区域
- **🧠 记忆系统**：分层持久化关键洞察（用户画像 / 历史报告 / AI 建议），每次分析带上下文，越跑越懂你
- **📊 同期对比**：自动对比上一周期数据，追踪消费趋势变化
- **📬 多频次**：日 / 周 / 月报自由切换

---

## 部署步骤

### 第一步：获取 QQ 邮箱授权码

QQ 邮箱发信需要「授权码」而非 QQ 密码：

1. 打开 QQ 邮箱网页版 → 设置 → 账户
2. 找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」
3. 开启「SMTP服务」，按提示发短信验证
4. 生成并复制授权码（格式类似 `abcdabcdabcd`）

### 第二步：配置 GitHub Secrets

仓库页面：`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

依次添加以下 Secret：

| Secret 名称 | 填入内容 | 必填 |
|------------|---------|:--:|
| `QQ_EMAIL` | QQ 邮箱地址，如 `123456@qq.com` | ✅ |
| `QQ_AUTH_CODE` | 第一步获取的 SMTP 授权码 | ✅ |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | ✅ |
| `AMAP_API_KEY` | 高德地图 API Key（用于位置解析） | ✅ |
| `WEBDAV_BASE_URL` | 坚果云 WebDAV 地址（默认 `https://dav.jianguoyun.com/dav/`） | ✅ |
| `WEBDAV_USERNAME` | 坚果云账号 | ✅ |
| `WEBDAV_PASSWORD` | 坚果云应用密码 | ✅ |
| `WEBDAV_BACKUP_FOLDER` | 备份文件夹名（默认 `账单备份`） | — |
| `TO_EMAIL` | 收件邮箱（默认与 `QQ_EMAIL` 相同） | — |
| `REPORT_MODE` | 报告模式：`daily` / `weekly` / `monthly`（默认 `weekly`） | — |

### 第三步：手动触发测试

1. 仓库 → `Actions` → 左侧「一木财务报告」
2. 点 `Run workflow` → `Run workflow`
3. 等待 2-3 分钟，查看运行日志
4. 检查 QQ 邮箱是否收到报告

---

## 调整报告频率

修改 `.github/workflows/report.yml` 里的 cron 表达式：

| 频率 | cron | 说明 |
|------|------|------|
| 每天 | `0 0 * * *` | 每日 UTC 0:00 = 北京时间 8:00 |
| 每周一 | `0 0 * * 1` | 每周一 UTC 0:00 |
| 每月1号 | `0 0 1 * *` | 每月1日 UTC 0:00 |

---

## 项目结构

```
yimu-report/
├── main.py                   # 主流程：下载→解析→分析→邮件
├── data_processor.py         # 账单解析、数据摘要、同期对比
├── webdav.py                 # 坚果云 WebDAV 下载备份
├── prompts.py                # AI 提示词（日/周/月报模板）
├── memory.py                 # 🧠 记忆系统（画像/洞察/建议追踪）
├── location_resolver.py      # 🍜 高德地图位置解析 + 空间聚类
├── save_auth.py              # 一木网页端登录凭证获取（备用）
├── download.py               # 一木网页端账单下载（备用）
├── backup.py                 # 独立备份脚本
├── requirements.txt          # Python 依赖
├── .amap_cache/              # 高德 API 缓存（地理编码结果，TTL 30 天）
└── .github/workflows/
    └── report.yml            # GitHub Actions 定时任务
```

---

## 🧠 记忆系统设计

每次 GitHub Action 运行是无状态的，记忆模块解决这个问题——让 AI 带着上下文分析，而不是每次"重新认识你"。

### 分层存储

| 文件 | 内容 | 容量 |
|------|------|:--:|
| `memory/yimu/profile.json` | 用户画像（身份、预算、消费特征） | 长期 |
| `memory/yimu/insights_daily.json` | 日报关键洞察 | 最近 7 期 |
| `memory/yimu/insights_weekly.json` | 周报关键洞察 | 最近 12 期 |
| `memory/yimu/insights_monthly.json` | 月报关键洞察 | 几乎永久 |
| `memory/yimu/last_report.json` | 上一次报告的指标快照 | 1 份 |
| `memory/yimu/advice_log.json` | AI 历史建议追踪 | 最多 10 条 |

### 记忆生命周期

```
AI 生成报告
    │
    ├──▶ 提取关键指标 → last_report.json（下次同期对比）
    ├──▶ 截取报告摘要 → insights_{mode}.json（滚动累积）
    └──▶ 记录建议内容 → advice_log.json（追踪执行）

下次分析时
    │
    └──▶ build_memory_context() 组装 → 注入 Prompt 用户背景段
        ├─ 用户画像（月预算¥2000，大三学生）
        ├─ 上次报告的指标快照
        └─ 近期洞察摘要 + 历史建议回顾
```

### 目录位置

记忆文件存放于 `/root/cow/memory/yimu/`，通过 `.gitignore` 排除版本控制。
每次 Action 运行后通过 `git commit && git push` 自动持久化。

---

## 环境变量速查

| 变量 | 用途 | 必填 |
|------|------|:--:|
| `QQ_EMAIL` | 发件 QQ 邮箱 | ✅ |
| `QQ_AUTH_CODE` | QQ SMTP 授权码 | ✅ |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | ✅ |
| `AMAP_API_KEY` | 高德地图 API Key | ✅ |
| `WEBDAV_BASE_URL` | 坚果云 WebDAV 地址 | ✅ |
| `WEBDAV_USERNAME` | 坚果云账号 | ✅ |
| `WEBDAV_PASSWORD` | 坚果云应用密码 | ✅ |
| `WEBDAV_BACKUP_FOLDER` | 备份文件夹名 | — |
| `TO_EMAIL` | 收件邮箱 | — |
| `REPORT_MODE` | 报告模式 | — |
