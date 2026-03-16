"""Probe signup with detailed logging of form state."""
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

        # Use type() which simulates keyboard input - more reliable for React
        first = page.locator('input[name="first_name"]')
        await first.click()
        await first.type("Test", delay=50)

        last = page.locator('input[name="last_name"]')
        await last.click()
        await last.type("User", delay=50)

        phone = page.locator('input[name="phone"]')
        await phone.click()
        await phone.type("3478901234", delay=50)

        eml = page.locator('input[name="email"]')
        await eml.click()
        await eml.type(email, delay=50)

        pwd = page.locator('input[name="password"]')
        await pwd.click()
        await pwd.type(pw, delay=50)

        # Check values before submit
        print("Values before submit:")
        for name in ["first_name", "last_name", "phone", "email", "password"]:
            val = await page.locator(f'input[name="{name}"]').input_value()
            print(f"  {name}: {val!r}")

        print(f"Submitting with: {email}")
        await page.locator('button[type="submit"]').click()
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        print(f"After signup: {page.url}")

        if "sign-up" in page.url:
            # Check for error messages
            body = (await page.inner_text("body") or "")[:600]
            print(f"Still on sign-up. Body:\n{body}")

        await browser.close()


asyncio.run(main())
