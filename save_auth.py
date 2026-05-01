"""
本地运行一次，手动登录后自动保存完整的存储状态（包含 localStorage 和 Cookies）。
保存的 auth_state.json 内容粘贴到 GitHub Secret: YIMU_AUTH_STATE
"""
import json
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("正在打开一木记账网页端，请在浏览器中手动登录（包括验证码）...")
        await page.goto("https://www.yimubill.com/")

        print("请在浏览器里完成登录，登录成功后这里会自动继续...")
        await page.wait_for_selector("text=账单导出", timeout=120000)  
        print("检测到登录成功！正在保存完整的登录凭证 (Storage State)...")

        await context.storage_state(path="auth_state.json")

        print("✅ 登录状态已完整保存到 auth_state.json")
        print("请打开 auth_state.json，复制全部内容，粘贴到 GitHub Secret 中")
        await browser.close()

asyncio.run(main())