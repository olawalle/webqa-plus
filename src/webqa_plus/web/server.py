"""FastAPI server for WebQA-Plus web interface."""

import asyncio
import httpx
import os
import sys
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from webqa_plus.core.engine import TestEngine
from webqa_plus.utils.config import AppConfig, load_config
from webqa_plus.utils.llm_providers import LLMProvider, get_default_model_for_provider

# In-memory storage for test sessions
test_sessions: Dict[str, Dict[str, Any]] = {}


def _append_log(session: Dict[str, Any], level: str, message: str) -> None:
    """Append a structured log entry and cap log size."""
    session["logs"].append(
        {
            "ts": datetime.now().isoformat(),
            "level": level,
            "message": message,
        }
    )
    if len(session["logs"]) > 500:
        session["logs"] = session["logs"][-500:]


def _friendly_error_message(error: Exception) -> str:
    """Convert technical runtime errors into user-friendly messages."""
    message = str(error)
    lower = message.lower()

    if "executable doesn't exist" in lower and "playwright" in lower:
        return (
            "Browser runtime is not installed yet. "
            "Please try again in a moment while setup completes."
        )

    if "api key" in lower or "authentication" in lower:
        return "Authentication failed. Please verify your credentials and try again."

    if "timeout" in lower:
        return "The test took too long to start. Please retry in a few moments."

    if "weasyprint" in lower or "libgobject" in lower:
        return (
            "Test finished but PDF report generation is unavailable on this server right now."
        )

    return "Test run failed due to a system issue. Please try again."


def _log_exception_details(session: Dict[str, Any], error: Exception, phase: str) -> None:
    """Log technical error diagnostics for root-cause tracing."""
    error_type = error.__class__.__name__
    _append_log(session, "error", f"[Root cause • {phase}] {error_type}: {error}")
    session.setdefault("debug_errors", []).append(f"{phase}: {error_type}: {error}")

    traceback_lines = traceback.format_exception(type(error), error, error.__traceback__)
    traceback_text = "".join(traceback_lines).strip()
    if traceback_text:
        tail_lines = traceback_text.splitlines()[-8:]
        session.setdefault("debug_errors", []).append("\n".join(tail_lines))
        if len(session["debug_errors"]) > 20:
            session["debug_errors"] = session["debug_errors"][-20:]
        for line in tail_lines:
            cleaned = line.strip()
            if cleaned:
                _append_log(session, "error", f"[Trace] {cleaned[:400]}")


