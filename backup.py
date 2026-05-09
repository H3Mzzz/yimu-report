#!/usr/bin/env python3
"""备份脚本：一木记账 → 下载账单 → 上传坚果云 + 同步知识库。

供定时任务独立运行（每天一次），与报告生成解耦。
"""

import os
import sys
import json
import asyncio
from datetime import datetime

# 确保脚本所在目录在 Python 路径中，避免 CWD 不同时导入失败
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from download import download_excel
from webdav import ensure_backup_folder, upload_backup, cleanup_old_backups

KNOWLEDGE_DATA_DIR = os.path.expanduser("~/cow/knowledge/finance/data")


async def main():
    print("=== 一木记账 → 坚果云 备份 ===")

    auth_state_json = os.environ.get("YIMU_AUTH_STATE")
    if not auth_state_json:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            auth_path = os.path.join(script_dir, "auth_state.json")
            with open(auth_path, "r", encoding="utf-8") as f:
                auth_state = json.load(f)
        except FileNotFoundError:
            raise RuntimeError("请设置 YIMU_AUTH_STATE 或提供 auth_state.json")
    else:
        auth_state = json.loads(auth_state_json)

    if not ensure_backup_folder():
        print("坚果云不可用，备份中止")
        return

    print("下载账单...")
    excel_bytes = await download_excel(auth_state)

    print("上传坚果云...")
    filename = upload_backup(excel_bytes)
    print(f"已上传: {filename}")
    cleanup_old_backups(keep=10)

    os.makedirs(KNOWLEDGE_DATA_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    knowledge_file = os.path.join(KNOWLEDGE_DATA_DIR, f"bills_{today}.xlsx")
    with open(knowledge_file, "wb") as f:
        f.write(excel_bytes)
    print(f"已同步知识库: {knowledge_file}")

    all_bills = sorted(
        [f for f in os.listdir(KNOWLEDGE_DATA_DIR) if f.startswith("bills_") and f.endswith(".xlsx")],
        reverse=True,
    )
    for old_file in all_bills[5:]:
        os.remove(os.path.join(KNOWLEDGE_DATA_DIR, old_file))


if __name__ == "__main__":
    asyncio.run(main())
