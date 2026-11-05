"""Public functions for the API lane. Unknown cases return None, never demo data."""

import copy
from functools import lru_cache
from typing import Any

from backend.network.analysis import NetworkAnalysis, analyze_network
from backend.network.dataset import load_dataset

DEMO_CASE_ID = "demo-001"


@lru_cache(maxsize=1)
def _demo_analysis() -> NetworkAnalysis:
    return analyze_network(load_dataset())


def get_network_payload(case_id: str) -> dict[str, list[dict[str, Any]]] | None:
    """Return ``{nodes, edges, timeline}``, or None when the case has no network data."""
    if case_id != DEMO_CASE_ID:
        return None
    return copy.deepcopy(_demo_analysis().payload())


def get_network_module_result(case_id: str) -> dict[str, Any] | None:
    """Return a dict of ``ModuleResult`` fields, or None when the case has no network data."""
    if case_id != DEMO_CASE_ID:
        return None
    return copy.deepcopy(_demo_analysis().module_result)


def get_network_clusters(case_id: str) -> list[dict[str, Any]] | None:
    """Return per-cluster scores and components for an evidence or detail view."""
    if case_id != DEMO_CASE_ID:
        return None
    return copy.deepcopy(_demo_analysis().clusters)
