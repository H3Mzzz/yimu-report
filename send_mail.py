#!/usr/bin/env python3
"""QQ 邮箱 SMTP 发送工具。供 send_report.py 调用。"""

import argparse
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(subject, plain_body, html_body=None, from_addr=None, to_addr=None, auth_code=None):
    from_addr = from_addr or os.environ.get("QQ_EMAIL", "")
    to_addr = to_addr or os.environ.get("TO_EMAIL", from_addr)
    auth_code = auth_code or os.environ.get("QQ_AUTH_CODE", "")

    if not from_addr or not auth_code:
        raise RuntimeError("缺少 QQ_EMAIL 或 QQ_AUTH_CODE 环境变量")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
        server.login(from_addr, auth_code)
        server.sendmail(from_addr, to_addr, msg.as_string())
    print(f"邮件已发送到 {to_addr}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="发送邮件")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", help="纯文本正文")
    parser.add_argument("--body-file", help="从文件读取纯文本正文")
    parser.add_argument("--html-file", help="HTML 正文（可选）")
    args = parser.parse_args()

    if args.body:
        plain = args.body
    elif args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as f:
            plain = f.read()
    else:
        raise ValueError("必须指定 --body 或 --body-file")

    html = None
    if args.html_file:
        with open(args.html_file, "r", encoding="utf-8") as f:
            html = f.read()

    send_email(args.subject, plain, html)
