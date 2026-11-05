AGENT: Akshay (Akshaynbhat), lane akshay_claude
RESPONSIBILITY: T1 media forensics and image provenance: detector, metadata, keyframes, pHash, web source search, benchmark, explanations
BRANCH: feat/media-forensics
CURRENT TASK: Media prompt items 4 to 10, together in one PR: forensics, faces, OCR, video, synthetic speech, lip-sync decision, search history
STATUS: Doing
COMPLETED: Media adapter (#5); API wiring (#7); web source search (#12); benchmark tool (#15); search and trace in the API (#18); accuracy results (#19, #20); detector panel (#33); ImageHash fingerprints (#34); Content Credentials (#35)
IN PROGRESS: One PR for items 4 to 10, waiting on Akshay's word to merge
NEXT ACTION: Which detector drives the score, and whether a fingerprint match or a signed AI declaration counts as a signal, wait for Akshay's decision. Install Tesseract to run OCR for real
FILES OWNED: backend/media/**, backend/provenance/**, data/demo/provenance_demo*, data/eval/**
LATEST COMMIT: see my newest branch on GitHub
INTERFACES CHANGED: to_checks() adds media.forensics, faces, ocr, speech, audio_synthetic, frames and provenance.similar. Media result adds extracted_text. No API routes or contracts change
DEPENDENCIES: PyAV and pytesseract in requirements-model.txt. Tesseract program is optional and installed separately
BLOCKERS: none
LAST UPDATED: 2026-11-06
PROTOCOL: adopted 2026-11-05
