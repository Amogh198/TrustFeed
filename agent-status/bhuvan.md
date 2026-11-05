AGENT: Bhuvan Bapat (bhuvanbapat), lane bhuvan_claude
RESPONSIBILITY: T2 network tracing: dataset, co-sharing, graph scoring, role tags, timeline, real-post adapters, multi-platform monitoring
BRANCH: fix/network-trace-hardening
CURRENT TASK: Findings, real-post tracing, monitoring and demo story are merged (PRs #9-#11); security hardening still needs merging
STATUS: Validated
COMPLETED: Five findings fixed; Mastodon, Lemmy and Hacker News adapters; trace_case; Monitor; demo-story-001; 185 tests pass offline, plus manual live runs
IN PROGRESS: none
NEXT ACTION: Connect Bluesky, Reddit or YouTube if the team gets credentials; add Mastodon repost data; support T3 wiring
FILES OWNED: backend/network/**, data/demo/network_demo*, data/demo/README.md
LATEST COMMIT: see fix/network-trace-hardening
INTERFACES CHANGED: Additive: nodes gain appears_at; new trace_case, get_network_coverage, Monitor, get_demo_story, demo-story-001. See backend/network/README.md
DEPENDENCIES: T3 must call trace_case and expose get_network_coverage; T1 provenance page links feed its urls argument; T4 must show synthetic labels and use appears_at
BLOCKERS: none; development isn't blocked
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
