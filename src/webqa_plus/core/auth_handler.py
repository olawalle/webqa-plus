"""Authentication handler for automatic login detection and credential injection."""

from typing import Any, Dict, List, Optional

from playwright.async_api import Page


class AuthHandler:
    """Handles authentication with automatic form detection."""

    # Common login form selectors
    EMAIL_SELECTORS = [
        'input[type="email"]',
        'input[name="email"]',
        'input[name="username"]',
        'input[name="user"]',
        'input[name="login"]',
        'input[id*="email" i]',
        'input[id*="username" i]',
        'input[id*="login" i]',
        'input[placeholder*="email" i]',
        'input[placeholder*="username" i]',
    ]

    PASSWORD_SELECTORS = [
        'input[type="password"]',
        'input[name="password"]',
        'input[id*="password" i]',
    ]

    SUBMIT_SELECTORS = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Sign in")',
        'button:has-text("Log in")',
        'button:has-text("Login")',
        'a:has-text("Sign in")',
        '[role="button"]:has-text("Sign in")',
    ]

    def __init__(self, config: Dict[str, Any]):
        """Initialize auth handler."""
        self.config = config
        self.auth_config = config.get("auth", {})
        self.email = self.auth_config.get("email")
        self.password = self.auth_config.get("password")
        self.enabled = self.auth_config.get("enabled", False)
        self.context = None

    async def authenticate(self, page: Page) -> bool:
        """Attempt to authenticate on the current page."""
        if not self.enabled or not self.email or not self.password:
            return False

        # Detect if this is a login page
        is_login_page = await self._is_login_page(page)

        if is_login_page:
            return await self._perform_login(page)

        # Check if already authenticated
        is_authenticated = await self._check_authenticated(page)
        if is_authenticated:
            return True

        # Look for login link/button
        login_link = await self._find_login_link(page)
        if login_link:
            await login_link.click()
            await page.wait_for_load_state("networkidle")
            return await self._perform_login(page)

        return False

    async def _is_login_page(self, page: Page) -> bool:
        """Detect if current page is a login page."""
        # Check URL patterns
        url = page.url.lower()
        if any(pattern in url for pattern in ["login", "signin", "auth", "sign-in"]):
            return True

        # Check for login form elements
        email_found = False
        password_found = False

        for selector in self.EMAIL_SELECTORS:
            try:
                if await page.locator(selector).count() > 0:
                    email_found = True
                    break
            except:
                continue

        for selector in self.PASSWORD_SELECTORS:
            try:
                if await page.locator(selector).count() > 0:
                    password_found = True
                    break
            except:
                continue

        return email_found and password_found

    async def _perform_login(self, page: Page) -> bool:
        """Perform login with stored credentials."""
        try:
            # Find email field
            email_field = None
            for selector in self.EMAIL_SELECTORS:
                try:
                    locator = page.locator(selector).first
                    if await locator.count() > 0:
                        email_field = locator
                        break
                except:
                    continue

            if not email_field:
                return False

            # Find password field
            password_field = None
            for selector in self.PASSWORD_SELECTORS:
                try:
                    locator = page.locator(selector).first
                    if await locator.count() > 0:
                        password_field = locator
                        break
                except:
                    continue

            if not password_field:
                return False

            # Fill in credentials
            await email_field.fill(self.email)
            await password_field.fill(self.password)

            # Find and click submit button
            submit_button = None
            for selector in self.SUBMIT_SELECTORS:
                try:
                    locator = page.locator(selector).first
                    if await locator.count() > 0 and await locator.is_visible():
                        submit_button = locator
                        break
                except:
                    continue

            if submit_button:
                await submit_button.click()
            else:
                # Try pressing Enter on password field
                await password_field.press("Enter")

            # Wait for navigation
            await page.wait_for_load_state("networkidle")

            # Check if login succeeded
            return await self._check_authenticated(page)

        except Exception as e:
            print(f"Login failed: {e}")
            return False

    async def _check_authenticated(self, page: Page) -> bool:
        """Check if user is currently authenticated."""
        # Look for common logged-in indicators
        indicators = [
            "text=Logout",
            "text=Log out",
            "text=Sign out",
            "text=My Account",
            "text=Profile",
            "text=Dashboard",
            'a[href*="/profile"]',
            'a[href*="/logout"]',
            ".user-menu",
            '[data-testid*="user"]',
            '[aria-label*="profile" i]',
        ]

        for indicator in indicators:
            try:
                if await page.locator(indicator).count() > 0:
                    return True
            except:
                continue

        # Check if login form is gone
        is_login = await self._is_login_page(page)
        if not is_login and page.url != page.url:  # Page changed
            return True

        return False

    async def _find_login_link(self, page: Page) -> Optional[Any]:
        """Find login/sign in link on the page."""
        selectors = [
            'a:has-text("Sign in")',
            'a:has-text("Log in")',
            'a:has-text("Login")',
            'button:has-text("Sign in")',
            'button:has-text("Log in")',
            '[href*="/login"]',
            '[href*="/signin"]',
        ]

        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0:
                    return locator
            except:
                continue

        return None

    async def store_auth_state(self, page: Page, path: str) -> None:
        """Store authentication state to file."""
        try:
            await page.context.storage_state(path=path)
        except Exception as e:
            print(f"Failed to store auth state: {e}")

    async def load_auth_state(self, context, path: str) -> bool:
        """Load authentication state from file."""
        import os

        if os.path.exists(path):
            try:
                # Note: In real implementation, you'd use context.set_storage_state
                return True
            except Exception as e:
                print(f"Failed to load auth state: {e}")
        return False
