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
python -m backend.network.seed_story            # regenerate the demo story
python -m backend.network.seed_story --check    # confirm the demo story is current
```

## Interface for the API lane

```python
from backend.network import get_network_payload, get_network_module_result, get_network_clusters

get_network_payload("demo-001")        # {"nodes": [...], "edges": [...], "timeline": [...]}
get_network_module_result("demo-001")  # dict with the ModuleResult fields
get_network_clusters("demo-001")       # per-cluster scores, for an evidence view
```

Every function returns `None` for any other case id. **Don't give user-submitted cases the demo network**, because it would present invented spread as a finding about their content. Keep `network` as `unavailable` for them.

### Real public posts

```python
from backend.network import trace_case, get_network_coverage

trace_case(case_id, text=..., url=..., urls=page_links, hashtags=(...))  # returns ModuleResult fields
get_network_coverage(case_id)  # what was searched and missed, and the found posts in order
```

After `trace_case`, `get_network_payload`, `get_network_module_result` and `get_network_clusters` work for that case, so the existing `GET /api/network/{case_id}` route serves it without changes. It reads live platforms and can take up to about 25 seconds. **Pass `urls`, the page links found by a web source search, to trace an image:** platforms can't be searched by an image alone, so without text, links or hashtags the result is `unavailable`.

| Platform, checked without a login on 2026-11-05 | State | What can be searched |
|---|---|---|
| Mastodon (`mastodon.social`) | Connected | Hashtags only. Text search returns nothing and the link timeline returns 404 |
| Lemmy (`lemmy.world` and instances it federates with) | Connected | Links and text |
| Hacker News (Algolia API) | Connected | Links, and text in stories and comments |
| Bluesky | Not connected | Post search returns 403 and 401 without a login |
| Reddit | Not connected | Search returns 403 without registered API credentials |
| YouTube | Not connected | The Data API returns 403 without a key |
| X | Not connected | Not tried: no paid API access |
| WhatsApp and other private channels | Can't be traced | No public API can see them |

- **Only real matches count.** Search results are candidates. A post is kept only if it carries the searched link, hashtag or phrase.
- **Repetition comes from account histories.** Searching for one item can only find one shared item, and one item is never treated as coordination. So the other recent public posts of up to 20 accounts that posted within the window are read as well.
- **Account identity stays per platform.** The same name on two platforms is two accounts.
- **Failures are reported.** Each platform has a `status` of `searched`, `partial`, `failed` or `not_searchable`, with notes. If none can be searched the result is `unavailable`. If nothing matches the result is `Inconclusive`, never clean.
- **Offline runs.** `RecordingFetch` saves a run and `ReplayFetch` plays it back, by passing `fetch=`. Recordings hold real people's public posts, so keep them out of Git.
- **Tests never use the network.** Only a manual run has read the live platforms, so a platform changing its API would not show up in tests.

### Monitoring two or more platforms

```python
from backend.network import Monitor

monitor = Monitor("watch-1", urls=(link,), hashtags=("floods",))
snapshot = monitor.poll()  # call on a schedule; results accumulate between polls
```

```bash
python -m backend.network.watch --watch-id watch-1 --hashtag floods --url https://example.org/a --polls 3 --interval 300
```

A watch with a hashtag and a link reads all three connected platforms: Mastodon through the hashtag, and Lemmy and Hacker News through the link. A watch with only one of these reads fewer, and `platforms_read` on each snapshot says exactly which were read. Each snapshot also has `new_posts`, `total_matching_posts`, `alerts` and `module_result`. Alerts are `coordination_signal`, for a person to review, and `platform_unreachable`, when a platform that worked before stops working. After a poll, the getters above work with the watch id.

**This is repeated polling of public search, not a complete feed.** The command line waits at least 60 seconds between polls. `--state` keeps results between runs. That file holds real people's public posts, so keep it under `backend/network/recordings/`, which Git ignores.

### Linked demo story

`demo-story-001` is one invented rumour traced end to end offline: a sample post goes through the real adapters, matching, history reads and engine, reading a synthetic recording in each platform's real format. It covers three invented platforms, 12 co-posting accounts, a resident who asked about the photo hours earlier, sceptical late replies and search results that must be filtered out.

```python
from backend.network import DEMO_STORY_CASE_ID, get_demo_story

