AGENT: Amogh (Amogh198), repo admin, T3 lane
RESPONSIBILITY: T3 FastAPI API, text/URL rules, fusion, contracts, replay and local case history
BRANCH: feat/amogh-replay-history
CURRENT TASK: Ship an offline replay/history/action-packet milestone and backend CI
STATUS: Doing
COMPLETED: API/media/network fusion is on main; this branch adds claims, local history, replay, export, structured action packets and CI
IN PROGRESS: Final compatibility check and remote backup of the T3 replay/history milestone
NEXT ACTION: T4 can consume the published routes; final integration merges this branch after the other lanes are ready
FILES OWNED: backend/api/**, backend/text/**, contracts/**, API_CONTRACTS.md, .github/workflows/backend-api.yml, pyrightconfig.json
LATEST COMMIT: pending first replay/history milestone commit
INTERFACES CHANGED: Added claims, case-history, export and replay routes; existing response fields remain compatible
DEPENDENCIES: T1 media result and T2 network functions already integrated on main
BLOCKERS: Windows OpenCV cannot encode MP4 test fixtures locally; non-video API checks pass
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
