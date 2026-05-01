#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一木账单 Excel 导出模块，使用 Playwright 模拟浏览器下载"""

import os
import json
import asyncio
from playwright.async_api import async_playwright

YIMU_URL = "https://www.yimubill.com/"


async def download_excel(auth_state: dict) -> bytes:
    """
    使用已保存的登录状态（无头浏览器）导出账单 Excel。
    参数：
        auth_state: Playwright storage_state 格式的字典
    返回：
        下载文件的二进制内容
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=auth_state,
            accept_downloads=True,
            viewport={"width": 1280, "height": 720}
        )
        print("登录状态已注入，进入主页...")
        page = await context.new_page()
        await page.goto(YIMU_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded")   
        await page.wait_for_timeout(10000)
        # 验证登录状态
        if await page.query_selector("text=登 录") is not None:
            raise RuntimeError(
                "登录状态已过期！请重新获取 auth_state.json 并更新 GitHub Secret: YIMU_AUTH_STATE"
            )
        print("登录状态有效 ✓")

        # 等待页面数据同步
        await page.wait_for_timeout(60000)

        # 点击设置图标（第二个 svg）
        print("点击设置图标...")
        await page.locator("svg").nth(1).click()
        await page.wait_for_timeout(1000)

        # 点击“账单导出”
        print("点击菜单中的账单导出...")
        await page.get_by_text("账单导出").click()
        await page.wait_for_timeout(1000)

        # 拦截下载并确认导出 Excel
        print("确认导出，等待文件下载...")
        async with page.expect_download(timeout=60000) as dl_info:
            await page.get_by_text("导出 Excel").click()

        download = await dl_info.value
        path = await download.path()
        with open(path, "rb") as f:
            content = f.read()

        await browser.close()
        print(f"下载成功，大小：{len(content)} bytes")
        return content


# 如果直接运行本模块，可从环境变量加载 auth_state 并执行下载（用于本地测试）
if __name__ == "__main__":
    auth_state_json = os.environ.get("YIMU_AUTH_STATE")
    if not auth_state_json:
        # 也可尝试从本地文件读取
        try:
            with open("auth_state.json", "r") as f:
                auth_state = json.load(f)
        except FileNotFoundError:
            raise RuntimeError("请设置环境变量 YIMU_AUTH_STATE 或提供 auth_state.json 文件")
    else:
        auth_state = json.loads(auth_state_json)

    excel_bytes = asyncio.run(download_excel(auth_state))
    # 保存到本地文件，方便检查
    with open("exported.xlsx", "wb") as f:
        f.write(excel_bytes)
    print("文件已保存为 exported.xlsx")