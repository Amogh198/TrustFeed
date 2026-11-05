AGENT: Akshay (Akshaynbhat), lane akshay_claude
RESPONSIBILITY: T1 media forensics and image provenance: detector, metadata, keyframes, pHash, web source search, benchmark, explanations
BRANCH: feat/wire-provenance-tracing
CURRENT TASK: Connect source search and the public-post trace to the API, at Akshay's request, then benchmark results, explanations and heatmap
STATUS: Doing
COMPLETED: Media adapter (PR #5); API wiring (PR #7); web source search (PR #12), merged but no real search run yet; benchmark tool (PR #15)
IN PROGRESS: API wiring in its PR, which edits T3 files because Akshay asked for it; the first full benchmark run is still going, so there are no accuracy figures yet
NEXT ACTION: Publish benchmark results in a separate PR; run one real search once Akshay has a key; build to_checks and the heatmap
FILES OWNED: backend/media/**, backend/provenance/**, data/demo/provenance_demo*, data/eval/**
LATEST COMMIT: see my newest branch on GitHub
INTERFACES CHANGED: adds search_web, modules.provenance, /provenance, /timeline and /network/{id}/coverage to the API, in API_CONTRACTS.md; T3 reviews, T4 builds on it
DEPENDENCIES: T2 shares a media hash for the demo case
BLOCKERS: a real web search needs Akshay to create a provider key
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
