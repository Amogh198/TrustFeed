# Backend API

This is the API for text, URL and media triage, plus the synthetic network demo. It works offline unless a request sets `search_web`. It does not verify factual claims or fetch submitted URLs. Results are signals, not proof.

## Run locally

From the repository root, install the backend dependencies and start the development server:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend/api/requirements-dev.txt
python -m uvicorn backend.api.app.main:app --reload
```

The media model is optional and about 343 MB. Without it, uploads still return metadata evidence, with the `media` module marked `unavailable`. To enable it:

```powershell
python -m pip install -r backend/media/requirements-model.txt
python -m backend.media download-model
```

Run the backend unit/API tests from the repository root with `python -m pytest backend/api/tests -q`.

Open `http://127.0.0.1:8000/docs` for the generated OpenAPI interface. The frontend dev server at `http://localhost:5173` is allowed by the current CORS configuration.

The default CORS origins include both `http://localhost:5173` and `http://127.0.0.1:5173`. To allow a different local or deployed frontend, set `CORS_ORIGINS` to a comma-separated list before starting Uvicorn, for example:

```powershell
$env:CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,https://demo.example.org"
python -m uvicorn backend.api.app.main:app --reload
```

## Current routes

- `GET /health` — basic liveness response.
- `POST /api/cases/analyze` — JSON body with `text`, `url`, or both, and optional `search_web`. Returns rule-based text/URL indicators.
- `POST /api/cases/analyze-media` — multipart form with `file`, and optional `text`, `url` and `search_web`. Adds the media module's result. Uploads go to a temporary file that is deleted after analysis.
- `GET /api/cases` — lists saved local case summaries. Use `?risk_level=high` or `?limit=10` to narrow the results.
- `GET /api/cases/{case_id}` — fetches a saved result. `demo-001` is always available and contains synthetic network and source search results only.
- `GET /api/cases/{case_id}/export` — returns a saved report as JSON for local export.
- `GET /api/cases/{case_id}/provenance` — returns the full source search report: pages found, dates and what each date rests on.
- `GET /api/cases/{case_id}/timeline` — returns web appearances, matching posts and flagged co-sharing activity in time order. Undated events stay at the end with a null time.
- `GET /api/network/{case_id}` — returns the synthetic graph and timeline for `demo-001`, the traced graph for a case with `search_web`, and empty arrays otherwise.
- `GET /api/network/{case_id}/coverage` — says what a trace searched and missed, and lists matching posts in time order. Returns `null` if no trace ran.
- `GET /api/replay/scenarios` — lists the bundled offline demo scenarios.
- `POST /api/replay/{scenario_id}/start` — runs a synthetic offline scenario through the same text/URL flow and saves it in case history.
- `POST /api/cases/{case_id}/action-packet` — returns a clearly labeled evidence-based draft and structured evidence, uncertainty, claim-status and action sections; no generative model is called.

`search_web` is off by default. Setting it to `true` sends the image to the source search providers with keys set, and the text and links to public platforms' search services. It can add about two minutes to a request. The keys are listed in `.env.example`. With no key, `provenance` says no web search ran.

Without `search_web`, submitted cases report `network` as `unavailable` and nothing leaves the server. Neither result changes `overall_risk`. See `API_CONTRACTS.md` for the response shapes, upload errors and how `overall_risk` is combined.

Example request:

```json
{
  "text": "Urgent! Forward this message now to claim your prize.",
  "url": "http://example.zip/login"
}
```

Cases are stored locally in `trusttrace.db` by default, or at `CASE_STORE_PATH` if set. The database stores the rendered analysis record; it does not store an original upload, which is deleted after analysis. A case with `search_web` also stores the pages it found, and the public account handles and post links from its trace. Do not send secrets, private data, or credentials in analysis requests.
