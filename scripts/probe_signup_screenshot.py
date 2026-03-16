"""Probe signup with screenshot capture after submit."""
import asyncio
import random
import string
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        rnd = ''.join(random.choices(string.ascii_lowercase, k=8))
        email = f"test_{rnd}@mailinator.com"
        pw = "TestPass123!"

        await page.goto("https://app.aptlyflow.xyz/sign-up", wait_until="networkidle", timeout=20000)

        for name, value in [("first_name", "Test"), ("last_name", "User"), ("phone", "3478901234"), ("email", email), ("password", pw)]:
            loc = page.locator(f'input[name="{name}"]')
            await loc.click()
            await loc.type(value, delay=30)

        print(f"Submitting: {email}")
        await page.locator('button[type="submit"]').click()

        # Wait and capture screenshots to see what happens
        for i in range(6):
            await page.wait_for_timeout(1000)
            url = page.url
            print(f"  [{i+1}s] URL: {url}")
            await page.screenshot(path=f"/tmp/signup_t{i+1}.png")
            if "create-business" in url:
                print("  -> Reached create-business!")
                break

        # Check for any alert/error text
        try:
            alerts = await page.locator('[role="alert"], .error, .alert, [class*="error"], [class*="alert"]').all()
            for a in alerts:
                txt = (await a.text_content() or "").strip()
                vis = await a.is_visible()
                if txt:
                    print(f"Alert/error visible={vis}: {txt!r}")
        except Exception:
            pass

        # Full page contents
        body = (await page.inner_text("body") or "")
        print(f"\nFull body ({len(body)} chars):\n{body[:800]}")

        await browser.close()


asyncio.run(main())
