#!/usr/bin/env python3
"""一木记账 DB 同步：从坚果云下载加密 zip → 7z 解密 → 保存 Custom.db 到知识库。

独立于 backup.py（xlsx 流程），不依赖 webdav.py。
供定时任务或手动运行。
"""

import os
import sys
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

# ── WebDAV 配置 ──────────────────────────────────────────────
WEBDAV_BASE_URL = os.environ.get("WEBDAV_BASE_URL", "https://dav.jianguoyun.com/dav/")
WEBDAV_USERNAME = os.environ.get("WEBDAV_USERNAME", "")
WEBDAV_PASSWORD = os.environ.get("WEBDAV_PASSWORD", "")
ZIP_FOLDER = os.environ.get("WEBDAV_ZIP_FOLDER", "一木记账")
ZIP_PASSWORD = os.environ.get("ZIP_PASSWORD", "")
if not ZIP_PASSWORD:
    raise RuntimeError("请设置 ZIP_PASSWORD 环境变量")

KNOWLEDGE_DATA_DIR = os.path.expanduser("~/cow/knowledge/finance/data")
DB_FILENAME = "Custom.db"


def _folder_url():
    return WEBDAV_BASE_URL.rstrip("/") + "/" + ZIP_FOLDER + "/"


def _file_url(filename):
    return WEBDAV_BASE_URL.rstrip("/") + "/" + ZIP_FOLDER + "/" + filename


def list_zip_files():
    """列出坚果云 一木记账/ 目录中的 .zip 文件，按名称降序。"""
    headers = {"Depth": "1"}
    body = """<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:">
  <D:prop><D:displayname/><D:getcontentlength/></D:prop>
</D:propfind>"""

    try:
        resp = requests.request(
            "PROPFIND", _folder_url(),
            auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD),
            headers=headers, data=body, timeout=30,
        )
    except requests.exceptions.ConnectionError:
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
            if name and size > 0 and name.lower().endswith(".zip"):
                files.append({"name": name, "size": size})

    files.sort(key=lambda x: x["name"], reverse=True)
    return files


def download_and_extract_db():
    """从坚果云下载最新 zip → 7z 解密 → 返回 Custom.db 二进制内容。

    Returns:
        bytes: Custom.db 文件内容，失败返回 None。
    """
    files = list_zip_files()
    if not files:
        print("坚果云 一木记账/ 目录无 zip 文件")
        return None

    latest = files[0]
    url = _file_url(latest["name"])
    print(f"下载: {latest['name']} ({latest['size']:,} bytes)")

    try:
        resp = requests.get(url, auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD), timeout=120)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"下载失败: {e}")
        return None

    # 写入临时文件 → 7z 解密
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, latest["name"])
        with open(zip_path, "wb") as f:
            f.write(resp.content)

        result = subprocess.run(
            ["7z", "x", f"-p{ZIP_PASSWORD}", f"-o{tmpdir}", zip_path, "-y"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"7z 解密失败:\n{result.stderr}")
            return None

        db_path = os.path.join(tmpdir, DB_FILENAME)
        if not os.path.exists(db_path):
            print(f"zip 中未找到 {DB_FILENAME}")
            return None

        with open(db_path, "rb") as f:
            db_bytes = f.read()

    print(f"解密成功: {DB_FILENAME} ({len(db_bytes):,} bytes)")
    return db_bytes


def main():
    print("=== 一木记账 DB 同步 ===")

    db_bytes = download_and_extract_db()
    if db_bytes is None:
        print("同步失败")
        sys.exit(1)

    os.makedirs(KNOWLEDGE_DATA_DIR, exist_ok=True)
    dest = os.path.join(KNOWLEDGE_DATA_DIR, DB_FILENAME)
    with open(dest, "wb") as f:
        f.write(db_bytes)
    print(f"已保存: {dest}")


if __name__ == "__main__":
    main()
