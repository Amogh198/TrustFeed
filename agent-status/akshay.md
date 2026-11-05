AGENT: Akshay (Akshaynbhat), lane akshay_claude
RESPONSIBILITY: T1 media forensics and image provenance: detector, metadata, keyframes, pHash, web source search, benchmark, explanations
BRANCH: fix/audit-items
CURRENT TASK: Make Nonescape mini the default detector, as Akshay decided on 2026-11-06
STATUS: Doing
COMPLETED: Media adapter (#5); API wiring (#7); source search (#12); benchmark (#15); search and trace (#18); accuracy results (#19, #20); detector panel (#33); fingerprints (#34); Content Credentials (#35); media items 4 to 10 (#36)
IN PROGRESS: Default detector PR, waiting on Akshay's word to merge
NEXT ACTION: Whether a fingerprint match or a signed AI declaration counts as a signal, and any band change, wait for Akshay's decision. Install Tesseract to run OCR for real
FILES OWNED: backend/media/**, backend/provenance/**, data/demo/provenance_demo*, data/eval/**
LATEST COMMIT: see my newest branch on GitHub
INTERFACES CHANGED: Default media model_id is now nonescape/nonescape-mini-v0, so scores change. No routes or response shapes change
DEPENDENCIES: PyAV and pytesseract in requirements-model.txt. Tesseract program is optional and installed separately
BLOCKERS: none
LAST UPDATED: 2026-11-06
PROTOCOL: adopted 2026-11-05
