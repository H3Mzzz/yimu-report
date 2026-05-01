# 一木记账 · 自动财务报告

每周/每日/每月自动从一木网页端导出账单，用 AI 生成财务分析，发送到 QQ 邮箱。

---

## 部署步骤

### 第一步：配置 QQ 邮箱授权码

QQ 邮箱发信需要「授权码」，不是 QQ 密码：

1. 打开 QQ 邮箱网页版 → 设置 → 账户
2. 找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」
3. 开启「SMTP服务」，按提示发短信验证
4. 生成并复制授权码（格式类似 `abcdabcdabcd`）

### 第二步：在 GitHub 配置 Secrets

在你的 GitHub 仓库页面：`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

依次添加以下 5 个 Secret：

| Secret 名称 | 填入内容 |
|------------|---------|
| `YIMU_EMAIL` | 一木账号（邮箱/手机号）|
| `YIMU_PASSWORD` | 一木密码 |
| `QQ_EMAIL` | 你的 QQ 邮箱，如 `123456@qq.com` |
| `QQ_AUTH_CODE` | 上一步获取的授权码 |
| `ANTHROPIC_API_KEY` | DeepSeek API Key|

### 第三步：手动触发测试

1. 进入仓库 → `Actions` 标签页
2. 左侧点击「一木财务报告」
3. 右侧点「Run workflow」→「Run workflow」
4. 等待约 2-3 分钟，查看运行日志
5. 检查 QQ 邮箱是否收到报告

---

## 调整报告频率

修改 `.github/workflows/report.yml` 里的 cron 表达式：

```
每周一：0 0 * * 1
每天：  0 0 * * *
每月1号：0 0 1 * *
```

时区说明：cron 是 UTC 时间，北京时间 = UTC+8，所以早上8点北京时间 = UTC 0点。

---

## 文件说明

```
yimu-report/
├── main.py                        # 主脚本
├── data_processor.py              # 数据预处理
├── prompts.py                     # AI提示词
├── download.py                    # 下载账单
├── requirements.txt               # Python 依赖
├── .github/
│   └── workflows/
│       └── report.yml             # GitHub Actions 定时任务配置
└── README.md                      # 本文件
```
