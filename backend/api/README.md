# Backend API

This is the initial offline API slice for text and URL triage. It does not verify factual claims, fetch submitted URLs, or run the media/network models.

## Run locally

From the repository root, install the backend dependencies and start the development server:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend/api/requirements-dev.txt
python -m uvicorn backend.api.app.main:app --reload
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
- `POST /api/cases/analyze` — JSON body with `text`, `url`, or both. Returns rule-based text/URL indicators and marks media/network modules unavailable.
- `GET /api/cases/{case_id}` — fetches the result from this server process's memory.
- `GET /api/network/{case_id}` — currently returns empty graph/timeline arrays for a known case.
- `POST /api/cases/{case_id}/action-packet` — returns a clearly labeled generic draft template; no generative model is called.

Example request:

```json
{
  "text": "Urgent! Forward this message now to claim your prize.",
  "url": "http://example.zip/login"
}
```

Cases are process-local and disappear when the server stops. Do not send secrets, private data, or credentials in analysis requests.
