"""Public functions for the API lane. Unknown cases return None, never demo data."""

import copy
import threading
from collections import OrderedDict
from functools import lru_cache
from typing import Any

from backend.network.analysis import NetworkAnalysis, analyze_network
from backend.network.dataset import load_dataset
from backend.network.trace import TraceResult, trace_public_spread

DEMO_CASE_ID = "demo-001"
# Traced cases live in memory, like T3's cases, and the oldest are dropped first.
_MAX_TRACED_CASES = 128

_traced: OrderedDict[str, TraceResult] = OrderedDict()
_traced_lock = threading.Lock()


@lru_cache(maxsize=1)
def _demo_analysis() -> NetworkAnalysis:
    return analyze_network(load_dataset())


def _traced_case(case_id: str) -> TraceResult | None:
    with _traced_lock:
        return _traced.get(case_id)


def _analysis(case_id: str) -> NetworkAnalysis | None:
    if case_id == DEMO_CASE_ID:
        return _demo_analysis()
    traced = _traced_case(case_id)
    return traced.analysis if traced else None


def trace_case(case_id: str, **submission: Any) -> dict[str, Any]:
    """Trace a submitted case's public spread and keep the result for the getters below.

    Takes the arguments of ``trace_public_spread``. This reads live platforms by
    default and can take up to about 25 seconds, so call it outside a request's hot path.
    """
    if case_id == DEMO_CASE_ID:
        raise ValueError(f"{DEMO_CASE_ID} is reserved for the synthetic demo")
    result = trace_public_spread(case_id, **submission)
    with _traced_lock:
        _traced[case_id] = result
        _traced.move_to_end(case_id)
        while len(_traced) > _MAX_TRACED_CASES:
            _traced.popitem(last=False)
    return copy.deepcopy(result.module_result)


def get_network_payload(case_id: str) -> dict[str, list[dict[str, Any]]] | None:
    """Return ``{nodes, edges, timeline}``, or None when the case has no network data."""
    analysis = _analysis(case_id)
    return copy.deepcopy(analysis.payload()) if analysis else None


def get_network_module_result(case_id: str) -> dict[str, Any] | None:
    """Return a dict of ``ModuleResult`` fields, or None when the case has no network data."""
    traced = _traced_case(case_id)
    if traced:
        return copy.deepcopy(traced.module_result)
    return copy.deepcopy(_demo_analysis().module_result) if case_id == DEMO_CASE_ID else None


def get_network_clusters(case_id: str) -> list[dict[str, Any]] | None:
    """Return per-cluster scores and components for an evidence or detail view."""
    analysis = _analysis(case_id)
    return copy.deepcopy(analysis.clusters) if analysis else None


def get_network_coverage(case_id: str) -> dict[str, Any] | None:
    """Return what was searched, what wasn't and the found posts in order, for a traced case."""
    traced = _traced_case(case_id)
    return copy.deepcopy(traced.coverage) if traced else None
