"""Probe the create-business page dropdown and submission in detail.

Usage:
    uv run python scripts/probe_create_business.py [BASE_URL]

If no URL is provided, reads WEBQA_TARGET_URL from the environment.
"""
import asyncio, os, random, string, sys
from playwright.async_api import async_playwright

SIGNUP_CTA_SELECTORS = [
    'a:has-text("Sign up")', 'a:has-text("Create account")',
    'a:has-text("Register")', '[href*="sign-up" i]', '[href*="signup" i]',
    'button:has-text("Sign up")', 'button:has-text("Get started")',
    '[role="button"]:has-text("Sign up")',
]


def _get_base_url() -> str:
    base = (
        sys.argv[1].rstrip("/")
        if len(sys.argv) > 1
        else os.environ.get("WEBQA_TARGET_URL", "").rstrip("/")
    )
    if not base:
        print("ERROR: Provide a base URL as the first argument or set WEBQA_TARGET_URL.")
        sys.exit(1)
    return base


async def fill(page, selectors, value):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible() and await loc.is_enabled():
                await loc.fill(value, timeout=4000)
                return sel
        except Exception:
            continue
    return None


async def click_sel(page, selectors):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=5000)
                return sel
        except Exception:
            continue
    return None


async def main():
    base_url = _get_base_url()
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    email = f"webqa.{suffix}@mailinator.com"
    password = f"WebQA!{suffix}A1"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Navigate → click signup CTA
        await page.goto(base_url)
        try: await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception: pass
        cta = await click_sel(page, SIGNUP_CTA_SELECTORS)
        print(f"CTA clicked: {cta}  →  {page.url}")
        try: await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception: pass

        # If we landed on login first, look for a signup link on that page
        if any(k in page.url.lower() for k in ["/login", "/signin", "/sign-in"]):
            switch = await click_sel(page, [
                'a:has-text("Sign up")', 'a:has-text("Create account")',
                '[href*="sign-up" i]', '[href*="signup" i]',
            ])
            print(f"Switched from login to signup: {switch}  →  {page.url}")
            try: await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception: pass

        print(f"\nSignup form at: {page.url}")
        print(f"Using email: {email}")

        # Fill signup form fields
        await fill(page, ['input[name*="email" i]', 'input[placeholder*="email" i]'], email)
        await fill(page, ['input[type="password"]'], password)
        await fill(page, ['input[name*="first" i]', 'input[placeholder*="first" i]'], "WebQA")
        await fill(page, ['input[name*="last" i]', 'input[placeholder*="last" i]'], "Tester")
        await fill(page, [
            'input[type="number"][name*="phone" i]',
            'input[type="number"][placeholder*="phone" i]',
            'input[name*="phone" i]',
        ], "3478901234")

        await click_sel(page, [
            'button[type="submit"]', 'button:has-text("Sign Up")',
            'button:has-text("Sign up")', 'button:has-text("Create account")',
        ])
        await page.wait_for_timeout(5000)
        try: await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception: pass
        print(f"\nURL after signup: {page.url}")

        # ── CREATE-BUSINESS PAGE ──────────────────────────────────────────
        print("\n=== CREATE-BUSINESS PAGE ===")
        print(f"URL: {page.url}")

        # Dump every interactive element
        for el in await page.locator(
            "input, textarea, select, button, [role='combobox'], [role='listbox'],"
            " [role='option'], [role='button']"
        ).all():
            try:
                tag = await el.evaluate("e => e.tagName.toLowerCase()")
                role = await el.get_attribute("role") or ""
                name = await el.get_attribute("name") or ""
                itype = await el.get_attribute("type") or ""
                txt = (await el.text_content() or "").strip()[:60]
                placeholder = await el.get_attribute("placeholder") or ""
                visible = await el.is_visible()
                print(f"  <{tag}> role={role!r} type={itype!r} name={name!r} "
                      f"placeholder={placeholder!r} text={txt!r} visible={visible}")
            except Exception:
                continue

        # Fill business name
        biz_sel = await fill(page, [
            'input[name="name"]',
            'input[placeholder*="business" i]',
            'input[placeholder*="company" i]',
            'input[name*="business" i]',
            'input[name*="company" i]',
        ], "WebQA Test Business")
        print(f"\nFilled business name via: {biz_sel}")

        # ── DROPDOWN: click trigger, inspect options, pick one ───────────
        print("\n--- Clicking business type dropdown ---")
        trigger = await click_sel(page, [
            '[role="combobox"]',
            'button:has-text("Select a business type")',
            'button:has-text("business type")',
        ])
        print(f"Trigger clicked: {trigger}")
        await page.wait_for_timeout(800)

        # Collect visible options from the popover
        option_texts = []
        option_values = []
        for el in await page.locator("[role='option'], [role='menuitem'], [role='listitem'], li").all():
            try:
                txt = (await el.text_content() or "").strip()
                visible = await el.is_visible()
                if visible and txt:
                    option_texts.append(txt)
                    print(f"  OPTION: {txt!r}")
            except Exception:
                continue

        if not option_texts:
            # Fall back to native <select> options
            sel_el = page.locator("select").first
            if await sel_el.count() > 0:
                opts = await sel_el.locator("option").all()
                for opt in opts:
                    val = await opt.get_attribute("value") or ""
                    txt = (await opt.text_content() or "").strip()
                    if val:
                        option_values.append(val)
                        print(f"  SELECT OPTION value={val!r}: {txt!r}")

        # Pick first real option
        if option_texts:
            chosen = option_texts[0]
            print(f"\nSelecting option: {chosen!r}")
            picked = await click_sel(page, [
                f'[role="option"]:has-text("{chosen[:30]}")',
                f'li:has-text("{chosen[:30]}")',
                f'[role="menuitem"]:has-text("{chosen[:30]}")',
            ])
            print(f"Picked via: {picked}")
        elif option_values:
            try:
                await page.locator("select").first.select_option(value=option_values[0], timeout=3000)
                print(f"  Selected native option: {option_values[0]!r}")
            except Exception as e:
                print(f"  Native select failed: {e}")
        else:
            print("WARNING: No options found in dropdown!")

        await page.wait_for_timeout(500)

        # State before submit
        print("\n--- Input values before submit ---")
        for inp in await page.locator("input:visible").all():
            try:
                name = await inp.get_attribute("name") or ""
                val = await inp.input_value(timeout=500)
                print(f"  {name!r}: {val!r}")
            except Exception:
                continue

        # Submit
        sub = await click_sel(page, [
            'button:has-text("Create business")',
            'button:has-text("Create Business")',
            'input[type="submit"]',
            'button[type="submit"]',
        ])
        print(f"\nSubmit clicked: {sub}")
        await page.wait_for_timeout(5000)
        try: await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception: pass

        print(f"\nFINAL URL: {page.url}")
        alerts = await page.locator('[role="alert"], [class*="error" i], [class*="toast" i]').all_text_contents()
        if alerts:
            print(f"Alerts: {[a.strip() for a in alerts if a.strip()]}")

        await browser.close()


asyncio.run(main())
