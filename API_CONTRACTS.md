# API Contracts — Initial Integration Boundary

Status: **proposal for kickoff; Gemini lane 1 owns publishing the first concrete schema in a PR.** Keep this file small and stable. Any change requires an Issue note before implementation and a PR that names affected lanes.

## Design rules

- JSON over HTTP for request/response; replay mode uses the same response shapes.
- Use a stable `case_id`; include `created_at` in UTC ISO-8601; represent unavailable measurements as `null` with an explanation, never as a fabricated score.
- Every model/rule result includes `status`, `score` (0–1 when applicable), `confidence` (0–1 when calibrated), `evidence[]`, and `limitations[]`.
- Risk values: `low`, `moderate`, `high`, `critical`, `inconclusive`. An AI detector score is not a factual verdict.
- Keep user-supplied content out of logs and demo fixtures unless it is intentionally public/sample data.

## Proposed endpoints

- `GET /health` -> service status and version.
- `POST /api/cases/analyze` -> accepts a text claim, URL, or uploaded-media reference; returns one case summary and available module results.
- `GET /api/cases/{case_id}` -> stored/replay case result.
- `GET /api/network/{case_id}` -> `{nodes: [], edges: [], timeline: []}` for graph/timeline UI.
- `POST /api/cases/{case_id}/action-packet` -> draft countermeasure text with evidence references and clear AI-generated label.

Exact field names and upload mechanics are for the contract Issue. Agree before multiple lanes implement against these suggestions.

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

This is an illustrative shape, not a frozen schema. The integration lane must settle Pydantic/OpenAPI types and sample fixtures before feature branches depend on it.
