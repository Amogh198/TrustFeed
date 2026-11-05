AGENT: Bhuvan Bapat (bhuvanbapat), lane bhuvan_claude
RESPONSIBILITY: T2 network tracing: dataset, co-sharing, graph scoring, role tags, timeline, real-post adapters, multi-platform monitoring
BRANCH: feat/scam-detection
CURRENT TASK: Text, link, report and dashboard work assigned by Bhuvan; item 3 of 10: scam detection, stacked on feat/claim-verification (PR #32); paths assigned by Bhuvan beyond T2: backend/text, backend/api, frontend, API_CONTRACTS.md
STATUS: Validated
COMPLETED: Item 1 with the real NER model; item 2: Wikipedia, GDELT and Fact Check sources, MiniLM and DeBERTa comparison, cautious verdicts
IN PROGRESS: none
NEXT ACTION: Item 3, scam detection; its model download needs Bhuvan's approval
FILES OWNED: backend/network/**, data/demo/network_demo*, data/demo/README.md
LATEST COMMIT: see feat/claim-verification
INTERFACES CHANGED: Additive: ClaimRecord gains kind, checkable, entities, sources; new verdict values; AnalysisResponse gains claim_analysis. See API_CONTRACTS.md
DEPENDENCIES: PR #30 changes the same text and API files; the merge is expected to need small conflict fixes
BLOCKERS: none; GDELT rate limits often, and a Fact Check key is optional
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
