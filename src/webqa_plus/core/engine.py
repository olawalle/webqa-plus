"""Main test engine that orchestrates the entire testing process."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from webqa_plus.core.agents import ExplorerAgent, ReporterAgent, TesterAgent, ValidatorAgent
from webqa_plus.core.auth_handler import AuthHandler
from webqa_plus.core.graph import GraphState, LangGraphOrchestrator
from webqa_plus.core.mcp_client import MCPClient
from webqa_plus.core.visual_overlay import VisualOverlay
from webqa_plus.utils.config import AppConfig


class TestEngine:
    """Main test engine for WebQA-Plus."""

    def __init__(self, config: AppConfig, console: Console, verbose: bool = False):
        """Initialize test engine."""
        self.config = config
        self.console = console
        self.verbose = verbose
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

        # Initialize components
        self.mcp_client = MCPClient(config.mcp.model_dump())
        self.auth_handler = AuthHandler(config.model_dump())
        self.visual_overlay = VisualOverlay(config.visual.model_dump())

        # Initialize agents
        self.explorer = ExplorerAgent(config.model_dump())
        self.tester = TesterAgent(config.model_dump())
        self.validator = ValidatorAgent(config.model_dump())
        self.reporter = ReporterAgent(config.model_dump())

        # Initialize orchestrator
        self.orchestrator = LangGraphOrchestrator(
            self.explorer,
            self.tester,
            self.validator,
            self.reporter,
        )

        # State tracking
        self.live_display: Optional[Live] = None
        self.page = None
        self.browser = None
        self.context = None
        self.latest_graph_state: Optional[GraphState] = None
        self._overlay_binding_installed = False

    async def run(
        self,
        on_update: Optional[Callable[[GraphState], Awaitable[None]]] = None,
    ) -> GraphState:
        """Execute the test run."""
        self.start_time = datetime.now()

        async with async_playwright() as p:
            # Launch browser
            browser_config = self.config.playwright

            if browser_config.browser == "chromium":
                browser_type = p.chromium
            elif browser_config.browser == "firefox":
                browser_type = p.firefox
            elif browser_config.browser == "webkit":
                browser_type = p.webkit
            else:
                browser_type = p.chromium

            launch_args = ["--no-sandbox", "--disable-setuid-sandbox"] if os.getenv("CI") else []
            visual_headed_mode = self.config.testing.mode == "visual" and not browser_config.headless
            if visual_headed_mode and browser_config.browser == "chromium":
                launch_args.append("--start-maximized")

            self.browser = await browser_type.launch(
                headless=browser_config.headless,
                args=launch_args,
            )

            # Create context
            context_kwargs = {
                "record_video_dir": str(Path(self.config.testing.output_dir) / "videos")
                if not browser_config.headless
                else None,
            }
            if visual_headed_mode:
                context_kwargs["viewport"] = None
                context_kwargs["no_viewport"] = True
            else:
                context_kwargs["viewport"] = browser_config.viewport

            self.context = await self.browser.new_context(**context_kwargs)

            if self.config.testing.mode == "visual":
                await self._setup_overlay_directive_binding()

            # Create page
            self.page = await self.context.new_page()

            # Apply stealth mode if needed
            if self.config.testing.mode == "stealth":
                await Stealth().apply_stealth_async(self.page)

            # Set timeouts
            self.page.set_default_timeout(browser_config.timeout)
            self.page.set_default_navigation_timeout(browser_config.timeout)

            # Inject visual overlay if in visual mode
            if self.config.testing.mode == "visual":
                await self.visual_overlay.inject(self.page)

            # Setup console and network monitoring
            await self._setup_monitoring()

            # Navigate to target URL
            await self.page.goto(self.config.testing.url)
            await self.page.wait_for_load_state("networkidle")

            # Re-inject overlay after initial navigation to ensure it is visible on the target app.
            if self.config.testing.mode == "visual":
                await self.visual_overlay.inject(self.page)

                pre_auth_state: GraphState = {
                    "current_state": "initializing",
                    "current_step": 0,
                    "max_steps": self.config.testing.max_steps,
                    "browser": self.page,
                    "mcp_client": self.mcp_client,
                    "current_url": self.page.url,
                    "page_title": await self.page.title(),
                    "visited_urls": [self.page.url],
                    "discovered_flows": [],
                    "current_flow": None,
                    "test_results": [],
                    "coverage_metrics": {"urls": 0, "flows": 0, "steps": 0},
                    "llm_calls": 0,
                    "total_tokens": 0,
                    "estimated_cost": 0.0,
                    "config": self.config.model_dump(),
                    "auth_completed": False,
                    "artifacts": {},
                    "errors": [],
                    "should_stop": False,
                }
                self.latest_graph_state = pre_auth_state
                await self._update_visual_overlay(pre_auth_state)

            auth_success = not self.config.auth.enabled

            objective_description = ""
            try:
                objectives_cfg = self.config.objectives or {}
                objective_items = objectives_cfg.get("objectives", []) if isinstance(objectives_cfg, dict) else []
                if objective_items and isinstance(objective_items[0], dict):
                    objective_description = str(objective_items[0].get("description", "")).lower()
            except Exception:
                objective_description = ""

            has_auth_credentials = bool(
                self.config.auth.enabled and self.config.auth.email and self.config.auth.password
            )
            disable_forced_auth = (
                not has_auth_credentials
                and any(
                    token in objective_description
                    for token in ["sign up", "signup", "register", "create account"]
                )
            )

            # Handle authentication if provided
            if self.config.auth.enabled:
                if disable_forced_auth:
                    auth_success = True
                    self.console.print(
                        "[dim]Skipping forced login because objective targets signup/register flow.[/dim]"
                    )
                else:
                    self.console.print("[dim]Attempting authentication...[/dim]")
                    auth_success = await self.auth_handler.authenticate(self.page)
                    if auth_success:
                        self.console.print("[green]✓ Authentication successful[/green]")
                    else:
                        self.console.print("[yellow]⚠ Authentication not required or failed[/yellow]")

            # Initialize live display
            if self.config.testing.mode == "visual":
                self.live_display = Live(
                    self._create_dashboard(),
                    console=self.console,
                    refresh_per_second=4,
                )
                self.live_display.start()

            # Initialize graph state
            initial_state: GraphState = {
                "current_state": "idle",
                "current_step": 0,
                "max_steps": self.config.testing.max_steps,
                "browser": self.page,
                "mcp_client": self.mcp_client,
                "current_url": self.page.url,
                "page_title": await self.page.title(),
                "visited_urls": [self.page.url],
                "discovered_flows": [],
                "current_flow": None,
                "test_results": [],
                "coverage_metrics": {"urls": 0, "flows": 0, "steps": 0},
                "llm_calls": 0,
                "total_tokens": 0,
                "estimated_cost": 0.0,
                "config": self.config.model_dump(),
                "auth_completed": auth_success,
                "artifacts": {},
                "errors": [],
                "should_stop": False,
            }

            try:
                async def emit_update(state: GraphState) -> None:
                    self.latest_graph_state = state
                    if self.config.testing.mode == "visual":
                        await self._update_visual_overlay(state)
                    if on_update:
                        await on_update(state)

                # Push one immediate update so overlay doesn't stay at static init state.
                await emit_update(initial_state)

                # Run with streaming updates so visual overlay and websocket status stay in sync.
                result = await self.orchestrator.run_with_updates(initial_state, emit_update)

                # Update final state
                self.end_time = datetime.now()

                if self.live_display:
                    self.live_display.stop()

                return result

            except Exception as e:
                if self.live_display:
                    self.live_display.stop()
                raise
            finally:
                # Cleanup
                await self._cleanup()

    async def generate_report(self, state: GraphState) -> Path:
        """Generate PDF report from test results."""
        from webqa_plus.reporter.pdf_generator import PDFReportGenerator

        generator = PDFReportGenerator(self.config)

        report_data = {
            "config": self.config.model_dump(),
            "state": state,
            "start_time": self.start_time,
            "end_time": self.end_time or datetime.now(),
            "duration": ((self.end_time or datetime.now()) - self.start_time).total_seconds(),
        }

        output_path = (
            Path(self.config.testing.output_dir)
            / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )

        await generator.generate(report_data, output_path)

        return output_path

    async def _setup_monitoring(self) -> None:
        """Setup console and network monitoring."""
        # Console monitoring
        self.page.on("console", self._on_console_message)

        # Network monitoring
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)

    def _on_console_message(self, msg) -> None:
        """Handle console message."""
        if self.verbose:
            self.console.print(f"[dim][Console {msg.type}][/dim] {msg.text}")

    def _on_request(self, request) -> None:
        """Handle network request."""
        if self.verbose:
            self.console.print(f"[dim]>>> {request.method} {request.url[:80]}[/dim]")

    def _on_response(self, response) -> None:
        """Handle network response."""
        if self.verbose:
            self.console.print(f"[dim]<<< {response.status} {response.url[:80]}[/dim]")

    def _create_dashboard(self) -> Layout:
        """Create Rich dashboard for visual mode."""
        layout = Layout()

        # Header
        header = Panel(
            "[bold blue]🧪 WebQA-Plus[/bold blue] - Visual Testing Mode",
            border_style="blue",
        )

        layout.split_column(
            Layout(header, size=3),
            Layout(name="body"),
        )

        # Body layout
        layout["body"].split_row(
            Layout(name="left", ratio=2),
            Layout(name="right", ratio=1),
        )

        # Progress section
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
        )
        progress.add_task("Exploration", total=100)
        progress.add_task("Flows", total=10)
        progress.add_task("Validation", total=100)

        layout["left"].split_column(
            Layout(Panel(progress, title="Progress", border_style="green")),
            Layout(Panel("Testing in progress...", title="Current Action", border_style="yellow")),
        )

        # Stats section
        stats_table = Table(show_header=False, box=None)
        stats_table.add_row("URLs Visited:", "0")
        stats_table.add_row("Flows Found:", "0")
        stats_table.add_row("Steps:", "0")
        stats_table.add_row("Errors:", "0")

        layout["right"].update(Panel(stats_table, title="Statistics", border_style="cyan"))

        return layout

    async def _cleanup(self) -> None:
        """Cleanup resources."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()

    def _apply_runtime_directive(self, instruction: str) -> None:
        """Apply a live objective update to the active engine and agents."""
        from webqa_plus.utils.objectives import directive_to_objectives

        objectives = directive_to_objectives(instruction)
        self.config.objectives = objectives
        for agent in [self.explorer, self.tester, self.validator, self.reporter]:
            if hasattr(agent, "config") and isinstance(agent.config, dict):
                agent.config["objectives"] = objectives

    async def _setup_overlay_directive_binding(self) -> None:
        """Expose a browser binding so the overlay can steer the test live."""
        if not self.context or self._overlay_binding_installed:
            return

        async def handle_overlay_directive(_source: Any, instruction: Any) -> Dict[str, Any]:
            text = str(instruction or "").strip()
            if not text:
                return {"ok": False, "error": "Directive cannot be empty."}

            self._apply_runtime_directive(text)

            if self.latest_graph_state is not None:
                await self._update_visual_overlay(self.latest_graph_state)

            return {"ok": True, "objective": text}

        await self.context.expose_binding("webqaPlusUpdateDirective", handle_overlay_directive)
        self._overlay_binding_installed = True

    async def _update_visual_overlay(self, state: GraphState) -> None:
        """Push live graph state to in-browser visual overlay."""
        if not self.page:
            return

        flows = state.get("discovered_flows", []) or []

        def _flow_name(flow: Any) -> str:
            if isinstance(flow, dict):
                return str(flow.get("name", ""))
            return str(getattr(flow, "name", ""))

        def _flow_status(flow: Any) -> str:
            if isinstance(flow, dict):
                return str(flow.get("status", ""))
            return str(getattr(flow, "status", ""))

        completed = [_flow_name(flow) for flow in flows if _flow_status(flow) == "completed"][:6]
        upcoming = [
            _flow_name(flow)
            for flow in flows
            if _flow_status(flow) not in {"completed", "failed"}
        ][:6]

        current_flow = state.get("current_flow")
        if isinstance(current_flow, dict):
            flow_name = str(current_flow.get("name", ""))
        else:
            flow_name = getattr(current_flow, "name", "") if current_flow else "Exploring"
        if not flow_name:
            flow_name = "Exploring"

        test_results = state.get("test_results", []) or []
        current_action = None
        if test_results:
            last = test_results[-1]
            if isinstance(last, dict):
                action = str(last.get("action", ""))
                target = str(last.get("target", "") or "")
            else:
                action = getattr(last, "action", "")
                target = getattr(last, "target", "") or ""
            current_action = f"{action} {target}".strip()

        max_steps = int(state.get("max_steps", self.config.testing.max_steps))
        current_step = int(state.get("current_step", 0))
        coverage = float(state.get("coverage_metrics", {}).get("steps", 0.0))
        if coverage <= 0 and max_steps > 0:
            coverage = min(100.0, (current_step / max_steps) * 100)

        current_phase = str(state.get("current_state", "idle"))
        objective_text = "No objective set."
        objective_config = self.config.objectives or {}
        objective_items = objective_config.get("objectives") if isinstance(objective_config, dict) else None
        if objective_items and isinstance(objective_items, list):
            first_objective = objective_items[0] if objective_items else None
            if isinstance(first_objective, dict):
                objective_text = str(first_objective.get("description") or first_objective.get("name") or objective_text)

        pages = []
        if self.context:
            try:
                pages = list(self.context.pages)
            except Exception:
                pages = []
        if not pages and self.page:
            pages = [self.page]

        for current_page in pages:
            try:
                await self.visual_overlay.update(
                    current_page,
                    flow_name=flow_name,
                    current_phase=current_phase,
                    objective_text=objective_text,
                    current_step=current_step,
                    max_steps=max_steps,
                    completed_flows=completed,
                    upcoming_flows=upcoming,
                    url_count=len(state.get("visited_urls", [])),
                    coverage=coverage,
                    current_action=current_action,
                )
            except Exception:
                continue
