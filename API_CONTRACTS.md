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
- `POST /api/cases/analyze` -> accepts a text claim and/or URL as JSON, plus optional `search_web` (boolean, default `false`); returns one case summary and available module results. `media` and `provenance` are `not_applicable`.
- `POST /api/cases/analyze-media` -> multipart form with `file` (required; JPEG, PNG, WebP, MP4, MOV, WebM or AVI), plus optional `text`, `url` and `search_web` (boolean, default `false`). Returns the same response shape as `analyze`.
- `GET /api/cases/{case_id}` -> saved local case result. `demo-001` is always available: a synthetic case with network and source search results only.
- `GET /api/cases/{case_id}/provenance` -> the full source search report. See "Source search and public-post trace".
- `GET /api/cases/{case_id}/timeline` -> `{events: []}`, combining web appearances, matching posts and flagged co-sharing activity.
- `GET /api/cases` -> local case-history summaries. Optional `risk_level` filters by the triage label; `limit` is 1–100 and defaults to 25.
- `GET /api/cases/{case_id}/export` -> the complete saved case report as JSON for local export or offline presentation.
- `GET /api/network/{case_id}` -> `{nodes: [], edges: [], timeline: []}` for graph/timeline UI. Filled for `demo-001`, where every item has `synthetic: true`, which the UI must show. Empty for submitted cases unless a public-post trace ran for them; they never receive the demo network.
- `GET /api/network/{case_id}/coverage` -> what a trace searched and missed, and the matching posts in time order. `null` when no trace ran for the case.
- `POST /api/cases/{case_id}/action-packet` -> draft countermeasure text with evidence references and clear AI-generated label.
- `GET /api/replay/scenarios` -> the bundled offline replay scenarios, with their synthetic labels.
- `POST /api/replay/{scenario_id}/start` -> runs a bundled scenario through the normal text/URL analysis flow and saves a case marked as replay data.

## Claims, history and replay

- Text submissions return `claims`: separate statements with `id`, `text`, `verdict`, and `rationale`. The current verdict is always `unverified`, because no external evidence source is queried.
- Each claim also has `kind` (`factual`, `opinion`, `question`, `call_to_action` or `fragment`), `checkable` (true only for `factual`) and `entities`. An entity has `text`, `type` (`date`, `number`, `person`, `organization`, `place` or `other`), `value`, `unit`, `bound`, `source` (`rule` or `model`) and `score`. A date's `value` is ISO text at the precision stated, such as `2024-03` or `--03-05`, and is `null` for a relative or ambiguous date. Names and places need the optional `dslim/bert-base-NER` model.
- `claim_analysis` is `null` when no text was submitted. Otherwise it has `entity_model_status` (a module status), `entity_model_reason`, `inconsistencies`, `omitted_claims` (statements past the limit of 20) and `limitations`.
- An inconsistency has `id`, `kind`, `severity`, `claim_ids` and `explanation`. `kind` is `negation`, `figures`, `dates`, `places`, `impossible_date`, `weekday_mismatch`, `future_date`, `impossible_share` or `part_exceeds_whole`, and the UI must show an unknown kind as text. `severity` is `conflict` (they cannot both stand as written) or `note` (they differ but need not be wrong). A flag never says which statement is wrong, and it does not change any score or `overall_risk`. Each one is also added to `modules.text.evidence`.
- Every normal or replay analysis is retained in a local SQLite case store. The store saves the analysis result, not the original upload; uploaded media remains temporary and is deleted after analysis. A traced case also saves the public account handles and post links it found.
- Replay scenarios are synthetic and offline. Their responses set `is_replay: true` and include `replay_label`; the UI must display that label.
- `action-packet` returns structured `sections` alongside its readable draft. It is an evidence-based template, not an AI-generated or independently verified statement.

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

## Source search and public-post trace

Nothing leaves the server unless the request sets `search_web` to `true`. The UI must ask first and say what is sent:

