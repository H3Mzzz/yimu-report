# 一木记账 · 自动财务报告

从一木记账网页端自动导出账单 → 上传坚果云 WebDAV → AI 生成财务分析报告 → 发送 QQ 邮箱。

核心能力：
- **🍜 位置智能**：高德地图地理编码 + DBSCAN 空间聚类，自动发现高频消费区域
- **🧠 记忆系统**：分层持久化关键洞察（用户画像 / 历史报告 / AI 建议），每次分析带上下文，越跑越懂你
- **📊 同期对比**：自动对比上一周期数据，追踪消费趋势变化
- **📬 多频次**：日报 / 周报 / 月报，各自独立触发

---

## 架构概览

```
┌────────────────────────────────────────────┐
│              Cron 调度层                     │
│      /etc/cron.d/yimu-report                │
│      source /etc/yimu-report/env            │
└──────┬──────────────────┬──────────────────┘
       │                  │
       ▼                  ▼
  ┌─────────┐      ┌──────────────┐
  │ 备份管道 │      │   报告管道     │
  │ 23:50   │      │ 日报 00:00    │
  │         │      │ 周报 周一00:00 │
  │         │      │ 月报 1号00:00  │
  └────┬────┘      └──────┬───────┘
       │                  │
       ▼                  ▼
  一木网页登录     坚果云 WebDAV 下载
  → 导出账单       → 解析 & 筛选
  → 上传坚果云     → 高德空间聚类
                   → DeepSeek 生成报告
                   → 记忆持久化
                   → QQ 邮箱发送
```

两条管道**完全解耦** — 备份挂了不影响历史报告重跑，报告挂了不影响备份积累。

---

## 部署方式

### 服务器 Cron（当前主力）

环境变量统一管理于 `/etc/yimu-report/env`，cron 执行时 `source` 加载：

```bash
# /etc/cron.d/yimu-report 中的每行格式：
0 16 * * * root bash -c 'set -a; source /etc/yimu-report/env; set +a; cd /root/yimu-report && REPORT_MODE=daily /usr/bin/python3 main.py'
```

| 任务 | 触发时间 | 模式 |
|------|------|------|
| 备份 | 每天 23:50 (UTC 15:50) | `backup.py` |
| 日报 | 每天 00:00 (UTC 16:00) | `REPORT_MODE=daily` |
| 周报 | 每周一 00:00 | `REPORT_MODE=weekly` |
| 月报 | 每月 1 号 00:00 | `REPORT_MODE=monthly` |

### GitHub Actions（冗余通道，当前未启用 schedule）

```yaml
# .github/workflows/ 下有四个独立 workflow：
backup.yml         # 备份
daily_report.yml   # 日报
weekly_report.yml  # 周报
monthly_report.yml # 月报
```

---

## 环境变量

| 变量 | 用途 | 必填 |
|------|------|:--:|
| `QQ_EMAIL` | 发件 QQ 邮箱 | ✅ |
| `QQ_AUTH_CODE` | QQ SMTP 授权码 | ✅ |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | ✅ |
| `DEEPSEEK_API_BASE` | API 端点（默认 `https://api.deepseek.com/v1`） | — |
| `AMAP_API_KEY` | 高德地图 API Key | ✅ |
| `WEBDAV_BASE_URL` | 坚果云 WebDAV 地址 | ✅ |
| `WEBDAV_USERNAME` | 坚果云账号 | ✅ |
| `WEBDAV_PASSWORD` | 坚果云应用密码 | ✅ |
| `WEBDAV_BACKUP_FOLDER` | 备份文件夹名（默认 `账单备份`） | — |
| `WEBDAV_FILE_PREFIX` | 备份文件前缀（默认 `yimu_bill`） | — |
| `TO_EMAIL` | 收件邮箱（默认与 `QQ_EMAIL` 相同） | — |
| `REPORT_MODE` | 报告模式：`daily` / `weekly` / `monthly` | — |
| `MONTHLY_BUDGET` | 月预算（默认 2000） | — |
| `USER_IDENTITY` | 用户身份描述（注入 prompt） | — |
| `MEMORY_DIR` | 记忆存储路径（默认 `/root/cow/memory/bill`） | — |

---

## 项目结构

```
yimu-report/
├── main.py                   # 报告主流程：下载→解析→分析→记忆→邮件
├── backup.py                 # 备份主流程：一木下载→坚果云上传
├── data_processor.py         # 账单解析、时间筛选、结构化摘要、环比计算
├── location_resolver.py      # 🍜 高德地理编码 + DBSCAN 空间聚类（637行，最复杂模块）
├── prompts.py                # AI 提示词模板（日报/周报/月报三套）
├── memory.py                 # 🧠 分层记忆系统（画像/洞察/报告快照/建议追踪）
├── webdav.py                 # 坚果云 WebDAV 操作（文件夹检查/上传/下载/清理）
├── download.py               # Playwright 无头浏览器：登录一木→导出账单
├── save_auth.py              # 一木网页端登录凭证获取（初始化用）
├── requirements.txt          # Python 依赖
├── CODE_REVIEW.md            # 代码审查记录
├── auth_state.json           # 一木登录态（本地文件，.gitignore 排除）
├── .amap_cache/              # 高德 API 缓存（地理编码结果，TTL 30 天）
└── .github/workflows/
    ├── backup.yml
    ├── daily_report.yml
    ├── weekly_report.yml
    └── monthly_report.yml
```

---

## 记忆系统

每次 Action/cron 执行是无状态的，记忆模块解决这个问题——让 AI 带着上下文分析。

### 分层存储（路径：`/root/cow/memory/bill/`）

| 文件 | 内容 | 容量 |
|------|------|:--:|
| `profile.json` | 用户画像（身份、预算、消费特征） | 长期 |
| `insights.json` | 跨模式关键洞察 | 滚动 20 条 |
| `last_report.json` | 上一次报告的指标快照 | 1 份 |
| `advice_log.json` | AI 历史建议追踪 | 最多 10 条 |

### 记忆生命周期

```
AI 生成报告
    │
    ├──▶ 提取关键指标 → last_report.json（下次同期对比）
    ├──▶ 截取报告洞察 → insights.json（滚动累积）
    └──▶ 记录建议内容 → advice_log.json（追踪执行）

下次分析时
    │
    └──▶ build_memory_context() 组装 → 注入 Prompt 用户背景段
        ├─ 用户画像（身份、预算、消费特征）
        ├─ 上次报告的指标快照
        └─ 近期洞察摘要 + 历史建议回顾
```
