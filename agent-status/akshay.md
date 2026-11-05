AGENT: Akshay (Akshaynbhat), lane akshay_claude
RESPONSIBILITY: T1 media forensics and image provenance: detector, metadata, keyframes, pHash, web source search, benchmark, explanations
BRANCH: feat/clear-upload-results
CURRENT TASK: Clear results for every upload: combines #24 and #26, fixes the trust score, renames to TrustFeed
STATUS: Doing
COMPLETED: Media adapter (PR #5); API wiring (PR #7); web source search (PR #12); benchmark tool (PR #15); search and trace in the API (PR #18); first accuracy results (PR #19); benchmark record correction (PR #20); explanation checks and heatmap (PR #22); first real SerpApi searches
IN PROGRESS: Combined PR, waiting on Akshay's word to merge; benchmark rerun with the fixed downloader
NEXT ACTION: Publish the benchmark in its own PR, then measure extra signals; detector thresholds or training wait for Akshay's decision
FILES OWNED: backend/media/**, backend/provenance/**, data/demo/provenance_demo*, data/eval/**
LATEST COMMIT: see my newest branch on GitHub
INTERFACES CHANGED: adds search_web, modules.provenance, /provenance, /timeline and /network/{id}/coverage to the API, in API_CONTRACTS.md; T3 reviews, T4 builds on it
DEPENDENCIES: T2 shares a media hash for the demo case
BLOCKERS: none
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
