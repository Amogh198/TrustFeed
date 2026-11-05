"""Dissemination-network analysis: how content spread, not whether it is authentic."""

from backend.network.analysis import NetworkAnalysis, analyze_network
from backend.network.config import CoordinationConfig
from backend.network.dataset import Dataset, load_dataset, parse_dataset
from backend.network.service import (
    DEMO_CASE_ID,
    get_network_clusters,
    get_network_coverage,
    get_network_module_result,
    get_network_payload,
    trace_case,
)
from backend.network.trace import TraceResult, trace_public_spread

__all__ = [
    "DEMO_CASE_ID",
    "CoordinationConfig",
    "Dataset",
    "NetworkAnalysis",
    "TraceResult",
    "analyze_network",
    "get_network_clusters",
    "get_network_coverage",
    "get_network_module_result",
    "get_network_payload",
    "load_dataset",
    "parse_dataset",
    "trace_case",
    "trace_public_spread",
]
