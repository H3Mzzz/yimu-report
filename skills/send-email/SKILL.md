---
name: send-email
description: Send emails via SMTP (QQ Mail). Use when the user asks to send an email, send a report by email, forward content via email, or when the agent needs to deliver financial reports/notifications via email.
metadata:
  requires:
    bins: ["python3"]
    env: ["MAIL_USER", "MAIL_PASSWORD", "MAIL_TO"]
---

## Setup

Email is sent via QQ Mail SMTP (端口 465, SSL).

Environment variables (already configured):
- `MAIL_USER` — sender email (e.g. `1021348725@qq.com`)
- `MAIL_PASSWORD` — QQ Mail authorization code (not login password)
- `MAIL_TO` — default recipient (can be overridden)

## Usage

Run the script with subject and body:

```bash
python3 "<base_dir>/scripts/send_mail.py" --subject "主题" --body "正文内容"
```

For HTML body:
```bash
python3 "<base_dir>/scripts/send_mail.py" --subject "主题" --body "<h1>标题</h1><p>内容</p>"
```

For file body:
```bash
python3 "<base_dir>/scripts/send_mail.py" --subject "主题" --body-file /path/to/body.html
```

Override recipient:
```bash
python3 "<base_dir>/scripts/send_mail.py" --subject "主题" --body "内容" --to "other@example.com"
```

Attach files:
```bash
python3 "<base_dir>/scripts/send_mail.py" --subject "主题" --body "内容" --attach /path/to/file.pdf
```

## Parameters

| 参数 | 说明 | 必需 |
|------|------|------|
| `--subject` | 邮件主题 | ✅ |
| `--body` | 邮件正文（纯文本或 HTML） | 二选一 |
| `--body-file` | 从文件读取正文 | 二选一 |
| `--to` | 收件人（默认用 MAIL_TO） | ❌ |
| `--attach` | 附件路径（可多次使用） | ❌ |

## Notes

- 正文包含 `<html>` 或 `<h1>` 等标签时自动以 HTML 格式发送
- 使用 QQ Mail SMTP SSL (smtp.qq.com:465)
- 发送成功返回 exit code 0，失败返回 1 并打印错误
