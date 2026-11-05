# Network analysis (T2)

Finds groups of accounts that spread the same content in lockstep, tags their roles and builds the spread timeline.

**This module measures how content spread, not whether it is true or authentic.** Authenticity belongs to the media (T1) and text (T3) lanes. A high score here does not make content fake, and a low score does not make it genuine.

## Run

From the repository root, on Python 3.11+:

```bash
pip install -r backend/network/requirements-dev.txt
python -m pytest backend/network/tests -q
python -m backend.network                       # print the demo result
python -m backend.network.seed_network          # regenerate demo data
python -m backend.network.seed_network --check  # confirm committed data is current
```

## Interface for the API lane

```python
from backend.network import get_network_payload, get_network_module_result, get_network_clusters

get_network_payload("demo-001")        # {"nodes": [...], "edges": [...], "timeline": [...]}
get_network_module_result("demo-001")  # dict with the ModuleResult fields
get_network_clusters("demo-001")       # per-cluster scores, for an evidence view
```

Every function returns `None` for any other case id. **Don't give user-submitted cases the demo network**, because it would present invented spread as a finding about their content. Keep `network` as `unavailable` for them.

To analyze other data, use `analyze_network(parse_dataset(raw))`.

### Payload fields

| List | Fields |
|---|---|
| `nodes` | `id`, `handle`, `followers`, `role`, `role_label`, `cluster_id`, `in_flagged_cluster`, `degree_centrality`, `weighted_degree`, `post_count`, `platforms`, `first_post_at`, `first_campaign_post_at`, `synthetic` |
| `edges` | `id`, `source`, `target`, `type`, `weight`, `signals`, `platforms`, `cross_platform`, `min_delay_seconds`, `median_delay_seconds`, `first_seen_at`, `cluster_id`, `synthetic` |
| `timeline` | `frame`, `offset_seconds`, `start`, `end`, `post_count`, `cluster_member_post_count`, `new_account_ids`, `cumulative_account_count`, `cumulative_cluster_member_count`, `cluster_ids`, `platforms`, `synthetic` |

- **Roles:** `origin_candidate`, `amplifier`, `participant`, `target`, `background`. Show `role_label` to users. It keeps the "earliest observed" wording.
- **Edge types:** `co_share` (repeated, counts as a signal), `weak_co_share` (one item only, not a signal; draw it faintly), `mention` (directed).
- **Time slider:** show a node from `first_campaign_post_at` and an edge from `first_seen_at`. Empty time buckets are left out of `timeline`, so position frames by `offset_seconds`.
- **Platforms:** each post may name a platform. The engine reports where items spread and marks `cross_platform` edges. Platform does not affect the score. Missing values stay empty.
- **Synthetic label:** when `synthetic` is true, the dashboard must say so.

## How detection works

1. **Co-shares.** Two accounts co-share when they post the same item within **120 seconds** (inclusive, from the blueprint). The delay is measured between the two posts. An item is matched on any of:
   - **URL**, ignoring tracking parameters and fragments
   - **Media hash**, exact match
   - **Text**, after removing case, punctuation and links, if at least 20 characters remain
2. **Repetition.** A pair counts only after co-sharing **at least 2 distinct items**. One co-share happens by chance whenever many people react to the same event.
3. **Clusters.** Louvain community detection with a fixed seed and resolution 0.5. The default of 1.0 split the demo campaign into two arbitrary parts, while 0.5 keeps it whole and still separates distinct campaigns.
4. **Score and flag.** A cluster is flagged at **5+ accounts and a score of 0.5+**. Smaller groups are reported as `inconclusive`.

### Coordination Risk Score

A weighted sum between 0 and 1. It is a **heuristic, not a probability**, so `confidence` is always `null`.

| Component | Weight | Measures |
|---|---|---|
| `temporal_tightness` | 0.30 | How far the median delay falls inside the window |
| `identical_text` | 0.20 | Share of the cluster's pairs with matching text |
| `shared_media` | 0.20 | Share of the cluster's pairs with matching media |
| `density` | 0.15 | Share of possible pairs that are connected |
| `repetition` | 0.15 | Mean distinct items per pair, reaching 1.0 at 4 |

Risk bands: under 0.35 `low`, under 0.55 `moderate`, under 0.75 `high`, otherwise `critical`. The weights and bands were set by judgement and have not been calibrated against real data. The blueprint names text embeddings as a signal, but normalized text is used instead to avoid a heavy model dependency.

### Roles

- **`origin_candidate`:** the earliest post of the cluster's items by any account, including outsiders. If another account follows within 5 seconds, it is marked `ambiguous` because the order isn't meaningful.
- **`amplifier`:** co-shares with at least half of the cluster.
- **`participant`:** other cluster members.
- **`target`:** an outsider mentioned by at least 3 cluster members.

## Limitations

- **Demo results prove little.** The engine recovers the planted cluster in data built to contain one. That shows it works as designed, not how accurate it would be on real data.
- **No claims about people.** Co-sharing does not establish intent, common control, automation or attribution. Newsrooms and fan communities can look similar.
- **Origin is limited to the dataset.** The true source may have posted elsewhere or earlier.
- **Evasion is easy.** Paraphrases, re-encoded media and delays over 120 seconds are all missed. Perceptual matching from T1 could address the media case after integration.
- **Single-threaded and in-memory.** Suitable for demo-sized data. Very large bursts within the window get slow, since every pair is compared.
