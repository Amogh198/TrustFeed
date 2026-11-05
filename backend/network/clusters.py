"""Community detection and the Coordination Risk Score."""

import statistics
from dataclasses import dataclass, replace

import networkx as nx

from backend.network.config import CoordinationConfig
from backend.network.coshare import CoShare

# Published in the README and exposed per cluster so that a score can be explained.
SCORE_WEIGHTS = {
    "temporal_tightness": 0.30,
    "identical_text": 0.20,
    "shared_media": 0.20,
    "density": 0.15,
    "repetition": 0.15,
}
# Mean distinct items per pair at which the repetition component reaches 1.0.
_REPETITION_SATURATION = 4


@dataclass(frozen=True)
class Cluster:
    id: str
    members: tuple[str, ...]
    score: float
    components: dict[str, float]
    risk_level: str
    flagged: bool
    item_keys: frozenset[tuple[str, str]]
    distinct_items: int
    median_delay_seconds: float


def build_coordination_graph(
    co_shares: dict[tuple[str, str], CoShare], config: CoordinationConfig
) -> nx.Graph:
    """Build a graph of only those pairs with repeated co-sharing."""
    graph = nx.Graph()
    for key in sorted(co_shares):
        pair = co_shares[key]
        if pair.distinct_items >= config.min_shared_items:
            graph.add_edge(pair.source, pair.target, weight=pair.distinct_items)
    return graph


def _score_components(
    subgraph: nx.Graph, edges: list[CoShare], config: CoordinationConfig
) -> dict[str, float]:
    median_delay = statistics.median(pair.median_delay for pair in edges)
    mean_items = statistics.fmean(pair.distinct_items for pair in edges)
    return {
        "temporal_tightness": max(0.0, 1 - median_delay / config.window_seconds),
        "identical_text": sum(1 for pair in edges if pair.items["text"]) / len(edges),
        "shared_media": sum(1 for pair in edges if pair.items["media"]) / len(edges),
        "density": nx.density(subgraph),
        "repetition": min(1.0, (mean_items - 1) / (_REPETITION_SATURATION - 1)),
    }


def _risk_level(score: float, size: int, config: CoordinationConfig) -> str:
    if size < config.min_cluster_size:
        return "inconclusive"
    if score < 0.35:
        return "low"
    if score < 0.55:
        return "moderate"
    if score < 0.75:
        return "high"
    return "critical"


def detect_clusters(
    graph: nx.Graph, co_shares: dict[tuple[str, str], CoShare], config: CoordinationConfig
) -> list[Cluster]:
    """Split the coordination graph into scored clusters, strongest first."""
    if graph.number_of_edges() == 0:
        return []

    communities = nx.community.louvain_communities(
        graph, weight="weight", resolution=config.louvain_resolution, seed=config.louvain_seed
    )
    clusters = []
    for community in communities:
        subgraph = graph.subgraph(community)
        edges = [co_shares[tuple(sorted(edge))] for edge in subgraph.edges]
        if not edges:
            continue  # An isolated node has no co-shares to score.
        components = _score_components(subgraph, edges, config)
        score = round(sum(SCORE_WEIGHTS[name] * value for name, value in components.items()), 4)
        size = len(community)
        clusters.append(
            Cluster(
                id="",  # Numbered below, once the final order is known.
                members=tuple(sorted(community)),
                score=score,
                components={name: round(value, 4) for name, value in components.items()},
                risk_level=_risk_level(score, size, config),
                flagged=size >= config.min_cluster_size and score >= config.flag_score_threshold,
                item_keys=frozenset(key for pair in edges for key in pair.item_keys()),
                distinct_items=max(pair.distinct_items for pair in edges),
                median_delay_seconds=statistics.median(pair.median_delay for pair in edges),
            )
        )

    clusters.sort(key=lambda item: (not item.flagged, -item.score, -len(item.members), item.members[0]))
    return [
        replace(cluster, id=f"cluster_{index:02d}") for index, cluster in enumerate(clusters, start=1)
    ]
