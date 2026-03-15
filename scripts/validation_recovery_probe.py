from webqa_plus.core.agents import TesterAgent


agent = TesterAgent(
    {
        "llm": {"provider": "gemini", "api_key": "", "model": "gemini-2.0-flash"},
        "testing": {},
    }
)
state = {"current_url": "https://app.example.com/records"}
store = {
    "https://app.example.com/records": {
        "stage": 3,
        "active": True,
        "invalid_done": True,
        "valid_done": False,
        "filled_targets": ["sel-1"],
        "clicked_targets": ["btn-1"],
        "modal_submit_failures": 0,
        "validation_retry_round": 0,
    }
}

agent._update_form_validation_state(
    state,
    {"form_stage": "modal_submit", "target": "submit"},
    {"success": False},
    store,
)
entry = store["https://app.example.com/records"]
print(
    "stage",
    entry["stage"],
    "failures",
    entry["modal_submit_failures"],
    "filled",
    entry["filled_targets"],
    "clicked",
    entry["clicked_targets"],
)
print(
    "validation_signal",
    agent._has_validation_error_signal(
        [
            {"text": "records[1].id is a required field", "type": "click", "in_dialog": True},
            {"type": "select", "required": True, "in_dialog": True, "selector": "#record-2"},
        ]
    ),
)
