"""Probe /login page for sign-up navigation links and form fields."""
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://app.aptlyflow.xyz/login", wait_until="networkidle", timeout=20000)
        print(f"Final URL: {page.url}\n")

        # Check all anchor tags
        links = await page.query_selector_all("a")
        print(f"Links ({len(links)}):")
        for lnk in links:
            txt = (await lnk.text_content() or "").strip()[:50]
            href = await lnk.get_attribute("href") or ""
            vis = await lnk.is_visible()
            print(f"  href={href!r} visible={vis} text={txt!r}")

        # Check for specific sign-up selectors
        print("\n--- Sign-up link selectors ---")
        selectors = [
            'a:has-text("Sign up")',
            'a:has-text("Create account")',
            'a:has-text("Register")',
            'button:has-text("Sign up")',
            'button:has-text("Create account")',
            '[href*="sign-up" i]',
            '[href*="signup" i]',
            '[href*="register" i]',
        ]
        for sel in selectors:
            el = page.locator(sel).first
            cnt = await el.count()
            if cnt > 0:
                txt = (await el.text_content() or "").strip()[:40]
                vis = await el.is_visible()
                print(f"  FOUND: {sel!r} visible={vis} text={txt!r}")
            else:
                print(f"  not found: {sel!r}")

        # Now check what happens when we click Sign up / navigate
        print("\n--- Trying navigation to /sign-up ---")
        try:
            await page.goto("https://app.aptlyflow.xyz/sign-up", wait_until="networkidle", timeout=10000)
            print(f"  Navigated to: {page.url}")
            fields = await page.query_selector_all("input")
            print(f"  Input fields ({len(fields)}):")
            for f in fields:
                name = await f.get_attribute("name") or ""
                tp = await f.get_attribute("type") or "text"
                ph = await f.get_attribute("placeholder") or ""
                vis = await f.is_visible()
                print(f"    name={name!r} type={tp!r} placeholder={ph!r} visible={vis}")
        except Exception as e:
            print(f"  Error: {e}")

        await browser.close()


asyncio.run(main())
