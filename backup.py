#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立备份脚本 —— 从一木记账下载账单并上传到坚果云 WebDAV

用途：定时任务独立运行（如每天一次），与报告生成完全解耦。
运行后坚果云"账单备份"文件夹中始终有最新账单可供报告脚本消费。

依赖环境变量：
- YIMU_AUTH_STATE          : 一木记账登录状态 JSON
- WEBDAV_BASE_URL          : (可选) 坚果云地址
- WEBDAV_USERNAME          : (可选) 坚果云账号
- WEBDAV_PASSWORD          : (可选) 坚果云应用密码
- WEBDAV_BACKUP_FOLDER     : (可选) 备份文件夹名

运行方式：
    python backup.py
"""

import os
import json
import asyncio
from download import download_excel
from webdav import ensure_backup_folder, upload_backup


async def main():
    print("=== 一木记账 → 坚果云 备份任务 ===")

    # 1. 加载登录状态
    auth_state_json = os.environ.get("YIMU_AUTH_STATE")
    if not auth_state_json:
        # 尝试从本地文件读取（本地测试用）
        try:
            with open("auth_state.json", "r", encoding="utf-8") as f:
                auth_state = json.load(f)
        except FileNotFoundError:
            raise RuntimeError("请设置环境变量 YIMU_AUTH_STATE 或提供 auth_state.json 文件")
    else:
        auth_state = json.loads(auth_state_json)

    # 2. 确保坚果云备份文件夹存在
    if not ensure_backup_folder():
        print("❌ 坚果云不可用，备份失败")
        return

    # 3. 从一木记账网页下载账单
    print("📥 正在从一木记账下载账单...")
    try:
        excel_bytes = await download_excel(auth_state)
        print(f"✅ 一木记账下载成功（{len(excel_bytes)} bytes）")
    except Exception as e:
        print(f"❌ 一木记账下载失败: {e}")
        raise

    # 4. 上传到坚果云
    print("📤 正在上传到坚果云...")
    try:
        filename = upload_backup(excel_bytes)
        print(f"🎉 备份完成！文件: {filename}")
    except Exception as e:
        print(f"❌ 上传坚果云失败: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
