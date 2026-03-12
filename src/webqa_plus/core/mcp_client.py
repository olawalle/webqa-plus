"""Playwright MCP client wrapper for structured accessibility and actions."""

import asyncio
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from playwright.async_api import Page


class MCPClient:
    """MCP (Model Context Protocol) client wrapper for Playwright."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize MCP client."""
        self.config = config
        self.server_url = config.get("server_url", "http://localhost:3000")
        self.timeout = config.get("timeout", 10000)
        self._last_tree = None
        self._selector_counter = 0
        self._selector_fallbacks: Dict[str, str] = {}
        self._console_events: List[Dict[str, Any]] = []
        self._network_events: List[Dict[str, Any]] = []
        self._bound_page_ids: set[int] = set()
        self._bound_context_ids: set[int] = set()

    async def get_accessibility_tree(self, page: Page) -> Dict[str, Any]:
        """Get structured accessibility tree from the page."""
        try:
            # Get the full accessibility tree using Playwright's accessibility API
            snapshot = await page.accessibility.snapshot()

            # Process into structured format
            tree = self._process_accessibility_node(snapshot)

            # Also get interactive elements
            interactive_elements = await self._get_interactive_elements(page)

            return {
                "tree": tree,
                "interactive_elements": interactive_elements,
                "url": page.url,
                "title": await page.title(),
            }
        except Exception as e:
            return {
                "tree": {},
                "interactive_elements": [],
                "error": str(e),
            }

    def _process_accessibility_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """Process an accessibility node into structured format."""
        if not node:
            return {}

        result = {
            "role": node.get("role", ""),
            "name": node.get("name", ""),
            "description": node.get("description", ""),
            "value": node.get("value", ""),
        }

        # Process children
        children = node.get("children", [])
        if children:
            result["children"] = [self._process_accessibility_node(child) for child in children]

        return result

    async def _get_interactive_elements(self, page: Page) -> List[Dict[str, Any]]:
        """Get all interactive elements on the page."""
        selectors = [
            "button",
            "a[href]",
            "input",
            "select",
            "textarea",
            '[role="button"]',
            '[role="link"]',
            '[role="checkbox"]',
            '[role="radio"]',
            '[tabindex]:not([tabindex="-1"])',
        ]

        elements = []
        has_open_modal = await self._has_open_dialog_overlay(page)

        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()

                for i in range(min(count, 50)):  # Limit to 50 per type
                    try:
                        element = locator.nth(i)

                        # Get element properties
                        visible = await element.is_visible()
                        if not visible:
                            continue

                        in_dialog = await self._is_element_within_active_modal(element)

                        if has_open_modal and not in_dialog:
                            continue

                        if not await self._is_element_topmost(page, element):
                            continue

                        text = await element.inner_text()
                        if len(text) > 100:  # Truncate long text
                            text = text[:100] + "..."

                        # Get bounding box for visual reference
                        bbox = await element.bounding_box()
                        fallback_selector = f":nth-match({selector}, {i + 1})"
                        stable_selector = await self._stable_selector_for_element(
                            element,
                            fallback_selector,
                        )

                        element_info = {
                            "type": selector.replace("[", "")
                            .replace("]", "")
                            .replace('="', "_")
                            .replace('"', ""),
                            "selector": stable_selector,
                            "fallback_selector": fallback_selector,
                            "text": text.strip() if text else "",
                            "description": await self._get_element_description(element, page),
                            "role": await element.get_attribute("role") or "",
                            "aria_label": await element.get_attribute("aria-label") or "",
                            "title": await element.get_attribute("title") or "",
                            "name": await element.get_attribute("name") or "",
                            "id": await element.get_attribute("id") or "",
                            "href": await element.get_attribute("href") or "",
                            "placeholder": await element.get_attribute("placeholder") or "",
                            "input_type": await element.get_attribute("type") or "",
                            "required": bool(await element.get_attribute("required") is not None),
                            "pattern": await element.get_attribute("pattern") or "",
                            "minlength": await element.get_attribute("minlength") or "",
                            "maxlength": await element.get_attribute("maxlength") or "",
                            "inputmode": await element.get_attribute("inputmode") or "",
                            "aria_invalid": (await element.get_attribute("aria-invalid") or "").lower(),
                            "in_dialog": in_dialog,
                            "bbox": bbox,
                            "enabled": await element.is_enabled(),
                        }

                        elements.append(element_info)
                    except:
                        continue

            except Exception:
                continue

        return elements

    async def _get_element_description(self, element, page: Page) -> str:
        """Generate a human-readable description of an element."""
        try:
            tag = await element.evaluate("el => el.tagName.toLowerCase()")
            text = await element.inner_text()
            aria_label = await element.get_attribute("aria-label")
            title = await element.get_attribute("title")
            placeholder = await element.get_attribute("placeholder")

            description = tag
            if text:
                description += f" - {text.strip()[:50]}"
            elif aria_label:
                description += f" - {aria_label}"
            elif title:
                description += f" - {title}"
            elif placeholder:
                description += f" - placeholder: {placeholder}"

            return description
        except:
            return "element"

    async def get_available_actions(self, page: Page) -> List[Dict[str, Any]]:
        """Get list of available actions on current page."""
        elements = await self._get_interactive_elements(page)

        actions = []
        for elem in elements:
            if not elem.get("enabled", True):
                continue

            action_type = self._infer_action_type(elem["type"])

            action = {
                "type": action_type,
                "selector": elem["selector"],
                "description": elem["description"],
                "text": elem["text"],
                "role": elem.get("role", ""),
                "aria_label": elem.get("aria_label", ""),
                "title": elem.get("title", ""),
                "name": elem.get("name", ""),
                "id": elem.get("id", ""),
                "href": elem.get("href", ""),
                "placeholder": elem.get("placeholder", ""),
                "input_type": elem.get("input_type", ""),
                "required": elem.get("required", False),
                "pattern": elem.get("pattern", ""),
                "minlength": elem.get("minlength", ""),
                "maxlength": elem.get("maxlength", ""),
                "inputmode": elem.get("inputmode", ""),
                "aria_invalid": elem.get("aria_invalid", ""),
                "in_dialog": bool(elem.get("in_dialog", False)),
                "requires_input": action_type == "type",
            }

            actions.append(action)

        return actions

    def _infer_action_type(self, element_type: str) -> str:
        """Infer the action type from element type."""
        if "input" in element_type or "textarea" in element_type:
            return "type"
        elif "select" in element_type:
            return "select"
        elif "checkbox" in element_type:
            return "check"
        else:
            return "click"

    async def execute_action(
        self, page: Page, action_type: str, target: str, value: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute an action on the page."""
        try:
            await self._ensure_listeners(page)
            network_start = len(self._network_events)
            locator = await self._resolve_target_locator(page, target)
            wait_for_network_idle = action_type in {"click", "navigate", "select"}
            active_page = page
            popup_url = ""
            popup_validated = False

            if action_type == "click":
                try:
                    has_open_modal = await self._has_open_dialog_overlay(page)
                    if has_open_modal and not await self._is_locator_within_active_modal(locator):
                        await self._dismiss_blocking_overlays(page)
                        locator = await self._resolve_target_locator(page, target)
                except Exception:
                    pass

            if action_type == "click":
                try:
                    async with page.context.expect_page(timeout=2500) as popup_info:
                        await locator.click(timeout=5000)
                    popup_page = await popup_info.value
                    try:
                        await popup_page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    popup_url = popup_page.url or ""
                    popup_validated = bool(popup_url)
                    await popup_page.close()
                except Exception as click_error:
                    error_text = str(click_error).lower()
                    if "intercepts pointer events" in error_text:
                        await self._dismiss_blocking_overlays(page)
                        locator = await self._resolve_target_locator(page, target)
                        try:
                            async with page.context.expect_page(timeout=2000) as popup_info:
                                await locator.click(timeout=5000)
                            popup_page = await popup_info.value
                            try:
                                await popup_page.wait_for_load_state("domcontentloaded", timeout=5000)
                            except Exception:
                                pass
                            popup_url = popup_page.url or ""
                            popup_validated = bool(popup_url)
                            await popup_page.close()
                        except Exception:
                            if await self._is_locator_within_active_modal(locator):
                                await locator.click(timeout=5000, force=True)
                            else:
                                raise RuntimeError(
                                    "Blocked by active modal overlay; target is outside dialog scope"
                                )
                    else:
                        await locator.click(timeout=5000)
            elif action_type == "type":
                await self._fill_with_fallback(page, locator, target, value or "")
            elif action_type == "clear":
                await locator.clear(timeout=5000)
            elif action_type == "select":
                await self._select_with_fallback(page, locator, target, value)
            elif action_type == "check":
                await locator.check(timeout=5000)
            elif action_type == "uncheck":
                await locator.uncheck(timeout=5000)
            elif action_type == "hover":
                await locator.hover(timeout=5000)
            elif action_type == "navigate":
                await page.goto(value, wait_until="networkidle")
                active_page = page

            # Wait for any navigation or network activity
            if wait_for_network_idle:
                await active_page.wait_for_load_state("networkidle", timeout=5000)

            if action_type == "click":
                await self._attempt_post_click_picker_completion(active_page, target)

            recent_network = self._network_events[network_start:]
            mutation_events = self._extract_mutation_events(recent_network)

            return {
                "success": True,
                "action": action_type,
                "target": target,
                "value": value,
                "new_url": active_page.url,
                "popup_url": popup_url,
                "popup_validated": popup_validated,
                "mutation_events": mutation_events,
            }

        except Exception as e:
            return {
                "success": False,
                "action": action_type,
                "target": target,
                "error": str(e),
                "trace": "\n".join(traceback.format_exception(type(e), e, e.__traceback__)[-6:]),
            }

    async def _fill_with_fallback(self, page: Page, locator: Any, target: str, value: str) -> None:
        """Fill input with fallback strategies for unreliable selectors and auth fields."""
        try:
            try:
                current_value = await locator.input_value(timeout=1500)
                if current_value == value:
                    return
            except Exception:
                pass
            await locator.fill(value, timeout=5000)
            try:
                await locator.press("Tab", timeout=1000)
            except Exception:
                pass
            return
        except Exception:
            pass

        lowered = (target or "").lower()
        fallback_selectors = []
        if any(k in lowered for k in ["email", "username", "login", "user"]):
            fallback_selectors = [
                'input[type="email"]',
                'input[name*="email" i]',
                'input[id*="email" i]',
                'input[name*="user" i]',
                'input[id*="user" i]',
                'input[autocomplete="username"]',
            ]
        elif "password" in lowered:
            fallback_selectors = [
                'input[type="password"]',
                'input[name*="password" i]',
                'input[id*="password" i]',
                'input[autocomplete="current-password"]',
                'input[autocomplete="new-password"]',
            ]
        else:
            fallback_selectors = [
                'input[type="text"]',
                'textarea',
                'input:not([type="hidden"])',
            ]

        last_error: Optional[Exception] = None
        for selector in fallback_selectors:
            try:
                candidate = page.locator(selector).first
                if await candidate.count() > 0 and await candidate.is_visible():
                    try:
                        current_value = await candidate.input_value(timeout=1500)
                        if current_value == value:
                            return
                    except Exception:
                        pass
                    await candidate.fill(value, timeout=5000)
                    try:
                        await candidate.press("Tab", timeout=1000)
                    except Exception:
                        pass
                    return
            except Exception as e:
                last_error = e

        if last_error:
            raise last_error

        raise RuntimeError("No editable input field found for type action")

    async def _ensure_listeners(self, page: Page) -> None:
        """Ensure console and network listeners are attached once per page/context."""
        page_id = id(page)
        if page_id not in self._bound_page_ids:
            page.on("console", self._on_console_message)
            self._bound_page_ids.add(page_id)

        context_id = id(page.context)
        if context_id not in self._bound_context_ids:
            page.context.on("request", self._on_request)
            page.context.on("response", self._on_response)
            self._bound_context_ids.add(context_id)

    def _on_console_message(self, msg: Any) -> None:
        """Capture console messages for per-step validation."""
        try:
            self._console_events.append(
                {
                    "level": str(getattr(msg, "type", "log")),
                    "message": str(getattr(msg, "text", "")),
                    "timestamp": datetime.now().isoformat(),
                }
            )
            if len(self._console_events) > 400:
                self._console_events = self._console_events[-250:]
        except Exception:
            pass

    def _on_request(self, request: Any) -> None:
        """Capture request metadata for mutation detection."""
        try:
            payload = ""
            try:
                payload = request.post_data or ""
            except Exception:
                payload = ""

            self._network_events.append(
                {
                    "event": "request",
                    "method": str(getattr(request, "method", "")),
                    "url": str(getattr(request, "url", "")),
                    "status": 0,
                    "post_data": payload[:4000] if payload else "",
                    "timestamp": datetime.now().isoformat(),
                }
            )
            if len(self._network_events) > 1200:
                self._network_events = self._network_events[-800:]
        except Exception:
            pass

    def _on_response(self, response: Any) -> None:
        """Capture response metadata for network validation."""
        try:
            request = response.request
            self._network_events.append(
                {
                    "event": "response",
                    "method": str(getattr(request, "method", "")),
                    "url": str(getattr(response, "url", "")),
                    "status": int(getattr(response, "status", 0) or 0),
                    "post_data": "",
                    "timestamp": datetime.now().isoformat(),
                }
            )
            if len(self._network_events) > 1200:
                self._network_events = self._network_events[-800:]
        except Exception:
            pass

    async def _select_with_fallback(
        self, page: Page, locator: Any, target: str, value: Optional[str]
    ) -> None:
        """Select option robustly, with auto-pick fallback for unknown values."""
        requested = (value or "").strip()
        if requested and requested != "__webqa_auto__":
            try:
                await locator.select_option(requested, timeout=5000)
                return
            except Exception:
                try:
                    await locator.select_option(label=requested, timeout=5000)
                    return
                except Exception:
                    pass

        try:
            options = await locator.evaluate(
                """
                (el) => {
                    if (!el || el.tagName.toLowerCase() !== 'select') return [];
                    return Array.from(el.options || [])
                        .filter(o => !o.disabled)
                        .map(o => ({ value: (o.value || '').trim(), label: (o.label || o.textContent || '').trim() }));
                }
                """
            )
        except Exception:
            options = []

        for option in options or []:
            candidate_value = str(option.get("value", "")).strip()
            if candidate_value:
                try:
                    await locator.select_option(candidate_value, timeout=5000)
                    return
                except Exception:
                    continue

        lowered_target = (target or "").lower()
        if any(token in lowered_target for token in ["date", "time", "slot", "calendar"]):
            await self._attempt_post_click_picker_completion(page, target)
            return

        raise RuntimeError("Unable to select an option for select input")

    async def _attempt_post_click_picker_completion(self, page: Page, target: str) -> None:
        """Try selecting an item in open dropdown/date pickers after trigger clicks."""
        lowered_target = (target or "").lower()
        if not any(token in lowered_target for token in ["select", "date", "time", "slot", "calendar", "staff", "service", "client"]):
            return

        candidate_selectors = [
            '[role="option"]:visible',
            '[data-radix-collection-item]:visible',
            '[data-slot="select-item"]:visible',
            '[data-state="open"] [role="option"]:visible',
            '[role="gridcell"]:visible',
            '.react-datepicker__day:not(.react-datepicker__day--disabled):visible',
            '[data-slot="calendar"] button:visible',
            '[role="dialog"] button:visible',
        ]

        skip_tokens = {"cancel", "close", "clear", "delete", "remove", "back", "previous"}
        for selector in candidate_selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
            except Exception:
                continue

            for idx in range(min(count, 8)):
                try:
                    option = locator.nth(idx)
                    if not await option.is_visible() or not await option.is_enabled():
                        continue
                    label = (await option.inner_text() or "").strip().lower()
                    if any(token in label for token in skip_tokens):
                        continue
                    await option.click(timeout=2000)
                    await page.wait_for_timeout(120)
                    return
                except Exception:
                    continue

    def _extract_mutation_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract likely API mutations from recent network events."""
        mutations: List[Dict[str, Any]] = []
        for event in events:
            method = str(event.get("method", "")).upper()
            url = str(event.get("url", ""))
            payload = str(event.get("post_data", ""))
            lowered_url = url.lower()
            lowered_payload = payload.lower()

            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                if any(token in lowered_url for token in [".css", ".js", ".png", ".jpg", ".svg", "fonts", "analytics", "sentry", "segment", "mixpanel"]):
                    continue

                is_graphql_mutation = (
                    "graphql" in lowered_url
                    and ("mutation" in lowered_payload or '"operationname"' in lowered_payload)
                )
                is_rest_mutation = any(token in lowered_url for token in ["/api/", "/v1/", "/v2/", "/graphql"]) or bool(
                    payload
                )

                if is_graphql_mutation or is_rest_mutation:
                    mutations.append(
                        {
                            "method": method,
                            "url": url,
                            "status": int(event.get("status", 0) or 0),
                            "post_data": payload[:2000],
                            "timestamp": event.get("timestamp", ""),
                        }
                    )

        return mutations

    async def _stable_selector_for_element(self, element: Any, fallback_selector: str) -> str:
        """Attach stable DOM attribute to element and return selector for it."""
        try:
            existing_id = await element.get_attribute("data-webqa-plus-id")
            if existing_id:
                self._selector_fallbacks[existing_id] = fallback_selector
                return f'[data-webqa-plus-id="{existing_id}"]'

            self._selector_counter += 1
            generated_id = f"wq-{self._selector_counter}"
            assigned_id = await element.evaluate(
                """
                (el, value) => {
                    if (!el.getAttribute('data-webqa-plus-id')) {
                        el.setAttribute('data-webqa-plus-id', value);
                    }
                    return el.getAttribute('data-webqa-plus-id');
                }
                """,
                generated_id,
            )
            if assigned_id:
                self._selector_fallbacks[str(assigned_id)] = fallback_selector
                return f'[data-webqa-plus-id="{assigned_id}"]'
        except Exception:
            pass

        return fallback_selector

    async def _resolve_target_locator(self, page: Page, target: str) -> Any:
        """Resolve action target with stable selector first and known fallback selectors."""
        locator = page.locator(target).first
        try:
            if await locator.count() > 0:
                return locator
        except Exception:
            pass

        if "data-webqa-plus-id" in (target or ""):
            element_id = ""
            try:
                element_id = target.split('data-webqa-plus-id="', 1)[1].split('"', 1)[0]
            except Exception:
                element_id = ""

            if element_id:
                fallback_selector = self._selector_fallbacks.get(element_id)
                if fallback_selector:
                    return page.locator(fallback_selector).first

        return locator

    async def _has_open_dialog_overlay(self, page: Page) -> bool:
        """Check if a modal overlay/dialog is currently open."""
        try:
            return bool(
                await page.evaluate(
                    """
                    () => {
                        const overlaySelectors = [
                            '[data-slot="dialog-overlay"][data-state="open"]',
                            '[data-state="open"][data-slot="dialog-overlay"]',
                            '[role="dialog"][aria-modal="true"]',
                            '[data-slot="dialog-content"][data-state="open"]'
                        ];
                        return overlaySelectors.some((selector) => {
                            const node = document.querySelector(selector);
                            if (!node) return false;
                            const style = window.getComputedStyle(node);
                            return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                        });
                    }
                    """
                )
            )
        except Exception:
            return False

    async def _is_element_within_active_modal(self, element: Any) -> bool:
        """Check if element belongs to active dialog/popover content."""
        try:
            return bool(
                await element.evaluate(
                    """
                    (el) => {
                        return !!el.closest(
                            [
                                '[role="dialog"]',
                                '[aria-modal="true"]',
                                '[data-slot="dialog-content"]',
                                '[data-radix-popper-content-wrapper]',
                                '[data-slot="popover-content"]'
                            ].join(',')
                        );
                    }
                    """
                )
            )
        except Exception:
            return False

    async def _is_locator_within_active_modal(self, locator: Any) -> bool:
        """Check whether a locator target is inside the active modal context."""
        try:
            if await locator.count() == 0:
                return False
            return await self._is_element_within_active_modal(locator.first)
        except Exception:
            return False

    async def _is_element_topmost(self, page: Page, element: Any) -> bool:
        """Check if element is top-most at its center to avoid blocked clicks."""
        try:
            return bool(
                await element.evaluate(
                    """
                    (el) => {
                        const rect = el.getBoundingClientRect();
                        if (!rect || rect.width <= 0 || rect.height <= 0) return false;
                        const cx = Math.min(window.innerWidth - 1, Math.max(0, rect.left + rect.width / 2));
                        const cy = Math.min(window.innerHeight - 1, Math.max(0, rect.top + rect.height / 2));
                        const top = document.elementFromPoint(cx, cy);
                        if (!top) return false;
                        return top === el || el.contains(top) || top.contains(el);
                    }
                    """
                )
            )
        except Exception:
            try:
                box = await element.bounding_box()
                return bool(box)
            except Exception:
                return False

    async def _dismiss_blocking_overlays(self, page: Page) -> None:
        """Attempt to dismiss active modal overlays that block pointer events."""
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.15)
        except Exception:
            pass

        close_selectors = [
            '[data-slot="dialog-close"]',
            'button[aria-label*="close" i]',
            'button:has-text("Close")',
            'button:has-text("Cancel")',
            '[role="button"][aria-label*="close" i]',
        ]
        for selector in close_selectors:
            try:
                candidate = page.locator(selector).first
                if await candidate.count() > 0 and await candidate.is_visible() and await candidate.is_enabled():
                    await candidate.click(timeout=2000)
                    await asyncio.sleep(0.15)
                    return
            except Exception:
                continue

        backdrop_selectors = [
            '[data-slot="dialog-overlay"][data-state="open"]',
            '[data-state="open"][data-slot="dialog-overlay"]',
            '[aria-hidden="true"][data-slot="dialog-overlay"]',
        ]
        for selector in backdrop_selectors:
            try:
                backdrop = page.locator(selector).first
                if await backdrop.count() > 0 and await backdrop.is_visible():
                    await backdrop.click(timeout=2000, force=True)
                    await asyncio.sleep(0.15)
                    return
            except Exception:
                continue

    async def get_console_logs(self, page: Page) -> List[Dict[str, Any]]:
        """Get browser console logs."""
        await self._ensure_listeners(page)
        logs = list(self._console_events)
        self._console_events.clear()
        return logs

    async def get_network_logs(self, page: Page) -> List[Dict[str, Any]]:
        """Get network request logs."""
        await self._ensure_listeners(page)
        logs = list(self._network_events)
        self._network_events.clear()
        return logs

    async def get_element_locator(self, page: Page, description: str) -> Optional[Any]:
        """Find element by natural language description (self-healing)."""
        # Try multiple strategies
        strategies = [
            description,
            f"text={description}",
            f'[aria-label="{description}"]',
            f'[title="{description}"]',
        ]

        for strategy in strategies:
            try:
                locator = page.locator(strategy).first
                if await locator.count() > 0:
                    return locator
            except:
                continue

        return None

    async def wait_for_element(
        self, page: Page, selector: str, timeout: Optional[int] = None
    ) -> bool:
        """Wait for element to appear on page."""
        try:
            await page.wait_for_selector(selector, timeout=timeout or self.timeout)
            return True
        except:
            return False
