"""Run the full analysis and shape its output for the API and dashboard."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from backend.network.clusters import (
    SCORE_WEIGHTS,
    Cluster,
    build_coordination_graph,
    detect_clusters,
)
from backend.network.config import CoordinationConfig
from backend.network.coshare import CoShare, find_co_shares
from backend.network.dataset import Dataset, format_timestamp
from backend.network.roles import (
    ROLE_LABELS,
    AccountRole,
    Origin,
    assign_roles,
    campaign_posts,
)
from backend.network.timeline import build_timeline

SYNTHETIC_NOTICE = (
    "SYNTHETIC DEMO DATA: simulated accounts and posts. "
    "This is not evidence of real-world activity by any person or group."
)
_BASE_LIMITATIONS = [
    "The Coordination Risk Score is a heuristic, not a calibrated probability.",
    "This module measures how content spread, not whether the content is authentic or false.",
    "Co-sharing does not establish intent, common control, automation or attribution.",
    "Earliest observed means earliest in this dataset, which may not be the true origin.",
    (
        "Only exact media hashes and normalized text are compared, so paraphrases and "
        "re-encoded media are missed."
    ),
]


@dataclass(frozen=True)
class NetworkAnalysis:
    case_id: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    module_result: dict[str, Any]

    def payload(self) -> dict[str, list[dict[str, Any]]]:
        """Return the ``GET /api/network/{case_id}`` body from API_CONTRACTS.md."""
        return {"nodes": self.nodes, "edges": self.edges, "timeline": self.timeline}


def _build_nodes(
    dataset: Dataset,
    roles: dict[str, AccountRole],
    clusters: list[Cluster],
    edges: list[dict[str, Any]],
    config: CoordinationConfig,
) -> list[dict[str, Any]]:
    first_post: dict[str, str] = {}
    post_counts: dict[str, int] = defaultdict(int)
    platforms: dict[str, set[str]] = defaultdict(set)
    for post in dataset.posts:
        first_post.setdefault(post.account_id, format_timestamp(post.created_at))
        post_counts[post.account_id] += 1
        if post.platform:
            platforms[post.account_id].add(post.platform)

    in_campaign = {
        post.id
        for cluster in clusters
        if cluster.flagged
        for post in campaign_posts(dataset.posts, cluster, config)
    }
    first_campaign_post: dict[str, str] = {}
    for post in dataset.posts:  # In time order, so the first one seen is the earliest.
        if post.on_topic or post.id in in_campaign:
            first_campaign_post.setdefault(post.account_id, format_timestamp(post.created_at))

    # A node must be on the slider by the time any of its edges is. This also places
    # targets, which are mentioned but may never post. UTC ISO strings sort by time.
    appears_at = dict(first_campaign_post)
    for edge in edges:
        for endpoint in (edge["source"], edge["target"]):
            current = appears_at.get(endpoint)
            if current is None or edge["first_seen_at"] < current:
                appears_at[endpoint] = edge["first_seen_at"]

    flagged_ids = {cluster.id for cluster in clusters if cluster.flagged}
    nodes = []
    for account in sorted(dataset.accounts, key=lambda item: item.id):
        role = roles.get(account.id, AccountRole())
        nodes.append(
            {
                "id": account.id,
                "handle": account.handle,
                "followers": account.followers,
                "role": role.role,
                "role_label": ROLE_LABELS[role.role],
                "cluster_id": role.cluster_id,
                "in_flagged_cluster": role.cluster_id in flagged_ids,
                "degree_centrality": role.degree_centrality,
                "weighted_degree": role.weighted_degree,
                "post_count": post_counts[account.id],
                "platforms": sorted(platforms[account.id]),
                "first_post_at": first_post.get(account.id),
                "first_campaign_post_at": first_campaign_post.get(account.id),
                "appears_at": appears_at.get(account.id),
                "synthetic": dataset.synthetic,
            }
        )
    return nodes


def _build_edges(
    dataset: Dataset,
    co_shares: dict[tuple[str, str], CoShare],
    clusters: list[Cluster],
    config: CoordinationConfig,
) -> list[dict[str, Any]]:
    cluster_of = {member: cluster.id for cluster in clusters for member in cluster.members}
    edges = []
    for key in sorted(co_shares):
        pair = co_shares[key]
        repeated = pair.distinct_items >= config.min_shared_items
        same_cluster = repeated and cluster_of.get(pair.source) == cluster_of.get(pair.target)
        edges.append(
            {
                "id": f"{'co_share' if repeated else 'weak_co_share'}:{pair.source}|{pair.target}",
                "source": pair.source,
                "target": pair.target,
                "type": "co_share" if repeated else "weak_co_share",
                "weight": pair.distinct_items,
                "signals": pair.signal_counts,
                "platforms": sorted(pair.platforms),
                "cross_platform": len(pair.platforms) > 1,
                "min_delay_seconds": pair.min_delay,
                "median_delay_seconds": pair.median_delay,
                "first_seen_at": format_timestamp(pair.first_seen_at),
                "cluster_id": cluster_of.get(pair.source) if same_cluster else None,
                "synthetic": dataset.synthetic,
            }
        )

    mentions: dict[tuple[str, str], list[str]] = defaultdict(list)
    for post in dataset.posts:
        for account_id in post.mentions:
            if account_id != post.account_id:
                mentions[(post.account_id, account_id)].append(format_timestamp(post.created_at))
    for (source, target), times in sorted(mentions.items()):
        edges.append(
            {
                "id": f"mention:{source}|{target}",
                "source": source,
                "target": target,
                "type": "mention",
                "weight": len(times),
                "signals": {},
                "platforms": [],
                "cross_platform": False,
                "min_delay_seconds": None,
                "median_delay_seconds": None,
                "first_seen_at": times[0],
                "cluster_id": None,
                "synthetic": dataset.synthetic,
            }
        )
    return edges


def _cluster_platforms(dataset: Dataset, cluster: Cluster, config: CoordinationConfig) -> list[str]:
    posts = campaign_posts(dataset.posts, cluster, config)
    return sorted({post.platform for post in posts if post.platform})


def _build_cluster_summaries(
    clusters: list[Cluster], origins: dict[str, Origin], dataset: Dataset, config: CoordinationConfig
) -> list[dict[str, Any]]:
    summaries = []
    for cluster in clusters:
        origin = origins.get(cluster.id)
        summaries.append(
            {
                "id": cluster.id,
                "size": len(cluster.members),
                "members": list(cluster.members),
                "flagged": cluster.flagged,
                "risk_level": cluster.risk_level,
                "coordination_risk_score": cluster.score,
                "score_components": cluster.components,
                "score_weights": SCORE_WEIGHTS,
                "distinct_items": cluster.distinct_items,
                "platforms": _cluster_platforms(dataset, cluster, config),
                "median_delay_seconds": cluster.median_delay_seconds,
                "earliest_observed": None
                if origin is None
                else {
                    "account_id": origin.account_id,
                    "post_id": origin.post_id,
                    "observed_at": format_timestamp(origin.observed_at),
                    "in_cluster": origin.in_cluster,
                    "ambiguous": origin.ambiguous,
                },
                "synthetic": dataset.synthetic,
            }
        )
    return summaries


def _build_module_result(
    dataset: Dataset,
    co_shares: dict[tuple[str, str], CoShare],
    clusters: list[Cluster],
    origins: dict[str, Origin],
    config: CoordinationConfig,
) -> dict[str, Any]:
    """Build a dict with exactly the fields of the shared ``ModuleResult`` model."""
    limitations = list(_BASE_LIMITATIONS)
    evidence = [SYNTHETIC_NOTICE] if dataset.synthetic else []

    if not dataset.posts:
        return {
            "status": "not_applicable",
            "score": None,
            "confidence": None,
            "evidence": evidence,
            "limitations": ["No posts were available to analyze.", *limitations],
        }

    handles = {account.id: account.handle for account in dataset.accounts}
    repeated_pairs = sum(1 for pair in co_shares.values() if pair.distinct_items >= config.min_shared_items)
    evidence.append(
        f"Analyzed {len(dataset.posts)} posts from {len(dataset.accounts)} accounts; "
        f"{repeated_pairs} account pairs co-shared at least {config.min_shared_items} distinct items "
        f"within {config.window_seconds} seconds."
    )

    flagged = [cluster for cluster in clusters if cluster.flagged]
    for cluster in flagged:
        evidence.append(
            f"{cluster.id}: {len(cluster.members)} accounts, Coordination Risk Score {cluster.score:.2f}, "
            f"median delay between co-shares {cluster.median_delay_seconds:.0f} seconds, "
            f"up to {cluster.distinct_items} distinct items shared per pair."
        )
        platforms = _cluster_platforms(dataset, cluster, config)
        if platforms:
            evidence.append(f"{cluster.id}: its items appeared on {len(platforms)} platform(s): {', '.join(platforms)}.")
        origin = origins.get(cluster.id)
        if origin is not None:
            place = "inside" if origin.in_cluster else "outside"
            tie = " The next account followed within seconds, so this order is uncertain." if origin.ambiguous else ""
            evidence.append(
                f"{cluster.id}: earliest observed post is by {handles[origin.account_id]} "
                f"({place} the cluster) at {format_timestamp(origin.observed_at)}.{tie}"
            )

    without_campaign_item = [cluster.id for cluster in flagged if not cluster.item_keys]
    if without_campaign_item:
        limitations.append(
            f"{', '.join(without_campaign_item)}: no single item was shared widely enough across the "
            "cluster, so no earliest account or timeline is reported for it."
        )

    small = sum(1 for cluster in clusters if not cluster.flagged)
    if small:
        limitations.append(
            f"{small} other co-sharing group(s) did not meet the flagging criteria and are "
            "reported as unflagged. This does not show they are or are not coordinated."
        )
    if not flagged:
        limitations.insert(
            0,
            "Inconclusive: no cluster met the flagging criteria. This does not show that "
            "coordination is absent.",
        )

    return {
        "status": "complete",
        # No measured signal is reported as null, never as a fabricated 0.
        "score": max((cluster.score for cluster in flagged), default=None),
        "confidence": None,
        "evidence": evidence,
        "limitations": limitations,
    }


def analyze_network(dataset: Dataset, config: CoordinationConfig | None = None) -> NetworkAnalysis:
    config = config or CoordinationConfig()
    co_shares = find_co_shares(dataset.posts, config)
    graph = build_coordination_graph(co_shares, config)
    clusters = detect_clusters(graph, co_shares, config)
    roles, origins = assign_roles(dataset, graph, clusters, config)
    edges = _build_edges(dataset, co_shares, clusters, config)
    return NetworkAnalysis(
        case_id=dataset.case_id,
        nodes=_build_nodes(dataset, roles, clusters, edges, config),
        edges=edges,
        timeline=build_timeline(dataset, clusters, config),
        clusters=_build_cluster_summaries(clusters, origins, dataset, config),
        module_result=_build_module_result(dataset, co_shares, clusters, origins, config),
    )
