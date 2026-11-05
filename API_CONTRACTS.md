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
- `POST /api/cases/analyze` -> accepts a text claim and/or URL as JSON; returns one case summary and available module results. `media` is `not_applicable`.
- `POST /api/cases/analyze-media` -> multipart form with `file` (required; JPEG, PNG, WebP, MP4, MOV, WebM or AVI), plus optional `text` and `url`. Returns the same response shape as `analyze`.
- `GET /api/cases/{case_id}` -> most recent in-memory case result for the running process (persistence is deferred). `demo-001` is always available: a synthetic case with network results only.
- `GET /api/network/{case_id}` -> `{nodes: [], edges: [], timeline: []}` for graph/timeline UI. Filled for `demo-001`, where every item has `synthetic: true`, which the UI must show. Empty for submitted cases, which have no spread data; they never receive the demo network.
- `POST /api/cases/{case_id}/action-packet` -> draft countermeasure text with evidence references and clear AI-generated label.

Persistent storage is deferred. The frontend must not depend on persistence surviving a server restart.

## Media upload

A rejected upload creates no case and returns `{"detail": {"code": "...", "message": "..."}}`:

| Status | `code` | Meaning |
|---|---|---|
| 411 | `length_required` | The request has no `Content-Length`. |
| 413 | `too_large` | Over 25 MB for an image, 200 MB for a video, or the image has too many pixels. |
| 415 | `unsupported_type` | The file's content is not a supported type. The file name and extension are ignored. |
| 422 | `empty_file`, `corrupt_media` | The file is empty or cannot be decoded. |

Other `422` responses, for a missing `file` or an invalid `url`, use the standard FastAPI `detail` list.

If the file is valid but the model cannot run, the response is `200` with the `media` module `unavailable`, a `null` score and the reason in `limitations`. Metadata and pHash evidence is still returned.

`overall_risk` for an upload comes from the media module's assessment, not its raw score, combined with any text and URL results. Media alone reaches at most `high`. A result is `low` only if every module reached a result; otherwise it is `inconclusive`.

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

This is the current response shape. The backend exposes Pydantic/OpenAPI types and deterministic rule-based text/URL results.
