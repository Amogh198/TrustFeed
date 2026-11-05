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

Last updated 2026-11-05. Backend features are on `main`. The dashboard runs on the real API.

| Area | Works now | Not done or not measured |
|---|---|---|
| API | Text, link, image and video input, risk summary, saved history, export, offline replay, source search report, timeline, network coverage, explanation, heatmap and monitor routes, rule-based action packets | Action packets from a generative model, background jobs |
| Media | Image model, metadata, keyframes, known-image matching, accuracy benchmark, explanation checks, occlusion heatmap | OCR, audio, lip-sync, video accuracy |
| Source search | Works with a provider key the user sets up, and only on opt-in. Includes an explanation check. | Coverage not measured. Results depend on what search services have indexed. |
| Network | Co-sharing detection, risk score, roles, timeline, public-post tracing, monitoring, explanation checks | Repost timing, accuracy on real campaigns |
| Dashboard | Real API: check form, opt-in, spread replay with time bar and account details, coverage, explanation, benchmark, heatmap, monitoring, history, JSON export, printable report, action packet with correction draft, offline replay, demo walkthrough | Tested in one browser at desktop and phone widths |

### Detector accuracy

These figures are for `dima806/deepfake_vs_real_image_detection` at its current bands, from [data/eval/commons_2026-11-05.json](data/eval/commons_2026-11-05.json). The test split has 157 fake and 75 real images.

| Measure | Result |
|---|---|
| Fakes flagged | 1 of 157 |
| Real images wrongly flagged | 1 of 75 |
| Fakes that scored low | 128 of 157 |
| Real images that scored low | 72 of 75 |
| AUC | 0.8541 |

The model separates fakes from real images better than these bands show, so the bands are under review and haven't been changed. Real images in this benchmark are only photos of people, and face swaps weren't measured. See [backend/media/README.md](backend/media/README.md) for details.

**Known limits**

- **The image detector is not reliable at its current settings.** It flagged only 3 of 301 fakes across the whole benchmark, so a low media result doesn't show that media is authentic.
- **The heatmap shows sensitivity, not proof of editing.** It shows where covering part of an image moved the model's score.
- **Coordination detection hasn't been measured on real campaigns.** It has only been shown working on synthetic data built to contain a campaign.
- **Platform coverage is partial.** Public search is read on Mastodon, Lemmy, Hacker News and Bluesky, and none of these is a complete feed. Mastodon finds links only while they trend. Reddit, YouTube and X aren't connected, and private channels such as WhatsApp can't be traced.
- **Text rules are weak.** They are fixed phrase lists, and caught only 1 of 8 new scam and rumour examples in a small check. Link rules caught 6 of 6 with no false alarms on 6 real sites. Neither is measured on labelled data.
- **GitHub's automated checks aren't running yet,** so run the checks locally.

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

Then start the dashboard, which reads the API at `http://localhost:8000`:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. It needs Node 18 or later. For the demo script, open **Walkthrough** in the top bar.

**Offline demos need no keys or internet:** `demo-001` and `demo-story-001` are synthetic networks, and `GET /api/replay/scenarios` lists the replay cases. The dashboard bundles its fonts, so it also runs with no internet once installed.

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
python -m pytest tools -q
```

```bash
python tools/compat_check.py
```

For the dashboard, run this from `frontend`. It covers the type check, lint, tests and build:

```bash
npm run check
```

## Team and docs

| Lane | Owner | Paths |
|---|---|---|
| T1 media and source search | Akshay | `backend/media`, `backend/provenance` |
| T2 network tracing | Bhuvan | `backend/network`, `data/demo/network_demo*` |
| T3 API, text, fusion, coordination | Amogh | `backend/api`, `backend/text`, `API_CONTRACTS.md` |
| T4 dashboard | Manas; rebuilt by Bhuvan's lane at Bhuvan's request on `feat/dashboard-rebuild` | `frontend` |

- **Contributors and agents:** start with [CLAUDE.md](CLAUDE.md), then [AGENT_COORDINATION.md](AGENT_COORDINATION.md).
- **API:** [API_CONTRACTS.md](API_CONTRACTS.md).
- **Media checks, benchmark and heatmap:** [backend/media/README.md](backend/media/README.md).
- **Source search:** [backend/provenance/README.md](backend/provenance/README.md).
- **Network tracing:** [backend/network/README.md](backend/network/README.md).
- **Branches:** each feature gets its own branch, and merged branches are kept, so the repository lists more branches than active work. `main` is the current state.
