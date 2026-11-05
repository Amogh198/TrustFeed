AGENT: Bhuvan Bapat (bhuvanbapat), lane bhuvan_claude
RESPONSIBILITY: T2 network tracing; also rebuilding the T4 dashboard at Bhuvan's request
BRANCH: feat/dashboard-rebuild
CURRENT TASK: Dashboard rebuild against the published API, stacked on fix/full-project-audit
STATUS: Validated
COMPLETED: Trust score and visible reasoning; tools/start_demo.py; new dashboard: spread replay, findings, media with benchmark and heatmap, source, timeline, action packet, cases, watch, walkthrough, limits
IN PROGRESS: none
NEXT ACTION: Merge PR #24 and resolve its conflict with PR #25, then this branch. T1 band decision is the biggest gap in the demo
FILES OWNED: backend/network/**, data/demo/network_demo*, data/demo/README.md; frontend/** for this rebuild
LATEST COMMIT: see feat/dashboard-rebuild
INTERFACES CHANGED: None. Frontend only: same API routes. New frontend npm scripts: test, typecheck, lint, check
DEPENDENCIES: T3 routes from fix/full-project-audit, which isn't on main yet
BLOCKERS: none; compat_check fails only on the PR #24 and #25 merge conflict
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
