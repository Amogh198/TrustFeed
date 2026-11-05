# TrustFeed frontend UX contract

## Supported local flow

1. An analyst opens **New investigation**.
2. They choose text, URL, or media. Text and URL require content; media requires a local file selection.
3. The UI validates missing input inline, then submits to the configured local API. Source search stays off until the analyst explicitly consents.
4. A saved case report opens with assessment, provenance, evidence, dissemination graph, timeline, and a clearly labelled next step.

## State rules

| State | Required UI behaviour |
| --- | --- |
| Empty text / URL | Explain what is missing; do not navigate away. |
| Empty media | Ask for a local image or video selection. |
| Preparing | Disable the submit action and show whether a local analysis or opted-in source search is running. |
| Replay result | Keep the replay banner and label synthetic or replay data. Replay scenarios use the API's recorded scenario route. |
| Provenance unavailable | Show what is missing and never imply verified origin. |
| Source search | Default off. Consent explains that images go to configured source-search services and text/links go to Mastodon, Lemmy, and Hacker News. |
| Graph/timeline | Label fixture metadata and co-sharing patterns as analytical leads, not coordination or intent. |

## Boundaries

- The normal intake flow calls `VITE_API_BASE_URL` (default `http://localhost:8000`); it makes no third-party request unless source search is opted in.
- Replay uses the API's labelled recorded-scenario routes. It is not presented as a live feed or verification service.
- API errors are not simulated as successful results. Failures remain visible and do not replace the last good report.

## Accessibility baseline

- Keyboard focus is visible on all interactive controls.
- Form notices use a polite live region.
- Native controls carry the consent and media-selection semantics.
- Reduced-motion users do not receive nonessential spinner or graph/timeline motion.
