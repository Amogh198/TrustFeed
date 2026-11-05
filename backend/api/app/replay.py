"""Offline replay scenarios used by the demo without live network dependencies."""

import json
from pathlib import Path

from pydantic import HttpUrl

from backend.api.app.models import ReplayScenario

_SCENARIOS_PATH = Path(__file__).parent / "fixtures" / "replay_scenarios.json"


class ReplayInput(ReplayScenario):
    text: str
    url: HttpUrl | None = None


def load_scenarios() -> list[ReplayInput]:
    return [ReplayInput.model_validate(item) for item in json.loads(_SCENARIOS_PATH.read_text(encoding="utf-8"))]


def list_scenarios() -> list[ReplayScenario]:
    return [ReplayScenario.model_validate(item) for item in load_scenarios()]


def get_scenario(scenario_id: str) -> ReplayInput | None:
    return next((item for item in load_scenarios() if item.id == scenario_id), None)
