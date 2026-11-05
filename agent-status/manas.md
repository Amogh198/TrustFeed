AGENT: manasprashant06-ux, T4 frontend
RESPONSIBILITY: T4 React dashboard, upload and text workflow, evidence panel, graph and timeline, replay mode
BRANCH: feature/manas-api-integration
CURRENT TASK: Connect the React dashboard to the published T3 HTTP API.
STATUS: Validated locally; live API check pending backend availability.
COMPLETED: Dashboard and offline replay presentation merged in PR #17.
IN PROGRESS: Publish the integration branch; run the live API smoke check when backend is available.
NEXT ACTION: Start the backend and rerun `pnpm run smoke:api`, then open the integration PR.
FILES OWNED: frontend/**
LATEST COMMIT: 30a9b60
INTERFACES CHANGED: T4 consumes existing T3 HTTP endpoints only; no contract change.
DEPENDENCIES: T3 HTTP responses (PR #1); T2 payload fields in backend/network/README.md (PR #3)
BLOCKERS: Live API smoke test cannot pass until backend dependencies are installed and the API is running on localhost:8000. `compat_check.py` also cannot create its temporary worktree under the sandbox Temp directory.
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
