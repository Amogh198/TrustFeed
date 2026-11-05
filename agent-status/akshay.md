AGENT: Akshay (Akshaynbhat), lane akshay_claude
RESPONSIBILITY: T1 media forensics and image provenance: detector, metadata, keyframes, pHash, web source search, benchmark, explanations
BRANCH: feat/media-explanations
CURRENT TASK: Explanation checks (to_checks) and the occlusion heatmap
STATUS: Doing
COMPLETED: Media adapter (PR #5); API wiring (PR #7); web source search (PR #12); benchmark tool (PR #15); search and trace in the API (PR #18); first accuracy results (PR #19); benchmark record correction (PR #20); first real SerpApi searches
IN PROGRESS: PR for to_checks and the heatmap, waiting on Akshay's word to merge
NEXT ACTION: Record one offline demo search, rerun the benchmark in its own PR; detector thresholds or training wait for Akshay's decision. T3 builds the /explanation route, using these functions
FILES OWNED: backend/media/**, backend/provenance/**, data/demo/provenance_demo*, data/eval/**
LATEST COMMIT: see my newest branch on GitHub
INTERFACES CHANGED: adds search_web, modules.provenance, /provenance, /timeline and /network/{id}/coverage to the API, in API_CONTRACTS.md; T3 reviews, T4 builds on it
DEPENDENCIES: T2 shares a media hash for the demo case
BLOCKERS: none
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
