AGENT: manasprashant06-ux, T4 frontend
RESPONSIBILITY: T4 React dashboard, upload and text workflow, evidence panel, graph and timeline, replay mode
BRANCH: feature/manas-api-integration
CURRENT TASK: Connect the React dashboard to the published T3 HTTP API.
STATUS: Doing
COMPLETED: Dashboard and offline replay presentation merged in PR #17.
IN PROGRESS: API client, submission, results, provenance, timeline, network coverage, history, export and action-packet wiring.
NEXT ACTION: Run API and frontend together, then publish the integration PR.
FILES OWNED: frontend/**
LATEST COMMIT: pending
INTERFACES CHANGED: T4 consumes existing T3 HTTP endpoints only; no contract change.
DEPENDENCIES: T3 HTTP responses (PR #1); T2 payload fields in backend/network/README.md (PR #3)
BLOCKERS: Local API smoke test is blocked because backend dependencies are not installed in this workspace; the frontend build is available.
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
