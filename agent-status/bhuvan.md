AGENT: Bhuvan Bapat (bhuvanbapat), lane bhuvan_claude
RESPONSIBILITY: T2 network tracing: dataset, co-sharing, graph scoring, role tags, timeline, real-post adapters, multi-platform monitoring
BRANCH: fix/network-findings
CURRENT TASK: Fix the five T2 findings, then add real-post adapters and platform monitoring
STATUS: Doing
COMPLETED: Network engine merged (PR #3); wired into API by PR #7; all five findings fixed on fix/network-findings with 42 new tests
IN PROGRESS: Checking which public platforms can really be read, then building adapters
NEXT ACTION: Real-post adapters and networks for real cases on their own branch
FILES OWNED: backend/network/**, data/demo/network_demo*, data/demo/README.md
LATEST COMMIT: see fix/network-findings
INTERFACES CHANGED: nodes gain appears_at; T4 should use it for the time slider instead of first_campaign_post_at. Additive.
DEPENDENCIES: none for the fixes
BLOCKERS: none; development isn't blocked
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
