"""Dissemination-network analysis: how content spread, not whether it is authentic."""

from backend.network.analysis import NetworkAnalysis, analyze_network
from backend.network.checks import build_network_checks
from backend.network.config import CoordinationConfig
from backend.network.dataset import Dataset, load_dataset, parse_dataset
from backend.network.monitor import Monitor
from backend.network.service import (
    DEMO_CASE_ID,
    get_network_checks,
    get_network_clusters,
    get_network_coverage,
    get_network_module_result,
    get_network_payload,
    get_network_tests,
    trace_case,
)
from backend.network.story import DEMO_STORY_CASE_ID, get_demo_story
from backend.network.trace import TraceResult, trace_public_spread
from backend.network.watches import (
    WatchError,
    list_watches,
    poll_watch,
    start_watch,
    stop_watch,
)

__all__ = [
    "DEMO_CASE_ID",
    "DEMO_STORY_CASE_ID",
    "CoordinationConfig",
    "Dataset",
    "Monitor",
    "NetworkAnalysis",
    "TraceResult",
    "WatchError",
    "analyze_network",
    "build_network_checks",
    "get_demo_story",
    "get_network_checks",
    "get_network_clusters",
    "get_network_coverage",
    "get_network_module_result",
    "get_network_payload",
    "get_network_tests",
    "list_watches",
    "load_dataset",
    "parse_dataset",
    "poll_watch",
    "start_watch",
    "stop_watch",
    "trace_case",
    "trace_public_spread",
]
