# Benchmark Loop Summary

Generated: 2026-03-11T19:58:25.458063

## busha_staging
- URL: https://staging.dash.busha.io/
- Benchmarks: {'min_coverage_pct': 50, 'min_success_rate_pct': 50, 'min_flows_completed': 1}
- Iteration 1: run failed (exit=1)
  - stdout tail: ╭─────────── Starting Test Session ───────────╮
│ 🧪 WebQA-Plus - Autonomous AI Web QA Tester │
│ Target: https://staging.dash.busha.io/      │
│ Mode: STEALTH                               │
│ Max Steps: 110                              │
╰─────────────────────────────────────────────╯

✗ Test failed: Timeout 30000ms exceeded.
⠦ Running test session...

Error: Timeout 30000ms exceeded.
  - stderr tail: <frozen runpy>:128: RuntimeWarning: 'webqa_plus.cli' found in sys.modules after import of package 'webqa_plus', but prior to execution of 'webqa_plus.cli'; this may result in unpredictable behaviour
  - plan: benchmarks/plans/busha_staging.iteration1.md
- Iteration 2: run failed (exit=1)
  - stdout tail: ╭─────────── Starting Test Session ───────────╮
│ 🧪 WebQA-Plus - Autonomous AI Web QA Tester │
│ Target: https://staging.dash.busha.io/      │
│ Mode: STEALTH                               │
│ Max Steps: 140                              │
╰─────────────────────────────────────────────╯

✗ Test failed: Timeout 30000ms exceeded.
⠙ Running test session...

Error: Timeout 30000ms exceeded.
  - stderr tail: <frozen runpy>:128: RuntimeWarning: 'webqa_plus.cli' found in sys.modules after import of package 'webqa_plus', but prior to execution of 'webqa_plus.cli'; this may result in unpredictable behaviour
  - plan: benchmarks/plans/busha_staging.iteration2.md
- Iteration 3: coverage=50.0% success=50.0% flows_completed=1 report=report_20260311_200111.html
  - plan: benchmarks/plans/busha_staging.iteration3.md
- Status: benchmark satisfied at iteration 3

## aptlyflow_app
- URL: https://app.aptlyflow.xyz
- Benchmarks: {'min_coverage_pct': 95, 'min_success_rate_pct': 95, 'min_flows_completed': 1}
- Iteration 1: coverage=100.0% success=100.0% flows_completed=1 report=report_20260311_200200.html
  - plan: benchmarks/plans/aptlyflow_app.iteration1.md
- Status: benchmark satisfied at iteration 1
