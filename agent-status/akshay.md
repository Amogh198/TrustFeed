AGENT: Akshay (Akshaynbhat), lane akshay_claude
RESPONSIBILITY: T1 media forensics and image provenance: detector, metadata, keyframes, pHash, web source search, benchmark, explanations
BRANCH: feat/media-content-credentials
CURRENT TASK: Media prompt item 3: Content Credentials with c2pa-python
STATUS: Doing
COMPLETED: Media adapter (#5); API wiring (#7); web source search (#12); benchmark tool (#15); search and trace in the API (#18); accuracy results (#19, #20); detector panel (#33); ImageHash fingerprints (#34)
IN PROGRESS: PR for the media.c2pa check, waiting on Akshay's word to merge
NEXT ACTION: Item 4, forensics with OpenCV and NumPy. Which detector drives the score, and whether a fingerprint match or a signed AI declaration counts as a signal, wait for Akshay's decision
FILES OWNED: backend/media/**, backend/provenance/**, data/demo/provenance_demo*, data/eval/**
LATEST COMMIT: see my newest branch on GitHub
INTERFACES CHANGED: to_checks() adds media.c2pa, in the existing check shape. No API routes or contracts change
DEPENDENCIES: backend/media/requirements.txt adds c2pa-python, so reinstall to enable the check. Without it the check reports unavailable
BLOCKERS: none
LAST UPDATED: 2026-11-06
PROTOCOL: adopted 2026-11-05
