"""Direct probe for /create-business page after signup."""
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
        print(f"On: {page.url}")

        await page.fill('input[name="first_name"]', "Test")
        await page.fill('input[name="last_name"]', "User")
        await page.fill('input[name="phone"]', "3478901234")
        await page.fill('input[name="email"]', email)
        await page.fill('input[name="password"]', pw)

        print(f"Submitting with: {email}")
        await page.click('button[type="submit"]')
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        print(f"After signup: {page.url}")

        if "create-business" in page.url:
            print("\n=== /create-business page ===")
            for el in await page.locator("input, textarea, select, button, [role='combobox']").all():
                try:
                    tag = await el.evaluate("e => e.tagName.toLowerCase()")
                    itype = await el.get_attribute("type") or ""
                    name2 = await el.get_attribute("name") or ""
                    ph = await el.get_attribute("placeholder") or ""
                    role = await el.get_attribute("role") or ""
                    txt = (await el.text_content() or "").strip()[:60]
                    vis = await el.is_visible()
                    print(f"  <{tag}> type={itype!r} name={name2!r} ph={ph!r} role={role!r} text={txt!r} vis={vis}")
                except Exception:
                    pass

            body_text = (await page.inner_text("body") or "")[:600]
            print(f"\nPage body text:\n{body_text}")
        else:
            body = (await page.inner_text("body") or "")[:400]
            print(f"Not on create-business. URL={page.url}\nContent:\n{body}")

        await browser.close()


asyncio.run(main())
