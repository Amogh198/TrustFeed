"""Role tags: earliest observed account, amplifiers, participants and targets."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import networkx as nx

from backend.network.clusters import Cluster
from backend.network.config import CoordinationConfig
from backend.network.coshare import post_signals
from backend.network.dataset import Dataset, Post

ROLE_LABELS = {
    "origin_candidate": "Earliest observed account in this dataset (Patient Zero candidate)",
    "amplifier": "Amplifier: co-shares widely within the cluster",
    "participant": "Participant: co-shares with part of the cluster",
    "target": "Target: repeatedly mentioned by cluster members",
    "background": "Background: no coordination signal",
}

# A member must co-share with at least this share of its cluster to be an amplifier.
_AMPLIFIER_MIN_CENTRALITY = 0.5


@dataclass(frozen=True)
class Origin:
    account_id: str
    post_id: str
    observed_at: datetime
    in_cluster: bool
    # True when another account posted so soon after that the order is not meaningful.
    ambiguous: bool


@dataclass(frozen=True)
class AccountRole:
    role: str = "background"
    cluster_id: str | None = None
    degree_centrality: float = 0.0
    weighted_degree: float = 0.0


def campaign_posts(posts: tuple[Post, ...], cluster: Cluster, config: CoordinationConfig) -> list[Post]:
    """Return every post of the cluster's items, by any account, in time order."""
    return [
        post
        for post in posts
        if any(signal in cluster.item_keys for signal in post_signals(post, config))
    ]


def find_origin(
    dataset: Dataset, cluster: Cluster, config: CoordinationConfig
) -> Origin | None:
    """Find the earliest post of the cluster's items, even if posted by an outsider."""
    posts = campaign_posts(dataset.posts, cluster, config)
    if not posts:
        return None
    first = posts[0]
    ambiguous = any(
        post.account_id != first.account_id
        and (post.created_at - first.created_at).total_seconds() <= config.origin_tie_seconds
        for post in posts[1:]
    )
    return Origin(
        account_id=first.account_id,
        post_id=first.id,
        observed_at=first.created_at,
        in_cluster=first.account_id in cluster.members,
        ambiguous=ambiguous,
    )


def _find_targets(
    posts: tuple[Post, ...], cluster: Cluster, config: CoordinationConfig
) -> list[str]:
    members = set(cluster.members)
    mentioned_by: dict[str, set[str]] = defaultdict(set)
    for post in posts:
        if post.account_id in members:
            for account_id in post.mentions:
                if account_id not in members:
                    mentioned_by[account_id].add(post.account_id)
    return sorted(
        account_id
        for account_id, sources in mentioned_by.items()
        if len(sources) >= config.min_target_mentions
    )


def assign_roles(
    dataset: Dataset, graph: nx.Graph, clusters: list[Cluster], config: CoordinationConfig
) -> tuple[dict[str, AccountRole], dict[str, Origin]]:
    """Tag accounts in cluster order, so the strongest cluster's role wins a clash."""
    roles: dict[str, AccountRole] = {}
    origins: dict[str, Origin] = {}

    for cluster in clusters:
        subgraph = graph.subgraph(cluster.members)
        centrality = nx.degree_centrality(subgraph)
        weighted_degree = dict(subgraph.degree(weight="weight"))
        for member in cluster.members:
            role = "background"
            if cluster.flagged:
                widely_connected = centrality[member] >= _AMPLIFIER_MIN_CENTRALITY
                role = "amplifier" if widely_connected else "participant"
            roles[member] = AccountRole(
                role=role,
                cluster_id=cluster.id,
                degree_centrality=round(centrality[member], 4),
                weighted_degree=float(weighted_degree[member]),
            )

    for cluster in clusters:
        if not cluster.flagged:
            continue
        for account_id in _find_targets(dataset.posts, cluster, config):
            if account_id not in roles or roles[account_id].role == "background":
                existing = roles.get(account_id, AccountRole())
                roles[account_id] = AccountRole(
                    "target", existing.cluster_id, existing.degree_centrality, existing.weighted_degree
                )
        origin = find_origin(dataset, cluster, config)
        if origin is not None:
            origins[cluster.id] = origin
            existing = roles.get(origin.account_id, AccountRole())
            roles[origin.account_id] = AccountRole(
                "origin_candidate",
                existing.cluster_id,
                existing.degree_centrality,
                existing.weighted_degree,
            )
    return roles, origins
