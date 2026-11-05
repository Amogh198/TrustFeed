AGENT: Akshay (Akshaynbhat), lane akshay_claude
RESPONSIBILITY: T1 image model, metadata, video keyframes, pHash match, explainable evidence JSON
BRANCH: feat/wire-media-network-api
CURRENT TASK: Wiring T1 and T2 into the T3 API, at Akshay's request; touches T3 files, so Amogh is notified on the PR
STATUS: Validated
COMPLETED: Media forensics adapter merged in PR #5; all open PRs merged in order #6, #1, #5, #3
IN PROGRESS: PR for the upload route, demo network route and media fusion, not yet merged
NEXT ACTION: Test the detector on known real and fake samples when Akshay provides them
FILES OWNED: backend/media/**
LATEST COMMIT: see feat/wire-media-network-api on GitHub
INTERFACES CHANGED: POST /api/cases/analyze-media added; media is not_applicable on JSON cases; demo-001 served; see API_CONTRACTS.md
DEPENDENCIES: T3 owns the changed API files; T4 consumes the new upload route
BLOCKERS: none known
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
