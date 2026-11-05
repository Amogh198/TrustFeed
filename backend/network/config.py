"""Tunable thresholds for dissemination-network analysis.

Every value is a heuristic chosen for an explainable demo, not a calibrated
parameter. ``backend/network/README.md`` explains why each one exists.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CoordinationConfig:
    # Two posts of the same item count as a co-share at most this far apart.
    window_seconds: int = 120
    # Distinct items a pair must co-share before the pair counts as coordinated.
    min_shared_items: int = 2
    # Shorter normalized text is ignored, as "breaking news" can match by chance.
    min_text_length: int = 20
    # Smaller clusters are reported as inconclusive, never flagged.
    min_cluster_size: int = 5
    # Minimum Coordination Risk Score for a large-enough cluster to be flagged.
    flag_score_threshold: float = 0.5
    louvain_seed: int = 42
    # At the default of 1.0, Louvain splits one dense campaign into arbitrary parts.
    # 0.5 keeps it whole while still separating campaigns joined by a few accounts.
    louvain_resolution: float = 0.5
    # An item defines a cluster's campaign only if enough members co-shared it. Otherwise
    # a popular link that two members happened to post would pull in unrelated accounts.
    campaign_item_min_members: int = 3
    campaign_item_min_share: float = 0.25
    # Distinct flagged-cluster members that must mention an outsider to tag it a target.
    min_target_mentions: int = 3
    # A second account this close to the earliest post makes the origin ambiguous.
    origin_tie_seconds: int = 5
    timeline_bucket_seconds: int = 60
    # How many times post timing is shuffled for the comparison with chance, and the time allowed.
    null_test_permutations: int = 199
    null_test_max_seconds: float = 5.0
    null_test_seed: int = 42
    # Image fingerprints this close count as one image. The media check uses the same distance.
    fingerprint_max_distance: int = 5

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.min_shared_items < 1:
            raise ValueError("min_shared_items must be at least 1")
        if self.timeline_bucket_seconds <= 0:
            raise ValueError("timeline_bucket_seconds must be positive")
        if not 0 < self.campaign_item_min_share <= 1:
            raise ValueError("campaign_item_min_share must be above 0 and at most 1")
