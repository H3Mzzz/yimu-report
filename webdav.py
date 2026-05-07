#!/usr/bin/env python3
"""坚果云 WebDAV 客户端：上传/下载/列表/清理账单备份。"""

import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

WEBDAV_BASE_URL = os.environ.get("WEBDAV_BASE_URL", "https://dav.jianguoyun.com/dav/")
WEBDAV_USERNAME = os.environ.get("WEBDAV_USERNAME", "")
WEBDAV_PASSWORD = os.environ.get("WEBDAV_PASSWORD", "")
BACKUP_FOLDER = os.environ.get("WEBDAV_BACKUP_FOLDER", "账单备份")
FILE_PREFIX = os.environ.get("WEBDAV_FILE_PREFIX", "bill")


def _base():
    return WEBDAV_BASE_URL.rstrip("/") + "/"


def _folder_url():
    return f"{_base()}{BACKUP_FOLDER}/"


def _file_url(filename):
    return f"{_base()}{BACKUP_FOLDER}/{filename}"


def ensure_backup_folder():
    """确保备份文件夹存在（MKCOL，405=已存在也视为成功）。"""
    try:
        resp = requests.request("MKCOL", _folder_url(),
                                auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD), timeout=15)
        if resp.status_code in (201, 405):
            return True
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        return False
    return True


def list_backup_files():
    """列出备份文件夹中所有 .xlsx 文件，按名称降序。"""
    headers = {"Depth": "1"}
    body = """<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:">
  <D:prop><D:displayname/><D:getcontentlength/><D:getlastmodified/></D:prop>
</D:propfind>"""

    try:
        resp = requests.request("PROPFIND", _folder_url(),
                                auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD),
                                headers=headers, data=body, timeout=30)
    except requests.exceptions.ConnectionError:
        return []

    if resp.status_code == 404:
        return []
    if resp.status_code != 207:
        return []

    ns = {"d": "DAV:"}
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []

    files = []
    for elem in root.findall("d:response", ns):
        name_el = elem.find(".//d:displayname", ns)
        size_el = elem.find(".//d:getcontentlength", ns)
        if name_el is not None:
            name = name_el.text or ""
            size = int(size_el.text) if size_el is not None and size_el.text else 0
            if name and size > 0 and name.lower().endswith(".xlsx"):
                files.append({"name": name, "size": size})

    files.sort(key=lambda x: x["name"], reverse=True)
    return files


def download_latest_backup():
    """下载最新账单备份，返回 (bytes, filename) 或 (None, None)。"""
    files = list_backup_files()
    if not files:
        return None, None

    latest = files[0]
    url = _file_url(latest["name"])
    try:
        resp = requests.get(url, auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD), timeout=60)
        resp.raise_for_status()
        print(f"已下载: {latest['name']} ({len(resp.content)} bytes)")
        return resp.content, latest["name"]
    except requests.exceptions.RequestException as e:
        print(f"下载失败: {e}")
        return None, None


def upload_backup(excel_bytes, filename=None):
    """上传账单备份，默认按时间戳自动命名。返回最终文件名。"""
    if filename is None:
        tz = timezone(timedelta(hours=8))
        filename = f"{FILE_PREFIX}_{datetime.now(tz).strftime('%Y%m%d_%H%M%S')}.xlsx"

    url = _file_url(filename)
    resp = requests.put(url, data=excel_bytes,
                        auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD), timeout=120)
    resp.raise_for_status()
    print(f"已上传: /{BACKUP_FOLDER}/{filename} ({len(excel_bytes)} bytes)")
    return filename


def delete_backup(filename):
    """删除指定文件。"""
    try:
        resp = requests.delete(_file_url(filename),
                               auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD), timeout=15)
        return resp.status_code in (200, 204)
    except requests.exceptions.RequestException:
        return False


def cleanup_old_backups(keep=10):
    """仅保留最新 keep 个备份，删除其余。"""
    files = list_backup_files()
    if len(files) <= keep:
        return
    for f in files[keep:]:
        delete_backup(f["name"])
