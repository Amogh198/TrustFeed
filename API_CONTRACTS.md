# API Contracts — Initial Integration Boundary

Status: **initial implementation contract**. Any change requires a PR that names affected lanes. Keep this file small and stable.

## Design rules

- JSON over HTTP for request/response; replay mode uses the same response shapes.
- Use a stable `case_id`; include `created_at` in UTC ISO-8601; represent unavailable measurements as `null` with an explanation, never as a fabricated score.
- Every model/rule result includes `status`, `score` (0–1 when applicable), `confidence` (0–1 when calibrated), `evidence[]`, and `limitations[]`.
- Risk values: `low`, `moderate`, `high`, `critical`, `inconclusive`. An AI detector score is not a factual verdict.
- Keep user-supplied content out of logs and demo fixtures unless it is intentionally public/sample data.

## Endpoints

- `GET /health` -> service status and version.
- `POST /api/cases/analyze` -> accepts a text claim and/or URL; returns one case summary and available module results. Media uploads are deferred to a later issue.
- `GET /api/cases/{case_id}` -> most recent in-memory case result for the running process (persistence is deferred).
- `GET /api/network/{case_id}` -> `{nodes: [], edges: [], timeline: []}` for graph/timeline UI.
- `POST /api/cases/{case_id}/action-packet` -> draft countermeasure text with evidence references and clear AI-generated label.

Media upload mechanics and persistent storage are deferred. The frontend should submit JSON for text/URL analysis and must not depend on persistence surviving a server restart.

## Common response sketch

```json
{
  "case_id": "demo-001",
  "created_at": "2026-01-01T00:00:00Z",
  "overall_risk": "inconclusive",
  "summary": "Insufficient evidence to determine authenticity.",
  "modules": {
    "media": {"status": "unavailable", "score": null, "confidence": null, "evidence": [], "limitations": ["No model result"]},
    "text": {"status": "complete", "score": 0.2, "confidence": null, "evidence": [], "limitations": []},
    "network": {"status": "not_applicable", "score": null, "confidence": null, "evidence": [], "limitations": []}
  },
  "uncertainties": [],
  "recommended_actions": []
}
```

This is the current response shape. The backend exposes Pydantic/OpenAPI types and deterministic rule-based text/URL results. Media is marked unavailable until the media lane integrates.
