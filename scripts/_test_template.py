"""Quick template sanity check."""
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader("src/webqa_plus/reporter"))
env.filters["format_datetime"] = lambda dt: str(dt)
tpl = env.get_template("template.html.j2")

html = tpl.render(
    title="Test",
    generated_at=datetime.now(),
    duration=10.5,
    config={"testing": {"url": "https://example.com", "mode": "standard"}},
    metrics=dict(
        total_steps=5, successful_steps=4, failed_steps=1, success_rate="80%",
        total_flows=1, completed_flows=1, visited_urls=3, coverage_pct=80.0,
        llm_calls=12, estimated_cost="$0.0012",
    ),
    objectives=[{"name": "signup", "description": "Sign up for a new account", "priority": 1}],
    visited_urls=["https://example.com", "https://example.com/signup"],
    flows=[],
    test_results=[{
        "step_number": 1, "agent": "tester", "action": "click",
        "target": "btn", "status": "success", "error_message": None,
        "visuals": None, "duration_ms": 120,
    }],
    errors=[],
    mutation_assertions={
        "required_entities": ["business"],
        "detected_entities": ["business"],
        "checked_submits": 1,
    },
)
print("Template OK, length:", len(html))
