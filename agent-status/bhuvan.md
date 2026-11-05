AGENT: Bhuvan Bapat (bhuvanbapat), lane bhuvan_claude
RESPONSIBILITY: T2 network tracing: dataset, co-sharing, graph scoring, role tags, timeline, real-post adapters, multi-platform monitoring
BRANCH: feat/text-claims
CURRENT TASK: Text, link, report and dashboard work assigned by Bhuvan; item 1 of 10: split claims, entities, inconsistency flags
STATUS: Validated
COMPLETED: Claim splitting and kinds; rule-based dates and numbers; context-aware inconsistency flags; optional NER adapter tested with a fake only
IN PROGRESS: none
NEXT ACTION: Item 2, claim verification, once the model downloads are approved; real NER run needs the same approval
FILES OWNED: Assigned by Bhuvan for this work: backend/text/**, backend/api/**, backend/network/**, frontend/**, API_CONTRACTS.md
LATEST COMMIT: see feat/text-claims
INTERFACES CHANGED: Additive: ClaimRecord gains kind, checkable, entities; AnalysisResponse gains claim_analysis. See API_CONTRACTS.md
DEPENDENCIES: PR #30 changes the same text and API files; the merge is expected to need small conflict fixes
BLOCKERS: Model downloads await Bhuvan's approval; rules work without them
LAST UPDATED: 2026-11-05
PROTOCOL: adopted 2026-11-05
