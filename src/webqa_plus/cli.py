"""WebQA-Plus CLI entrypoint with Typer."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

# Load environment variables
load_dotenv()

console = Console()
app = typer.Typer(
    name="webqa-plus",
    help="Best-of-all-worlds autonomous AI web QA tester",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


def _project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "src").exists():
            return parent
    return current.parents[2]


# Web UI command
@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind the web server"),
    port: int = typer.Option(8095, "--port", "-p", help="Port to run the web server"),
):
    """Launch the WebQA-Plus web interface.

    Opens a browser-based interface for configuring and running tests.
    """
    console.print(
        Panel.fit(
            "[bold blue]🧪 WebQA-Plus[/bold blue] - Web Interface\n"
            f"[dim]Starting server at http://{host}:{port}[/dim]",
            title="Launching Web UI",
            border_style="green",
        )
    )

    try:
        from webqa_plus.web.server import start_server

        start_server(host=host, port=port)
    except ImportError as e:
        console.print(f"[red]Error: Web interface dependencies not installed. {e}[/red]")
        console.print("[dim]Install with: uv sync[/dim]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error starting web server: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def suite(
    host: str = typer.Option("127.0.0.1", "--host", help="Backend host"),
    backend_port: int = typer.Option(8095, "--backend-port", help="Backend port"),
    frontend_port: int = typer.Option(5273, "--frontend-port", help="Frontend dev server port"),
    prod: bool = typer.Option(False, "--prod", help="Run backend only and serve built React frontend"),
):
    """Run the full WebQA-Plus suite (backend + frontend) with one command."""
    from webqa_plus.web.server import start_server

    root = _project_root()
    frontend_dir = root / "frontend"

    if prod:
        console.print(
            Panel.fit(
                "[bold blue]🧪 WebQA-Plus[/bold blue] - Full Suite (PROD)\n"
                f"[dim]Backend + built frontend at http://{host}:{backend_port}[/dim]",
                title="Starting Full Suite",
                border_style="green",
            )
        )
        start_server(host=host, port=backend_port)
        return

    if not frontend_dir.exists():
        console.print(f"[red]Frontend project not found at {frontend_dir}[/red]")
        raise typer.Exit(1)

    console.print(
        Panel.fit(
            "[bold blue]🧪 WebQA-Plus[/bold blue] - Full Suite (DEV)\n"
            f"[dim]Backend:[/dim] http://{host}:{backend_port}\n"
            f"[dim]Frontend:[/dim] http://{host}:{frontend_port}",
            title="Starting Full Suite",
            border_style="green",
        )
    )

    backend_cmd = [
        sys.executable,
        "-c",
        (
            "from webqa_plus.web.server import start_server; "
            f"start_server(host='{host}', port={backend_port})"
        ),
    ]
    frontend_cmd = ["npm", "run", "dev", "--", "--host", host, "--port", str(frontend_port)]

    backend_proc = None
    frontend_proc = None
    try:
        backend_proc = subprocess.Popen(backend_cmd, cwd=str(root))
        frontend_proc = subprocess.Popen(frontend_cmd, cwd=str(frontend_dir))

        exit_code = frontend_proc.wait()
        if exit_code != 0:
            raise typer.Exit(exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping full suite...[/yellow]")
    finally:
        for proc in [frontend_proc, backend_proc]:
            if proc and proc.poll() is None:
                proc.terminate()
        for proc in [frontend_proc, backend_proc]:
            if proc:
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()


# Version command
@app.command()
def version():
    """Show version information."""
    from webqa_plus import __version__

    console.print(
        Panel.fit(
            f"[bold blue]WebQA-Plus[/bold blue] v{__version__}\n"
            "[dim]Autonomous AI Web QA Tester[/dim]",
            title="Version",
            border_style="blue",
        )
    )


# Main test command
@app.command()
def test(
    url: str = typer.Option(..., "--url", "-u", help="Target URL to test"),
    email: Optional[str] = typer.Option(None, "--email", "-e", help="Login email"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Login password"),
    mode: str = typer.Option("stealth", "--mode", "-m", help="Runtime mode: visual or stealth"),
    max_steps: int = typer.Option(200, "--max-steps", "-s", help="Maximum exploration steps"),
    output_dir: Path = typer.Option(
        Path("./reports"), "--output-dir", "-o", help="Output directory for reports"
    ),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Configuration file path"),
    objectives: Optional[Path] = typer.Option(None, "--objectives", help="Custom objectives file"),
    headless_override: Optional[bool] = typer.Option(
        None, "--headless/--no-headless", help="Override headless mode"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Run autonomous QA testing on a web application.

    [bold]Examples:[/bold]

    # Basic stealth test
    webqa-plus test --url https://example.com

    # Visual mode with authentication
    webqa-plus test --url https://app.example.com -e user@example.com -p secret --mode visual

    # Full configuration
    webqa-plus test --url https://example.com -m visual -s 200 -o ./reports --config config.yaml
    """

    # Validate inputs
    if mode not in ["visual", "stealth"]:
        console.print("[red]Error: --mode must be 'visual' or 'stealth'[/red]")
        raise typer.Exit(1)

    if email and not password:
        console.print("[red]Error: --password required when --email is provided[/red]")
        raise typer.Exit(1)

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Show banner
    console.print(
        Panel.fit(
            "[bold blue]🧪 WebQA-Plus[/bold blue] - Autonomous AI Web QA Tester\n"
            f"[dim]Target:[/dim] {url}\n"
            f"[dim]Mode:[/dim] {mode.upper()}\n"
            f"[dim]Max Steps:[/dim] {max_steps}",
            title="Starting Test Session",
            border_style="green",
        )
    )

    # Run the test
    try:
        asyncio.run(
            _run_test(
                url=url,
                email=email,
                password=password,
                mode=mode,
                max_steps=max_steps,
                output_dir=output_dir,
                config_path=config,
                objectives_path=objectives,
                headless_override=headless_override,
                verbose=verbose,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Test interrupted by user[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        if verbose:
            console.print_exception()
        raise typer.Exit(1)


async def _run_test(
    url: str,
    email: Optional[str],
    password: Optional[str],
    mode: str,
    max_steps: int,
    output_dir: Path,
    config_path: Optional[Path],
    objectives_path: Optional[Path],
    headless_override: Optional[bool],
    verbose: bool,
):
    """Execute the test run."""
    from webqa_plus.core.engine import TestEngine
    from webqa_plus.utils.config import load_config

    # Load configuration
    config = load_config(config_path)

    # Override with CLI arguments
    config.testing.url = url
    config.testing.mode = mode
    config.testing.max_steps = max_steps
    config.testing.output_dir = str(output_dir)

    if email and password:
        config.auth.email = email
        config.auth.password = password
        config.auth.enabled = True

    if headless_override is not None:
        config.playwright.headless = headless_override
    else:
        config.playwright.headless = mode == "stealth"

    # Load custom objectives if provided
    if objectives_path:
        from webqa_plus.utils.objectives import load_objectives

        config.objectives = load_objectives(objectives_path)

    # Initialize and run test engine
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Initializing test engine...", total=None)

        engine = TestEngine(config, console, verbose)
        progress.update(task, description="Running test session...")

        try:
            result = await engine.run()

            progress.update(task, description="Generating report...")
            report_path = await engine.generate_report(result)

            console.print(f"\n[green]✓ Test completed successfully![/green]")
            console.print(f"[dim]Report saved to:[/dim] {report_path}")

        except Exception as e:
            console.print(f"\n[red]✗ Test failed: {e}[/red]")
            raise


# Doctor command to check setup
@app.command()
def doctor():
    """Check system setup and dependencies."""
    import subprocess

    console.print("[bold]🔍 Running System Checks...[/bold]\n")

    # Check LLM providers
    llm_providers = []
    if os.getenv("OPENAI_API_KEY"):
        llm_providers.append("OpenAI")
    if os.getenv("ANTHROPIC_API_KEY"):
        llm_providers.append("Anthropic")
    if os.getenv("OPENROUTER_API_KEY"):
        llm_providers.append("OpenRouter")

    checks = [
        ("Python 3.12+", f"{sys.version_info.major}.{sys.version_info.minor}"),
        ("Playwright", _check_playwright()),
        ("LLM Providers", ", ".join(llm_providers) if llm_providers else "None configured"),
        ("WeasyPrint", "✓" if _check_weasyprint() else "✗"),
    ]

    all_passed = True
    llm_configured = len(llm_providers) > 0

    for name, status in checks:
        icon = "✓" if status not in ["✗", "missing", "None configured"] else "✗"
        color = "green" if icon == "✓" else "red"
        console.print(f"  [{color}]{icon}[/{color}] {name}: {status}")
        if name == "LLM Providers" and not llm_configured:
            all_passed = False

    console.print()
    if all_passed:
        console.print("[green]All checks passed! Ready to test.[/green]")
    else:
        console.print("[yellow]Some checks failed. Run --help for setup instructions.[/yellow]")
        console.print("\n[dim]To configure LLM providers, set one of:[/dim]")
        console.print("  - OPENAI_API_KEY for OpenAI")
        console.print("  - ANTHROPIC_API_KEY for Anthropic (Claude)")
        console.print("  - OPENROUTER_API_KEY for OpenRouter")


def _check_playwright():
    """Check if Playwright browsers are installed."""
    try:
        import subprocess

        result = subprocess.run(
            ["playwright", "chromium", "--version"], capture_output=True, text=True, timeout=5
        )
        return "✓" if result.returncode == 0 else "✗ (run: playwright install)"
    except:
        return "✗ (not installed)"


def _check_weasyprint():
    """Check if WeasyPrint dependencies are available."""
    try:
        import weasyprint

        return True
    except:
        return False


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
