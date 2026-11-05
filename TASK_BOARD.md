# Task Board — TruthTrace AI

This is the work split, and it is enough to determine responsibilities; Issues are optional. **Live status is in `agent-status/`**, shown by `python tools/agent_sync.py`. The integration coordinator alone updates this summary table when packages change. This avoids simultaneous edits and Markdown merge conflicts.

## Difficulty-based ownership

| ID | Difficulty | Work package | Primary AI | Human partner | Path ownership (proposed) |
|---|---|---|---|---|---|
| T1 | Hard | Media forensics adapter: run one chosen image model, metadata, video keyframe sampling, pHash match, explainable evidence JSON | `akshay_claude` (Claude A) | M1 / vision lead | `backend/media/**` |
| T2 | Hard | Synthetic social dataset, time-window co-sharing, graph/community scoring, patient-zero/role tags, timeline JSON | `bhuvan_claude` (Claude B) | M2 / graph lead | `backend/network/**`, `data/demo/**` |
| T3 | Medium/Hard | FastAPI app, text/claim and URL rules, unified response/fusion, demo fixtures and replay endpoint; publish shared API contract first | Gemini lane 1 | M3 / backend & integration coordinator | `backend/api/**`, `backend/text/**`, `contracts/**` |
| T4 | Medium | React dashboard, upload/text workflow, evidence panel, graph/timeline rendering, replay-mode presentation | Gemini lane 2 | M4 / UI lead | `frontend/**` |
| T5 | Medium | End-to-end wiring, offline replay, demo script/data, bug fixes | Assigned by the coordinator, who sequences it after T1–T4 | M3 coordinates | only explicitly assigned paths |

M1–M4 and the Claude/Gemini labels are role placeholders. Actual GitHub handles are recorded in `AGENT_COORDINATION.md`. `akshay_claude` and `bhuvan_claude` are account labels, not GitHub usernames.

## Order and dependencies

1. T3 publishes minimal request/response schemas in `API_CONTRACTS.md`; other lanes read them, and raise concerns without waiting, before building adapters/UI.
2. T1 and T2 can build independently against those schemas or isolated internal result models. They must not edit `contracts/**` without agreement.
3. T3 provides deterministic mock responses early so T4 can build without waiting for ML models or live APIs.
4. T4 consumes only the agreed response models; it does not reach into backend internals.
5. T5 integration starts when each lane exposes a working demo fixture. Freeze features around hour 18 of the 24-hour event; leave final time for QA and rehearsal.

## Keep scope feasible

- Do not attempt to integrate Harken, LockStep, OSoMe, DeepTrace, Nonescape, and DeepfakeBench all at once. The blueprint lists them as candidate references, not required dependencies. Before adopting any, check install/runtime cost, license, data/network needs, and whether it helps the demo. Prefer a small adapter or synthetic replay where setup threatens schedule.
- Live platform ingestion, audio model inference, robust bot attribution, and regulatory/legal conclusions are optional. Demo with synthetic or user-provided sample data and label simulated evidence clearly.
- Deliver a vertical slice: input -> analysis -> evidence-backed/inconclusive result -> coordinated-spread visualization -> action packet -> offline replay.

## Status vocabulary

Use only: `Ready`, `Doing`, `Validated`, `Blocked`, `Done`. Each agent's status file is canonical; this file is an ownership/dependency map, not a live activity feed.
