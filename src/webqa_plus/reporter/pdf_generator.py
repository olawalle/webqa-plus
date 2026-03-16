"""PDF report generator using WeasyPrint."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader

from webqa_plus.utils.config import AppConfig
from webqa_plus.utils.weasyprint_env import configure_weasyprint_env


class PDFReportGenerator:
    """Generates PDF reports from test results."""

    def __init__(self, config: AppConfig):
        """Initialize report generator."""
        self.config = config
        self.template_dir = Path(config.report.template_dir)

        # Setup Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=True,
        )
        self.env.filters["format_datetime"] = lambda dt: (
            dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "N/A"
        )

    async def generate(self, data: Dict[str, Any], output_path: Path) -> Path:
        """Generate PDF report, or gracefully fall back to HTML when PDF backend is unavailable."""
        # Render HTML
        template = self.env.get_template("template.html.j2")
        html_content = template.render(**self._prepare_data(data))

        # Write HTML for debugging
        html_path = output_path.with_suffix(".html")
        html_path.write_text(html_content)

        try:
            configure_weasyprint_env()
            from weasyprint import CSS, HTML
        except Exception:
            return html_path

        # Generate PDF
        html = HTML(string=html_content, base_url=str(self.template_dir))
        css = CSS(string=self._get_css())
        html.write_pdf(output_path, stylesheets=[css])

        return output_path

    def _prepare_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare data for template rendering."""
        state = data.get("state", {})
        config = data.get("config", {})

        test_results_raw = state.get("test_results", [])
        test_results = [self._as_dict(item) for item in test_results_raw]
        flows_raw = state.get("discovered_flows", [])
        flows = [self._as_dict(item) for item in flows_raw]
        step_visuals = state.get("artifacts", {}).get("step_visuals", {})

        for result in test_results:
            step_number = result.get("step_number")
            visual_entry = step_visuals.get(str(step_number)) or step_visuals.get(step_number)
            if isinstance(visual_entry, dict):
                result["visuals"] = self._normalize_visual_paths(visual_entry)

        # Calculate metrics
        total_steps = len(test_results)
        successful_steps = len([s for s in test_results if s.get("status") == "success"])
        failed_steps = len([s for s in test_results if s.get("status") == "failed"])

        total_flows = len(flows)
        completed_flows = len([f for f in flows if f.get("status") == "completed"])

        coverage_pct = 0.0
        if total_steps > 0:
            coverage_pct = (successful_steps / total_steps) * 100

        # Build rich diagnostic data
        failures = self._build_failure_deep_dives(test_results)
        all_console_errors = self._aggregate_console_errors(test_results)
        all_network_failures = self._aggregate_network_failures(test_results)
        perf = self._build_perf_stats(test_results)

        return {
            "title": "WebQA-Plus Test Report",
            "generated_at": datetime.now(),
            "config": config,
            "metrics": {
                "total_steps": total_steps,
                "successful_steps": successful_steps,
                "failed_steps": failed_steps,
                "success_rate": f"{(successful_steps / total_steps * 100):.1f}%"
                if total_steps > 0
                else "N/A",
                "total_flows": total_flows,
                "completed_flows": completed_flows,
                "visited_urls": len(state.get("visited_urls", [])),
                "coverage_pct": coverage_pct,
                "llm_calls": state.get("llm_calls", 0),
                "estimated_cost": f"${state.get('estimated_cost', 0):.4f}",
            },
            "flows": flows,
            "test_results": test_results,
            "errors": state.get("errors", []),
            "duration": data.get("duration", 0),
            "visited_urls": state.get("visited_urls", []),
            "objectives": self._extract_objectives(state),
            "mutation_assertions": state.get("artifacts", {}).get("mutation_assertions", {}),
            # Diagnostic sections
            "failures": failures,
            "all_console_errors": all_console_errors,
            "all_network_failures": all_network_failures,
            "perf": perf,
        }

    def _build_failure_deep_dives(self, test_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build per-failure diagnostic objects with severity, reproduction path, and log excerpts."""
        failures = []
        total = len(test_results)
        for i, result in enumerate(test_results):
            if result.get("status") != "failed":
                continue

            step_num = result.get("step_number", i + 1)
            action = str(result.get("action") or "")

            # Severity heuristic: position + action type
            is_early = step_num <= max(3, total // 4)
            is_submit = any(k in action.lower() for k in ("submit", "navigate", "click"))
            if step_num == 1 or (is_early and is_submit):
                severity = "CRITICAL"
            elif step_num <= total // 2 or "submit" in action.lower():
                severity = "HIGH"
            else:
                severity = "MEDIUM"

            # Console errors/warnings captured during this step
            console_errors = [
                log for log in (result.get("console_logs") or [])
                if isinstance(log, dict)
                and str(log.get("level", "")).lower() in {"error", "warning", "warn"}
            ][:8]

            # Failed network requests (4xx/5xx responses) during this step
            network_failures = [
                req for req in (result.get("network_logs") or [])
                if isinstance(req, dict)
                and req.get("event") == "response"
                and int(req.get("status", 0)) >= 400
            ][:8]

            # Reproduction path: last 6 successful steps before this failure
            prior_success = [s for s in test_results[:i] if s.get("status") == "success"]
            repro_path = prior_success[-6:]

            failures.append({
                "bug_id": f"BUG-{len(failures) + 1:03d}",
                "severity": severity,
                "step_number": step_num,
                "action": action,
                "target": str(result.get("target") or "—"),
                "agent": str(result.get("agent") or "tester"),
                "error_message": str(result.get("error_message") or "Unknown error"),
                "console_errors": console_errors,
                "network_failures": network_failures,
                "repro_path": repro_path,
                "visuals": result.get("visuals") or {},
                "duration_ms": result.get("duration_ms"),
            })
        return failures

    def _aggregate_console_errors(self, test_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collect unique console errors and warnings across all steps."""
        seen: set = set()
        entries = []
        for result in test_results:
            for log in (result.get("console_logs") or []):
                if not isinstance(log, dict):
                    continue
                level = str(log.get("level", "")).lower()
                if level not in {"error", "warning", "warn"}:
                    continue
                msg = str(log.get("message", "")).strip()
                if not msg or msg in seen:
                    continue
                seen.add(msg)
                entries.append({
                    "step": result.get("step_number"),
                    "level": level,
                    "message": msg,
                    "timestamp": log.get("timestamp", ""),
                })
        return entries[:60]

    def _aggregate_network_failures(self, test_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collect unique 4xx/5xx responses across all steps."""
        seen: set = set()
        failures = []
        for result in test_results:
            for req in (result.get("network_logs") or []):
                if not isinstance(req, dict):
                    continue
                if req.get("event") != "response":
                    continue
                status = int(req.get("status", 0))
                if status < 400:
                    continue
                url = str(req.get("url", ""))
                key = f"{status}:{url}"
                if key in seen:
                    continue
                seen.add(key)
                failures.append({
                    "step": result.get("step_number"),
                    "method": req.get("method", "GET"),
                    "url": url,
                    "status": status,
                    "timestamp": req.get("timestamp", ""),
                })
        return failures[:40]

    def _build_perf_stats(self, test_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute performance stats: average, slowest steps, slow-step count."""
        threshold_ms = 3000
        timed = [r for r in test_results if r.get("duration_ms")]
        if not timed:
            return {"avg_ms": 0, "slowest": [], "slow_count": 0, "threshold_ms": threshold_ms}

        avg_ms = int(sum(r["duration_ms"] for r in timed) / len(timed))
        slowest = sorted(timed, key=lambda r: -(r.get("duration_ms") or 0))[:5]
        slow_count = sum(1 for r in timed if (r.get("duration_ms") or 0) >= threshold_ms)
        max_ms = max(r.get("duration_ms", 0) for r in slowest) if slowest else 1

        for r in slowest:
            r["_bar_pct"] = int(((r.get("duration_ms") or 0) / max(max_ms, 1)) * 100)

        return {
            "avg_ms": avg_ms,
            "slowest": slowest,
            "slow_count": slow_count,
            "threshold_ms": threshold_ms,
        }

    def _extract_objectives(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Pull objectives from state or from the nested config.objectives structure."""
        # Direct field (if ever stored on state)
        direct = state.get("objectives", [])
        if direct:
            return [o if isinstance(o, dict) else {"description": str(o)} for o in direct]
        # Nested under config.objectives.objectives
        cfg = state.get("config", {})
        obj_cfg = cfg.get("objectives", {}) if isinstance(cfg, dict) else {}
        if isinstance(obj_cfg, dict):
            items = obj_cfg.get("objectives", [])
        elif isinstance(obj_cfg, list):
            items = obj_cfg
        else:
            items = []
        return [o if isinstance(o, dict) else {"description": str(o)} for o in items]

    def _as_dict(self, value: Any) -> Dict[str, Any]:
        """Convert model-like objects to dictionaries for templating."""
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            try:
                return value.model_dump()
            except Exception:
                pass
        if hasattr(value, "dict"):
            try:
                return value.dict()
            except Exception:
                pass
        return {}

    def _normalize_visual_paths(self, visuals: Dict[str, Any]) -> Dict[str, Any]:
        """Convert local image paths into file URIs for report rendering."""
        normalized: Dict[str, Any] = {}
        image_fields = {
            "before_full",
            "before_crop",
            "after_full",
            "after_crop",
            "annotated_failure",
        }
        for key, value in visuals.items():
            if key in image_fields and isinstance(value, str) and value.strip():
                path = Path(value)
                if path.exists():
                    normalized[key] = path.resolve().as_uri()
                else:
                    normalized[key] = value
            else:
                normalized[key] = value
        return normalized

    def _get_css(self) -> str:
        """Get CSS styles for PDF."""
        return """
            @page {
                size: A4;
                margin: 2cm;
                @bottom-center {
                    content: "Page " counter(page) " of " counter(pages);
                    font-size: 9pt;
                    color: #666;
                }
            }
            
            * {
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                font-size: 11pt;
                line-height: 1.6;
                color: #333;
                margin: 0;
                padding: 0;
            }
            
            .cover {
                page-break-after: always;
                text-align: center;
                padding-top: 100px;
            }
            
            .cover h1 {
                font-size: 36pt;
                color: #2563eb;
                margin-bottom: 20px;
            }
            
            .cover .subtitle {
                font-size: 16pt;
                color: #666;
                margin-bottom: 40px;
            }
            
            .cover .metadata {
                font-size: 11pt;
                color: #999;
            }
            
            h1 {
                font-size: 24pt;
                color: #2563eb;
                border-bottom: 2px solid #2563eb;
                padding-bottom: 10px;
                margin-top: 30px;
            }
            
            h2 {
                font-size: 18pt;
                color: #333;
                margin-top: 25px;
            }
            
            h3 {
                font-size: 14pt;
                color: #555;
                margin-top: 20px;
            }
            
            .metrics-grid {
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                margin: 20px 0;
            }
            
            .metric-card {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 15px;
                min-width: 150px;
                text-align: center;
            }
            
            .metric-value {
                font-size: 24pt;
                font-weight: bold;
                color: #2563eb;
            }
            
            .metric-label {
                font-size: 10pt;
                color: #666;
                text-transform: uppercase;
            }
            
            .coverage-bar {
                background: #e2e8f0;
                border-radius: 4px;
                height: 20px;
                margin: 10px 0;
            }
            
            .coverage-fill {
                background: linear-gradient(90deg, #2563eb, #10b981);
                border-radius: 4px;
                height: 100%;
            }
            
            table {
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
                font-size: 10pt;
            }
            
            th, td {
                border: 1px solid #e2e8f0;
                padding: 8px;
                text-align: left;
            }
            
            th {
                background: #f8fafc;
                font-weight: 600;
                color: #333;
            }
            
            tr:nth-child(even) {
                background: #f8fafc;
            }
            
            .status-success {
                color: #10b981;
                font-weight: 600;
            }
            
            .status-failed {
                color: #ef4444;
                font-weight: 600;
            }
            
            .status-pending {
                color: #f59e0b;
            }
            
            .flow-diagram {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 15px;
                margin: 15px 0;
                font-family: monospace;
                font-size: 9pt;
            }
            
            .error-box {
                background: #fef2f2;
                border: 1px solid #fecaca;
                border-radius: 4px;
                padding: 10px;
                margin: 10px 0;
                color: #991b1b;
            }
            
            .screenshot {
                max-width: 100%;
                border: 1px solid #e2e8f0;
                border-radius: 4px;
                margin: 10px 0;
            }
            
            .step-detail {
                background: #f8fafc;
                border-left: 4px solid #2563eb;
                padding: 10px 15px;
                margin: 10px 0;
            }
            
            .page-break {
                page-break-before: always;
            }
        """
