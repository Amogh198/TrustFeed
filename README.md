# TrustFeed

**TrustFeed AI** analyses images, videos, text, links and public social posts to find signs of manipulated media, misleading content and coordinated spread, and shows the evidence and its limits. It was built for problem DL-SJBIT-HK26-GOVP006 at LAKSHYA 2026.

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

These figures are for `nonescape/nonescape-mini-v0` at its current bands, from [data/eval/commons_licensed_2026-11-05.json](data/eval/commons_licensed_2026-11-05.json). The test split has 137 fake and 148 real images.

| Measure | Result |
|---|---|
| Fakes flagged | 44 of 137 |
| Real images wrongly flagged | 17 of 148 |
| Fakes that scored low | 50 of 137 |
| Real images that scored low | 98 of 148 |
| AUC | 0.69 [0.63–0.75] |

This is the best single detector of six measured on this set, where the previous default scored AUC 0.53. It still misses most fakes. The bands haven't changed, and face swaps, video and images re-saved by social media weren't measured. See [backend/media/README.md](backend/media/README.md) for details.

**Known limits**

- **The image detector is not reliable on its own.** On the test split it flagged 44 of 137 fakes and wrongly flagged 17 of 148 real images, so neither a low nor an elevated result settles whether media is authentic.
- **The heatmap shows sensitivity, not proof of editing.** It shows where covering part of an image moved the model's score.
- **Coordination detection hasn't been measured on real campaigns.** It has only been shown working on synthetic data built to contain a campaign.
- **Platform coverage is partial.** Public search is read on Mastodon, Lemmy, Hacker News and Bluesky, and none of these is a complete feed. Mastodon finds links only while they trend. Reddit, YouTube and X aren't connected, and private channels such as WhatsApp can't be traced.
- **Text rules are weak.** They are fixed phrase lists, and caught only 1 of 8 new scam and rumour examples in a small check. Link rules caught 6 of 6 with no false alarms on 6 real sites. Neither is measured on labelled data.
- **GitHub's automated checks aren't running yet,** so run the checks locally.

## Run it

Needs Python 3.11 or later and Node 18 or later. **Use Python 3.12, which is the version the image model was tested on. On Python 3.14 the model's packages may not install, and uploads then have no media score.** Run these from the repository root, inside a virtual environment:

```bash
pip install -r backend/api/requirements-dev.txt
```

```bash
pip install -r backend/media/requirements-model.txt
```

The second install is the image model. Without it, uploads have no media score and no trust score. Then start everything. It uses `.venv` if there is one, and warns if the model can't run:

```bash
python tools/start_demo.py
```

To use source search keys, copy `.env.example` to `.env`, and never commit `.env`. To start the parts separately:

```bash
python -m uvicorn backend.api.app.main:app
```

Then start the dashboard. In local development, Vite proxies `/api/*` and `/health` to `http://127.0.0.1:8000`, so the browser calls the frontend's own origin and avoids hostname and CORS mismatches:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. It needs Node 18 or later. For the demo script, open **Walkthrough** in the top bar.

To run the API on another host or port, set `TRUSTFEED_API_TARGET` before starting Vite. For a separately hosted frontend build, set `VITE_API_BASE_URL` to the API origin (for example, `https://api.example.org`) and allow the frontend origin in the API's `CORS_ORIGINS`.

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
