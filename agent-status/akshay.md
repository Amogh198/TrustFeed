AGENT: Akshay (Akshaynbhat), lane akshay_claude
RESPONSIBILITY: T1 media forensics and image provenance: detector, metadata, keyframes, pHash, web source search, benchmark, explanations
BRANCH: feat/media-forensics
CURRENT TASK: Media prompt item 4: pixel forensics with OpenCV and NumPy
STATUS: Doing
COMPLETED: Media adapter (#5); API wiring (#7); web source search (#12); benchmark tool (#15); search and trace in the API (#18); accuracy results (#19, #20); detector panel (#33); ImageHash fingerprints (#34); Content Credentials (#35)
IN PROGRESS: PR for the media.forensics check, waiting on Akshay's word to merge
NEXT ACTION: Item 5, face regions. Which detector drives the score, and whether a fingerprint match or a signed AI declaration counts as a signal, wait for Akshay's decision
FILES OWNED: backend/media/**, backend/provenance/**, data/demo/provenance_demo*, data/eval/**
LATEST COMMIT: see my newest branch on GitHub
INTERFACES CHANGED: to_checks() adds media.forensics, in the existing check shape. No API routes or contracts change
DEPENDENCIES: none new
BLOCKERS: none
LAST UPDATED: 2026-11-06
PROTOCOL: adopted 2026-11-05
