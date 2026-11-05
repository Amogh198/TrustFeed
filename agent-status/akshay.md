AGENT: Akshay (Akshaynbhat), lane akshay_claude
RESPONSIBILITY: T1 media forensics and image provenance: detector, metadata, keyframes, pHash, web source search, benchmark, explanations
BRANCH: fix/benchmark-record-and-keys
CURRENT TASK: Correct the benchmark record and fix the image downloader, then explanations and heatmap
STATUS: Doing
COMPLETED: Media adapter (PR #5); API wiring (PR #7); web source search (PR #12); benchmark tool (PR #15); search and trace in the API (PR #18); first accuracy results (PR #19); first real SerpApi searches
IN PROGRESS: Correction PR for the benchmark record
NEXT ACTION: Build to_checks, the heatmap and /explanation; detector thresholds or training wait for Akshay's decision
FILES OWNED: backend/media/**, backend/provenance/**, data/demo/provenance_demo*, data/eval/**
LATEST COMMIT: see my newest branch on GitHub
INTERFACES CHANGED: adds search_web, modules.provenance, /provenance, /timeline and /network/{id}/coverage to the API, in API_CONTRACTS.md; T3 reviews, T4 builds on it
DEPENDENCIES: T2 shares a media hash for the demo case
BLOCKERS: none
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
