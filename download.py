#!/usr/bin/env python3
"""一木账单网页下载模块，Playwright 无头浏览器模拟登录 → 导出 Excel。"""

import os
import json
import asyncio
from playwright.async_api import async_playwright

YIMU_URL = "https://www.yimubill.com/"


async def download_excel(auth_state: dict) -> bytes:
    """使用已保存的登录状态导出账单 Excel，返回文件二进制内容。"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=auth_state,
            accept_downloads=True,
            viewport={"width": 1280, "height": 720},
        )
        page = await context.new_page()
        await page.goto(YIMU_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(10000)

        if await page.query_selector("text=登 录") is not None:
            raise RuntimeError("登录状态已过期，请重新获取 auth_state.json")

        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(5000)

        settings_btn = page.locator('[aria-label*="设置"], [aria-label*="setting"], [title*="设置"], [aria-label*="更多"]').first
        if await settings_btn.count() == 0:
            settings_btn = page.locator("svg").nth(1)
        await settings_btn.click()
        await page.wait_for_timeout(1000)

        await page.get_by_text("账单导出").click()
        await page.wait_for_timeout(1000)

        async with page.expect_download(timeout=60000) as dl_info:
            await page.get_by_text("导出 Excel").click()

        download = await dl_info.value
        path = await download.path()
        with open(path, "rb") as f:
            content = f.read()

        await browser.close()
        print(f"下载成功，{len(content)} bytes")
        return content


if __name__ == "__main__":
    auth_state_json = os.environ.get("YIMU_AUTH_STATE")
    if not auth_state_json:
        try:
            with open("auth_state.json", "r") as f:
                auth_state = json.load(f)
        except FileNotFoundError:
            raise RuntimeError("请设置 YIMU_AUTH_STATE 或提供 auth_state.json")
    else:
        auth_state = json.loads(auth_state_json)

    excel_bytes = asyncio.run(download_excel(auth_state))
    with open("exported.xlsx", "wb") as f:
        f.write(excel_bytes)
    print("已保存 exported.xlsx")
