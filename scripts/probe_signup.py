"""Quick probe to test the signup form with the agent's exact selectors.

Navigates to the base URL and clicks the signup CTA — no hardcoded paths.

Usage:
    uv run python scripts/probe_signup.py [BASE_URL]

Examples:
    uv run python scripts/probe_signup.py https://app.aptlyflow.xyz
    uv run python scripts/probe_signup.py https://staging.myapp.com

If no URL is provided, reads WEBQA_TARGET_URL from the environment.
"""
import asyncio
import os
import sys
from playwright.async_api import async_playwright

SIGNUP_CTA_SELECTORS = [
    'a:has-text("Sign up")',
    'a:has-text("Create account")',
    'a:has-text("Register")',
    'button:has-text("Sign up")',
    'button:has-text("Create account")',
    'button:has-text("Get started")',
    '[role="button"]:has-text("Sign up")',
    '[href*="sign-up" i]',
    '[href*="signup" i]',
    '[href*="register" i]',
]


def _get_base_url() -> str:
    base = (
        sys.argv[1].rstrip("/")
        if len(sys.argv) > 1
        else os.environ.get("WEBQA_TARGET_URL", "").rstrip("/")
    )
    if not base:
        print("ERROR: Provide a base URL as the first argument or set WEBQA_TARGET_URL.")
        print("  Example: uv run python scripts/probe_signup.py https://app.example.com")
        sys.exit(1)
    return base


async def _navigate_to_signup(page) -> bool:
    """Click the signup CTA from the landing page. Returns True if a CTA was found."""
    for sel in SIGNUP_CTA_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                print(f"Clicking signup CTA: {sel}")
                await loc.click(timeout=5000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                await page.wait_for_timeout(500)
                return True
        except Exception:
            continue
    return False


async def main():
    base_url = _get_base_url()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"Navigating to: {base_url}")
        await page.goto(base_url)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(1000)

        found_cta = await _navigate_to_signup(page)
        if not found_cta:
            print("WARNING: No signup CTA found on landing page — already on signup form or CTA is hidden.")
        print("Signup URL:", page.url)

        # Agent's exact fill sequence
        async def fill_first_visible(selectors, value):
            for selector in selectors:
                try:
                    loc = page.locator(selector).first
                    if await loc.count() > 0 and await loc.is_visible() and await loc.is_enabled():
                        cur = ""
                        try:
                            cur = await loc.input_value(timeout=1000)
                        except Exception:
                            pass
                        if cur != value:
                            await loc.fill(value, timeout=5000)
                        return True, selector
                except Exception:
                    continue
            return False, None

        # Fill email (type="text" name="email")
        ok, sel = await fill_first_visible([
            'input[type="email"]', 'input[name*="email" i]',
            'input[id*="email" i]', 'input[placeholder*="email" i]',
        ], "webqa.probe123@mailinator.com")
        print(f"Email fill: {ok} via {sel}")

        # Fill password
        ok, sel = await fill_first_visible(['input[type="password"]'], "WebQA!probe123A1")
        print(f"Password fill: {ok} via {sel}")

        # Fill first name
        ok, sel = await fill_first_visible([
            'input[name*="first" i]', 'input[id*="first" i]', 'input[placeholder*="first" i]'
        ], "WebQA")
        print(f"First name fill: {ok} via {sel}")

        # Fill last name
        ok, sel = await fill_first_visible([
            'input[name*="last" i]', 'input[id*="last" i]', 'input[placeholder*="last" i]'
        ], "Tester")
        print(f"Last name fill: {ok} via {sel}")

        # Fill phone (type="number" name="phone") — numeric only!
        ok, sel = await fill_first_visible([
            'input[type="tel"]',
            'input[type="number"][name*="phone" i]',
            'input[type="number"][placeholder*="phone" i]',
            'input[name*="phone" i]',
            'input[placeholder*="phone" i]',
        ], "3478901234")
        print(f"Phone fill: {ok} via {sel}")

        # Show all values after filling
        print("\n--- Input values after fill ---")
        for inp in await page.locator("input").all():
            nm = await inp.get_attribute("name")
            t = await inp.get_attribute("type")
            val = ""
            try:
                val = await inp.input_value(timeout=500)
            except Exception:
                pass
            print(f"  name={nm!r} type={t!r} value={val!r}")

        # Click submit
        print("\n--- Clicking Sign Up ---")
        submit = page.locator('button[type="submit"], button:has-text("Sign Up")').first
        if await submit.count() > 0:
            enabled = await submit.is_enabled()
            print(f"Submit enabled: {enabled}")
            await submit.click(timeout=5000)
            await page.wait_for_timeout(3000)
            print(f"After submit URL: {page.url}")
            # Check for error messages
            errors = await page.locator('[class*="error" i], [role="alert"], [class*="toast" i]').all_text_contents()
            print(f"Errors/alerts: {errors}")
        else:
            print("No submit button found!")

        await browser.close()


asyncio.run(main())