get_demo_story()["submission"]  # the {text, url} a presenter submits
trace_case(case_id, **get_demo_story()["submission"])  # replays the recording, never the internet
```

- Only the story's exact text or link replays it, so real content never receives this data.
- All the usual getters work with `demo-story-001`, and `synthetic` is true throughout. **The dashboard must say so.**
- It shows that the earliest post found isn't the source: the resident is earliest, and is outside the flagged group.

To analyze other data, use `analyze_network(parse_dataset(raw))`. `parse_dataset` raises `ValueError` for any malformed record.

### Payload fields

| List | Fields |
|---|---|
| `nodes` | `id`, `handle`, `followers`, `role`, `role_label`, `cluster_id`, `in_flagged_cluster`, `degree_centrality`, `weighted_degree`, `post_count`, `platforms`, `first_post_at`, `first_campaign_post_at`, `appears_at`, `synthetic` |
| `edges` | `id`, `source`, `target`, `type`, `weight`, `signals`, `platforms`, `cross_platform`, `min_delay_seconds`, `median_delay_seconds`, `first_seen_at`, `cluster_id`, `synthetic` |
| `timeline` | `frame`, `offset_seconds`, `start`, `end`, `post_count`, `cluster_member_post_count`, `new_account_ids`, `cumulative_account_count`, `cumulative_cluster_member_count`, `cluster_ids`, `platforms`, `synthetic` |

- **Roles:** `origin_candidate`, `amplifier`, `participant`, `target`, `background`. Show `role_label` to users. It keeps the "earliest observed" wording.
- **Edge types:** `co_share` (repeated, counts as a signal), `weak_co_share` (one item only, not a signal; draw it faintly), `mention` (directed).
- **Time slider:** show a node from `appears_at` and an edge from `first_seen_at`. A node always appears no later than its edges. `appears_at` is null only for accounts with no part in the spread, which can stay hidden. Items dated before the first frame show from the start. Empty time buckets are left out of `timeline`, so position frames by `offset_seconds`.
- **Platforms:** each post may name a platform. The engine reports where items spread and marks `cross_platform` edges. Platform does not affect the score. Missing values stay empty.
- **Synthetic label:** when `synthetic` is true, the dashboard must say so.

## How detection works

1. **Co-shares.** Two accounts co-share when they post the same item within **120 seconds** (inclusive, from the blueprint). The delay is measured between the two posts. An item is matched on any of:
   - **URL**, ignoring tracking parameters, fragments, `www.` and http versus https. Text that isn't a usable link gives no signal.
   - **Media hash**, exact match
   - **Text**, after removing case, punctuation and links, if at least 20 characters remain. Letters, numbers and combining marks are kept, so Indic vowels still count.
2. **Repetition.** A pair counts only after co-sharing **at least 2 distinct items**. One co-share happens by chance whenever many people react to the same event. Signals on one post are one item. Different posts matched by different signals are different items, and so are different links.
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

- **`origin_candidate`:** the earliest post of the cluster's campaign items by any account, including outsiders. If another account follows within 5 seconds, it is marked `ambiguous` because the order isn't meaningful. A campaign item is one that at least 3 members, and at least 25% of the cluster, co-shared, so a popular link two members happened to post can't name an unrelated account. The origin, timeline and platform lists use only these items. If no item qualifies, no origin or timeline is reported.
- **`amplifier`:** co-shares with at least half of the cluster.
- **`participant`:** other cluster members.
- **`target`:** an outsider mentioned by at least 3 cluster members.

## Limitations

- **Coverage is partial.** Only three platforms are read, public search doesn't return every post, and the histories read are recent and capped. Lemmy shows what one server has federated.
- **Reposts are left out.** Mastodon reposts are dropped, so account relationships are still limited to mentions.
- **Demo results prove little.** The engine recovers the planted cluster in data built to contain one. That shows it works as designed, not how accurate it would be on real data.
- **No claims about people.** Co-sharing does not establish intent, common control, automation or attribution. Newsrooms and fan communities can look similar.
- **Evidence coverage.** Similarity alone is never treated as coordination: a pair must co-share repeatedly within the time window. The engine uses timestamps, shared URLs, media hashes, normalized text and mentions. It has no repost data, and mentions are its only account relationship. Real posts currently give no media hashes, so images are compared only through shared links.
- **Origin is limited to the dataset.** The true source may have posted elsewhere or earlier.
- **Evasion is easy.** Paraphrases, re-encoded media and delays over 120 seconds are all missed. Perceptual matching from T1 could address the media case after integration.
- **Single-threaded and in-memory.** Suitable for demo-sized data. Very large bursts within the window get slow, since every pair is compared.
