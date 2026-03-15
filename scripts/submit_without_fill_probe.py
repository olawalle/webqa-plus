from webqa_plus.core.agents import TesterAgent


agent = TesterAgent(
    {
        "llm": {"provider": "gemini", "api_key": "", "model": "gemini-2.0-flash"},
        "testing": {},
    }
)

generated_user = {
    "email": "qa@example.com",
    "password": "StrongPass123!",
    "first_name": "QA",
    "last_name": "Tester",
    "full_name": "QA Tester",
    "phone": "+12025550123",
}

def assert_pre_submit_fills_required_select_first() -> None:
    actions = [
        {
            "type": "click",
            "selector": "button[type='submit']",
            "description": "submit",
            "in_dialog": True,
        },
        {
            "type": "select",
            "selector": "#country",
            "description": "country",
            "required": True,
            "aria_invalid": "true",
            "in_dialog": True,
        },
        {
            "type": "type",
            "selector": "#email",
            "description": "email",
            "required": True,
            "in_dialog": True,
        },
    ]

    action_plan = {
        "action_type": "click",
        "target": "button[type='submit']",
        "value": "submit",
    }

    candidate = agent._build_pre_submit_fill_action(actions, action_plan, generated_user, {})
    assert candidate is not None, "Expected pre-submit guard action, got None"
    assert candidate["action_type"] == "select", (
        "Expected required select to be handled before submit; "
        f"got {candidate}"
    )
    assert candidate["target"] == "#country", f"Unexpected select target: {candidate}"


def assert_pre_submit_fills_likely_required_text_when_required_flags_missing() -> None:
    actions = [
        {
            "type": "click",
            "selector": "button[type='submit']",
            "description": "submit",
            "in_dialog": False,
        },
        {
            "type": "type",
            "selector": "#full_name",
            "description": "Full Name",
            "required": False,
            "aria_invalid": "",
            "in_dialog": False,
        },
    ]

    action_plan = {
        "action_type": "click",
        "target": "button[type='submit']",
        "value": "submit",
    }

    candidate = agent._build_pre_submit_fill_action(actions, action_plan, generated_user, {})
    assert candidate is not None, "Expected fallback pre-submit fill action, got None"
    assert candidate["action_type"] == "type", f"Expected type action, got {candidate}"
    assert candidate["target"] == "#full_name", f"Unexpected type target: {candidate}"
    assert candidate["value"] == generated_user["full_name"], (
        "Expected generated full name for likely required name field; "
        f"got {candidate}"
    )


def assert_validation_exploration_gate() -> None:
    assert agent._should_run_validation_exploration("Create and submit a profile form") is False, (
        "Validation exploration should be OFF for normal submit objectives"
    )
    assert agent._should_run_validation_exploration("Verify invalid input validation errors") is True, (
        "Validation exploration should be ON for explicit validation objectives"
    )


if __name__ == "__main__":
    assert_pre_submit_fills_required_select_first()
    assert_pre_submit_fills_likely_required_text_when_required_flags_missing()
    assert_validation_exploration_gate()
    print("submit_without_fill_probe: PASS")
