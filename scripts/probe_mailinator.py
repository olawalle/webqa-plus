"""Probe script: verify a signup form works end-to-end with a mailinator.com address.

Navigates to the base URL and clicks the signup CTA — no hardcoded paths.

Usage:
    uv run python scripts/probe_mailinator.py [BASE_URL]

Examples:
    uv run python scripts/probe_mailinator.py https://app.aptlyflow.xyz
    uv run python scripts/probe_mailinator.py https://staging.myapp.com

If no URL is provided, reads WEBQA_TARGET_URL from the environment.
"""
import asyncio
import os
import random
import string
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
        print("  Example: uv run python scripts/probe_mailinator.py https://app.example.com")
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
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        await page.wait_for_timeout(1000)

        found_cta = await _navigate_to_signup(page)
        if not found_cta:
            print("WARNING: No signup CTA found on landing page — already on signup form or CTA is hidden.")
        print(f"Current URL after CTA click: {page.url}")

        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        email = f"webqa.{suffix}@mailinator.com"
        print(f"Testing with email: {email}")

        async def fill_first_visible(selectors, value):
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible() and await loc.is_enabled():
                        cur = ""
                        try:
                            cur = await loc.input_value(timeout=1000)
                        except Exception:
                            pass
                        if cur != value:
                            await loc.fill(value, timeout=5000)
                        return True, sel
                except Exception:
                    continue
            return False, None

        ok, sel = await fill_first_visible(
            ['input[type="email"]', 'input[name*="email" i]', 'input[placeholder*="email" i]'], email
        )
        print(f"email: {ok} via {sel}")

        ok, sel = await fill_first_visible(['input[type="password"]'], "WebQA!testA1")
        print(f"password: {ok} via {sel}")

        ok, sel = await fill_first_visible(
            ['input[name*="first" i]', 'input[placeholder*="first" i]'], "WebQA"
        )
        print(f"first_name: {ok} via {sel}")

        ok, sel = await fill_first_visible(
            ['input[name*="last" i]', 'input[placeholder*="last" i]'], "Tester"
        )
        print(f"last_name: {ok} via {sel}")

        ok, sel = await fill_first_visible(
            ['input[type="tel"]', 'input[type="number"][name*="phone" i]', 'input[name*="phone" i]'],
            "3478901234",
        )
        print(f"phone: {ok} via {sel}")

        sub = page.locator('button[type="submit"]').first
        if await sub.count() > 0:
            print(f"Submit button enabled: {await sub.is_enabled()}")
            await sub.click(timeout=5000)
            await page.wait_for_timeout(4000)
            print(f"URL after submit: {page.url}")
            errors = await page.locator('[role="alert"], [class*="error" i]').all_text_contents()
            if errors:
                print(f"Errors/alerts: {[e for e in errors if e.strip()]}")
        else:
            print("Submit button NOT FOUND!")

        await browser.close()


asyncio.run(main())
