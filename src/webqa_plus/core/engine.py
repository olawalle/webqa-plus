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

            # Handle authentication if provided
            if self.config.auth.enabled:
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
                "current_url": self.config.testing.url,
                "page_title": await self.page.title(),
                "visited_urls": [self.config.testing.url],
                "discovered_flows": [],
                "current_flow": None,
                "test_results": [],
                "coverage_metrics": {"urls": 0, "flows": 0, "steps": 0},
                "llm_calls": 0,
                "total_tokens": 0,
                "estimated_cost": 0.0,
                "config": self.config.model_dump(),
                "auth_completed": self.config.auth.enabled,
                "artifacts": {},
                "errors": [],
                "should_stop": False,
            }

            try:
                async def emit_update(state: GraphState) -> None:
                    if self.config.testing.mode == "visual":
                        await self._update_visual_overlay(state)
                    if on_update:
                        await on_update(state)

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

    async def _update_visual_overlay(self, state: GraphState) -> None:
        """Push live graph state to in-browser visual overlay."""
        if not self.page:
            return

        flows = state.get("discovered_flows", []) or []
        completed = [f.name for f in flows if getattr(f, "status", "") == "completed"][:6]
        upcoming = [f.name for f in flows if getattr(f, "status", "") not in {"completed", "failed"}][:6]

        current_flow = state.get("current_flow")
        flow_name = getattr(current_flow, "name", "") if current_flow else "Exploring"
        if not flow_name:
            flow_name = "Exploring"

        test_results = state.get("test_results", []) or []
        current_action = None
        if test_results:
            last = test_results[-1]
            action = getattr(last, "action", "")
            target = getattr(last, "target", "") or ""
            current_action = f"{action} {target}".strip()

        max_steps = int(state.get("max_steps", self.config.testing.max_steps))
        current_step = int(state.get("current_step", 0))
        coverage = float(state.get("coverage_metrics", {}).get("steps", 0.0))
        if coverage <= 0 and max_steps > 0:
            coverage = min(100.0, (current_step / max_steps) * 100)

        await self.visual_overlay.update(
            self.page,
            flow_name=flow_name,
            current_step=current_step,
            max_steps=max_steps,
            completed_flows=completed,
            upcoming_flows=upcoming,
            url_count=len(state.get("visited_urls", [])),
            coverage=coverage,
            current_action=current_action,
        )
