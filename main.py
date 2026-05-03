#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一木账单自动财务报告脚本

数据获取流程：
  1. 从坚果云 WebDAV "账单备份" 文件夹下载最新账单（由独立备份脚本定期上传）
  2. 若 WebDAV 无备份，报告任务中止（不再回退到网页下载）

依赖环境变量：
- QQ_EMAIL               : 发件 QQ 邮箱地址
- QQ_AUTH_CODE           : QQ 邮箱 SMTP 授权码
- DEEPSEEK_API_KEY       : DeepSeek API Key
- TO_EMAIL               : (可选) 收件邮箱，默认为 QQ_EMAIL
- REPORT_MODE            : (可选) daily / weekly / monthly，默认 weekly
- WEBDAV_BASE_URL        : (可选) 坚果云 WebDAV 地址，默认 https://dav.jianguoyun.com/dav/
- WEBDAV_USERNAME        : (可选) 坚果云账号
- WEBDAV_PASSWORD        : (可选) 坚果云应用密码
- WEBDAV_BACKUP_FOLDER   : (可选) 备份文件夹名
"""

import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from openai import OpenAI
from prompts import get_prompt
from data_processor import parse_transactions, summarize, generate_comparison_summary
from webdav import ensure_backup_folder, download_latest_backup


# ======================== 配置与常量 ========================
REQUIRED_ENV_VARS = ["QQ_EMAIL", "QQ_AUTH_CODE", "DEEPSEEK_API_KEY"]
MODE_DAYS_MAP = {"daily": 1, "weekly": 7, "monthly": 30}


def _get_config() -> dict:
    """从环境变量读取并校验配置，返回配置字典"""
    missing = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing:
        raise RuntimeError(f"缺少必需环境变量: {', '.join(missing)}")
    return {
        "qq_email": os.environ["QQ_EMAIL"],
        "qq_auth_code": os.environ["QQ_AUTH_CODE"],
        "to_email": os.environ.get("TO_EMAIL", os.environ["QQ_EMAIL"]),
        "deepseek_key": os.environ["DEEPSEEK_API_KEY"],
        "report_mode": os.environ.get("REPORT_MODE", "weekly"),
    }


# ======================== 第一步：从坚果云 WebDAV 下载备份 ========================
# 见 webdav.py 中的 download_latest_backup() 函数


# ======================== 第二步：解析 Excel 并筛选 ========================
# 见 data_processor.py 中的 parse_transactions() 函数


# ======================== 第三步：生成数据摘要 ========================
# 见 data_processor.py 中的 summarize() 函数


# ======================== 第四步：AI 生成专业报告 ========================
def generate_report(summary: str, period_label: str, api_key: str, mode: str,
                    comparison_summary: str = None, previous_label: str = None) -> str:
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    prompt = get_prompt(
        mode=mode,
        period_label=period_label,
        summary=summary,
        comparison_summary=comparison_summary,
        previous_label=previous_label
    )
    try:
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            max_tokens=4000,          # 根据需要调整输出长度，过短可能不够详细，过长可能被截断
            messages=[{"role": "user", "content": prompt}],
            reasoning_effects="high",
            extra_body={"thinking": {"type": "enabled"}}

        )
        choice = response.choices[0]
        content = choice.message.content
        finish_reason = choice.finish_reason

        if finish_reason == "length":
            print("⚠️ 警告：AI 输出因 max_tokens 限制被截断，当前回答长度可能不足，请考虑继续增加 max_tokens")
        elif finish_reason != "stop":
            print(f"⚠️ 异常终止原因: {finish_reason}")

        if not content or not content.strip():
            print("❌ AI 返回内容为空")
            return "（⚠️ AI 报告生成失败，请检查 API 账户或数据）"

        return content
    except Exception as e:
        print(f"❌ 调用 DeepSeek API 失败: {e}")
        return f"（⚠️ AI 报告生成失败：{e}）"

# ======================== 第五步：发送邮件 ========================
def send_email(subject: str, body: str, from_addr: str, to_addr: str, auth_code: str):
    """通过 QQ 邮箱 SMTP 发送纯文本邮件"""
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
        server.login(from_addr, auth_code)
        server.sendmail(from_addr, to_addr, msg.as_string())
    print(f"✅ 邮件已发送到 {to_addr}")


# ======================== 主流程 ========================
def main():
    print("=== 一木财务报告自动化（GitHub Action 版）===")
    config = _get_config()
    print(f"报告模式: {config['report_mode']}")

    try:
        # ========== 从坚果云 WebDAV 下载最新账单备份 ==========
        print("--- 获取账单数据 ---")
        if not ensure_backup_folder():
            raise RuntimeError("坚果云 WebDAV 不可用，无法获取账单备份")

        excel_bytes, downloaded_filename = download_latest_backup()
        if excel_bytes is None:
            raise RuntimeError("坚果云无可用账单备份，请确认独立备份脚本是否正常运行")

        print(f"📥 使用坚果云备份文件: {downloaded_filename}")

        mode = config["report_mode"]
        df, period_label = parse_transactions(excel_bytes, mode)
        if df.empty:
            print("⚠️ 该时间段无数据，跳过报告生成。")
            return

        summary = summarize(df, period_label)

        # ========== 尝试提取上一周期数据 ==========
        comparison_summary = None
        previous_label = None
        try:
            previous_mode = f"previous_{mode}"   # 例如 "previous_weekly"
            df_prev, prev_label = parse_transactions(excel_bytes, previous_mode)
            if not df_prev.empty:
                previous_label = prev_label
                comparison_summary = generate_comparison_summary(df, df_prev, period_label, previous_label)
        except Exception as e:
            print(f"无法生成上周期对比数据（可能无历史记录）: {e}")

        report = generate_report(
            summary,
            period_label,
            config["deepseek_key"],
            mode,
            comparison_summary=comparison_summary,
            previous_label=previous_label
        )

        print("\n--- AI 报告 ---\n" + report)
        china_tz = timezone(timedelta(hours=8))
        today_str = datetime.now(china_tz).strftime("%Y年%m月%d日")
        email_body = f"{summary}\n\n{'='*50}\n\n{report}"
        send_email(
            subject=f"💰 {period_label}财务报告 · {today_str}",
            body=email_body,
            from_addr=config["qq_email"],
            to_addr=config["to_email"],
            auth_code=config["qq_auth_code"],
        )
    except Exception as e:
        print(f"❌ 主流程出错: {e}")
        try:
            send_email(
                subject="⚠️ 财务报告生成失败",
                body=f"自动财务报告运行出错：\n\n{e}",
                from_addr=config["qq_email"],
                to_addr=config["to_email"],
                auth_code=config["qq_auth_code"],
            )
        except Exception as mail_err:
            print(f"发送错误邮件也失败: {mail_err}")
        raise


if __name__ == "__main__":
    main()