AGENT: Akshay (Akshaynbhat), lane akshay_claude
RESPONSIBILITY: T1 media forensics and image provenance: detector, metadata, keyframes, pHash, web source search, benchmark, explanations
BRANCH: feat/media-benchmark
CURRENT TASK: Accuracy benchmark for the media detector, then explanations and heatmap
STATUS: Doing
COMPLETED: Media adapter (PR #5); API wiring (PR #7); web source search (PR #12), merged but no real search run yet
IN PROGRESS: Benchmark tool in its PR; the first full run on openly licensed images is still going, so there are no accuracy figures yet
NEXT ACTION: Publish benchmark results in a separate PR; run one real search once Akshay has a key; build to_checks and the heatmap
FILES OWNED: backend/media/**, backend/provenance/**, data/demo/provenance_demo*, data/eval/**
LATEST COMMIT: see my newest branch on GitHub
INTERFACES CHANGED: adds backend.provenance.investigate_provenance per draft v2, plus reference_index, synthetic, media_sha256, phash, nullable page_url; T3 decides
DEPENDENCIES: T3 publishes contract v2 and calls investigate_provenance; T2 shares a media hash for the demo case
BLOCKERS: a real web search needs Akshay to create a provider key
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
