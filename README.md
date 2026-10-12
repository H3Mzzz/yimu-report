# 一木财务报告系统 (yimu-report)

> 基于「一木记账」App 导出的 SQLite 账单库，按周 / 月自动生成**中文财务分析报告**并通过邮件发送的自动化系统。
> 由 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的 cron 定时驱动，报告内容由 AI 依据 `bill-analyzer` skill 生成。

---

## 它做什么

```
手机「一木记账」App
      │  记账 / 分类 / 账户余额
      ▼
  坚果云 WebDAV（自动同步导出的 zip）
      │  sync_bill_db.sh —— 每天 23:50 下载 + 解密 + 落库
      ▼
  ~/knowledge/finance/data/Custom.db   ← SQLite 唯一数据源
      │  main.py —— 取数，输出结构化 JSON
      ▼
  AI 分析（bill-analyzer / finance-*-report skill）
      │  Python + pandas 复核数字，撰写分析段落
      ▼
  邮件报告（send_report.py，HTML + 附件）
```

**一句话**：把「每天记账」变成「每周一早上收到一份有人味儿的消费分析」。

---

## 特性

- **纯本地数据**：账单只存在服务器本机 SQLite，不上传任何第三方。
- **可复现的数字**：所有金额由 pandas 从 SQLite 直接算出，AI 只负责解读，不凭空生成数字。
- **长期记忆**：消费画像、预算配置、历史洞察存于 `knowledge/` 目录，报告会引用并更新。
- **中文优先**：分类、账户、报告文案全中文，适配国内记账习惯。

---

## 目录结构

```
yimu-report/
├── main.py                  # 取数入口：读 SQLite → 结构化 JSON
├── data_processor.py        # 核心统计逻辑（收入/支出/分类/账户/预算）
├── html_renderer.py         # 报告 HTML 渲染
├── location_resolver.py     # 消费地点反查（高德 API + 本地缓存）
├── send_report.py           # 邮件发送（SMTP）
├── send_mail.py             # 邮件发送底层
├── sync_db.py               # 从坚果云同步 DB
├── trim_knowledge.py        # 知识库归档精简
├── backup.py                # 备用：账单下载 + 上传（playwright 登录）
├── download.py / webdav.py / save_auth.py   # 备用上传链的组成模块
├── sync_bill_db.sh          # cron 入口：同步脚本
└── requirements.txt         # 运行时依赖
```

报告任务的**真实逻辑不在此仓库**，而在服务器的 Hermes skill 中（`bill-analyzer`、`finance-daily/weekly/monthly-report`），因为报告需要 AI 参与分析，属于 agent 流程而非纯脚本。

---

## 快速开始

**环境**：Linux / macOS + Python 3.10+，另需系统级 `7z`（解密坚果云 zip）。

```bash
pip install -r requirements.txt
```

**配置**（在 `~/.hermes/.env`，本仓库不含任何密钥）：

```bash
QQ_AUTH_CODE=<QQ邮箱SMTP授权码>
WEBDAV_USER=<坚果云账号>
WEBDAV_PASSWORD=<坚果云应用密码>
ZIP_PASSWORD=<账单导出密码>
AMAP_API_KEY=<高德地图Key，地点反查用>
```

**手动跑一次**：

```bash
# 1) 同步最新账单
bash sync_bill_db.sh

# 2) 取数（注意：首行是中文提示，跳掉才是纯 JSON）
python3 main.py --data-only --mode weekly | tail -n +2

# 3) 发送报告
python3 send_report.py --mode weekly --body-file /tmp/report.md
```

`--mode` 支持 `daily` / `weekly` / `monthly`。

---

## 数据表说明

系统实际只读 SQLite 中的 7 张表（库内共 130+ 张）：

| 表 | 作用 |
|---|---|
| `bill` | 收支明细（金额、时间、分类、地点） |
| `parentcategory` / `childcategory` | 一 / 二级分类 |
| `asset` | 账户与余额 |
| `budget` | 预算配置 |
| `refund` / `refund_refundinfos` | 退款与退款备注 |

---

## 隐私与安全

- **真实账单数据不进仓库**：数据库、导出文件、`.env` 均在 `.gitignore` 中。
- 仓库工作区与提交历史均不含真实金额、真实账号、真实地点或任何凭据。

---

## 关于本仓库

本仓库为**个人自用系统**的公开留档，主要用途是版本管理与架构参考。因含个人化的 skill 流程与私有数据依赖，**不建议直接 clone 后运行**；如需参考，请重点看 `data_processor.py` 的统计口径与 `main.py` 的取数结构。

## License

个人项目，未指定开源协议。代码仅供参考。