async def _ensure_playwright_browser(session: Dict[str, Any], browser: str) -> bool:
    """Ensure required Playwright browser runtime is installed (auto-repair if missing)."""
    target_browser = browser if browser in {"chromium", "firefox", "webkit"} else "chromium"

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser_type = getattr(p, target_browser)
            executable_path = Path(browser_type.executable_path)
            if executable_path.exists():
                return True

        _append_log(
            session,
            "warning",
            f"Setting up browser runtime ({target_browser}) for first use...",
        )

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "playwright",
            "install",
            target_browser,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)

        if process.returncode != 0:
            error_tail = (stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")).strip()
            short_error = " ".join(error_tail.splitlines()[-2:])[:240] if error_tail else "unknown reason"
            _append_log(
                session,
                "error",
                f"Automatic browser setup failed ({target_browser}): {short_error}",
            )
            return False

        _append_log(session, "success", f"Browser runtime ready ({target_browser}).")
        return True

    except asyncio.TimeoutError:
        _append_log(
            session,
            "error",
            "Automatic browser setup timed out. Please try again shortly.",
        )
        return False
    except Exception as e:
        _append_log(
            session,
            "error",
            "Could not verify browser runtime on this server.",
        )
        _log_exception_details(session, e, "browser-precheck")
        return False


class ProviderInfo(BaseModel):
    """Provider information."""

    id: str
    name: str
    icon: str
    description: str
    default_model: str
    env_var: str


class TestConfig(BaseModel):
    """Test configuration from web form."""

    # LLM Provider
    provider: str
    api_key: str
    model: str
    max_tokens: int = 4096
    temperature: float = 0.3

    # Target URL
    url: str

    # Authentication
    auth_enabled: bool = False
    auth_email: Optional[str] = None
    auth_password: Optional[str] = None

    # Testing Options
    mode: str = "stealth"
    max_steps: int = 200
    browser: str = "chromium"
    headless: bool = True
    screenshot_on_error: bool = True
    screenshot_on_action: bool = True
    hidden_menu_expander: bool = True
    deep_traversal: bool = True
    path_discovery_boost: int = 1
    form_validation_pass: bool = True
    email_verification_enabled: bool = False
    email_provider: str = "1secmail"
    email_provider_base_url: str = "https://www.1secmail.com/api/v1/"
    email_poll_timeout_seconds: int = 120
    email_poll_interval_seconds: int = 5
    email_request_timeout_seconds: float = 12.0

    # Output
    output_dir: str = "./reports"


class TestStatus(BaseModel):
    """Test execution status."""

    session_id: str
    status: str  # pending, running, completed, failed
    progress: float
    current_step: int
    max_steps: int
    urls_visited: int
    flows_discovered: int
    test_results: int
    errors: List[str]
    logs: List[Dict[str, str]]
    debug_errors: List[str] = []
    report_path: Optional[str] = None


PROVIDERS = [
    ProviderInfo(
        id="openai",
        name="OpenAI",
        icon="🤖",
        description="GPT-4 Turbo, GPT-4, GPT-3.5",
        default_model="gpt-4-turbo-preview",
        env_var="OPENAI_API_KEY",
    ),
    ProviderInfo(
        id="anthropic",
        name="Anthropic",
        icon="🧠",
        description="Claude 3 Opus, Sonnet, Haiku",
        default_model="claude-3-opus-20240229",
        env_var="ANTHROPIC_API_KEY",
    ),
    ProviderInfo(
        id="openrouter",
        name="OpenRouter",
        icon="🌐",
        description="Access multiple models via OpenRouter",
        default_model="anthropic/claude-3-opus",
        env_var="OPENROUTER_API_KEY",
    ),
]


STATIC_MODELS: Dict[str, List[Dict[str, str]]] = {
    "openai": [
        {"id": "gpt-4-turbo-preview", "name": "GPT-4 Turbo"},
        {"id": "gpt-4", "name": "GPT-4"},
        {"id": "gpt-4-32k", "name": "GPT-4 (32K)"},
        {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"},
    ],
    "anthropic": [
        {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus"},
        {"id": "claude-3-sonnet-20240229", "name": "Claude 3 Sonnet"},
        {"id": "claude-3-haiku-20240307", "name": "Claude 3 Haiku"},
    ],
    "openrouter": [
        {"id": "anthropic/claude-3-opus", "name": "Claude 3 Opus"},
        {"id": "anthropic/claude-3-sonnet", "name": "Claude 3 Sonnet"},
        {"id": "openai/gpt-4-turbo", "name": "GPT-4 Turbo"},
        {"id": "openai/gpt-4", "name": "GPT-4"},
        {"id": "google/gemini-pro", "name": "Gemini Pro"},
    ],
}


def _provider_env_var(provider: str) -> str:
    env_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    return env_map.get(provider, "")


def _resolve_api_key(provider: str, api_key: Optional[str]) -> str:
    if api_key and api_key.strip():
        return api_key.strip()
    env_var = _provider_env_var(provider)
    return os.getenv(env_var, "")


async def _fetch_openai_models(api_key: str) -> List[Dict[str, str]]:
    if not api_key:
        raise ValueError("OpenAI API key is required for dynamic model fetch")

    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
        payload = response.json()

    models = []
    for model in payload.get("data", []):
        model_id = model.get("id")
        if not model_id:
            continue
        models.append({"id": model_id, "name": model_id})

    return sorted(models, key=lambda m: m["id"])


async def _fetch_anthropic_models(api_key: str) -> List[Dict[str, str]]:
    if not api_key:
        raise ValueError("Anthropic API key is required for dynamic model fetch")

    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        response.raise_for_status()
        payload = response.json()

    models = []
    for model in payload.get("data", []):
        model_id = model.get("id")
        display_name = model.get("display_name") or model_id
        if not model_id:
            continue
        models.append({"id": model_id, "name": display_name})

    return sorted(models, key=lambda m: m["id"])


async def _fetch_openrouter_models(api_key: str) -> List[Dict[str, str]]:
    headers: Dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
        response.raise_for_status()
        payload = response.json()

    models = []
    for model in payload.get("data", []):
        model_id = model.get("id")
        display_name = model.get("name") or model_id
        if not model_id:
            continue
        models.append({"id": model_id, "name": display_name})

    return sorted(models, key=lambda m: m["id"])


async def _fetch_provider_models(provider: str, api_key: str) -> List[Dict[str, str]]:
    if provider == "openai":
        return await _fetch_openai_models(api_key)
    if provider == "anthropic":
        return await _fetch_anthropic_models(api_key)
    if provider == "openrouter":
        return await _fetch_openrouter_models(api_key)
    return []


def get_static_dir() -> Path:
    """Get static directory path."""
    return Path(__file__).parent / "static"


def get_templates_dir() -> Path:
    """Get templates directory path."""
    return Path(__file__).parent / "templates"


def get_frontend_dist_dir() -> Path:
    """Get React frontend production build directory path."""
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    # Startup
    yield
    # Shutdown


def create_app() -> FastAPI:
    """Create FastAPI application."""
    app = FastAPI(
        title="WebQA-Plus",
        description="Autonomous AI Web QA Tester",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files
    static_dir = get_static_dir()
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Templates
    templates_dir = get_templates_dir()
    templates = Jinja2Templates(directory=str(templates_dir))
    frontend_dist_dir = get_frontend_dist_dir()
    frontend_index = frontend_dist_dir / "index.html"

    # React build assets (production)
    frontend_assets_dir = frontend_dist_dir / "assets"
    if frontend_assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(frontend_assets_dir)), name="frontend-assets")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        """Serve main page."""
        if frontend_index.exists():
            return FileResponse(str(frontend_index))
        return templates.TemplateResponse("index.html", {"request": request})

    @app.get("/api/providers")
    async def get_providers():
        """Get available LLM providers."""
        return {
            "providers": [p.model_dump() for p in PROVIDERS],
        }

    @app.get("/api/models/{provider}")
    async def get_models(provider: str, api_key: Optional[str] = None):
        """Get available models for a provider (dynamic fetch with fallback)."""
        selected_provider = next((p for p in PROVIDERS if p.id == provider), None)
        if not selected_provider:
            return JSONResponse(status_code=404, content={"error": "Unknown provider"})

        resolved_api_key = _resolve_api_key(provider, api_key)

        try:
            models = await _fetch_provider_models(provider, resolved_api_key)
            if not models:
                raise ValueError("No models returned from provider API")
            return {
                "models": models,
                "source": "dynamic",
                "default_model": selected_provider.default_model,
            }
        except Exception:
            return {
                "models": STATIC_MODELS.get(provider, []),
                "source": "fallback",
                "default_model": selected_provider.default_model,
            }

    @app.post("/api/test/start")
    async def start_test(config: TestConfig, background_tasks: BackgroundTasks):
        """Start a new test session."""
        session_id = str(uuid.uuid4())

        # Create session storage
        test_sessions[session_id] = {
            "id": session_id,
            "config": config.model_dump(),
            "status": "pending",
            "progress": 0.0,
            "current_step": 0,
            "max_steps": config.max_steps,
            "urls_visited": 0,
            "flows_discovered": 0,
            "test_results": 0,
            "errors": [],
            "debug_errors": [],
            "logs": [],
            "report_path": None,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
        }

        # Start test in background
        background_tasks.add_task(run_test_session, session_id)

        return {"session_id": session_id, "status": "started"}

    @app.get("/api/test/{session_id}/status")
    async def get_test_status(session_id: str):
        """Get test session status."""
        if session_id not in test_sessions:
            return JSONResponse(status_code=404, content={"error": "Session not found"})

        session = test_sessions[session_id]
        return TestStatus(
            session_id=session_id,
            status=session["status"],
            progress=session["progress"],
            current_step=session["current_step"],
            max_steps=session["max_steps"],
            urls_visited=session["urls_visited"],
            flows_discovered=session["flows_discovered"],
            test_results=session["test_results"],
            errors=session["errors"],
            logs=session["logs"],
            debug_errors=session.get("debug_errors", []),
            report_path=session.get("report_path"),
        )

    @app.post("/api/test/{session_id}/stop")
    async def stop_test(session_id: str):
        """Stop a running test session."""
        if session_id not in test_sessions:
            return JSONResponse(status_code=404, content={"error": "Session not found"})

        test_sessions[session_id]["status"] = "stopped"
        _append_log(test_sessions[session_id], "warning", "Stop requested by user")
        return {"status": "stopped"}

    @app.get("/api/reports")
    async def list_reports():
        """List available test reports."""
        reports_dir = Path("./reports")
        if not reports_dir.exists():
            return {"reports": []}

        reports = []
        report_files = [
            *reports_dir.glob("*.pdf"),
            *reports_dir.glob("*.html"),
            *reports_dir.glob("*.htm"),
        ]
        report_files.sort(key=lambda item: item.stat().st_mtime, reverse=True)

        for report_file in report_files:
            reports.append(
                {
                    "filename": report_file.name,
                    "path": str(report_file),
                    "size": report_file.stat().st_size,
                    "created": datetime.fromtimestamp(report_file.stat().st_mtime).isoformat(),
                }
            )

        return {"reports": reports}

    @app.get("/api/reports/{filename}")
    async def get_report_file(filename: str, download: bool = False):
        """Serve a generated report file."""
        reports_dir = Path("./reports").resolve()
        requested = (reports_dir / filename).resolve()

        if requested.parent != reports_dir or not requested.exists() or not requested.is_file():
            return JSONResponse(status_code=404, content={"error": "Report not found"})

        disposition = "attachment" if download else "inline"
        suffix = requested.suffix.lower()
        media_type = "application/pdf"
        if suffix in {".html", ".htm"}:
            media_type = "text/html"

        return FileResponse(
            path=str(requested),
            media_type=media_type,
            filename=requested.name,
            headers={"Content-Disposition": f'{disposition}; filename="{requested.name}"'},
        )

    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        """WebSocket endpoint for real-time updates."""
        await websocket.accept()

        if session_id not in test_sessions:
            await websocket.close(code=4004)
            return

        try:
            while True:
                session = test_sessions[session_id]
                await websocket.send_json(
                    {
                        "status": session["status"],
                        "progress": session["progress"],
                        "current_step": session["current_step"],
                        "max_steps": session["max_steps"],
                        "urls_visited": session["urls_visited"],
                        "flows_discovered": session["flows_discovered"],
                        "test_results": session["test_results"],
                        "logs": session["logs"][-50:],
                    }
                )
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            pass

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Serve React SPA fallback for non-API, non-WS routes in production."""
        if full_path.startswith("api/") or full_path.startswith("ws/") or full_path.startswith("static/"):
            return JSONResponse(status_code=404, content={"error": "Not found"})

        candidate = frontend_dist_dir / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))

        if frontend_index.exists():
            return FileResponse(str(frontend_index))

        return JSONResponse(status_code=404, content={"error": "Not found"})

    return app


async def run_test_session(session_id: str):
    """Run test session in background."""
    session = test_sessions[session_id]
    config_data = session["config"]

    try:
        session["status"] = "running"
        _append_log(session, "info", f"Launching test for {config_data['url']}")

        browser_ready = await _ensure_playwright_browser(session, config_data.get("browser", "chromium"))
        if not browser_ready:
            raise RuntimeError(
                "Browser runtime is not available on this server. Please try again shortly."
            )

        # Create config
        from rich.console import Console

        console = Console(file=open(os.devnull, "w"))  # Suppress console output

        # Build configuration
        app_config = AppConfig()

        # LLM configuration
        app_config.llm.provider = config_data["provider"]
        app_config.llm.api_key = config_data["api_key"]
        app_config.llm.model = config_data["model"]
        app_config.llm.max_tokens = config_data["max_tokens"]
        app_config.llm.temperature = config_data["temperature"]

        # Testing configuration
        app_config.testing.url = config_data["url"]
        app_config.testing.mode = config_data["mode"]
        app_config.testing.max_steps = config_data["max_steps"]
        app_config.testing.output_dir = config_data["output_dir"]
        app_config.testing.screenshot_on_error = config_data["screenshot_on_error"]
        app_config.testing.screenshot_on_action = config_data["screenshot_on_action"]
        app_config.testing.hidden_menu_expander = config_data.get("hidden_menu_expander", True)
        app_config.testing.deep_traversal = config_data.get("deep_traversal", True)
        app_config.testing.path_discovery_boost = int(config_data.get("path_discovery_boost", 1))
        app_config.testing.form_validation_pass = config_data.get("form_validation_pass", True)
        app_config.testing.email_verification_enabled = config_data.get(
            "email_verification_enabled", False
        )
        app_config.testing.email_provider = config_data.get("email_provider", "1secmail")
        app_config.testing.email_provider_base_url = config_data.get(
            "email_provider_base_url", "https://www.1secmail.com/api/v1/"
        )
        app_config.testing.email_poll_timeout_seconds = int(
            config_data.get("email_poll_timeout_seconds", 120)
        )
        app_config.testing.email_poll_interval_seconds = int(
            config_data.get("email_poll_interval_seconds", 5)
        )
        app_config.testing.email_request_timeout_seconds = float(
            config_data.get("email_request_timeout_seconds", 12.0)
        )

        # Playwright configuration
        app_config.playwright.browser = config_data["browser"]
        app_config.playwright.headless = config_data["headless"]

        # Auth configuration
        if config_data["auth_enabled"]:
            app_config.auth.enabled = True
            app_config.auth.email = config_data.get("auth_email")
            app_config.auth.password = config_data.get("auth_password")

        # Ensure output directory exists
        output_dir = Path(config_data["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create and run engine
        engine = TestEngine(app_config, console, verbose=False)

        async def handle_state_update(state: Dict[str, Any]) -> None:
            if session.get("status") == "stopped":
                state["should_stop"] = True

            current_step = int(state.get("current_step", 0))
            max_steps = int(state.get("max_steps", config_data["max_steps"]))
            progress = min(99.0, (current_step / max_steps) * 100) if max_steps > 0 else 0.0

            session["current_step"] = current_step
            session["max_steps"] = max_steps
            session["progress"] = progress
            session["urls_visited"] = len(state.get("visited_urls", []))
            session["flows_discovered"] = len(state.get("discovered_flows", []))
            session["test_results"] = len(state.get("test_results", []))

            current_state = str(state.get("current_state", "running"))
            _append_log(
                session,
                "info",
                (
                    f"Step {current_step}/{max_steps} • {current_state} • "
                    f"URLs {session['urls_visited']} • Flows {session['flows_discovered']}"
                ),
            )

            for err in state.get("errors", []):
                existing = [e.get("message", "") for e in session["logs"] if e.get("level") == "error"]
                if err not in existing:
                    _append_log(session, "error", err)

        # Run test
        result = await engine.run(on_update=handle_state_update)

        # Generate report
        report_path: Optional[Path] = None
        try:
            report_path = await engine.generate_report(result)
        except Exception as report_error:
            _append_log(session, "warning", _friendly_error_message(report_error))
            _log_exception_details(session, report_error, "report-generation")

        # Update session with results
        session["status"] = "completed"
        session["progress"] = 100.0
        session["report_path"] = str(report_path) if report_path else None
        session["urls_visited"] = len(result.get("visited_urls", []))
        session["flows_discovered"] = len(result.get("discovered_flows", []))
        session["test_results"] = len(result.get("test_results", []))
        session["end_time"] = datetime.now().isoformat()
        if report_path:
            _append_log(session, "success", f"Test completed. Report: {report_path.name}")
        else:
            _append_log(session, "success", "Test completed.")

    except Exception as e:
        session["status"] = "failed"
        session["errors"].append(_friendly_error_message(e))
        session["end_time"] = datetime.now().isoformat()
        _append_log(session, "error", _friendly_error_message(e))
        _log_exception_details(session, e, "test-run")


def start_server(host: str = "127.0.0.1", port: int = 8095):
    """Start the web server."""
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=host, port=port)
