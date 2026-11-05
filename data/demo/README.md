# Demo data

**Everything in `network_demo*.json` is synthetic.** All accounts, posts, links and media hashes are invented by `backend/network/seed_network.py`. Links use the reserved `.example` domain, and the campaign concerns a fictional town. Results from this data are not evidence of real-world activity by any person or group.

| File | Purpose | Read by |
|---|---|---|
| `network_demo.json` | 320 accounts and 869 posts for case `demo-001` | Network engine |
| `network_demo_ground_truth.json` | Planted labels | **Tests only**, never the engine |

## What it contains

- **One coordinated cluster of 36 accounts:** a seed account, 29 core accounts and 6 peripheral accounts, posting 4 items in tight waves.
- **Three targets:** outside accounts that the cluster repeatedly mentions.
- **Hard negatives that must not be flagged:**
  - **Organic burst:** 24 accounts react to one event within 110 seconds in their own words.
  - **Late reshares:** 15 accounts share a campaign link hours later, well spread out.
  - **Syndication group:** 3 accounts repost identical headlines, which is too small to flag.
- **Background:** ordinary posts from the remaining accounts.

Regenerate with `python -m backend.network.seed_network`. The output is deterministic, and a test fails if these files fall out of date.

Other lanes can add their own demo files here using a different prefix.
