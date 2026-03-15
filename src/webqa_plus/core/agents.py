"""Agent implementations for the LangGraph orchestrator."""

import base64
import json
import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from PIL import Image, ImageDraw

from webqa_plus.core.graph import AgentState, GraphState, TestStep, UserFlow
from webqa_plus.utils.email_service import DynamicEmailService, InboxDetails, generate_fallback_identity
from webqa_plus.utils.llm_providers import LLMConfig


class BaseAgent(ABC):
    """Base class for all agents."""

    def __init__(self, config: Dict[str, Any], llm: Optional[BaseChatModel] = None):
        """Initialize the agent."""
        self.config = config
        self.llm_enabled = True
        try:
            self.llm = llm or self._create_llm()
        except Exception:
            self.llm = None
            self.llm_enabled = False
        self.name = self.__class__.__name__.replace("Agent", "").lower()

    def _create_llm(self) -> BaseChatModel:
        """Create LLM instance from config."""
        # Get LLM configuration from config
        llm_config_dict = self.config.get("llm", {})

        # Create LLMConfig and generate LLM instance
        llm_config = LLMConfig(**llm_config_dict)
        return llm_config.create_llm()

    @abstractmethod
    async def run(self, state: GraphState) -> GraphState:
        """Execute the agent's logic."""
        pass

    def _track_llm_usage(self, state: GraphState, tokens: int):
        """Track LLM API usage."""
        state["llm_calls"] += 1
        state["total_tokens"] += tokens
        cost_per_1k = self.config.get("cost", {}).get("estimated_cost_per_1k_tokens", 0.01)
        state["estimated_cost"] = (state["total_tokens"] / 1000) * cost_per_1k

    def _has_llm_configured(self) -> bool:
        """Check if LLM is configured with valid credentials."""
        llm_config = self.config.get("llm", {})
        return bool(llm_config.get("api_key")) and self.llm_enabled and self.llm is not None

    def _is_llm_auth_error(self, error: Exception) -> bool:
        """Check whether an LLM error indicates auth/credential issues."""
        message = str(error).lower()
        return (
            "401" in message
            or "missing authentication" in message
            or "invalid api key" in message
            or "403" in message
            or "404" in message
            or "no endpoints found" in message
            or "model not found" in message
            or "does not exist" in message
        )

    def _disable_llm(self, state: GraphState, reason: str) -> None:
        """Disable LLM usage for current run and surface a single friendly warning."""
        if self.llm_enabled:
            self.llm_enabled = False
            state["errors"].append(reason)

    def _objective_items(self) -> List[Dict[str, Any]]:
        """Return configured objective items in a uniform shape."""
        objective_config = self.config.get("objectives") or {}
        objective_items = objective_config.get("objectives") if isinstance(objective_config, dict) else None
        return [item for item in (objective_items or []) if isinstance(item, dict)]

    def _primary_objective(self) -> Optional[Dict[str, Any]]:
        """Return the highest-priority active objective, if any."""
        items = self._objective_items()
        return items[0] if items else None

    def _primary_objective_text(self) -> str:
        """Return the primary objective description for focused runs."""
        item = self._primary_objective()
        if not item:
            return ""
        return str(item.get("description") or item.get("name") or "").strip()

    def _auth_credentials_available(self) -> bool:
        """Return True when explicit auth credentials are configured."""
        auth_cfg = self.config.get("auth", {}) if isinstance(self.config, dict) else {}
        return bool(auth_cfg.get("enabled") and auth_cfg.get("email") and auth_cfg.get("password"))

    def _objective_is_strict(self) -> bool:
        """Treat user-directed objectives as strict focus requests."""
        item = self._primary_objective()
        if not item:
            return False
        if self._auth_credentials_available():
            objective_text = self._primary_objective_text().lower()
            if any(token in objective_text for token in ["sign up", "signup", "register", "create account"]):
                return False
        if "strict" in item:
            return bool(item.get("strict"))
        return str(item.get("name", "")).strip().lower() == "user directed objective"

    def _pick_signup_switch_action(self, actions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Prefer explicit signup CTA clicks when signup is required."""
        signup_tokens = [
            "sign up",
            "signup",
            "register",
            "create account",
            "get started",
            "start free",
            "join",
            "new here",
            "free trial",
        ]

        for action in actions:
            if action.get("type") not in {"click", "select"}:
                continue
            blob = (
                f"{action.get('text', '')} {action.get('description', '')} {action.get('selector', '')} "
                f"{action.get('name', '')} {action.get('id', '')} {action.get('aria_label', '')} "
                f"{action.get('title', '')} {action.get('href', '')}"
            ).lower()
            if any(token in blob for token in signup_tokens):
                return {
                    "action_type": action.get("type", "click"),
                    "target": action.get("selector", action.get("description", "")),
                    "value": self._action_semantic_key(action),
                }

        return None

    def _objective_terms(self) -> set[str]:
        """Extract lightweight keyword hints from configured objectives."""
        keywords: set[str] = set()
        for item in self._objective_items():
            name = str(item.get("name", ""))
            description = str(item.get("description", ""))
            required_elements = item.get("required_elements") or []
            critical_paths = item.get("critical_paths") or []

            corpus_parts = [name, description]
            corpus_parts.extend(str(value) for value in required_elements)
            for path in critical_paths:
                if isinstance(path, list):
                    corpus_parts.extend(str(step) for step in path)

            corpus = " ".join(corpus_parts).lower()
            for token in re.findall(r"[a-z][a-z0-9_-]{2,}", corpus):
                normalized = token.replace("_", "-")
                if normalized in {
                    "flow",
                    "page",
                    "user",
                    "create",
                    "manage",
                    "test",
                    "testing",
                    "verify",
                    "validate",
                    "check",
                    "ensure",
                    "focus",
                    "particular",
                    "only",
                }:
                    continue
                keywords.add(normalized)

        return keywords

    def _objective_matches_text(self, text: str) -> bool:
        """Check whether text aligns with the configured objective."""
        blob = str(text or "").lower()
        keywords = self._objective_terms()
        if not blob or not keywords:
            return False
        return any(keyword in blob for keyword in keywords)

    def _objective_flow_name(self) -> Optional[str]:
        """Build a concise flow name from the current objective."""
        text = self._primary_objective_text()
        if not text:
            return None

        normalized = re.sub(r"\s+", " ", text).strip()
        normalized = re.sub(
            r"^(please\s+)?(test|verify|validate|check|ensure|focus on|only|just)\s+",
            "",
            normalized,
            flags=re.IGNORECASE,
        ).strip(" .,:;-")
        if not normalized:
            return None

        words = normalized.split()
        short_name = " ".join(words[:5])
        if "flow" not in short_name.lower():
            short_name = f"{short_name.title()} Flow"
        return short_name


class ExplorerAgent(BaseAgent):
    """Explorer agent - discovers flows using WebQA + MCP."""

    SYSTEM_PROMPT = """You are an expert web QA explorer and visual analyst powered by Gemini. Your job is to discover user flows and interactive elements on a web page.

You will receive both the accessibility tree (structured data) AND a screenshot of the current page. Use both sources:
- The screenshot gives you the visual layout, colours, and any content not captured in the accessibility tree
- The accessibility tree gives you precise element roles, labels, and hierarchy

Using both inputs, identify:
1. Interactive elements (buttons, links, forms, inputs)
2. Navigation paths and user flows
3. Critical user journeys to test
4. Dead ends and error states
5. Any visual anomalies (broken images, overlapping elements, layout issues)

For each element, provide:
- element_type: button, link, input, etc.
- description: what the element does
- suggested_action: click, type, select
- priority: 1-5 (5 being most important)

Respond in JSON format with a list of discoverable actions."""

    async def run(self, state: GraphState) -> GraphState:
        """Explore the current page and discover actions."""
        page = state["browser"]
        mcp_client = state["mcp_client"]
        testing_cfg = self.config.get("testing", {})
        dom_exploration_enabled = bool(testing_cfg.get("dom_exploration_enabled", True))

        # Get accessibility tree from MCP
        if dom_exploration_enabled:
            try:
                accessibility_tree = await mcp_client.get_accessibility_tree(page)
            except Exception as e:
                state["errors"].append(f"MCP accessibility tree failed: {e}")
                accessibility_tree = {"elements": []}
        else:
            accessibility_tree = {
                "elements": [],
                "dom_exploration_enabled": False,
                "note": "DOM exploration disabled; use visual inference from screenshots.",
            }

        # Get page info
        current_url = page.url
        page_title = await page.title()
        objective_text = self._primary_objective_text()

        # Update state
        state["current_url"] = current_url
        state["page_title"] = page_title

        artifacts = state.setdefault("artifacts", {})
        known_flows = artifacts.setdefault("known_flow_names", set())
        try:
            available_actions = await mcp_client.get_available_actions(page)
        except Exception:
            available_actions = []

        if objective_text:
            objective_flow_name = self._objective_flow_name() or "Focused Objective Flow"
            objective_flow = None
            for flow in state["discovered_flows"]:
                flow_blob = f"{getattr(flow, 'name', '')} {getattr(flow, 'description', '')}"
                if self._objective_matches_text(flow_blob) or getattr(flow, "name", "") == objective_flow_name:
                    objective_flow = flow
                    break

            if objective_flow is None:
                objective_flow = UserFlow(
                    flow_id=f"objective_{state['current_step']}",
                    name=objective_flow_name,
                    description=objective_text,
                    start_url=current_url,
                    status="testing",
                )
                state["discovered_flows"].insert(0, objective_flow)
                known_flows.add(objective_flow.name.lower())

            state["current_flow"] = objective_flow

        # Use LLM to plan exploration (multimodal: accessibility tree + screenshot)
        if self._has_llm_configured():
            # Capture screenshot for multimodal vision input
            screenshot_b64: Optional[str] = None
            try:
                screenshot_bytes = await page.screenshot(type="png", full_page=False)
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            except Exception:
                pass  # Vision is additive; continue without it if screenshot fails

            # Build multimodal human message content
            text_content = (
                f"Page: {page_title}\n"
                f"URL: {current_url}\n\n"
                + (
                    f"Primary objective: {objective_text}\n"
                    "Prioritize actions and flows that directly support this objective. "
                    "If unrelated dialogs or share modals block the target flow, identify dismiss/close actions first.\n\n"
                    if objective_text
                    else ""
                )
                + (
                    "DOM exploration is disabled for this run. "
                    "Infer navigation and functionality primarily from the screenshot and visible UI cues.\n\n"
                    if not dom_exploration_enabled
                    else ""
                )
                +
                f"Accessibility Tree:\n{json.dumps(accessibility_tree, indent=2)}\n\n"
                f"Previous flows discovered: {len(state['discovered_flows'])}\n"
                f"Visited URLs: {len(state['visited_urls'])}\n\n"
                "What user flows and interactive elements should be tested next? "
                "Analyse both the accessibility tree and the screenshot carefully."
            )

            if screenshot_b64:
                human_message = HumanMessage(
                    content=[
                        {"type": "text", "text": text_content},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{screenshot_b64}"
                            },
                        },
                    ]
                )
            else:
                human_message = HumanMessage(content=text_content)

            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                human_message,
            ]

            try:
                response = await self.llm.ainvoke(messages)
                self._track_llm_usage(state, 1000)  # Approximate

                # Parse LLM response
                try:
                    actions = json.loads(response.content)
                except:
                    actions = {"discoveries": []}

                # Create a new flow if needed
                if actions.get("discoveries") and not state["current_flow"]:
                    flow = UserFlow(
                        flow_id=f"flow_{state['current_step']}",
                        name=actions["discoveries"][0].get("description", "Unknown flow"),
                        description="Auto-discovered flow",
                        start_url=current_url,
                    )
                    state["current_flow"] = flow
                    state["discovered_flows"].append(flow)
                    known_flows.add(flow.name.lower())

            except Exception as e:
                if self._is_llm_auth_error(e):
                    self._disable_llm(
                        state,
                        "LLM provider authentication failed. Continuing in adaptive heuristic mode.",
                    )
                else:
                    state["errors"].append(f"Explorer LLM error: {e}")

        # Heuristic flow discovery (works even without LLM)
        page_hint = f"{page_title} {current_url}".lower()
        heuristic_flows = []
        if any(k in page_hint for k in ["signup", "register", "create account", "sign up"]):
            heuristic_flows.append(("Signup flow", "Register a new account"))
        if any(k in page_hint for k in ["signin", "login", "log in", "sign in"]):
            heuristic_flows.append(("Signin flow", "Authenticate with existing account"))
        if any(k in page_hint for k in ["forgot", "reset password", "recover"]):
            heuristic_flows.append(("Forgot password flow", "Recover account access"))

        for flow_name, flow_desc in heuristic_flows:
            if flow_name.lower() not in known_flows:
                flow = UserFlow(
                    flow_id=f"flow_{state['current_step']}_{len(state['discovered_flows'])}",
                    name=flow_name,
                    description=flow_desc,
                    start_url=current_url,
                )
                state["discovered_flows"].append(flow)
                known_flows.add(flow_name.lower())
                if not state["current_flow"]:
                    state["current_flow"] = flow

        dynamic_flow_name = self._flow_name_from_url(current_url)
        if dynamic_flow_name and dynamic_flow_name.lower() not in known_flows:
            flow = UserFlow(
                flow_id=f"flow_{state['current_step']}_{len(state['discovered_flows'])}",
                name=dynamic_flow_name,
                description=f"Navigate and validate {dynamic_flow_name.lower()}",
                start_url=current_url,
            )
            state["discovered_flows"].append(flow)
            known_flows.add(dynamic_flow_name.lower())
            if not state["current_flow"]:
                state["current_flow"] = flow

        if dom_exploration_enabled:
            for hint in self._flow_hints_from_actions(available_actions):
                if hint.lower() in known_flows:
                    continue
                flow = UserFlow(
                    flow_id=f"flow_{state['current_step']}_{len(state['discovered_flows'])}",
                    name=hint,
                    description=f"Interact with {hint.lower().replace(' flow', '')}",
                    start_url=current_url,
                )
                state["discovered_flows"].append(flow)
                known_flows.add(hint.lower())
                if not state["current_flow"]:
                    state["current_flow"] = flow

        # Track visited URL
        if current_url not in state["visited_urls"]:
            state["visited_urls"].append(current_url)

        state["current_step"] += 1
        return state

    def _flow_name_from_url(self, current_url: str) -> Optional[str]:
        """Build flow name from URL path segments dynamically."""
        try:
            path = urlparse(current_url).path or ""
            segments = [segment for segment in path.split("/") if segment and segment not in {"app", "dashboard"}]
            if not segments:
                return None
            normalized = " ".join(segment.replace("-", " ").replace("_", " ") for segment in segments[:3]).strip()
            if not normalized:
                return None
            return f"{normalized.title()} Flow"
        except Exception:
            return None

    def _flow_hints_from_actions(self, actions: List[Dict[str, Any]]) -> List[str]:
        """Build dynamic flow hints from visible click/navigation labels."""
        hints: List[str] = []
        seen: set[str] = set()
        generic = {
            "menu",
            "close",
            "open",
            "next",
            "back",
            "cancel",
            "submit",
            "button",
            "home",
            "notifications",
            "profile",
        }

        for action in actions:
            if action.get("type") not in {"click", "select"}:
                continue
            raw = str(action.get("text") or action.get("name") or "").strip()
            if not raw:
                continue
            label = " ".join(raw.split())[:32]
            lowered = label.lower()
            if lowered in generic or len(label) < 4:
                continue
            if lowered in seen:
                continue
            seen.add(lowered)
            hints.append(f"{label.title()} Flow")
            if len(hints) >= 6:
                break

        return hints


class TesterAgent(BaseAgent):
    """Tester agent - executes actions and smart input generation."""

    INTENT_KEYWORDS: Dict[str, set[str]] = {
        "auth": {"login", "log in", "sign in", "signin", "signup", "sign up", "register", "password", "forgot"},
        "navigation": {"menu", "dashboard", "home", "page", "section", "tab", "view"},
        "crud": {"create", "new", "add", "edit", "update", "delete", "save", "submit", "confirm"},
        "search": {"search", "filter", "find", "query", "lookup"},
        "forms": {"form", "input", "field", "required", "validation"},
        "settings": {"setting", "settings", "config", "configuration", "preference", "preferences", "integration", "integrations", "payment", "payments", "billing"},
        "content": {"brand", "website", "page", "pages", "forms", "preview"},
    }

    SYSTEM_PROMPT = """You are an expert web QA tester. Execute actions on web pages and generate realistic test data.

When generating inputs:
1. Use realistic data (valid emails, phone numbers, etc.)
2. Test edge cases (empty, too long, special characters)
3. Consider business context for realistic values
4. Track credentials if authentication is involved

For each action, provide:
- action_type: click, type, select, navigate
- target: element selector or description
- value: input value (if applicable)
- expected_result: what should happen
- rationale: why this action tests something important

Respond in JSON format."""

    def __init__(self, config: Dict[str, Any], llm: Optional[BaseChatModel] = None):
        """Initialize tester agent with optional dynamic email service."""
        super().__init__(config, llm)
        self.email_service: Optional[DynamicEmailService] = None

        testing_cfg = self.config.get("testing", {})
        if bool(testing_cfg.get("email_verification_enabled", False)):
            self.email_service = DynamicEmailService(
                {
                    "provider": testing_cfg.get("email_provider", "1secmail"),
                    "base_url": testing_cfg.get(
                        "email_provider_base_url", "https://www.1secmail.com/api/v1/"
                    ),
                    "request_timeout_seconds": testing_cfg.get("email_request_timeout_seconds", 12.0),
                }
            )

    async def run(self, state: GraphState) -> GraphState:
        """Execute test actions on the current page."""
        page = state["browser"]
        mcp_client = state["mcp_client"]
        testing_cfg = self.config.get("testing", {})
        hidden_menu_expander_enabled = bool(testing_cfg.get("hidden_menu_expander", True))
        dom_exploration_enabled = bool(testing_cfg.get("dom_exploration_enabled", True))
        form_validation_pass_enabled = bool(testing_cfg.get("form_validation_pass", True))
        deep_traversal_enabled = bool(testing_cfg.get("deep_traversal", True))
        email_verification_enabled = bool(testing_cfg.get("email_verification_enabled", False))

        step_num = len(state["test_results"]) + 1
        artifacts = state.setdefault("artifacts", {})
        objective_text = self._primary_objective_text()
        strict_objective = self._objective_is_strict()
        validation_exploration_enabled = self._should_run_validation_exploration(objective_text)
        auth_progress = artifacts.setdefault(
            "auth_progress",
            {
                "signup_attempted": False,
                "signin_attempted": False,
                "forgot_attempted": False,
            },
        )
        auth_form_state = artifacts.setdefault(
            "auth_form_state",
            {
                "email_filled": False,
                "password_filled": False,
                "submitted": False,
                "submit_attempts": 0,
            },
        )
        recent_actions = artifacts.setdefault("recent_actions", [])
        generated_user = artifacts.setdefault("generated_user", self._generate_user_identity())
        await self._ensure_dynamic_email_identity(
            state,
            artifacts,
            generated_user,
            email_verification_enabled,
        )
        action_attempt_counts = artifacts.setdefault("action_attempt_counts", {})
        flow_attempt_counts = artifacts.setdefault("flow_attempt_counts", {})
        nav_labels_clicked = artifacts.setdefault("nav_labels_clicked", set())
        expanded_menu_urls = artifacts.setdefault("expanded_menu_urls", set())
        form_validation_state = artifacts.setdefault("form_validation_state", {})
        mutation_assertions = artifacts.setdefault(
            "mutation_assertions",
            {
                "required_entities": sorted(self._objective_intents_to_entities()),
                "detected_entities": [],
                "checked_submits": 0,
            },
        )
        deep_traversal_state = artifacts.setdefault(
            "deep_traversal_state",
            {
                "enabled": deep_traversal_enabled,
                "covered_intents": set(),
                "section_clicks": {},
            },
        )
        deep_traversal_state["enabled"] = deep_traversal_enabled

        try:
            url_key = self._url_key(str(state.get("current_url", "")))
            if (
                dom_exploration_enabled
                and hidden_menu_expander_enabled
                and url_key
                and url_key not in expanded_menu_urls
            ):
                expanded_count = await self._run_hidden_menu_expander_pass(page)
                if expanded_count > 0:
                    expanded_menu_urls.add(url_key)

            # Get available actions from MCP
            actions = await mcp_client.get_available_actions(page)
            context = self._classify_page_context(state, actions)
            flow_key = self._flow_signature(context, state)

            if context != "general" and int(flow_attempt_counts.get(flow_key, 0)) >= 3:
                if state.get("current_flow"):
                    state["current_flow"].status = "completed"
                    state["current_flow"].end_url = state.get("current_url", "")
                    state["current_flow"] = None
                state["errors"].append(
                    f"Skipping over-tested flow after 3 attempts: {context} @ {state.get('current_url', '')}"
                )
                state["current_step"] += 1
                return state

            # Deterministic auth handling to avoid login field loops.
            auth_step = await self._run_auth_sequence_step(
                page,
                generated_user,
                auth_form_state,
                context,
                action_attempt_counts,
            )

            before_full_path: Optional[str] = None
            before_crop_path: Optional[str] = None
            before_bbox: Optional[Dict[str, float]] = None
            after_full_path: Optional[str] = None
            after_crop_path: Optional[str] = None
            after_bbox: Optional[Dict[str, float]] = None
            duration = 0

            if auth_step is not None:
                action_plan, result = auth_step
                action_signature = self._action_signature(action_plan)
            else:
                if not actions:
                    # No actions available, try navigation
                    state["current_flow"] = None
                    state["current_step"] += 1
                    return state

                objective_text = self._primary_objective_text().lower()
                objective_targets_signup = any(
                    token in objective_text for token in ["sign up", "signup", "register", "create account"]
                )
                auth_credentials = self._auth_credentials_available()
                current_url_lower = str(state.get("current_url", "")).lower()
                login_surface = any(
                    token in current_url_lower for token in ["/login", "/signin", "/sign-in", "/auth"]
                )
                if objective_targets_signup and not auth_credentials and login_surface:
                    signup_switch = self._pick_signup_switch_action(actions)
                    if signup_switch is not None:
                        action_plan = signup_switch
                        action_signature = self._action_signature(action_plan)
                        if int(action_attempt_counts.get(action_signature, 0)) >= 3:
                            state["current_step"] += 1
                            return state

                        before_full_path, before_crop_path, before_bbox = await self._capture_step_visuals(
                            state,
                            page,
                            step_num,
                            action_plan,
                            phase="before",
                        )

                        start_time = datetime.now()
                        result = await mcp_client.execute_action(
                            page,
                            action_plan["action_type"],
                            action_plan["target"],
                            action_plan.get("value"),
                        )
                        duration = int((datetime.now() - start_time).total_seconds() * 1000)

                        after_full_path, after_crop_path, after_bbox = await self._capture_step_visuals(
                            state,
                            page,
                            step_num,
                            action_plan,
                            phase="after",
                        )
                    else:
                        state["current_step"] += 1
                        return state

                forced_focus_action = (
                    self._pick_obstruction_clear_action(actions) if strict_objective else None
                )

                if forced_focus_action is not None:
                    action_plan = forced_focus_action
                    action_signature = self._action_signature(action_plan)
                    if int(action_attempt_counts.get(action_signature, 0)) >= 3:
                        state["current_step"] += 1
                        return state

                    before_full_path, before_crop_path, before_bbox = await self._capture_step_visuals(
                        state,
                        page,
                        step_num,
                        action_plan,
                        phase="before",
                    )

                    start_time = datetime.now()
                    result = await mcp_client.execute_action(
                        page,
                        action_plan["action_type"],
                        action_plan["target"],
                        action_plan.get("value"),
                    )
                    duration = int((datetime.now() - start_time).total_seconds() * 1000)

                    after_full_path, after_crop_path, after_bbox = await self._capture_step_visuals(
                        state,
                        page,
                        step_num,
                        action_plan,
                        phase="after",
                    )
                else:

                    form_action = self._build_form_validation_action(
                        state,
                        actions,
                        generated_user,
                        form_validation_state,
                        action_attempt_counts,
                    )

                    if (
                        context == "general"
                        and form_validation_pass_enabled
                        and validation_exploration_enabled
                        and form_action is not None
                        and (not strict_objective or self._action_plan_matches_objective(form_action))
                    ):
                        action_plan = form_action
                        action_signature = self._action_signature(action_plan)
                        if int(action_attempt_counts.get(action_signature, 0)) >= 3:
                            state["current_step"] += 1
                            return state

                        before_full_path, before_crop_path, before_bbox = await self._capture_step_visuals(
                            state,
                            page,
                            step_num,
                            action_plan,
                            phase="before",
                        )

                        start_time = datetime.now()
                        result = await mcp_client.execute_action(
                            page,
                            action_plan["action_type"],
                            action_plan["target"],
                            action_plan.get("value"),
                        )
                        duration = int((datetime.now() - start_time).total_seconds() * 1000)

                        after_full_path, after_crop_path, after_bbox = await self._capture_step_visuals(
                            state,
                            page,
                            step_num,
                            action_plan,
                            phase="after",
                        )
                    else:
                        nav_action = self._pick_navigation_action(
                            state,
                            actions,
                            action_attempt_counts,
                            nav_labels_clicked,
                            deep_traversal_state,
                        )
                        in_post_auth_surface = "/dashboard" in current_url_lower or "/app" in current_url_lower
                        if context == "general" and in_post_auth_surface and nav_action is not None:
                            action_plan = nav_action
                        elif not dom_exploration_enabled and self._has_llm_configured():
                            action_plan = await self._build_visual_first_action(
                                state,
                                page,
                                actions,
                                generated_user,
                                auth_progress,
                                auth_form_state,
                                recent_actions,
                                action_attempt_counts,
                            )
                        elif self._has_llm_configured():
                            messages = [
                                ("system", self.SYSTEM_PROMPT),
                                (
                                    "human",
                                    f"""Current page: {state["page_title"]}
URL: {state["current_url"]}
Primary objective: {objective_text or 'None'}

Available actions:
{json.dumps(actions[:10], indent=2)}

Test step {step_num} of {state["max_steps"]}

Choose the next action that most directly advances the primary objective. Only choose unrelated actions if they are required prerequisites or if a blocking modal must be dismissed first.""",
                                ),
                            ]

                            try:
                                response = await self.llm.ainvoke(messages)
                                self._track_llm_usage(state, 500)

                                try:
                                    action_plan = json.loads(response.content)
                                except Exception:
                                    action_plan = self._build_heuristic_action(
                                        state,
                                        actions,
                                        generated_user,
                                        auth_progress,
                                        auth_form_state,
                                        recent_actions,
                                        action_attempt_counts,
                                    )
                            except Exception as e:
                                if self._is_llm_auth_error(e):
                                    self._disable_llm(
                                        state,
                                        "LLM provider authentication failed. Continuing in adaptive heuristic mode.",
                                    )
                                else:
                                    state["errors"].append(f"Tester LLM error: {e}")
                                action_plan = self._build_heuristic_action(
                                    state,
                                    actions,
                                    generated_user,
                                    auth_progress,
                                    auth_form_state,
                                    recent_actions,
                                    action_attempt_counts,
                                )
                        else:
                            action_plan = self._build_heuristic_action(
                                state,
                                actions,
                                generated_user,
                                auth_progress,
                                auth_form_state,
                                recent_actions,
                                action_attempt_counts,
                            )

                        if (
                            strict_objective
                            and objective_text
                            and any(self._action_matches_objective(action) for action in actions)
                            and not self._action_plan_matches_objective(action_plan)
                        ):
                            action_plan = self._build_heuristic_action(
                                state,
                                actions,
                                generated_user,
                                auth_progress,
                                auth_form_state,
                                recent_actions,
                                action_attempt_counts,
                            )

                        pre_submit_fill_action = self._build_pre_submit_fill_action(
                            actions,
                            action_plan,
                            generated_user,
                            action_attempt_counts,
                        )
                        if pre_submit_fill_action is not None:
                            action_plan = pre_submit_fill_action

                        action_signature = self._action_signature(action_plan)
                        if int(action_attempt_counts.get(action_signature, 0)) >= 3:
                            state["errors"].append(
                                f"Skipping repeated action after 3 attempts: {action_signature}"
                            )
                            state["current_step"] += 1
                            return state

                        before_full_path, before_crop_path, before_bbox = await self._capture_step_visuals(
                            state,
                            page,
                            step_num,
                            action_plan,
                            phase="before",
                        )

                        # Execute the action via MCP
                        start_time = datetime.now()
                        result = await mcp_client.execute_action(
                            page, action_plan["action_type"], action_plan["target"], action_plan.get("value")
                        )
                        duration = int((datetime.now() - start_time).total_seconds() * 1000)

                        after_full_path, after_crop_path, after_bbox = await self._capture_step_visuals(
                            state,
                            page,
                            step_num,
                            action_plan,
                            phase="after",
                        )

            if auth_step is not None:
                after_full_path, after_crop_path, after_bbox = await self._capture_step_visuals(
                    state,
                    page,
                    step_num,
                    action_plan,
                    phase="after",
                )

            action_attempt_counts[action_signature] = int(action_attempt_counts.get(action_signature, 0)) + 1
            flow_attempt_counts[flow_key] = int(flow_attempt_counts.get(flow_key, 0)) + 1

            self._update_auth_progress(action_plan, auth_progress)
            self._update_auth_form_state(action_plan, auth_form_state, generated_user)
            self._record_recent_action(action_plan, recent_actions)
            if result.get("success") and action_plan.get("nav_label"):
                nav_labels_clicked.add(str(action_plan["nav_label"]))
            if result.get("success") and action_plan.get("nav_intents"):
                covered_intents = deep_traversal_state.setdefault("covered_intents", set())
                for intent in action_plan.get("nav_intents", []):
                    covered_intents.add(str(intent))
            self._update_form_validation_state(
                state,
                action_plan,
                result,
                form_validation_state,
            )

            if auth_step is not None:
                duration = 0

            # Capture console and network logs
            console_logs = await mcp_client.get_console_logs(page)
            network_logs = await mcp_client.get_network_logs(page)
            mutation_logs = list(result.get("mutation_events", []))
            mutation_logs.extend(self._extract_mutation_logs_from_network(network_logs))
            detected_entities = self._detect_mutation_entities(mutation_logs)
            if detected_entities:
                tracked = set(str(value) for value in mutation_assertions.get("detected_entities", []))
                tracked.update(detected_entities)
                mutation_assertions["detected_entities"] = sorted(tracked)

            submit_like = self._is_submit_like_action(action_plan)
            if submit_like:
                mutation_assertions["checked_submits"] = int(mutation_assertions.get("checked_submits", 0)) + 1
                expected_entities = self._expected_entities_for_submit(action_plan, state, mutation_assertions)
            else:
                expected_entities = set()

            missing_entities = expected_entities - detected_entities if submit_like else set()
            mutation_assertion_failed = bool(submit_like and expected_entities and missing_entities)
            verification_note = ""
            if submit_like and self._should_check_email_verification(action_plan, context):
                verification_note = await self._attempt_email_verification_followup(
                    page,
                    state,
                    artifacts,
                    testing_cfg,
                )

            # Create test step
            step = TestStep(
                step_number=step_num,
                agent="tester",
                action=action_plan["action_type"],
                target=action_plan["target"],
                status="success" if result.get("success") else "failed",
                screenshot_path=after_full_path or before_full_path,
                console_logs=console_logs,
                network_logs=network_logs,
                duration_ms=duration,
            )

            step_visuals = artifacts.setdefault("step_visuals", {})
            step_visual_entry: Dict[str, Any] = {
                "before_full": before_full_path,
                "before_crop": before_crop_path,
                "after_full": after_full_path,
                "after_crop": after_crop_path,
            }
            if before_bbox:
                step_visual_entry["before_bbox"] = before_bbox
            if after_bbox:
                step_visual_entry["after_bbox"] = after_bbox
            step_visuals[str(step_num)] = step_visual_entry

            if not result.get("success"):
                step.error_message = result.get("error", "Action failed")
                error_detail = (
                    f"Tester action failed at step {step_num}: "
                    f"{action_plan['action_type']} on {action_plan['target']} - {result.get('error', 'Action failed')}"
                )
                state["errors"].append(error_detail)
                if result.get("trace"):
                    state["errors"].append(f"Trace: {result['trace']}")

            if mutation_assertion_failed:
                step.status = "failed"
                step.error_message = (
                    "Missing expected API mutation(s) after submit: "
                    + ", ".join(sorted(missing_entities))
                )
                state["errors"].append(
                    "Mutation assertion failed: expected "
                    + ", ".join(sorted(expected_entities))
                    + " from submit action but detected "
                    + (", ".join(sorted(detected_entities)) if detected_entities else "none")
                )

            if mutation_assertion_failed:
                ocr_fallback = await self._run_ocr_assertion_fallback(
                    state,
                    page,
                    action_plan,
                    expected_entities,
                    missing_entities,
                )
                if ocr_fallback:
                    step_visual_entry["ocr"] = ocr_fallback
                    if ocr_fallback.get("matched_expected"):
                        step.status = "success"
                        step.error_message = None
                        mutation_assertion_failed = False

            if step.status == "failed":
                annotation_bbox = after_bbox or before_bbox
                source_path = after_full_path or before_full_path
                annotated_path = self._create_annotated_failure_image(
                    source_path,
                    annotation_bbox,
                    step.error_message,
                    step_num,
                )
                if annotated_path:
                    step_visual_entry["annotated_failure"] = annotated_path

            if verification_note:
                state["errors"].append(verification_note)

            state["test_results"].append(step)

            if (
                strict_objective
                and step.status == "success"
                and self._is_submit_like_action(action_plan)
                and self._action_plan_matches_objective(action_plan)
                and (
                    not objective_text
                    or not self._objective_intents()
                    or self._objective_completion_reached(mutation_assertions)
                )
            ):
                state["should_stop"] = True

            # Update current flow
            if state["current_flow"]:
                state["current_flow"].steps.append(step)

            state["current_step"] += 1

        except Exception as e:
            state["errors"].append(f"Tester error: {e}")

            # Add failed step
            step = TestStep(
                step_number=step_num,
                agent="tester",
                action="error",
                status="failed",
                error_message=str(e),
            )
            state["test_results"].append(step)
            state["current_step"] += 1

        return state

    async def _capture_step_visuals(
        self,
        state: GraphState,
        page: Any,
        step_num: int,
        action_plan: Dict[str, Any],
        phase: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, float]]]:
        """Capture full-page and target crop screenshots for one step phase."""
        artifacts_dir = self._ensure_visual_artifacts_dir(state)
        if artifacts_dir is None:
            return None, None, None

        full_path = artifacts_dir / f"step_{step_num:04d}_{phase}_full.png"
        crop_path = artifacts_dir / f"step_{step_num:04d}_{phase}_crop.png"

        full_result: Optional[str] = None
        crop_result: Optional[str] = None
        bbox: Optional[Dict[str, float]] = None

        try:
            await page.screenshot(path=str(full_path), type="png", full_page=True)
            full_result = str(full_path)
        except Exception:
            full_result = None

        try:
            bbox = await self._find_target_bbox(page, str(action_plan.get("target", "")))
            if bbox:
                clip = {
                    "x": max(0.0, float(bbox.get("x", 0.0))),
                    "y": max(0.0, float(bbox.get("y", 0.0))),
                    "width": max(4.0, float(bbox.get("width", 4.0))),
                    "height": max(4.0, float(bbox.get("height", 4.0))),
                }
                await page.screenshot(path=str(crop_path), type="png", clip=clip)
                crop_result = str(crop_path)
        except Exception:
            crop_result = None

        return full_result, crop_result, bbox

    def _ensure_visual_artifacts_dir(self, state: GraphState) -> Optional[Path]:
        """Ensure visual artifacts output directory exists."""
        output_dir = (
            self.config.get("testing", {}).get("output_dir")
            or state.get("config", {}).get("testing", {}).get("output_dir")
            or "./reports"
        )
        try:
            artifacts_dir = Path(str(output_dir)) / "visual_artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            return artifacts_dir
        except Exception:
            return None

    async def _find_target_bbox(self, page: Any, target: str) -> Optional[Dict[str, float]]:
        """Best-effort attempt to resolve target element bbox for crop capture."""
        if not target:
            return None

        candidates = [target.strip()]
        seen = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)

            try:
                locator = page.locator(candidate).first
                count = await locator.count()
                if count > 0:
                    bbox = await locator.bounding_box()
                    if bbox and bbox.get("width", 0) > 0 and bbox.get("height", 0) > 0:
                        return {
                            "x": float(bbox["x"]),
                            "y": float(bbox["y"]),
                            "width": float(bbox["width"]),
                            "height": float(bbox["height"]),
                        }
            except Exception:
                pass

            try:
                text_locator = page.get_by_text(candidate, exact=False).first
                text_count = await text_locator.count()
                if text_count > 0:
                    bbox = await text_locator.bounding_box()
                    if bbox and bbox.get("width", 0) > 0 and bbox.get("height", 0) > 0:
                        return {
                            "x": float(bbox["x"]),
                            "y": float(bbox["y"]),
                            "width": float(bbox["width"]),
                            "height": float(bbox["height"]),
                        }
            except Exception:
                pass

        return None

    async def _run_ocr_assertion_fallback(
        self,
        state: GraphState,
        page: Any,
        action_plan: Dict[str, Any],
        expected_entities: set[str],
        missing_entities: set[str],
    ) -> Optional[Dict[str, Any]]:
        """Use Gemini vision as OCR fallback when DOM/mutation evidence is inconclusive."""
        if not self._has_llm_configured():
            return None

        try:
            screenshot_bytes = await page.screenshot(type="png", full_page=False)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        except Exception:
            return None

        expected_list = sorted(str(value) for value in expected_entities)
        missing_list = sorted(str(value) for value in missing_entities)
        prompt = (
            "Perform OCR and UI-state verification for this web QA step. "
            "Return strict JSON with keys: matched_expected (bool), confidence (low|medium|high), "
            "summary (string), evidence_keywords (array of strings).\n"
            f"Action type: {action_plan.get('action_type')}\n"
            f"Action target: {action_plan.get('target')}\n"
            f"Expected entities: {expected_list}\n"
            f"Missing entities from DOM/network checks: {missing_list}\n"
            "If visible confirmation text suggests success despite missing DOM mutation evidence, "
            "set matched_expected=true."
        )

        try:
            response = await self.llm.ainvoke(
                [
                    SystemMessage(
                        content="You are a precise OCR and UI-verification assistant for web QA. Return JSON only."
                    ),
                    HumanMessage(
                        content=[
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
                            },
                        ]
                    ),
                ]
            )
            self._track_llm_usage(state, 800)
        except Exception:
            return None

        content = response.content if isinstance(response.content, str) else str(response.content)
        try:
            parsed = json.loads(content)
        except Exception:
            json_match = re.search(r"\{[\s\S]*\}", content)
            if not json_match:
                return None
            try:
                parsed = json.loads(json_match.group(0))
            except Exception:
                return None

        return {
            "matched_expected": bool(parsed.get("matched_expected", False)),
            "confidence": str(parsed.get("confidence", "low")),
            "summary": str(parsed.get("summary", "")).strip(),
            "evidence_keywords": [str(item) for item in parsed.get("evidence_keywords", [])],
        }

    def _create_annotated_failure_image(
        self,
        source_image_path: Optional[str],
        bbox: Optional[Dict[str, float]],
        error_message: Optional[str],
        step_num: int,
    ) -> Optional[str]:
        """Create annotated failure image with bbox highlight and failure label."""
        if not source_image_path:
            return None

        source_path = Path(source_image_path)
        if not source_path.exists():
            return None

        annotated_path = source_path.with_name(f"step_{step_num:04d}_annotated_failure.png")

        try:
            image = Image.open(source_path).convert("RGB")
            draw = ImageDraw.Draw(image)
            width, _ = image.size

            if bbox:
                x = float(bbox.get("x", 0.0))
                y = float(bbox.get("y", 0.0))
                box_width = float(bbox.get("width", 0.0))
                box_height = float(bbox.get("height", 0.0))
                draw.rectangle(
                    [x, y, x + box_width, y + box_height],
                    outline=(220, 38, 38),
                    width=4,
                )

            label = f"Step {step_num} FAILED"
            if error_message:
                label = f"{label}: {error_message[:100]}"

            label_y = 10
            draw.rectangle([(8, label_y), (width - 8, label_y + 32)], fill=(220, 38, 38))
            draw.text((14, label_y + 8), label, fill=(255, 255, 255))

            image.save(annotated_path, format="PNG")
            return str(annotated_path)
        except Exception:
            return None

    async def _run_auth_sequence_step(
        self,
        page: Any,
        generated_user: Dict[str, str],
        auth_form_state: Dict[str, bool],
        context: str,
        action_attempt_counts: Dict[str, int],
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Execute one deterministic auth step to prevent getting stuck on login inputs."""
        if context not in {"signin", "signup"}:
            return None

        auth_credentials = self._auth_credentials_available()

        objective_text = self._primary_objective_text().lower()
        objective_targets_signup = any(
            token in objective_text
            for token in ["sign up", "signup", "register", "create account"]
        )
        should_force_signup = objective_targets_signup or not auth_credentials

        current_url = ""
        try:
            current_url = str(page.url).lower()
        except Exception:
            current_url = ""
        login_surface = any(token in current_url for token in ["/login", "/signin", "/sign-in", "/auth"])

        if should_force_signup and (context == "signin" or login_surface):
            switch_signup_action = {
                "action_type": "click",
                "target": "auth_switch_to_signup_link",
                "value": "",
            }
            if int(action_attempt_counts.get(self._action_signature(switch_signup_action), 0)) < 3:
                switched = await self._click_first_visible(
                    page,
                    [
                        'a:has-text("Sign up")',
                        'a:has-text("Create account")',
                        'a:has-text("Register")',
                        'button:has-text("Sign up")',
                        'button:has-text("Create account")',
                        '[role="button"]:has-text("Sign up")',
                        '[href*="sign-up" i]',
                        '[href*="signup" i]',
                        '[href*="register" i]',
                    ],
                )
                if switched:
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    return (
                        switch_signup_action,
                        {"success": True, "new_url": page.url},
                    )

        if should_force_signup and login_surface:
            return None

        if context == "signup" and auth_credentials:
            switch_signin_action = {
                "action_type": "click",
                "target": "auth_switch_to_signin_link",
                "value": "",
            }
            if int(action_attempt_counts.get(self._action_signature(switch_signin_action), 0)) < 3:
                switched = await self._click_first_visible(
                    page,
                    [
                        'a:has-text("Sign in")',
                        'a:has-text("Log in")',
                        'a:has-text("Login")',
                        'button:has-text("Sign in")',
                        'button:has-text("Log in")',
                        '[role="button"]:has-text("Sign in")',
                        '[href*="login" i]',
                        '[href*="signin" i]',
                    ],
                )
                if switched:
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    return (
                        switch_signin_action,
                        {"success": True, "new_url": page.url},
                    )

        login_identity = generated_user
        if auth_credentials:
            auth_cfg = self.config.get("auth", {}) if isinstance(self.config, dict) else {}
            login_identity = {
                **generated_user,
                "email": str(auth_cfg.get("email") or generated_user["email"]),
                "password": str(auth_cfg.get("password") or generated_user["password"]),
            }

        email_action = {
            "action_type": "type",
            "target": "auth_email_field",
            "value": login_identity["email"],
        }
        if (
            not auth_form_state.get("email_filled")
            and int(action_attempt_counts.get(self._action_signature(email_action), 0)) < 3
        ):
            success = await self._fill_first_visible(
                page,
                [
                    'input[type="email"]',
                    'input[name*="email" i]',
                    'input[id*="email" i]',
                    'input[autocomplete="username"]',
                    'input[name*="user" i]',
                    'input[id*="user" i]',
                ],
                login_identity["email"],
            )
            if success:
                return (
                    email_action,
                    {"success": True, "new_url": page.url},
                )

        password_action = {
            "action_type": "type",
            "target": "auth_password_field",
            "value": login_identity["password"],
        }
        if (
            not auth_form_state.get("password_filled")
            and int(action_attempt_counts.get(self._action_signature(password_action), 0)) < 3
        ):
            success = await self._fill_first_visible(
                page,
                [
                    'input[type="password"]',
                    'input[name*="password" i]',
                    'input[id*="password" i]',
                    'input[autocomplete="current-password"]',
                    'input[autocomplete="new-password"]',
                ],
                login_identity["password"],
            )
            if success:
                return (
                    password_action,
                    {"success": True, "new_url": page.url},
                )

        if context == "signup":
            signup_profile_actions = [
                (
                    {
                        "action_type": "type",
                        "target": "auth_signup_first_name_field",
                        "value": generated_user["first_name"],
                    },
                    [
                        'input[name*="first" i]',
                        'input[id*="first" i]',
                        'input[placeholder*="first" i]',
                    ],
                ),
                (
                    {
                        "action_type": "type",
                        "target": "auth_signup_last_name_field",
                        "value": generated_user["last_name"],
                    },
                    [
                        'input[name*="last" i]',
                        'input[id*="last" i]',
                        'input[placeholder*="last" i]',
                    ],
                ),
                (
                    {
                        "action_type": "type",
                        "target": "auth_signup_full_name_field",
                        "value": generated_user["full_name"],
                    },
                    [
                        'input[name*="full" i]',
                        'input[id*="full" i]',
                        'input[placeholder*="full name" i]',
                        'input[name*="name" i]:not([name*="first" i]):not([name*="last" i])',
                    ],
                ),
                (
                    {
                        "action_type": "type",
                        "target": "auth_signup_business_field",
                        "value": "Test Business",
                    },
                    [
                        'input[name*="business" i]',
                        'input[id*="business" i]',
                        'input[placeholder*="business" i]',
                        'input[name*="company" i]',
                        'input[id*="company" i]',
                        'input[placeholder*="company" i]',
                    ],
                ),
            ]

            for action, selectors in signup_profile_actions:
                if int(action_attempt_counts.get(self._action_signature(action), 0)) >= 2:
                    continue
                success = await self._fill_first_visible(page, selectors, action["value"])
                if success:
                    return (
                        action,
                        {"success": True, "new_url": page.url},
                    )

            required_signup_fill = {
                "action_type": "type",
                "target": "auth_signup_required_field",
                "value": "Sample value",
            }
            if int(action_attempt_counts.get(self._action_signature(required_signup_fill), 0)) < 2:
                required_filled = await self._fill_first_visible(
                    page,
                    [
                        'input[required]:not([type="email"]):not([type="password"])',
                        'textarea[required]',
                        'input[aria-required="true"]:not([type="email"]):not([type="password"])',
                    ],
                    required_signup_fill["value"],
                )
                if required_filled:
                    return (
                        required_signup_fill,
                        {"success": True, "new_url": page.url},
                    )

        submit_action = {"action_type": "click", "target": "auth_submit_button", "value": ""}
        if (
            not auth_form_state.get("submitted")
            and int(action_attempt_counts.get(self._action_signature(submit_action), 0)) < 3
        ):
            clicked = await self._click_first_visible(
                page,
                [
                    'button[type="submit"]',
                    'input[type="submit"]',
                    'button:has-text("Sign in")',
                    'button:has-text("Log in")',
                    'button:has-text("Login")',
                    '[role="button"]:has-text("Sign in")',
                    '[role="button"]:has-text("Log in")',
                ],
            )
            if clicked:
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                return (
                    submit_action,
                    {"success": True, "new_url": page.url},
                )

        return None

    async def _fill_first_visible(self, page: Any, selectors: List[str], value: str) -> bool:
        """Fill first visible matching input selector."""
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible() and await locator.is_enabled():
                    try:
                        current = await locator.input_value(timeout=1200)
                        if current != value:
                            await locator.fill(value, timeout=5000)
                    except Exception:
                        await locator.fill(value, timeout=5000)
                    try:
                        await locator.press("Tab", timeout=1000)
                    except Exception:
                        pass
                    return True
            except Exception:
                continue
        return False

    async def _click_first_visible(self, page: Any, selectors: List[str]) -> bool:
        """Click first visible matching selector."""
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible() and await locator.is_enabled():
                    try:
                        async with page.context.expect_page(timeout=2500) as popup_info:
                            await locator.click(timeout=5000)
                        popup_page = await popup_info.value
                        try:
                            await popup_page.wait_for_load_state("domcontentloaded", timeout=5000)
                        except Exception:
                            pass
                        await popup_page.close()
                    except Exception:
                        await locator.click(timeout=5000)
                    return True
            except Exception:
                continue
        return False

    def _generate_user_identity(self) -> Dict[str, str]:
        """Generate deterministic-enough test credentials for auth flows."""
        return generate_fallback_identity()

    async def _ensure_dynamic_email_identity(
        self,
        state: GraphState,
        artifacts: Dict[str, Any],
        generated_user: Dict[str, str],
        email_verification_enabled: bool,
    ) -> None:
        """Provision dynamic email inbox when verification testing is enabled."""
        if not email_verification_enabled:
            return
        if artifacts.get("dynamic_email_initialized"):
            return
        if not self.email_service:
            return

        try:
            inbox = await self.email_service.provision_inbox()
            artifacts["dynamic_email_initialized"] = True
            if not inbox:
                return

            generated_user["email"] = inbox.address
            artifacts["dynamic_email_inbox"] = {
                "address": inbox.address,
                "login": inbox.login,
                "domain": inbox.domain,
            }
        except Exception as error:
            artifacts["dynamic_email_initialized"] = True
            state["errors"].append(f"Dynamic email provisioning skipped: {error}")

    def _should_check_email_verification(self, action_plan: Dict[str, Any], context: str) -> bool:
        """Determine whether to poll mailbox after submit action."""
        if context in {"signup", "forgot"}:
            return True

        corpus = " ".join(
            [
                str(action_plan.get("target", "")),
                str(action_plan.get("value", "")),
                str(action_plan.get("form_stage", "")),
            ]
        ).lower()
        return any(
            token in corpus
            for token in ["verify", "verification", "forgot", "reset", "signup", "register"]
        )

    async def _attempt_email_verification_followup(
        self,
        page: Any,
        state: GraphState,
        artifacts: Dict[str, Any],
        testing_cfg: Dict[str, Any],
    ) -> str:
        """Poll dynamic inbox and apply verification link/code when available."""
        if not bool(testing_cfg.get("email_verification_enabled", False)):
            return ""
        if not self.email_service:
            return ""

        inbox_data = artifacts.get("dynamic_email_inbox") or {}
        inbox = InboxDetails(
            address=str(inbox_data.get("address", "")),
            login=str(inbox_data.get("login", "")),
            domain=str(inbox_data.get("domain", "")),
        )
        if not inbox.address or not inbox.login or not inbox.domain:
            return ""

        timeout_seconds = int(testing_cfg.get("email_poll_timeout_seconds", 120) or 120)
        interval_seconds = int(testing_cfg.get("email_poll_interval_seconds", 5) or 5)

        try:
            verification = await self.email_service.poll_for_verification(
                inbox,
                timeout_seconds=timeout_seconds,
                interval_seconds=interval_seconds,
            )
            if not verification:
                return ""

            link = str(verification.get("link", "")).strip()
            if link:
                await page.goto(link, wait_until="networkidle")
                return f"Email verification link consumed dynamically: {link[:120]}"

            code = str(verification.get("code", "")).strip()
            if code and await self._apply_verification_code(page, code):
                return "Email verification code applied dynamically"
            return ""
        except Exception as error:
            state["errors"].append(f"Email verification follow-up skipped: {error}")
            return ""

    async def _apply_verification_code(self, page: Any, code: str) -> bool:
        """Fill OTP/verification inputs and submit."""
        selectors = [
            'input[name*="code" i]',
            'input[id*="code" i]',
            'input[name*="otp" i]',
            'input[id*="otp" i]',
            'input[autocomplete="one-time-code"]',
            'input[inputmode="numeric"]',
        ]

        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
            except Exception:
                continue

            if count <= 0:
                continue

            if count == 1:
                try:
                    field = locator.first
                    if await field.is_visible() and await field.is_enabled():
                        await field.fill(code, timeout=5000)
                        try:
                            await field.press("Tab", timeout=1000)
                        except Exception:
                            pass
                        await self._click_first_visible(
                            page,
                            [
                                'button[type="submit"]',
                                'button:has-text("Verify")',
                                'button:has-text("Continue")',
                                'button:has-text("Confirm")',
                            ],
                        )
                        return True
                except Exception:
                    continue

            digits = list(code)
            for index in range(min(count, len(digits))):
                try:
                    field = locator.nth(index)
                    if await field.is_visible() and await field.is_enabled():
                        await field.fill(digits[index], timeout=3000)
                except Exception:
                    continue

            await self._click_first_visible(
                page,
                [
                    'button[type="submit"]',
                    'button:has-text("Verify")',
                    'button:has-text("Continue")',
                    'button:has-text("Confirm")',
                ],
            )
            return True

        return False

    def _classify_page_context(self, state: GraphState, actions: List[Dict[str, Any]]) -> str:
        """Classify current page intent for auth-focused heuristics."""
        title = str(state.get("page_title", "")).lower()
        url = str(state.get("current_url", "")).lower()
        objective_text = self._primary_objective_text().lower()
        objective_targets_signup = any(
            token in objective_text for token in ["sign up", "signup", "register", "create account"]
        )
        auth_credentials = self._auth_credentials_available()

        if ("/dashboard" in url or "/app" in url) and not any(
            auth_path in url for auth_path in ["/login", "/sign-up", "/signup", "/forgot", "/reset"]
        ):
            return "general"

        action_text = " ".join(
            f"{a.get('text', '')} {a.get('description', '')} {a.get('selector', '')}".lower()
            for a in actions[:20]
        )
        corpus = f"{title} {url} {action_text}"

        if any(k in corpus for k in ["forgot", "reset password", "recover"]):
            return "forgot"
        if auth_credentials and any(
            k in corpus
            for k in [
                "sign in",
                "signin",
                "log in",
                "login",
                "sign up",
                "signup",
                "register",
                "create account",
                "/login",
                "/signin",
                "/signup",
                "/sign-up",
            ]
        ):
            return "signin"
        if any(k in corpus for k in ["sign up", "signup", "register", "create account"]):
            return "signup"
        if objective_targets_signup and any(
            k in corpus for k in ["sign in", "signin", "log in", "login", "/login", "/signin"]
        ):
            return "signup"
        if any(k in corpus for k in ["sign in", "signin", "log in", "login"]):
            return "signin"
        return "general"

    def _score_action(self, action: Dict[str, Any], context: str, auth_progress: Dict[str, bool]) -> int:
        """Score candidate actions to prioritize meaningful auth and recovery journeys."""
        text_blob = (
            (
                f"{action.get('text', '')} {action.get('description', '')} {action.get('selector', '')} "
                f"{action.get('name', '')} {action.get('id', '')} {action.get('placeholder', '')} {action.get('input_type', '')} {action.get('href', '')} "
                f"{action.get('role', '')} {action.get('aria_label', '')} {action.get('title', '')}"
            ).lower()
        )
        score = 0

        if action.get("type") == "type":
            score += 20

        if context == "signup":
            if any(k in text_blob for k in ["email", "name", "password"]):
                score += 80
            if any(k in text_blob for k in ["create", "register", "sign up", "submit"]):
                score += 70
        elif context == "signin":
            if any(k in text_blob for k in ["email", "username", "password"]):
                score += 80
            if any(k in text_blob for k in ["sign in", "login", "log in", "submit"]):
                score += 70
            if not auth_progress.get("forgot_attempted") and any(
                k in text_blob for k in ["forgot", "reset password"]
            ):
                score -= 40
        elif context == "forgot":
            if any(k in text_blob for k in ["email", "username"]):
                score += 90
            if any(k in text_blob for k in ["reset", "send", "submit", "continue"]):
                score += 80
        else:
            if any(k in text_blob for k in ["start", "next", "continue", "submit", "search"]):
                score += 30
            if any(
                k in text_blob
                for k in [
                    "create",
                    "new",
                    "add",
                    "edit",
                    "update",
                    "manage",
                    "configure",
                ]
            ):
                score += 95
            if any(
                k in text_blob
                for k in [
                    "notification",
                    "notifications",
                    "popover-trigger",
                    "avatar",
                    "profile menu",
                    "user menu",
                    "facebook",
                    "twitter",
                    "linkedin",
                    "instagram",
                    "whatsapp",
                ]
            ):
                score -= 80

        objective_keywords = self._objective_keywords()
        if objective_keywords and any(keyword in text_blob for keyword in objective_keywords):
            score += 120

        return score

    def _value_for_input(self, action: Dict[str, Any], generated_user: Dict[str, str]) -> str:
        """Generate contextual input values for form fields."""
        text_blob = (
            (
                f"{action.get('text', '')} {action.get('description', '')} {action.get('selector', '')} "
                f"{action.get('name', '')} {action.get('id', '')} {action.get('placeholder', '')} {action.get('input_type', '')} {action.get('href', '')} "
                f"{action.get('role', '')} {action.get('aria_label', '')} {action.get('title', '')}"
            ).lower()
        )

        if "confirm" in text_blob and "password" in text_blob:
            return generated_user["password"]
        if "password" in text_blob:
            return generated_user["password"]
        if any(k in text_blob for k in ["email", "username", "user"]):
            return generated_user["email"]
        if "first" in text_blob and "name" in text_blob:
            return generated_user["first_name"]
        if "last" in text_blob and "name" in text_blob:
            return generated_user["last_name"]
        if "name" in text_blob:
            return generated_user["full_name"]
        if any(k in text_blob for k in ["phone", "mobile", "tel"]):
            return generated_user["phone"]
        if any(k in text_blob for k in ["date", "calendar"]) or str(action.get("input_type", "")).lower() == "date":
            return datetime.now().strftime("%Y-%m-%d")
        if any(k in text_blob for k in ["time", "slot"]):
            return "10:30"
        return "Sample value"

    def _build_heuristic_action(
        self,
        state: GraphState,
        actions: List[Dict[str, Any]],
        generated_user: Dict[str, str],
        auth_progress: Dict[str, bool],
        auth_form_state: Dict[str, bool],
        recent_actions: List[Dict[str, str]],
        action_attempt_counts: Dict[str, int],
    ) -> Dict[str, Any]:
        """Choose next action without LLM, optimized for auth journey coverage."""
        context = self._classify_page_context(state, actions)
        objective_text = self._primary_objective_text().lower()
        objective_targets_signup = any(
            token in objective_text for token in ["sign up", "signup", "register", "create account"]
        )
        auth_credentials = self._auth_credentials_available()
        current_url = str(state.get("current_url", "")).lower()
        login_surface = any(token in current_url for token in ["/login", "/signin", "/sign-in", "/auth"])

        def text_blob(action: Dict[str, Any]) -> str:
            return (
                (
                    f"{action.get('text', '')} {action.get('description', '')} {action.get('selector', '')} "
                    f"{action.get('name', '')} {action.get('id', '')} {action.get('placeholder', '')} {action.get('input_type', '')} {action.get('href', '')} "
                    f"{action.get('role', '')} {action.get('aria_label', '')} {action.get('title', '')}"
                ).lower()
            )

        def not_recent(action: Dict[str, Any]) -> bool:
            signature = f"{action.get('type', '')}:{action.get('selector', '')}"
            return signature not in {f"{a.get('type', '')}:{a.get('target', '')}" for a in recent_actions[-5:]}

        def under_attempt_limit(action: Dict[str, Any]) -> bool:
            probe = {
                "action_type": action.get("type", "click"),
                "target": action.get("selector", action.get("description", "")),
                "value": "",
            }
            if probe["action_type"] == "type":
                probe["value"] = self._value_for_input(action, generated_user)
            else:
                probe["value"] = self._action_semantic_key(action)
            signature = self._action_signature(probe)
            return int(action_attempt_counts.get(signature, 0)) < 3

        def pick(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            for candidate in candidates:
                if not_recent(candidate) and under_attempt_limit(candidate):
                    return candidate
            for candidate in candidates:
                if under_attempt_limit(candidate):
                    return candidate
            return candidates[0] if candidates else None

        def exploration_bonus(action: Dict[str, Any]) -> int:
            bonus = 0
            href = str(action.get("href", "")).strip()
            if href:
                href_path = href.split("?", 1)[0]
                visited_paths = {str(url).split("?", 1)[0] for url in state.get("visited_urls", [])}
                if href_path and href_path not in visited_paths:
                    bonus += 120

            blob = text_blob(action)
            if action.get("type") in {"click", "select"} and any(
                token in blob
                for token in [
                    "create",
                    "new",
                    "add",
                    "edit",
                    "update",
                    "schedule",
                    "manage",
                ]
            ):
                bonus += 70

            objective_keywords = self._objective_keywords()
            if objective_keywords and any(token in blob for token in objective_keywords):
                bonus += 140
            if self._objective_is_strict() and objective_keywords and not any(
                token in blob for token in objective_keywords
            ):
                bonus -= 220
            return bonus

        chosen: Optional[Dict[str, Any]] = None

        if objective_targets_signup and not auth_credentials and login_surface:
            signup_candidates = [
                action
                for action in actions
                if action.get("type") in {"click", "select"}
                and any(
                    token in text_blob(action)
                    for token in [
                        "sign up",
                        "signup",
                        "register",
                        "create account",
                        "get started",
                        "start free",
                        "join",
                        "new here",
                        "create your",
                        "free trial",
                    ]
                )
            ]
            chosen = pick(signup_candidates)

        if context in {"signin", "signup", "forgot"}:
            if not auth_form_state.get("email_filled"):
                email_candidates = [
                    action
                    for action in actions
                    if action.get("type") == "type"
                    and any(k in text_blob(action) for k in ["email", "username", "user", "login"])
                ]
                chosen = pick(email_candidates)

            if not chosen and not auth_form_state.get("password_filled") and context in {"signin", "signup"}:
                password_candidates = [
                    action
                    for action in actions
                    if action.get("type") == "type"
                    and "password" in text_blob(action)
                ]
                chosen = pick(password_candidates)

            if not chosen and auth_form_state.get("email_filled"):
                submit_candidates = [
                    action
                    for action in actions
                    if action.get("type") in {"click", "check"}
                    and any(
                        k in text_blob(action)
                        for k in ["sign in", "signin", "log in", "login", "submit", "continue", "next", "create", "register", "send"]
                    )
                ]
                chosen = pick(submit_candidates)

            if (
                not chosen
                and context == "signin"
                and auth_form_state.get("submit_attempts", 0) >= 2
                and not auth_progress.get("forgot_attempted")
            ):
                forgot_candidates = [
                    action
                    for action in actions
                    if action.get("type") == "click"
                    and any(k in text_blob(action) for k in ["forgot", "reset password", "recover"])
                ]
                chosen = pick(forgot_candidates)

        candidate_actions = actions
        objective_matches = [action for action in actions if self._action_matches_objective(action)]
        if self._objective_is_strict() and objective_matches and context == "general":
            candidate_actions = objective_matches

        if not chosen:
            scored = sorted(
                candidate_actions,
                key=lambda a: self._score_action(a, context, auth_progress)
                + exploration_bonus(a)
                - (120 if not_recent(a) is False else 0),
                reverse=True,
            )
            chosen = scored[0] if scored else actions[0]

        action_type = chosen.get("type", "click")
        target = chosen.get("selector", chosen.get("description", ""))
        value = ""
        if action_type == "type":
            value = self._value_for_input(chosen, generated_user)
        else:
            value = self._action_semantic_key(chosen)

        return {
            "action_type": action_type,
            "target": target,
            "value": value,
        }

    def _build_pre_submit_fill_action(
        self,
        actions: List[Dict[str, Any]],
        action_plan: Dict[str, Any],
        generated_user: Dict[str, str],
        action_attempt_counts: Dict[str, int],
    ) -> Optional[Dict[str, Any]]:
        """If submit is planned while required inputs are present, fill/select required fields first."""
        if not self._is_submit_like_action(action_plan):
            return None

        submit_in_dialog: Optional[bool] = None
        submit_target = str(action_plan.get("target", "")).strip()
        for action in actions:
            action_selector = str(action.get("selector", action.get("description", ""))).strip()
            if action_selector and action_selector == submit_target:
                submit_in_dialog = bool(action.get("in_dialog", False))
                break

        def in_scope(action: Dict[str, Any]) -> bool:
            if submit_in_dialog is None:
                return True
            return bool(action.get("in_dialog", False)) == submit_in_dialog

        def within_attempt_limit(candidate: Dict[str, Any], value: str) -> bool:
            signature = self._action_signature(
                {
                    "action_type": candidate.get("type", "click"),
                    "target": candidate.get("selector", candidate.get("description", "")),
                    "value": value,
                }
            )
            return int(action_attempt_counts.get(signature, 0)) < 3

        required_selects = [
            action
            for action in actions
            if action.get("type") == "select"
            and in_scope(action)
            and (
                bool(action.get("required"))
                or str(action.get("aria_invalid", "")).lower() == "true"
            )
        ]
        for field in required_selects:
            if within_attempt_limit(field, "__webqa_auto__"):
                return {
                    "action_type": "select",
                    "target": field.get("selector", field.get("description", "")),
                    "value": "__webqa_auto__",
                    "form_stage": "pre_submit_required_select",
                }

        required_text_inputs = [
            action
            for action in actions
            if action.get("type") == "type"
            and in_scope(action)
            and (
                bool(action.get("required"))
                or str(action.get("aria_invalid", "")).lower() == "true"
            )
        ]
        for field in required_text_inputs:
            value = self._value_for_input(field, generated_user)
            if within_attempt_limit(field, value):
                return {
                    "action_type": "type",
                    "target": field.get("selector", field.get("description", "")),
                    "value": value,
                    "form_stage": "pre_submit_required_fill",
                }

        likely_required_text_inputs = [
            action
            for action in actions
            if action.get("type") == "type"
            and in_scope(action)
            and any(
                token in self._action_semantic_key(action)
                for token in [
                    "name",
                    "email",
                    "phone",
                    "date",
                    "time",
                    "address",
                    "title",
                    "description",
                    "message",
                    "amount",
                    "quantity",
                ]
            )
        ]
        for field in likely_required_text_inputs:
            value = self._value_for_input(field, generated_user)
            if within_attempt_limit(field, value):
                return {
                    "action_type": "type",
                    "target": field.get("selector", field.get("description", "")),
                    "value": value,
                    "form_stage": "pre_submit_likely_required_fill",
                }

        candidate_selects = [
            action
            for action in actions
            if action.get("type") == "select" and in_scope(action)
        ]
        if 0 < len(candidate_selects) <= 3:
            for field in candidate_selects:
                if within_attempt_limit(field, "__webqa_auto__"):
                    return {
                        "action_type": "select",
                        "target": field.get("selector", field.get("description", "")),
                        "value": "__webqa_auto__",
                        "form_stage": "pre_submit_select_fill",
                    }

        return None

    def _should_run_validation_exploration(self, objective_text: str) -> bool:
        """Only run negative validation pass when objective explicitly asks for validation behavior."""
        text = str(objective_text or "").lower()
        if not text:
            return False
        return any(
            token in text
            for token in [
                "validation",
                "invalid",
                "required field",
                "error state",
                "form error",
                "input error",
                "negative test",
            ]
        )

    async def _build_visual_first_action(
        self,
        state: GraphState,
        page: Any,
        actions: List[Dict[str, Any]],
        generated_user: Dict[str, str],
        auth_progress: Dict[str, bool],
        auth_form_state: Dict[str, bool],
        recent_actions: List[Dict[str, str]],
        action_attempt_counts: Dict[str, int],
    ) -> Dict[str, Any]:
        """Choose next action primarily from screenshot understanding when DOM exploration is disabled."""
        screenshot_b64: Optional[str] = None
        try:
            screenshot_bytes = await page.screenshot(type="png", full_page=False)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        except Exception:
            screenshot_b64 = None

        objective_text = self._primary_objective_text()
        action_excerpt = [
            {
                "type": action.get("type"),
                "selector": action.get("selector"),
                "text": action.get("text"),
                "name": action.get("name"),
                "description": action.get("description"),
            }
            for action in actions[:12]
        ]

        prompt = (
            "DOM exploration is disabled. Use screenshot-first reasoning to infer what the app currently shows, "
            "what functionality is available, and the next best step. "
            "Choose an executable action from the provided action list. "
            "Return strict JSON with keys: action_type, target, value.\n"
            f"Page title: {state.get('page_title', '')}\n"
            f"URL: {state.get('current_url', '')}\n"
            f"Primary objective: {objective_text or 'None'}\n"
            f"Available actions (execution catalog): {json.dumps(action_excerpt, indent=2)}"
        )

        try:
            if screenshot_b64:
                response = await self.llm.ainvoke(
                    [
                        SystemMessage(
                            content=(
                                "You are a visual web QA planner. "
                                "Infer functionality from screenshot and choose one executable next action. "
                                "Return JSON only."
                            )
                        ),
                        HumanMessage(
                            content=[
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
                                },
                            ]
                        ),
                    ]
                )
            else:
                response = await self.llm.ainvoke(
                    [
                        ("system", self.SYSTEM_PROMPT),
                        ("human", prompt),
                    ]
                )
            self._track_llm_usage(state, 700)
            content = response.content if isinstance(response.content, str) else str(response.content)
            action_plan = json.loads(content)

            action_type = str(action_plan.get("action_type", "click"))
            target = str(action_plan.get("target", "")).strip()
            value = str(action_plan.get("value", ""))
            if not target:
                raise ValueError("Missing target in visual-first action response")

            if action_type == "type" and not value:
                matched_action = next(
                    (
                        action
                        for action in actions
                        if str(action.get("selector", "")).strip() == target
                        or str(action.get("description", "")).strip() == target
                    ),
                    None,
                )
                if matched_action:
                    value = self._value_for_input(matched_action, generated_user)

            return {
                "action_type": action_type,
                "target": target,
                "value": value,
            }
        except Exception:
            return self._build_heuristic_action(
                state,
                actions,
                generated_user,
                auth_progress,
                auth_form_state,
                recent_actions,
                action_attempt_counts,
            )

    def _pick_navigation_action(
        self,
        state: GraphState,
        actions: List[Dict[str, Any]],
        action_attempt_counts: Dict[str, int],
        nav_labels_clicked: set,
        deep_traversal_state: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Pick unseen navigation-like actions to expand coverage across app sections."""
        if not deep_traversal_state.get("enabled", True):
            return None

        path_boost = max(0, int(self.config.get("testing", {}).get("path_discovery_boost", 1)))
        boost_multiplier = 1 + min(path_boost, 5) * 0.35

        visited_paths = {str(url).split("?", 1)[0] for url in state.get("visited_urls", [])}
        ignored_tokens = [
            "notification",
            "profile",
            "avatar",
            "logout",
            "menu",
            "close",
            "help",
            "facebook",
            "twitter",
            "instagram",
            "linkedin",
            "documentation",
            "share",
            "open ai",
            "privacy",
            "terms",
            "back to login",
        ]
        priority_tokens = [
            "create",
            "add",
            "new",
            "edit",
            "update",
            "manage",
            "setting",
            "payment",
            "integration",
            "analytics",
            "brand",
            "website",
        ]
        objective_keywords = self._objective_keywords()
        if objective_keywords:
            priority_tokens.extend(sorted(objective_keywords)[:30])

        strict_objective = self._objective_is_strict()
        objective_matches_available = any(
            self._action_matches_objective(action)
            for action in actions
            if action.get("type") in {"click", "select"}
        )

        ranked: List[Tuple[int, Dict[str, Any], str]] = []
        covered_intents = deep_traversal_state.setdefault("covered_intents", set())
        section_clicks = deep_traversal_state.setdefault("section_clicks", {})
        for action in actions:
            if action.get("type") not in {"click", "select"}:
                continue

            semantic = self._action_semantic_key(action)
            if not semantic or semantic in nav_labels_clicked:
                continue
            if any(token in semantic for token in ignored_tokens):
                continue
            if strict_objective and objective_matches_available and not self._action_matches_objective(action):
                continue
            word_count = len(semantic.split())
            if word_count > 4:
                continue

            probe = {
                "action_type": action.get("type", "click"),
                "target": action.get("selector", action.get("description", "")),
                "value": semantic,
            }
            if int(action_attempt_counts.get(self._action_signature(probe), 0)) >= 3:
                continue

            href = str(action.get("href", "")).strip()
            score = 0
            intents = self._infer_action_intents(action)
            if href:
                href_path = href.split("?", 1)[0]
                if href_path and href_path not in visited_paths:
                    score += 120
                score += 30
            if 3 <= len(semantic) <= 28:
                score += 25
            if word_count <= 2:
                score += 90
            if any(k in semantic for k in ["create", "add", "new", "edit", "update", "manage"]):
                score += 60
            if any(token in semantic for token in priority_tokens):
                score += 120

            if objective_keywords and any(token in semantic for token in objective_keywords):
                score += 220

            if intents:
                unseen_intents = [intent for intent in intents if intent not in covered_intents]
                score += len(unseen_intents) * 140
                score += len(intents) * 20

            section_click_count = int(section_clicks.get(semantic, 0))
            score -= section_click_count * 70

            if "auth" in intents and "/dashboard" in str(state.get("current_url", "")).lower():
                score -= 240

            score = int(score * boost_multiplier)

            ranked.append((score, action, semantic))

        if not ranked:
            return None

        ranked.sort(key=lambda item: item[0], reverse=True)
        _, best_action, semantic = ranked[0]
        section_clicks[semantic] = int(section_clicks.get(semantic, 0)) + 1
        intents = sorted(self._infer_action_intents(best_action))
        return {
            "action_type": best_action.get("type", "click"),
            "target": best_action.get("selector", best_action.get("description", "")),
            "value": semantic,
            "nav_label": semantic,
            "nav_intents": intents,
        }

    def _objective_keywords(self) -> set[str]:
        """Extract lightweight keyword hints from configured objectives."""
        return self._objective_terms()

    def _objective_intents(self) -> set[str]:
        """Infer product intents directly from the active objective."""
        corpus = self._primary_objective_text().lower()
        intents: set[str] = set()
        if not corpus:
            return intents

        for intent, keywords in self.INTENT_KEYWORDS.items():
            if any(keyword in corpus for keyword in keywords):
                intents.add(intent)
        return intents

    def _objective_intents_to_entities(self) -> set[str]:
        """Derive expected mutation entities directly from objective keywords."""
        objective_keywords = set(self._objective_keywords())
        if not objective_keywords:
            return set()

        noise = {
            "flow",
            "page",
            "user",
            "test",
            "validate",
            "verify",
            "check",
            "focus",
            "only",
            "just",
            "objective",
            "directed",
            "sign",
            "signup",
            "register",
            "signin",
            "login",
            "log",
            "account",
            "password",
            "verify",
            "verification",
            "forgot",
            "reset",
            "create",
            "new",
            "add",
            "update",
            "edit",
            "delete",
        }
        entities = {
            self._normalize_entity_token(token)
            for token in objective_keywords
            if len(token) >= 4 and token not in noise
        }
        return {token for token in entities if token}

    def _objective_completion_reached(self, mutation_assertions: Dict[str, Any]) -> bool:
        """Check whether objective-required entities have been detected."""
        required = set(str(value) for value in mutation_assertions.get("required_entities", []))
        if not required:
            return True
        detected = set(str(value) for value in mutation_assertions.get("detected_entities", []))
        return required.issubset(detected)

    def _normalize_entity_token(self, token: str) -> str:
        """Normalize token into a stable singular-style entity identifier."""
        normalized = re.sub(r"[^a-z0-9_-]", "", str(token).strip().lower())
        if normalized.endswith("ies") and len(normalized) > 4:
            normalized = normalized[:-3] + "y"
        elif normalized.endswith("es") and len(normalized) > 4:
            normalized = normalized[:-2]
        elif normalized.endswith("s") and len(normalized) > 3:
            normalized = normalized[:-1]
        return normalized

    def _action_matches_objective(self, action: Dict[str, Any]) -> bool:
        """Check whether an available action aligns with the active objective."""
        blob = " ".join(
            [
                str(action.get("text", "")),
                str(action.get("description", "")),
                str(action.get("selector", "")),
                str(action.get("name", "")),
                str(action.get("id", "")),
                str(action.get("placeholder", "")),
                str(action.get("input_type", "")),
                str(action.get("href", "")),
                str(action.get("role", "")),
                str(action.get("aria_label", "")),
                str(action.get("title", "")),
            ]
        ).lower()

        objective_keywords = self._objective_keywords()
        if objective_keywords and any(token in blob for token in objective_keywords):
            return True

        objective_intents = self._objective_intents()
        if objective_intents and (self._infer_action_intents(action) & objective_intents):
            return True

        return False

    def _action_plan_matches_objective(self, action_plan: Dict[str, Any]) -> bool:
        """Check whether a resolved action plan aligns with the active objective."""
        blob = " ".join(
            [
                str(action_plan.get("action_type", "")),
                str(action_plan.get("target", "")),
                str(action_plan.get("value", "")),
                str(action_plan.get("form_stage", "")),
                str(action_plan.get("nav_label", "")),
            ]
        )
        return self._objective_matches_text(blob)

    def _pick_obstruction_clear_action(self, actions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Dismiss unrelated share/dialog overlays when they block a strict objective flow."""
        if not self._objective_is_strict() or not self._primary_objective_text():
            return None

        share_tokens = {
            "share",
            "facebook",
            "twitter",
            "linkedin",
            "instagram",
            "whatsapp",
            "sms",
            "mail",
            "copy link",
            "open ai",
        }
        close_tokens = {"close", "dismiss", "cancel", "not now", "done", "back"}

        share_like_actions = []
        close_candidates = []
        for action in actions:
            blob = " ".join(
                [
                    str(action.get("text", "")),
                    str(action.get("description", "")),
                    str(action.get("selector", "")),
                    str(action.get("aria_label", "")),
                    str(action.get("title", "")),
                ]
            ).lower()
            if any(token in blob for token in share_tokens):
                share_like_actions.append(action)
            if action.get("type") in {"click", "select"} and (
                any(token in blob for token in close_tokens)
                or re.search(r"\b[x×]\b", blob)
            ):
                close_candidates.append(action)

        if len(share_like_actions) >= 2 and close_candidates:
            close_action = close_candidates[0]
            return {
                "action_type": close_action.get("type", "click"),
                "target": close_action.get("selector", close_action.get("description", "")),
                "value": self._action_semantic_key(close_action) or "dismiss blocking dialog",
                "nav_label": "dismiss blocking dialog",
            }

        return None

    def _url_key(self, url: str) -> str:
        """Create stable URL key for per-page traversal bookkeeping."""
        return str(url or "").split("?", 1)[0].strip().lower()

    async def _run_hidden_menu_expander_pass(self, page: Any) -> int:
        """Expand likely collapsed menus to expose hidden navigation options."""
        selectors = [
            'button[aria-label*="menu" i]',
            '[role="button"][aria-label*="menu" i]',
            'button[aria-haspopup="menu"]',
            '[role="button"][aria-haspopup="menu"]',
            'button[aria-expanded="false"]',
            '[role="button"][aria-expanded="false"]',
            'button:has-text("Menu")',
            'button:has-text("More")',
            '[role="button"]:has-text("Menu")',
            '[role="button"]:has-text("More")',
            'button[class*="hamburger" i]',
            'button[class*="sidebar" i]',
            'button[class*="drawer" i]',
        ]
        skip_tokens = {"logout", "log out", "close", "delete", "remove"}
        expanded = 0

        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
            except Exception:
                continue

            for i in range(min(count, 5)):
                if expanded >= 3:
                    return expanded
                try:
                    candidate = locator.nth(i)
                    if not await candidate.is_visible() or not await candidate.is_enabled():
                        continue

                    label = (
                        f"{await candidate.inner_text()} "
                        f"{await candidate.get_attribute('aria-label') or ''} "
                        f"{await candidate.get_attribute('title') or ''}"
                    ).strip().lower()
                    if any(token in label for token in skip_tokens):
                        continue

                    marker = await candidate.get_attribute("data-webqa-expanded")
                    if marker == "1":
                        continue

                    await candidate.evaluate("el => el.setAttribute('data-webqa-expanded', '1')")
                    await candidate.click(timeout=2000)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=1200)
                    except Exception:
                        pass
                    await page.wait_for_timeout(200)
                    expanded += 1
                except Exception:
                    continue

        return expanded

    def _build_form_validation_action(
        self,
        state: GraphState,
        actions: List[Dict[str, Any]],
        generated_user: Dict[str, str],
        form_validation_state: Dict[str, Any],
        action_attempt_counts: Dict[str, int],
    ) -> Optional[Dict[str, Any]]:
        """Run a generic staged pass: missing submit -> invalid submit -> valid submit."""
        url_key = self._url_key(str(state.get("current_url", "")))
        if not url_key:
            return None

        state_entry = form_validation_state.setdefault(
            url_key,
            {
                "stage": 0,
                "active": False,
                "invalid_done": False,
                "valid_done": False,
                "filled_targets": [],
                "clicked_targets": [],
                "modal_submit_failures": 0,
                "validation_retry_round": 0,
            },
        )
        stage = int(state_entry.get("stage", 0))

        text_inputs = [a for a in actions if a.get("type") == "type"]
        submit_actions = [
            action
            for action in actions
            if action.get("type") in {"click", "check", "select"}
            and any(
                token in self._action_semantic_key(action)
                for token in [
                    "submit",
                    "save",
                    "create",
                    "add",
                    "continue",
                    "next",
                    "register",
                    "sign in",
                    "login",
                    "update",
                    "confirm",
                ]
            )
        ]

        modal_submit_actions = [action for action in submit_actions if bool(action.get("in_dialog", False))]
        modal_text_inputs = [action for action in text_inputs if bool(action.get("in_dialog", False))]
        in_modal_form = bool(modal_submit_actions and modal_text_inputs)

        if not text_inputs or not submit_actions:
            return None

        def within_attempt_limit(action: Dict[str, Any], value: str) -> bool:
            signature = self._action_signature(
                {
                    "action_type": action.get("type", "click"),
                    "target": action.get("selector", action.get("description", "")),
                    "value": value,
                }
            )
            return int(action_attempt_counts.get(signature, 0)) < 3

        submit = modal_submit_actions[0] if in_modal_form else submit_actions[0]
        submit_value = self._action_semantic_key(submit)

        if in_modal_form:
            modal_failures = int(state_entry.get("modal_submit_failures", 0))
            if modal_failures >= 4:
                state_entry["stage"] = 5
                state_entry["active"] = False
                return None

            has_validation_error = self._has_validation_error_signal(actions)
            filled_targets = set(str(value) for value in state_entry.get("filled_targets", []))
            clicked_targets = set(str(value) for value in state_entry.get("clicked_targets", []))

            modal_select_inputs = [
                action
                for action in actions
                if bool(action.get("in_dialog", False)) and action.get("type") == "select"
            ]

            for field in modal_select_inputs:
                target = str(field.get("selector", field.get("description", "")))
                if target in filled_targets and not has_validation_error:
                    continue
                if within_attempt_limit(field, "__webqa_auto__"):
                    return {
                        "action_type": "select",
                        "target": target,
                        "value": "__webqa_auto__",
                        "form_stage": "modal_select_input",
                    }

            modal_click_candidates = []
            for action in actions:
                if not bool(action.get("in_dialog", False)):
                    continue
                if action.get("type") not in {"click", "check"}:
                    continue
                semantic = self._action_semantic_key(action)
                href = str(action.get("href", "")).strip().lower()
                if any(token in semantic for token in ["close", "cancel", "remove", "delete", "back"]):
                    continue
                if any(token in semantic for token in ["create", "save", "submit", "confirm"]):
                    continue
                if href.startswith("http") or href.startswith("mailto:") or href.startswith("tel:"):
                    continue
                if any(
                    token in semantic
                    for token in [
                        "open",
                        "website",
                        "web site",
                        "external",
                        "learn more",
                        "documentation",
                        "docs",
                        "help",
                        "support",
                        "privacy",
                        "terms",
                        "instagram",
                        "facebook",
                        "twitter",
                        "linkedin",
                        "whatsapp",
                        "mailto",
                        "email us",
                    ]
                ):
                    continue
                if any(
                    token in semantic
                    for token in [
                        "select",
                        "choose",
                        "option",
                        "item",
                        "pick",
                        "date",
                        "time",
                        "duration",
                    ]
                ):
                    modal_click_candidates.append(action)

            for action in modal_click_candidates:
                target = str(action.get("selector", action.get("description", "")))
                if target in clicked_targets and not has_validation_error:
                    continue
                semantic = self._action_semantic_key(action)
                if within_attempt_limit(action, semantic):
                    return {
                        "action_type": action.get("type", "click"),
                        "target": target,
                        "value": semantic,
                        "form_stage": "modal_click_selector",
                    }

            required_modal_inputs = [
                action
                for action in modal_text_inputs
                if bool(action.get("required"))
                or str(action.get("aria_invalid", "")).lower() == "true"
            ]
            if not required_modal_inputs:
                required_modal_inputs = modal_text_inputs

            for field in required_modal_inputs:
                target = str(field.get("selector", field.get("description", "")))
                if target in filled_targets and not has_validation_error:
                    continue
                value = self._value_for_input(field, generated_user)
                if within_attempt_limit(field, value):
                    return {
                        "action_type": "type",
                        "target": target,
                        "value": value,
                        "form_stage": "modal_valid_input",
                    }

            if within_attempt_limit(submit, submit_value):
                return {
                    "action_type": submit.get("type", "click"),
                    "target": submit.get("selector", submit.get("description", "")),
                    "value": submit_value,
                    "form_stage": "modal_submit",
                }

        if stage == 0 and within_attempt_limit(submit, submit_value):
            return {
                "action_type": submit.get("type", "click"),
                "target": submit.get("selector", submit.get("description", "")),
                "value": submit_value,
                "form_stage": "missing_required",
            }

        target_input = next(
            (
                item
                for item in text_inputs
                if bool(item.get("required")) or "email" in self._action_semantic_key(item)
            ),
            text_inputs[0],
        )

        if stage in {1, 2} and not state_entry.get("invalid_done", False):
            invalid_value = self._invalid_value_for_input(target_input)
            if stage == 1 and within_attempt_limit(target_input, invalid_value):
                state_entry["active"] = True
                return {
                    "action_type": "type",
                    "target": target_input.get("selector", target_input.get("description", "")),
                    "value": invalid_value,
                    "form_stage": "wrong_validation_input",
                }
            if stage == 2 and within_attempt_limit(submit, submit_value):
                return {
                    "action_type": submit.get("type", "click"),
                    "target": submit.get("selector", submit.get("description", "")),
                    "value": submit_value,
                    "form_stage": "wrong_validation_submit",
                }

        if stage in {3, 4} and not state_entry.get("valid_done", False):
            valid_value = self._value_for_input(target_input, generated_user)
            if stage == 3 and within_attempt_limit(target_input, valid_value):
                state_entry["active"] = True
                return {
                    "action_type": "type",
                    "target": target_input.get("selector", target_input.get("description", "")),
                    "value": valid_value,
                    "form_stage": "valid_input",
                }
            if stage == 4 and within_attempt_limit(submit, submit_value):
                return {
                    "action_type": submit.get("type", "click"),
                    "target": submit.get("selector", submit.get("description", "")),
                    "value": submit_value,
                    "form_stage": "valid_submit",
                }

        return None

    def _has_validation_error_signal(self, actions: List[Dict[str, Any]]) -> bool:
        """Detect whether UI hints indicate unresolved form validation errors."""
        tokens = {
            "required",
            "is required",
            "required field",
            "invalid",
            "validation",
            "must be",
            "please enter",
            "please select",
            "error",
        }
        for action in actions:
            blob = " ".join(
                [
                    str(action.get("text", "")),
                    str(action.get("description", "")),
                    str(action.get("name", "")),
                    str(action.get("aria_label", "")),
                    str(action.get("title", "")),
                    str(action.get("selector", "")),
                ]
            ).lower()
            if any(token in blob for token in tokens):
                return True
            if bool(action.get("required")) or str(action.get("aria_invalid", "")).lower() == "true":
                return True
        return False

    def _invalid_value_for_input(self, action: Dict[str, Any]) -> str:
        """Generate intentionally invalid input to trigger browser/app validation."""
        text_blob = (
            (
                f"{action.get('text', '')} {action.get('description', '')} {action.get('selector', '')} "
                f"{action.get('name', '')} {action.get('id', '')} {action.get('placeholder', '')} {action.get('input_type', '')}"
            ).lower()
        )
        input_type = str(action.get("input_type", "")).lower()

        if "email" in text_blob or input_type == "email":
            return "invalid-email"
        if any(k in text_blob for k in ["phone", "mobile", "tel"]) or input_type == "tel":
            return "abc"
        if input_type in {"number", "range"}:
            return "not-a-number"
        if input_type == "date":
            return "13/99/0000"
        if "password" in text_blob:
            return "123"
        return ""

    def _update_form_validation_state(
        self,
        state: GraphState,
        action_plan: Dict[str, Any],
        result: Dict[str, Any],
        form_validation_state: Dict[str, Any],
    ) -> None:
        """Advance staged form-validation pass bookkeeping per page."""
        url_key = self._url_key(str(state.get("current_url", "")))
        if not url_key or url_key not in form_validation_state:
            return

        entry = form_validation_state[url_key]
        stage = int(entry.get("stage", 0))
        form_stage = str(action_plan.get("form_stage", ""))

        if stage == 0 and form_stage == "missing_required":
            entry["stage"] = 1
            return
        if form_stage == "modal_valid_input":
            filled_targets = set(str(value) for value in entry.get("filled_targets", []))
            filled_targets.add(str(action_plan.get("target", "")))
            entry["filled_targets"] = sorted(filled_targets)
            return
        if form_stage == "modal_select_input":
            filled_targets = set(str(value) for value in entry.get("filled_targets", []))
            filled_targets.add(str(action_plan.get("target", "")))
            entry["filled_targets"] = sorted(filled_targets)
            return
        if form_stage == "modal_click_selector":
            clicked_targets = set(str(value) for value in entry.get("clicked_targets", []))
            clicked_targets.add(str(action_plan.get("target", "")))
            entry["clicked_targets"] = sorted(clicked_targets)
            return
        if form_stage == "modal_submit":
            submit_success = bool(result.get("success"))
            entry["valid_done"] = submit_success
            entry["active"] = False
            if submit_success:
                entry["stage"] = 5
                entry["modal_submit_failures"] = 0
            else:
                entry["modal_submit_failures"] = int(entry.get("modal_submit_failures", 0)) + 1
                entry["validation_retry_round"] = int(entry.get("validation_retry_round", 0)) + 1
                entry["filled_targets"] = []
                entry["clicked_targets"] = []
                entry["stage"] = 1
            return
        if stage == 1 and form_stage == "wrong_validation_input":
            entry["stage"] = 2
            return
        if stage == 2 and form_stage == "wrong_validation_submit":
            entry["invalid_done"] = True
            entry["stage"] = 3
            return
        if stage == 3 and form_stage == "valid_input":
            entry["stage"] = 4
            return
        if stage == 4 and form_stage == "valid_submit":
            submit_success = bool(result.get("success"))
            entry["valid_done"] = submit_success
            entry["active"] = False
            if submit_success:
                entry["stage"] = 5
                entry["modal_submit_failures"] = 0
            else:
                entry["validation_retry_round"] = int(entry.get("validation_retry_round", 0)) + 1
                entry["stage"] = 1
            return

    def _update_auth_form_state(
        self,
        action_plan: Dict[str, Any],
        auth_form_state: Dict[str, bool],
        generated_user: Dict[str, str],
    ) -> None:
        """Track auth form progression to avoid retyping same field in a loop."""
        text_blob = f"{action_plan.get('target', '')} {action_plan.get('action_type', '')}".lower()
        if "auth_switch_to_signup" in text_blob or "auth_switch_to_signin" in text_blob:
            auth_form_state["email_filled"] = False
            auth_form_state["password_filled"] = False
            auth_form_state["submitted"] = False
            auth_form_state["submit_attempts"] = 0
            return
        if action_plan.get("action_type") == "type":
            if any(k in text_blob for k in ["email", "username", "user", "login"]):
                auth_form_state["email_filled"] = True
            if "password" in text_blob:
                auth_form_state["password_filled"] = True

        if action_plan.get("action_type") == "type":
            value = str(action_plan.get("value", ""))
            if "@" in value:
                auth_form_state["email_filled"] = True
            if value == generated_user.get("password", ""):
                auth_form_state["password_filled"] = True

        if action_plan.get("action_type") == "click" and any(
            k in text_blob for k in ["submit", "sign in", "login", "log in", "create", "register", "continue", "next", "reset", "send"]
        ):
            auth_form_state["submitted"] = True
            auth_form_state["submit_attempts"] = int(auth_form_state.get("submit_attempts", 0)) + 1

    def _record_recent_action(
        self, action_plan: Dict[str, Any], recent_actions: List[Dict[str, str]]
    ) -> None:
        """Store recent action signatures to discourage immediate repetition."""
        recent_actions.append(
            {
                "type": str(action_plan.get("action_type", "")),
                "target": str(action_plan.get("target", "")),
            }
        )
        if len(recent_actions) > 12:
            del recent_actions[:-12]

    def _action_signature(self, action_plan: Dict[str, Any]) -> str:
        """Create a stable signature used to cap repeated attempts."""
        action_type = str(action_plan.get("action_type", "")).strip().lower()
        target = str(action_plan.get("target", "")).strip().lower()
        target = re.sub(r"wq-\d+", "wq", target)
        value = str(action_plan.get("value", "")).strip().lower()
        return f"{action_type}:{target}:{value}"

    def _action_semantic_key(self, action: Dict[str, Any]) -> str:
        """Build semantic key for action repeat guarding across selector churn."""
        for field in ["text", "name", "aria_label", "title", "href", "description"]:
            candidate = str(action.get(field, "")).strip().lower()
            if candidate:
                return re.sub(r"\s+", " ", candidate)[:80]
        selector = str(action.get("selector", "")).strip().lower()
        return re.sub(r"wq-\d+", "wq", selector)[:80]

    def _infer_action_intents(self, action: Dict[str, Any]) -> set[str]:
        """Infer semantic intents for action labels/metadata using synonym clusters."""
        corpus = " ".join(
            [
                str(action.get("text", "")),
                str(action.get("name", "")),
                str(action.get("description", "")),
                str(action.get("href", "")),
                str(action.get("aria_label", "")),
                str(action.get("title", "")),
                str(action.get("id", "")),
            ]
        ).lower()

        intents: set[str] = set()
        for intent, keywords in self.INTENT_KEYWORDS.items():
            if any(keyword in corpus for keyword in keywords):
                intents.add(intent)

        return intents

    def _flow_signature(self, context: str, state: GraphState) -> str:
        """Create flow signature to avoid re-testing the same flow excessively."""
        base_url = str(state.get("current_url", "")).split("?")[0].lower()
        return f"{context}:{base_url}"

    def _update_auth_progress(self, action_plan: Dict[str, Any], auth_progress: Dict[str, bool]) -> None:
        """Mark attempted auth subflows based on executed action."""
        text_blob = f"{action_plan.get('target', '')} {action_plan.get('action_type', '')}".lower()
        if any(k in text_blob for k in ["register", "signup", "sign up", "create account"]):
            auth_progress["signup_attempted"] = True
        if any(k in text_blob for k in ["signin", "sign in", "login", "log in"]):
            auth_progress["signin_attempted"] = True
        if any(k in text_blob for k in ["forgot", "reset password", "recover"]):
            auth_progress["forgot_attempted"] = True

    def _extract_mutation_logs_from_network(self, network_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract likely API mutation requests from per-step network logs."""
        mutation_logs: List[Dict[str, Any]] = []
        for log in network_logs:
            method = str(log.get("method", "")).upper()
            url = str(log.get("url", ""))
            payload = str(log.get("post_data", ""))
            if method not in {"POST", "PUT", "PATCH", "DELETE"}:
                continue
            lowered_url = url.lower()
            lowered_payload = payload.lower()
            if any(token in lowered_url for token in [".css", ".js", ".png", ".jpg", ".svg", "analytics", "sentry", "segment", "mixpanel"]):
                continue
            if (
                any(token in lowered_url for token in ["/api/", "/v1/", "/v2/", "/graphql"])
                or "mutation" in lowered_payload
                or bool(payload)
            ):
                mutation_logs.append(
                    {
                        "method": method,
                        "url": url,
                        "status": int(log.get("status", 0) or 0),
                        "post_data": payload,
                    }
                )
        return mutation_logs

    def _detect_mutation_entities(self, mutation_logs: List[Dict[str, Any]]) -> set[str]:
        """Classify mutation logs into dynamic entities inferred from objective + API paths."""
        objective_entities = self._objective_intents_to_entities()
        noise_tokens = {
            "api",
            "graphql",
            "mutation",
            "query",
            "create",
            "update",
            "delete",
            "list",
            "bulk",
            "submit",
            "save",
            "v1",
            "v2",
            "v3",
        }
        detected: set[str] = set()
        for log in mutation_logs:
            corpus = " ".join(
                [
                    str(log.get("url", "")),
                    str(log.get("post_data", "")),
                ]
            ).lower()

            candidates = {
                self._normalize_entity_token(token)
                for token in re.findall(r"[a-z][a-z0-9_-]{2,}", corpus)
            }
            candidates = {token for token in candidates if token and token not in noise_tokens}

            if objective_entities:
                matched = {entity for entity in objective_entities if entity in candidates or entity in corpus}
                detected.update(matched)
                continue

            detected.update({token for token in candidates if len(token) >= 4})
        return detected

    def _is_submit_like_action(self, action_plan: Dict[str, Any]) -> bool:
        """Detect form-submit style actions where mutation assertion should run."""
        if str(action_plan.get("action_type", "")).lower() not in {"click", "select", "check"}:
            return False
        form_stage = str(action_plan.get("form_stage", "")).lower()
        if form_stage in {"modal_submit", "valid_submit"}:
            return True
        corpus = " ".join(
            [
                str(action_plan.get("target", "")),
                str(action_plan.get("value", "")),
                str(action_plan.get("form_stage", "")),
            ]
        ).lower()
        return any(token in corpus for token in ["submit", "save", "create", "add", "confirm"])

    def _expected_entities_for_submit(
        self,
        action_plan: Dict[str, Any],
        state: GraphState,
        mutation_assertions: Dict[str, Any],
    ) -> set[str]:
        """Infer which entity mutations should happen for this submit action."""
        corpus = " ".join(
            [
                str(action_plan.get("target", "")),
                str(action_plan.get("value", "")),
                str(state.get("current_url", "")),
                str(getattr(state.get("current_flow"), "name", "")) if state.get("current_flow") else "",
            ]
        ).lower()

        objective_entities = self._objective_intents_to_entities()
        expected = {entity for entity in objective_entities if entity and entity in corpus}
        if not expected and objective_entities:
            expected = set(objective_entities)

        if expected:
            return expected

        required = [str(v) for v in mutation_assertions.get("required_entities", [])]
        detected = set(str(v) for v in mutation_assertions.get("detected_entities", []))
        remaining = [entity for entity in required if entity not in detected]
        return {remaining[0]} if remaining else set()


class ValidatorAgent(BaseAgent):
    """Validator agent - checks for errors and validates state."""

    SYSTEM_PROMPT = """You are an expert QA validator. Check the current state for:

1. Console errors (JavaScript exceptions, warnings)
2. Network errors (failed requests, 4xx/5xx status codes)
3. UI state issues (404 pages, error messages, broken layouts)
4. Functional correctness (did the action achieve its goal?)
5. Accessibility issues (missing labels, contrast problems)

For each issue found, classify severity: CRITICAL, HIGH, MEDIUM, LOW

Respond in JSON format with validation results."""

    async def run(self, state: GraphState) -> GraphState:
        """Validate the current test state."""
        page = state["browser"]
        mcp_client = state["mcp_client"]

        # Get last step
        if not state["test_results"]:
            return state

        last_step = state["test_results"][-1]

        # Check for critical issues
        has_errors = False

        # Check console logs
        for log in last_step.console_logs:
            if log.get("level") in ["error", "severe"]:
                has_errors = True
                last_step.status = "failed"
                break

        # Check network logs
        for log in last_step.network_logs:
            status = log.get("status", 0)
            if status >= 400:
                has_errors = True
                if status >= 500:
                    last_step.status = "failed"

        # Use LLM for deeper validation
        if self._has_llm_configured() and self.config.get("visual", {}).get("screenshot_on_action"):
            messages = [
                ("system", self.SYSTEM_PROMPT),
                (
                    "human",
                    f"""Last action: {last_step.action} on {last_step.target}
Status: {last_step.status}
Console errors: {len([l for l in last_step.console_logs if l.get("level") == "error"])}
Network errors: {len([l for l in last_step.network_logs if l.get("status", 0) >= 400])}

Should we continue testing this flow or mark it complete?""",
                ),
            ]

            try:
                response = await self.llm.ainvoke(messages)
                self._track_llm_usage(state, 500)

                validation = json.loads(response.content)

                # Update flow status based on validation
                if state["current_flow"]:
                    if validation.get("should_complete_flow"):
                        objective_text = self._primary_objective_text().lower()
                        current_url = str(state.get("current_url", "")).lower()
                        if any(
                            token in objective_text
                            for token in ["sign up", "signup", "register", "create account"]
                        ) and any(token in current_url for token in ["/login", "/signin", "/sign-in"]):
                            pass
                        else:
                            state["current_flow"].status = "completed"
                            state["current_flow"].end_url = state["current_url"]
                            state["current_flow"] = None
                    elif has_errors and validation.get("is_critical_error"):
                        state["current_flow"].status = "failed"
                        state["current_flow"] = None

            except Exception as e:
                if self._is_llm_auth_error(e):
                    self._disable_llm(
                        state,
                        "LLM provider authentication failed. Continuing in adaptive heuristic mode.",
                    )
                else:
                    state["errors"].append(f"Validator LLM error: {e}")

        # Simple validation: complete flow if too many errors
        if state["current_flow"] and last_step.status == "failed":
            failed_steps = [s for s in state["current_flow"].steps if s.status == "failed"]
            if len(failed_steps) >= 3:
                state["current_flow"].status = "failed"
                state["current_flow"] = None

        return state


class ReporterAgent(BaseAgent):
    """Reporter agent - generates final report and cleanup."""

    async def run(self, state: GraphState) -> GraphState:
        """Prepare final state for reporting."""
        state["current_state"] = AgentState.COMPLETED

        # Calculate coverage metrics
        if state["discovered_flows"]:
            completed_flows = [f for f in state["discovered_flows"] if f.status == "completed"]
            state["coverage_metrics"]["flows"] = (
                len(completed_flows) / len(state["discovered_flows"]) * 100
            )

        if state["test_results"]:
            successful = len([s for s in state["test_results"] if s.status == "success"])
            state["coverage_metrics"]["steps"] = successful / len(state["test_results"]) * 100

        state["coverage_metrics"]["urls"] = len(state["visited_urls"])

        # Mark any remaining flows
        if state["current_flow"]:
            state["current_flow"].status = "completed"
            state["current_flow"].end_url = state["current_url"]

        mutation_assertions = state.get("artifacts", {}).get("mutation_assertions", {})
        required_entities = set(str(value) for value in mutation_assertions.get("required_entities", []))
        detected_entities = set(str(value) for value in mutation_assertions.get("detected_entities", []))
        missing_entities = sorted(required_entities - detected_entities)
        if missing_entities:
            state["errors"].append(
                "Missing required create-mutation coverage for: " + ", ".join(missing_entities)
            )

        return state
