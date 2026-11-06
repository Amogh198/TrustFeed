AGENT: Bhuvan Bapat (bhuvanbapat), lane bhuvan_claude
RESPONSIBILITY: T2 network tracing: dataset, co-sharing, graph scoring, role tags, timeline, real-post adapters, multi-platform monitoring
BRANCH: feat/scam-detection
CURRENT TASK: Text, link, report and dashboard work assigned by Bhuvan; items 4 to 10 of 10 committed locally on feat/scam-detection, not pushed
STATUS: Validated
COMPLETED: Items 1 and 2; item 3: named scam signs for six categories, measured with the phishing model on labelled examples, results in backend/text/evaluation/results
IN PROGRESS: none
NEXT ACTION: Bhuvan decides what to push. Threat list keys and a CLIP alternative also await Bhuvan
FILES OWNED: backend/network/**, data/demo/network_demo*, data/demo/README.md
LATEST COMMIT: see feat/scam-detection
INTERFACES CHANGED: Additive: ClaimRecord gains kind, checkable, entities, sources; new verdict values; AnalysisResponse gains claim_analysis and scam_analysis. See API_CONTRACTS.md
DEPENDENCIES: PR #30 changes the same text and API files; the merge is expected to need small conflict fixes
BLOCKERS: none; GDELT rate limits often, and a Fact Check key is optional
LAST UPDATED: 2026-11-06
PROTOCOL: adopted 2026-11-05
