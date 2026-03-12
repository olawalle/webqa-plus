"""PDF report generator using WeasyPrint."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader

from webqa_plus.utils.config import AppConfig


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

        # Calculate metrics
        total_steps = len(test_results)
        successful_steps = len([s for s in test_results if s.get("status") == "success"])
        failed_steps = len([s for s in test_results if s.get("status") == "failed"])

        total_flows = len(flows)
        completed_flows = len([f for f in flows if f.get("status") == "completed"])

        coverage_pct = 0.0
        if total_steps > 0:
            coverage_pct = (successful_steps / total_steps) * 100

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
        }

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
