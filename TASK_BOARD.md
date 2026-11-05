# Task Board — TruthTrace AI

This is the initial work split. **GitHub Issues are the live status board.** Create one Issue per task package, assign the human/AI pair, list exact allowed paths and acceptance criteria, and link its PR. Agents update the Issue at milestones; the integration coordinator alone updates this summary table when packages change. This avoids simultaneous edits and Markdown merge conflicts.

## Difficulty-based ownership

| ID | Difficulty | Work package | Primary AI | Human partner | Path ownership (proposed) | Independent reviewer |
|---|---|---|---|---|---|---|
| T1 | Hard | Media forensics adapter: run one chosen image model, metadata, video keyframe sampling, pHash match, explainable evidence JSON | `akshay_claude` (Claude A) | M1 / vision lead | `backend/media/**` | `bhuvan_claude` |
| T2 | Hard | Synthetic social dataset, time-window co-sharing, graph/community scoring, patient-zero/role tags, timeline JSON | `bhuvan_claude` (Claude B) | M2 / graph lead | `backend/network/**`, `data/demo/**` | `akshay_claude` |
| T3 | Medium/Hard | FastAPI app, text/claim and URL rules, unified response/fusion, demo fixtures and replay endpoint; publish shared API contract first | Gemini lane 1 | M3 / backend & integration coordinator | `backend/api/**`, `backend/text/**`, `contracts/**` | Gemini lane 2; consult A/B for their payload contracts |
| T4 | Medium | React dashboard, upload/text workflow, evidence panel, graph/timeline rendering, replay-mode presentation | Gemini lane 2 | M4 / UI lead | `frontend/**` | Gemini lane 1 |
| T5 | Medium | End-to-end wiring, offline replay, demo script/data, bug fixes | Assigned by issue; coordinator sequences it after T1–T4 | M3 coordinates | only explicitly assigned paths | non-author AI lane |

M1–M4 and the Claude/Gemini labels are role placeholders. Record actual GitHub handles and who operates each account in the kickoff Issue. `akshay_claude` and `bhuvan_claude` are account labels, not GitHub usernames.

## Order and dependencies

1. T3 publishes minimal request/response schemas in `API_CONTRACTS.md`; other lanes review the schemas before building adapters/UI.
2. T1 and T2 can build independently against those schemas or isolated internal result models. They must not edit `contracts/**` without agreement.
3. T3 provides deterministic mock responses early so T4 can build without waiting for ML models or live APIs.
4. T4 consumes only the agreed response models; it does not reach into backend internals.
5. T5 integration starts when each lane exposes a working demo fixture. Freeze features around hour 18 of the 24-hour event; leave final time for QA and rehearsal.

## Keep scope feasible

- Do not attempt to integrate Harken, LockStep, OSoMe, DeepTrace, Nonescape, and DeepfakeBench all at once. The blueprint lists them as candidate references, not required dependencies. Before adopting any, check install/runtime cost, license, data/network needs, and whether it helps the demo. Prefer a small adapter or synthetic replay where setup threatens schedule.
- Live platform ingestion, audio model inference, robust bot attribution, and regulatory/legal conclusions are optional. Demo with synthetic or user-provided sample data and label simulated evidence clearly.
- Deliver a vertical slice: input -> analysis -> evidence-backed/inconclusive result -> coordinated-spread visualization -> action packet -> offline replay.

## Status vocabulary

Use only: `Ready`, `Doing`, `In Review`, `Blocked`, `Done`. The Issue is canonical; this file is an ownership/dependency map, not a live activity feed.
