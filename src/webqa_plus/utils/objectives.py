"""Custom objectives loading utilities."""

from pathlib import Path
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel


class Objective(BaseModel):
    """A single testing objective."""

    name: str
    description: str
    critical_paths: List[List[str]] = []
    required_elements: List[str] = []
    priority: int = 1


class ObjectivesConfig(BaseModel):
    """Collection of testing objectives."""

    objectives: List[Objective]


def directive_to_objectives(instruction: str) -> Dict[str, Any]:
    """Convert free text directive into internal objectives structure."""
    text = instruction.strip()
    return {
        "objectives": [
            {
                "name": "User directed objective",
                "description": text,
                "critical_paths": [],
                "required_elements": [],
                "priority": 1,
                # Do NOT set strict=False here — _objective_is_strict() uses the
                # name-based fallback ("user directed objective" → True) to enable
                # strict focus mode for user instructions.
                "dynamic": True,
            }
        ]
    }


def load_objectives(path: Path) -> Dict[str, Any]:
    """Load custom testing objectives from YAML file."""
    with open(path, "r") as f:
        data = yaml.safe_load(f)

    config = ObjectivesConfig(**data)
    return {"objectives": [obj.model_dump() for obj in config.objectives]}
