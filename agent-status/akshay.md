AGENT: Akshay (Akshaynbhat), lane akshay_claude
RESPONSIBILITY: T1 media forensics and image provenance: detector, metadata, keyframes, pHash, web source search, benchmark, explanations
BRANCH: feat/image-provenance
CURRENT TASK: Web provenance module in backend/provenance, then the accuracy benchmark
STATUS: Doing
COMPLETED: Media adapter (PR #5); wiring of T1 and T2 into the API (PR #7); both merged to main
IN PROGRESS: Provenance PR open against draft contract v2; no real provider search run yet because it needs a key
NEXT ACTION: Run one real search once Akshay has a key; build backend/media/eval on feat/media-benchmark
FILES OWNED: backend/media/**, backend/provenance/**, data/demo/provenance_demo*, data/eval/**
LATEST COMMIT: see my newest branch on GitHub
INTERFACES CHANGED: adds backend.provenance.investigate_provenance per draft v2, plus reference_index, synthetic, media_sha256, phash, nullable page_url; T3 decides
DEPENDENCIES: T3 publishes contract v2 and calls investigate_provenance; T2 shares a media hash for the demo case
BLOCKERS: none known; a real web search needs Akshay to create a provider key
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
