#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""坚果云 WebDAV 账单备份模块"""

import os
import requests
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET

# ======================== 坚果云 WebDAV 配置 ========================
WEBDAV_BASE_URL = os.environ.get("WEBDAV_BASE_URL", "https://dav.jianguoyun.com/dav/")
WEBDAV_USERNAME = os.environ.get("WEBDAV_USERNAME", "")
WEBDAV_PASSWORD = os.environ.get("WEBDAV_PASSWORD", "")
BACKUP_FOLDER = os.environ.get("WEBDAV_BACKUP_FOLDER", "账单备份")
FILE_PREFIX = os.environ.get("WEBDAV_FILE_PREFIX", "bill")


def _get_folder_url():
    """获取备份文件夹的完整 WebDAV URL"""
    base = WEBDAV_BASE_URL.rstrip("/") + "/"
    return f"{base}{BACKUP_FOLDER}/"


def _get_file_url(filename: str):
    """获取文件的完整 WebDAV URL"""
    base = WEBDAV_BASE_URL.rstrip("/") + "/"
    return f"{base}{BACKUP_FOLDER}/{filename}"


def ensure_backup_folder():
    """确保备份文件夹存在（MKCOL 创建，405=已存在也视为成功）"""
    url = _get_folder_url()
    try:
        resp = requests.request(
            "MKCOL", url,
            auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD),
            timeout=15
        )
        if resp.status_code in (201, 405):
            print(f"✅ 坚果云备份文件夹已就绪: /{BACKUP_FOLDER}/")
            return True
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        print(f"⚠️ 无法连接坚果云服务器: {e}")
        return False
    return True


def list_backup_files():
    """列出备份文件夹中的所有 .xlsx 文件，返回列表按名称降序"""
    url = _get_folder_url()
    headers = {"Depth": "1"}

    propfind_body = """<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:">
  <D:prop>
    <D:displayname/>
    <D:getcontentlength/>
    <D:getlastmodified/>
  </D:prop>
</D:propfind>"""

    try:
        response = requests.request(
            "PROPFIND", url,
            auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD),
            headers=headers,
            data=propfind_body,
            timeout=30
        )
    except requests.exceptions.ConnectionError as e:
        print(f"⚠️ 无法连接坚果云列出文件: {e}")
        return []

    if response.status_code == 404:
        print(f"⚠️ 备份文件夹 /{BACKUP_FOLDER}/ 不存在")
        return []

    if response.status_code != 207:
        print(f"⚠️ PROPFIND 返回异常状态码: {response.status_code}")
        return []

    # 解析 XML 响应
    ns = {"d": "DAV:"}
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        print(f"⚠️ 解析 XML 失败: {e}")
        return []

    files = []
    for resp_elem in root.findall("d:response", ns):
        displayname = resp_elem.find(".//d:displayname", ns)
        content_length = resp_elem.find(".//d:getcontentlength", ns)
        last_modified = resp_elem.find(".//d:getlastmodified", ns)

        if displayname is not None:
            name = displayname.text or ""
            size = int(content_length.text) if content_length is not None and content_length.text else 0
            mtime = last_modified.text if last_modified is not None else ""

            # 只保留有实际大小的 .xlsx 文件
            if name and size > 0 and name.lower().endswith(".xlsx"):
                files.append({
                    "name": name,
                    "size": size,
                    "last_modified": mtime,
                })

    # 按文件名降序（日期越新越靠前）
    files.sort(key=lambda x: x["name"], reverse=True)
    print(f"📂 坚果云 /{BACKUP_FOLDER}/ 中共有 {len(files)} 个账单文件")
    return files


def download_latest_backup():
    """
    从坚果云下载最新的账单备份文件。
    返回 (bytes, filename) 或 (None, None)
    """
    files = list_backup_files()
    if not files:
        print("📭 坚果云备份文件夹为空，无可下载文件")
        return None, None

    latest = files[0]
    print(f"📥 准备从坚果云下载: {latest['name']}（{latest['size']} bytes）")

    url = _get_file_url(latest["name"])
    try:
        response = requests.get(
            url,
            auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD),
            timeout=60
        )
        response.raise_for_status()
        print(f"✅ 从坚果云下载成功: {latest['name']}（{len(response.content)} bytes）")
        return response.content, latest["name"]
    except requests.exceptions.RequestException as e:
        print(f"❌ 从坚果云下载失败: {e}")
        return None, None


def upload_backup(excel_bytes: bytes, filename: str = None):
    """
    上传账单备份到坚果云。
    参数:
        excel_bytes: Excel 文件的二进制内容
        filename: 自定义文件名，默认按日期自动命名
    返回: 上传后的文件名
    """
    if filename is None:
        china_tz = timezone(timedelta(hours=8))
        filename = f"{FILE_PREFIX}_{datetime.now(china_tz).strftime('%Y%m%d_%H%M%S')}.xlsx"

    url = _get_file_url(filename)
    try:
        response = requests.put(
            url,
            data=excel_bytes,
            auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD),
            timeout=120
        )
        response.raise_for_status()
        print(f"✅ 已上传备份到坚果云: /{BACKUP_FOLDER}/{filename}（{len(excel_bytes)} bytes）")
        return filename
    except requests.exceptions.RequestException as e:
        print(f"❌ 上传坚果云失败: {e}")
        raise


def delete_backup(filename: str) -> bool:
    """删除指定文件"""
    url = _get_file_url(filename)
    try:
        response = requests.delete(
            url,
            auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD),
            timeout=15
        )
        if response.status_code in (200, 204):
            print(f"🗑️ 已删除: {filename}")
            return True
        else:
            print(f"⚠️ 删除失败 ({filename}): HTTP {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ 删除请求失败 ({filename}): {e}")
        return False


def cleanup_old_backups(keep: int = 10):
    """
    清理旧备份，仅保留最新的 keep 个文件。
    由于文件按名称（时间戳）降序排列，直接删除 keep 之后的所有文件。
    """
    files = list_backup_files()
    if len(files) <= keep:
        print(f"📦 共 {len(files)} 个备份，未超过保留上限 {keep}，无需清理")
        return

    to_delete = files[keep:]  # 跳过前 keep 个最新的
    print(f"🧹 共 {len(files)} 个备份，将删除 {len(to_delete)} 个旧文件...")
    for f in to_delete:
        delete_backup(f["name"])
