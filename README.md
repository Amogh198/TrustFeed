# TrustFeed

**TruthTrace AI** analyses images, videos, text, links and public social posts to find signs of manipulated media, misleading content and coordinated spread, and shows the evidence and its limits. It was built for problem DL-SJBIT-HK26-GOVP006 at LAKSHYA 2026.

**Its results are signals for a person to review, not proof.** Unknown values stay empty with an explanation, and synthetic or replayed data is labelled.

## What it answers

| Question | How | Where |
|---|---|---|
| Does this media look synthetic or edited? | Pretrained image model, metadata, video keyframes, matching against known images | `backend/media` |
| Where has this image appeared? | Reverse image search, with the earliest appearance found | `backend/provenance` |
| Does the text or link look risky? | Rule-based language and URL checks, plus claim extraction | `backend/text`, `backend/api` |
| How did it spread on public platforms? | Finds matching posts and detects accounts repeatedly posting the same items | `backend/network` |

These are separate questions, and one never answers another. The earliest appearance found isn't shown to be the source, and accounts posting together aren't shown to be coordinating.

## Status

Backend features are on `main`. **The dashboard is on `main` but still uses local sample data and doesn't call the API yet.**

| Area | Works now | Not done or not measured |
|---|---|---|
| API | Text, link, image and video input, risk summary, saved history, export, offline replay, template action packets | Explanation route, generated action packets |
| Media | Image model, metadata, keyframes, known-image matching | OCR, audio, heatmaps, lip-sync |
| Source search | Works with a provider key the user sets up, and only on opt-in | Results depend on what search services have indexed |
| Network | Co-sharing detection, risk score, roles, timeline, public-post tracing, explanation checks | Monitoring routes, repost timing |
| Dashboard | Views on sample data | Connection to the real API |

**Known limits**

- **The image detector is not reliable at its current settings.** It flagged only 3 of 301 fakes in the benchmark, so a low media result doesn't show that media is authentic.
- **Coordination detection hasn't been measured on real campaigns.** It has only been shown working on synthetic data built to contain a campaign.
- **Platform coverage is partial.** Public search is read on Mastodon, Lemmy, Hacker News and Bluesky, and none of these is a complete feed. Reddit, YouTube and X aren't connected, and private channels such as WhatsApp can't be traced.
- **GitHub's automated checks haven't started on any branch yet,** so run the checks locally.

## Run it

Needs Python 3.11 or later. Run these from the repository root.

```bash
pip install -r backend/api/requirements-dev.txt
python -m uvicorn backend.api.app.main:app --env-file .env
```

Copy `.env.example` to `.env` first, and never commit `.env`. The image model is optional, and without it the media check reports `unavailable`:

```bash
pip install -r backend/media/requirements-model.txt
```

The dashboard is in `frontend/`, which has its own `package.json`.

**Offline demos need no keys or internet:** `demo-001` and `demo-story-001` are synthetic networks, and `GET /api/replay/scenarios` lists the replay cases.

**Privacy:** nothing leaves the server unless a request sets `search_web` to `true`. With it, an image goes to source search services, and the text and links go to public platform search. See [API_CONTRACTS.md](API_CONTRACTS.md).

## Tests

Run each folder separately, as two of them have test files with the same name.

```bash
python -m pytest backend/api/tests -q
```

```bash
python -m pytest backend/media/tests -q
```

```bash
python -m pytest backend/provenance -q
```

```bash
python -m pytest backend/network/tests -q
```

```bash
python tools/compat_check.py
```

## Team and docs

| Lane | Owner | Paths |
|---|---|---|
| T1 media and source search | Akshay | `backend/media`, `backend/provenance` |
| T2 network tracing | Bhuvan | `backend/network`, `data/demo/network_demo*` |
| T3 API, text, fusion, coordination | Amogh | `backend/api`, `backend/text`, `API_CONTRACTS.md` |
| T4 dashboard | Manas | `frontend` |

- **Contributors and agents:** start with [CLAUDE.md](CLAUDE.md), then [AGENT_COORDINATION.md](AGENT_COORDINATION.md).
- **API:** [API_CONTRACTS.md](API_CONTRACTS.md).
- **Network tracing:** [backend/network/README.md](backend/network/README.md).
- **Branches:** each feature gets its own branch, and merged branches are kept, so the repository lists more branches than active work. `main` is the current state.
