"""Propagation timeline frames for the dashboard's time slider."""

from typing import Any

from backend.network.clusters import Cluster
from backend.network.config import CoordinationConfig
from backend.network.coshare import post_signals
from backend.network.dataset import Dataset, Post, format_timestamp


def build_timeline(
    dataset: Dataset, clusters: list[Cluster], config: CoordinationConfig
) -> list[dict[str, Any]]:
    """Group posts of flagged clusters' items, and traced posts, into fixed time buckets.

    Buckets with no posts are left out, so frame numbers can skip ahead. Use
    ``offset_seconds`` to position a frame on the slider.
    """
    flagged = [cluster for cluster in clusters if cluster.flagged]

    posts_with_clusters: list[tuple[Post, list[Cluster]]] = []
    for post in dataset.posts:
        signals = set(post_signals(post, config))
        matched = [cluster for cluster in flagged if signals & cluster.item_keys]
        if matched or post.on_topic:
            posts_with_clusters.append((post, matched))
    if not posts_with_clusters:
        return []

    start = posts_with_clusters[0][0].created_at
    bucket_size = config.timeline_bucket_seconds
    buckets: dict[int, list[tuple[Post, list[Cluster]]]] = {}
    for entry in posts_with_clusters:
        offset = (entry[0].created_at - start).total_seconds()
        buckets.setdefault(int(offset // bucket_size), []).append(entry)

    members = {account_id for cluster in flagged for account_id in cluster.members}
    seen: set[str] = set()
    frames = []
    for bucket, entries in sorted(buckets.items()):
        accounts = {post.account_id for post, _ in entries}
        new_accounts = sorted(accounts - seen)
        seen |= accounts
        frames.append(
            {
                "frame": bucket,
                "offset_seconds": bucket * bucket_size,
                "start": format_timestamp(entries[0][0].created_at),
                "end": format_timestamp(entries[-1][0].created_at),
                "post_count": len(entries),
                "cluster_member_post_count": sum(
                    1 for post, _ in entries if post.account_id in members
                ),
                "new_account_ids": new_accounts,
                "cumulative_account_count": len(seen),
                "cumulative_cluster_member_count": len(seen & members),
                "cluster_ids": sorted({cluster.id for _, matched in entries for cluster in matched}),
                "platforms": sorted({post.platform for post, _ in entries if post.platform}),
                "synthetic": dataset.synthetic,
            }
        )
    return frames
