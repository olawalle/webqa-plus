"""Probe login form buttons."""
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://app.aptlyflow.xyz/login", wait_until="networkidle", timeout=20000)
        buttons = await page.query_selector_all("button")
        print(f"Buttons ({len(buttons)}):")
        for btn in buttons:
            t = await btn.get_attribute("type") or ""
            txt = (await btn.text_content() or "").strip()[:40]
            vis = await btn.is_visible()
            en = await btn.is_enabled()
            print(f"  type={t!r} visible={vis} enabled={en} text={txt!r}")

        sub = page.locator('button[type="submit"]').first
        print(f"\n'button[type=submit]' count: {await sub.count()}")

        sub2 = page.locator('button:has-text("Log in"), button:has-text("Login"), button:has-text("Sign in")').first
        cnt2 = await sub2.count()
        print(f"'button:has-text(login)' count: {cnt2}")
        if cnt2 > 0:
            print("  visible:", await sub2.is_visible(), "enabled:", await sub2.is_enabled())

        await browser.close()


asyncio.run(main())
