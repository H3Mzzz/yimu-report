"""本地运行一次，手动登录一木记账后自动保存 auth_state.json。"""
import json
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("请在浏览器中手动登录一木记账...")
        await page.goto("https://www.yimubill.com/")
        await page.wait_for_selector("text=账单导出", timeout=120000)

        print("登录成功，保存凭证...")
        await context.storage_state(path="auth_state.json")
        print("已保存到 auth_state.json")
        await browser.close()


asyncio.run(main())