| Step | Runs when | Sent to |
|---|---|---|
| Source search | A valid image is uploaded with `search_web` | The image, to each provider with a key set (Google Vision, TinEye, SerpApi). Result pages are then read to find dates and confirm matches. |
| Public-post trace | Any case with `search_web` | The text, the link, and up to 10 page links from the source search, to the search services of the connected public platforms. |

Both add to the request's time: the source search can take about 100 seconds with all three keys, and the trace up to about 25 seconds. With a `false` or absent `search_web`, cases take no extra outside time. A rejected upload is never searched.

Every case has `modules.provenance`, a normal module result:

- `score` and `confidence` are always `null`. A search result proves nothing about authenticity.
- `status` is `complete` if a search ran, `unavailable` with the reason (no key set, a video, every provider failed), or `not_applicable` if none was requested.

`modules.network` is `complete` or `unavailable` for a traced case, using the existing module shape. When no trace was requested it stays `unavailable`, with a reason saying nothing was sent.

**Neither module changes `overall_risk`.** They describe where content was found, not whether it is true. A network `score` on a traced case is a heuristic about how content spread, and the UI must not present it as proof that accounts are connected or automated.

`GET /api/cases/{case_id}/provenance` returns:

```json
{
  "case_id": "...",
  "status": "complete",
  "searched_at": "2026-11-05T12:00:00Z",
  "replay": false,
  "synthetic": false,
  "media_sha256": "...",
  "phash": "...",
  "providers": [{"name": "tineye", "status": "complete", "result_count": 12, "limitation": null}],
  "earliest_found": {
    "appearance_id": "a1",
    "observed_at": "2016-05-23T10:00:00Z",
    "date_source": "page_metadata",
    "caveat": "Earliest appearance these searches found. The true source may be older or elsewhere."
  },
  "appearances": [{
    "id": "a1", "page_url": "https://...", "page_title": "...", "domain": "...",
    "platform": "news", "image_url": "https://...", "match_type": "exact", "phash_distance": 3,
    "observed_at": "2016-05-23T10:00:00Z", "date_source": "page_metadata",
    "date_evidence": "JSON-LD datePublished on the page", "provider": "tineye"
  }],
  "limitations": ["..."]
}
```

- `platform` is `news`, `social`, `web` or `unknown`. `match_type` is `exact`, `partial` or `similar`. `date_source` is `page_metadata`, `crawl_date`, `social_post`, `reference_index` or `none`.
- `page_url`, `page_title`, `domain`, `image_url`, `phash_distance`, `observed_at`, `date_evidence` and `earliest_found` can be `null`.
- The UI must show `earliest_found.caveat` and never call that page "the source" or "the original".
- `replay: true` means recorded results, and `synthetic: true` means invented ones. The UI must show both labels.
- A case with no saved search returns `status: "not_applicable"` and no appearances. An unknown case returns 404.

`GET /api/cases/{case_id}/timeline` returns dated events first, oldest first. Undated events stay at the end with `at: null` and are never given an invented date:

```json
{"events": [{"at": "2026-01-15T09:00:00Z", "kind": "web_appearance", "label": "...", "module": "provenance", "ref": "a1", "date_source": "page_metadata", "synthetic": false}]}
```

`kind` is `web_appearance`, `social_post` or `cluster_activity`. `module` is `provenance` or `network`.

Setting `PROVENANCE_REPLAY_PATH` replays recorded searches and also stops live traces, so a replay stays offline. Submitting the demo story's exact text or link with `search_web` replays its labelled synthetic posts offline. The source search report and the trace are saved with the case, so they survive a restart. `GET /api/cases/{case_id}/explanation` is not built yet.

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
    "provenance": {"status": "not_applicable", "score": null, "confidence": null, "evidence": [], "limitations": []},
    "network": {"status": "not_applicable", "score": null, "confidence": null, "evidence": [], "limitations": []}
  },
  "uncertainties": [],
  "recommended_actions": []
}
```

This is the current response shape. The backend exposes Pydantic/OpenAPI types and deterministic rule-based text/URL results.
