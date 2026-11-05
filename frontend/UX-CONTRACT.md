# TrustFeed frontend UX contract

## Supported local flow

1. An analyst opens **New investigation**.
2. They choose text, URL, or media. Text and URL require content; media requires a local file selection.
3. The UI validates missing input inline, then shows a short **Preparing replay** busy state.
4. A deterministic report opens with assessment, provenance, evidence, dissemination graph, timeline, and a clearly labelled next step.

## State rules

| State | Required UI behaviour |
| --- | --- |
| Empty text / URL | Explain what is missing; do not navigate away. |
| Empty media | Ask for a local image or video selection. |
| Preparing | Disable the submit action and state that a local deterministic report is being prepared. |
| Replay result | Keep the replay banner and state that no live model, feed, or verification service was queried. |
| Provenance unavailable | Show what is missing and never imply verified origin. |
| Source search | Default off. Consent must be explicit because a real search could share an image with a third party. This build does not perform a search. |
| Graph/timeline | Label fixture metadata and co-sharing patterns as analytical leads, not coordination or intent. |

## Boundaries

- No network request, upload, model call, or browser persistence is made by this frontend replay flow.
- The interface uses deterministic fixtures from `src/fixtures.js` until an agreed API contract is connected.
- API errors are not simulated as successful results. When an API is added, failures must remain in place with a retry path and must not replace the last good report.

## Accessibility baseline

- Keyboard focus is visible on all interactive controls.
- Form notices use a polite live region.
- Native controls carry the consent and media-selection semantics.
- Reduced-motion users do not receive nonessential spinner or graph/timeline motion.
