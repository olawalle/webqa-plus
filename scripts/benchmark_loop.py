#!/usr/bin/env python3
"""Benchmark-driven iterative QA loop for multiple independent targets."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class Metrics:
    coverage_pct: float
    success_rate_pct: float
    flows_completed: int
    report_file: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run benchmark loops across targets.")
    parser.add_argument(
        "--config",
        default="benchmarks/benchmarks.yaml",
        help="Path to benchmark config YAML",
    )
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root (defaults to current directory)",
    )
    return parser.parse_args()


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)


def latest_report_for_target(reports_dir: Path, target_url: str, started_at: datetime) -> Optional[Path]:
    html_reports = sorted(reports_dir.glob("report_*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    for report in html_reports:
        if datetime.fromtimestamp(report.stat().st_mtime) < started_at:
            continue
        text = report.read_text(encoding="utf-8", errors="ignore")
        if target_url in text:
            return report
    return None


def extract_metrics(report_path: Path) -> Metrics:
    text = report_path.read_text(encoding="utf-8", errors="ignore")

    def first_float(pattern: str, default: float = 0.0) -> float:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        return float(match.group(1)) if match else default

    def first_int(pattern: str, default: int = 0) -> int:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        return int(match.group(1)) if match else default

    coverage = first_float(r"Overall test coverage:\s*([0-9]+(?:\.[0-9]+)?)%")
    success_rate = first_float(r"<td>\s*Success Rate\s*</td>\s*<td>\s*([0-9]+(?:\.[0-9]+)?)%\s*</td>")
    flows_completed = first_int(r"<td>\s*Flows Completed\s*</td>\s*<td>\s*([0-9]+)\s*</td>")

    return Metrics(
        coverage_pct=coverage,
        success_rate_pct=success_rate,
        flows_completed=flows_completed,
        report_file=report_path.name,
    )


def evaluate(metrics: Metrics, benchmarks: Dict[str, Any]) -> Dict[str, bool]:
    checks = {
        "coverage": metrics.coverage_pct >= float(benchmarks.get("min_coverage_pct", 0)),
        "success_rate": metrics.success_rate_pct >= float(benchmarks.get("min_success_rate_pct", 0)),
        "flows_completed": metrics.flows_completed >= int(benchmarks.get("min_flows_completed", 0)),
    }
    return checks


def improve_tuning(tuning: Dict[str, Any], iteration: int) -> Dict[str, Any]:
    next_tuning = dict(tuning)
    boost = int(next_tuning.get("path_discovery_boost", 1) or 1)
    next_tuning["path_discovery_boost"] = min(5, boost + 1)
    next_tuning["deep_traversal"] = True
    next_tuning["hidden_menu_expander"] = True
    next_tuning["form_validation_pass"] = True
    if iteration >= 2 and "email_verification_enabled" in next_tuning:
        next_tuning["email_verification_enabled"] = True
    return next_tuning


def plan_from_failures(target_id: str, checks: Dict[str, bool], metrics: Metrics, benchmarks: Dict[str, Any]) -> List[str]:
    plan: List[str] = []
    if not checks["coverage"]:
        plan.append(
            f"Increase exploration depth to improve coverage from {metrics.coverage_pct:.1f}% toward {float(benchmarks.get('min_coverage_pct', 0)):.1f}%."
        )
    if not checks["success_rate"]:
        plan.append(
            f"Prioritize flaky-step stabilization to raise success rate from {metrics.success_rate_pct:.1f}% toward {float(benchmarks.get('min_success_rate_pct', 0)):.1f}%."
        )
    if not checks["flows_completed"]:
        plan.append(
            f"Bias navigation toward end-to-end completion; flows completed is {metrics.flows_completed} but target is {int(benchmarks.get('min_flows_completed', 0))}."
        )
    if not plan:
        plan.append("Maintain current tuning and run a confirmation pass for regression confidence.")
    return [f"[{target_id}] {item}" for item in plan]


def run_target_loop(workspace: Path, target_cfg: Dict[str, Any], summary_lines: List[str]) -> None:
    target_id = str(target_cfg["id"])
    target_url = str(target_cfg["url"])
    mode = str(target_cfg.get("mode", "stealth"))
    objectives = str(target_cfg["objectives"])
    benchmarks = target_cfg.get("benchmarks", {})
    run_cfg = target_cfg.get("run", {})
    output_dir = str(run_cfg.get("output_dir", "./reports"))
    max_iterations = int(run_cfg.get("max_iterations", 1))
    max_steps = int(run_cfg.get("initial_max_steps", 80))
    tuning = dict(run_cfg.get("tuning", {}))

    plans_root = workspace / "benchmarks" / "plans"
    plans_root.mkdir(parents=True, exist_ok=True)

    summary_lines.append(f"## {target_id}")
    summary_lines.append(f"- URL: {target_url}")
    summary_lines.append(f"- Benchmarks: {benchmarks}")

    satisfied = False
    for iteration in range(1, max_iterations + 1):
        tune_path = workspace / "benchmarks" / f"runtime.{target_id}.iteration{iteration}.yaml"
        write_yaml(
            tune_path,
            {
                "testing": tuning,
            },
        )

        started_at = datetime.now()
        command = [
            "uv",
            "run",
            "python",
            "-m",
            "webqa_plus.cli",
            "test",
            "--url",
            target_url,
            "--mode",
            mode,
            "--max-steps",
            str(max_steps),
            "--objectives",
            objectives,
            "--config",
            str(tune_path.relative_to(workspace)),
            "--output-dir",
            output_dir,
        ]

        process = subprocess.run(command, cwd=str(workspace), capture_output=True, text=True)
        stdout_tail = "\n".join(process.stdout.splitlines()[-12:])
        stderr_tail = "\n".join(process.stderr.splitlines()[-12:])

        reports_path = (workspace / output_dir).resolve()
        report = latest_report_for_target(reports_path, target_url, started_at)
        if process.returncode != 0 or not report:
            summary_lines.append(f"- Iteration {iteration}: run failed (exit={process.returncode})")
            if stdout_tail:
                summary_lines.append(f"  - stdout tail: {stdout_tail}")
            if stderr_tail:
                summary_lines.append(f"  - stderr tail: {stderr_tail}")

            failure_actions: List[str] = []
            failure_blob = f"{stdout_tail}\n{stderr_tail}".lower()
            if "name_not_resolved" in failure_blob or "dns" in failure_blob:
                failure_actions.append(
                    f"[{target_id}] Infrastructure failure (DNS resolution). Validate environment/network reachability to {target_url} before next rerun."
                )
            if "timeout" in failure_blob:
                failure_actions.append(
                    f"[{target_id}] Navigation timeout observed. Increase timeout/max_steps and favor stealth mode for stabilization rerun."
                )
            if not failure_actions:
                failure_actions.append(
                    f"[{target_id}] Capture additional diagnostics (console/network tails) and rerun with increased step budget."
                )

            plan_file = plans_root / f"{target_id}.iteration{iteration}.md"
            plan_file.write_text(
                "\n".join(
                    [
                        f"# Improvement Plan - {target_id} Iteration {iteration}",
                        "",
                        "## Result vs Benchmark",
                        "- Run status: FAILED",
                        f"- Exit code: {process.returncode}",
                        f"- Coverage: N/A",
                        f"- Success Rate: N/A",
                        f"- Flows Completed: N/A",
                        "",
                        "## Next Actions",
                        *[f"- {item}" for item in failure_actions],
                    ]
                ),
                encoding="utf-8",
            )
            summary_lines.append(f"  - plan: {plan_file.relative_to(workspace)}")

            tuning = improve_tuning(tuning, iteration)
            max_steps = min(220, max_steps + 30)
            continue

        metrics = extract_metrics(report)
        checks = evaluate(metrics, benchmarks)
        all_ok = all(checks.values())

        summary_lines.append(
            f"- Iteration {iteration}: coverage={metrics.coverage_pct:.1f}% success={metrics.success_rate_pct:.1f}% flows_completed={metrics.flows_completed} report={metrics.report_file}"
        )

        plan_items = plan_from_failures(target_id, checks, metrics, benchmarks)
        plan_file = plans_root / f"{target_id}.iteration{iteration}.md"
        plan_file.write_text(
            "\n".join([
                f"# Improvement Plan - {target_id} Iteration {iteration}",
                "",
                "## Result vs Benchmark",
                f"- Coverage: {metrics.coverage_pct:.1f}%",
                f"- Success Rate: {metrics.success_rate_pct:.1f}%",
                f"- Flows Completed: {metrics.flows_completed}",
                f"- Checks: {checks}",
                "",
                "## Next Actions",
                *[f"- {item}" for item in plan_items],
            ]),
            encoding="utf-8",
        )

        summary_lines.append(f"  - plan: {plan_file.relative_to(workspace)}")

        if all_ok:
            satisfied = True
            summary_lines.append(f"- Status: benchmark satisfied at iteration {iteration}")
            break

        tuning = improve_tuning(tuning, iteration)
        max_steps = min(220, max_steps + 25)

    if not satisfied:
        summary_lines.append("- Status: benchmark not satisfied within max iterations; continue with generated plans.")


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    cfg_path = (workspace / args.config).resolve()
    cfg = load_yaml(cfg_path)
    targets = cfg.get("targets", [])
    if not targets:
        print("No targets configured in benchmark file.")
        return 1

    summary_lines: List[str] = [
        "# Benchmark Loop Summary",
        "",
        f"Generated: {datetime.now().isoformat()}",
        "",
    ]

    for target in targets:
        run_target_loop(workspace, target, summary_lines)
        summary_lines.append("")

    out = workspace / "benchmarks" / "latest_benchmark_summary.md"
    out.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"Benchmark summary written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
