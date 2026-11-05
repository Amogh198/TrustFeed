# PROJECT TRUTHTRACE AI: MASTER HACKATHON CONTEXT & EXECUTION BLUEPRINT

> **Background document.** This is the original plan and is kept for technical reference. Where it differs from `AGENT_COORDINATION.md`, `TASK_BOARD.md` or `API_CONTRACTS.md`, those files win. In particular:
>
> - The exact official problem wording is in `AGENT_COORDINATION.md`. Section 2 below adds a countermeasures clause to the description.
> - Features below are proposed implementation unless `AGENT_COORDINATION.md` lists them as official requirements.
> - T3 owns all HTTP routes, so Developer 2's "network payload endpoints" are Python functions that T3 serves.
> - The "AI tooling" and developer role labels are superseded by the lanes in `TASK_BOARD.md`.
> - "Botnet" and "Patient Zero" describe a synthetic demo scenario. Results don't establish real bot activity, intent or attribution, and show the earliest observed account, not a proven origin.

---

## 1. PROJECT METADATA & CONSTRAINTS

| Parameter | Specification |
| :--- | :--- |
| **Project Name** | **TruthTrace AI** |
| **Hackathon Event** | LAKSHYA 2026 — 24-Hour National Level Hackathon (SJBIT) |
| **Problem Statement Name** | **AI-Driven Detection & Countermeasures Against Fake Social Media Content** |
| **Problem Statement ID** | **DL-SJBIT-HK26-GOVP006** |
| **Track / Domain** | Governance / AI & Smart Systems |
| **Target Build Duration** | **20 Hours Core Build** (+ 4 Hours Buffer / QA / Rehearsal) |
| **Team Size** | **4 Developers** |
| **AI Tooling Assets** | 2× Claude Pro Accounts, 2× Gemini Pro Accounts |
| **Primary Architectural Objective** | Build a software-based threat intelligence platform that ingests multimodal content (Text, Image, Video, Audio, URLs), investigates authenticity, traces dissemination networks, and produces evidence-backed threat reports with actionable countermeasures without requiring physical hardware or live social API dependencies. |

---

## 2. PROBLEM STATEMENT DEFINITION (DL-SJBIT-HK26-GOVP006)

### Official Description
Develop a multi-platform monitoring system that ingests multi-format social media content, uses AI models to detect synthetic media and deepfakes, traces the dissemination network of coordinated disinformation, and provides actionable countermeasures.

### Core Challenge & Scope
1. **Multimodal Deepfake & Synthetic Media Detection:** Classify visual, auditory, and textual content as real, synthetic, or manipulated using explainable metrics.
2. **Dissemination Tracing & Coordination Mapping:** Identify account clusters, bot networks, temporal co-sharing behaviors, and "Patient Zero" (origin node).
3. **Evidence-Backed Triage & Countermeasures:** Produce structured, actionable intelligence reports, automated debunking responses, and platform reporting packets.

---

## 3. FULL REQUIREMENT SPECIFICATION

### Module 1: Image & Video Intelligence Engine
* **Image Forensics:** Upload (JPG, PNG, WebP). Metadata extraction (EXIF, creation date, device info). OCR text extraction. Pre-trained AI-generated image classification. Forensic indicator detection (compression inconsistencies, visual artifacts). Reverse-search / visual similarity logic. Historical misattribution detection (identifying authentic old photos reused with false recent captions).
* **Video Forensics:** Video ingestion & keyframe extraction (scene-change sampling to avoid frame-by-frame latency). Frame-level AI visual analysis. Audio extraction for speech-to-text and subtitle/caption cross-referencing. Frame-by-frame timeline reporting highlighting suspicious intervals.
* **Context & Historical Verification:** Date, location, and caption cross-checking against trusted sources. Identification of recycled media paired with misleading claims.

### Module 2: Text, Claim & URL Intelligence Engine
* **Text & Claim Analysis:** Ingest text, posts, captions, and forwarded messages. Atomize long posts into individual factual claims. Detect manipulative, urgent, or emotionally charged language. Flag scam patterns, phishing attempts, and fraudulent announcements.
* **Claim Verification Engine:** Compare extracted claims against evidence from reliable databases/APIs. Categorize results: *Supported*, *Contradicted*, *Partially Supported/Context Missing*, or *Unverified*. Output clear rationale for verdicts.
* **URL & Scam Security Tracker:** URL risk evaluation, shortener expansion, and domain reputation analysis. Detect phishing/impersonation markers (e.g., fake banking/job portals). Generate URL safety metrics.

### Module 3: Deepfake & Media Forensics Engine
* **Image Deepfake Classifier:** Facial region extraction, artifact detection, lighting/shadow consistency checks, and frequency-domain analysis.
* **Video Deepfake Classifier:** Inter-frame facial continuity, lip-sync mismatch detection, and temporal movement anomalies.
* **Audio Authenticity (Advanced/Optional):** Extract audio tracks, run synthetic speech/voice-clone detection (Wav2Vec2), and highlight audio-visual synchronization gaps.
* **Forensic Report Engine:** Output model confidence ranges, active risk indicators, localized heatmaps/bounding boxes when supported, and explicit **"Inconclusive"** markers for ambiguous media.

### Module 4: Social Network & Dissemination Campaign Intelligence (Key Differentiator)
* **Social Data Ingest & Ingestion Sandbox:** Process post metadata (timestamps, handles, media hashes, hashtags, URLs). Detect duplicate text, copied captions, and burst-sharing activity across multiple handles.
* **Interactive Network Graph (NetworkX + React Force Graph):** Render nodes (accounts) and edges (co-shares, retweets, co-occurrences). Graph community clustering (Louvain algorithm). Highlight central hubs, amplifiers, and origin nodes.
* **Coordinated Campaign Detection:** Calculate a **Coordination Risk Score** based on short time-window co-sharing ($\le 120\text{s}$), identical text embeddings, and shared media hashes.
* **Content Propagation Timeline:** Interactive timeline UI displaying how a claim or image spread from its earliest recorded appearance across account networks.

### Module 5: Unified AI Threat Intelligence Engine
* **Multi-Signal Risk Fusion:** Aggregate scores across Visual, Text, URL, Network, and Forensic modules into a single calibrated rating (*Low, Moderate, High, Critical, Inconclusive*). Apply a **Disagreement Penalty** when models conflict to prevent false confidence.
* **Explainable AI Intelligence Report:** Produce structured human-readable breakdowns explaining *What was submitted*, *What was detected*, *Which evidence supports/refutes it*, and *What uncertainties remain*.
* **Actionable Countermeasures:** Draft platform debunk posts, public fact-check summary cards, and compliance triage alerts (aligned with compressed regulatory takedown timelines).

### Module 6: Executive Operations Dashboard
* **Unified UI:** Tabbed workflow for Media Forensics, Text/URL Inspection, Network Graph Explorer, and Case History.
* **Case History & Exporting:** View active investigation lists, filter by risk level, and export structured digital reports.

---

## 4. SYSTEM ARCHITECTURE & TECH STACK

```
                                  ┌───────────────────────────┐
                                  │   MULTIMODAL INPUT FEED   │
                                  │ (Image, Video, Text, URL) │
                                  └─────────────┬─────────────┘
                                                │
                                                ▼
                                  ┌───────────────────────────┐
                                  │   FastAPI Gateway Hub     │
                                  └─────────────┬─────────────┘
                                                │
         ┌──────────────────────────────────────┼──────────────────────────────────────┐
         ▼                                      ▼                                      ▼
┌──────────────────┐                  ┌──────────────────┐                  ┌──────────────────┐
│ MEDIA FORENSICS  │                  │ TEXT & CLAIMS    │                  │ NETWORK GRAPH    │
│ (PyTorch, ViT,   │                  │ (HuggingFace NLP,│                  │ (NetworkX,       │
│  OpenCV, pHash)  │                  │  RAG Engine)     │                  │  Louvain Algo)   │
└────────┬─────────┘                  └────────┬─────────┘                  └────────┬─────────┘
         │                                     │                                     │
         └─────────────────────────────────────┼─────────────────────────────────────┘
                                               │
                                               ▼
                                  ┌───────────────────────────┐
                                  │  Unified Fusion Engine    │
                                  │  & Uncertainty Calibrator │
                                  └─────────────┬─────────────┘
                                                │
                                                ▼
                                  ┌───────────────────────────┐
                                  │ React Operations Dashboard│
                                  │ (Force-Graph, Timeline,   │
                                  │  Action Packet Studio)    │
                                  └───────────────────────────┘
```

### Technology Matrix
* **Frontend:** React.js (Vite, TypeScript), Tailwind CSS, Lucide Icons, Recharts.
* **Graph Visualization:** `react-force-graph-2d` / `vis-network`.
* **Backend Framework:** Python 3.11, FastAPI, Uvicorn, WebSockets, Pydantic.
* **Database & Hash Storage:** SQLite3 + `imagehash` (pHash) for fast perceptual matching.
* **AI/ML & Forensics:** PyTorch, Hugging Face Transformers (`dima806/deepfake_vs_real_image_detection`, `mo-thecreator/Deepfake-audio-detection`), OpenCV (`cv2`), Tesseract OCR / EasyOCR.
* **Graph Analytics:** NetworkX (Python), Louvain Community Detection.
* **Generative Countermeasures:** Gemini API / OpenAI API (Structured JSON output).

---

## 5. TEAM TASK DIVISION & RESPONSIBILITY MATRIX

The 4-developer structure operates along parallel tracks to avoid bottlenecks:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              DEVELOPER TRACKS                                    │
├──────────────────┬──────────────────┬──────────────────┬─────────────────────────┤
│ DEV 1            │ DEV 2            │ DEV 3            │ DEV 4                   │
│ Media ML &       │ Network Graph &  │ Text, Claims &   │ Frontend Dashboard &    │
│ Forensics Engine │ Ingestion Engine │ Backend API      │ System Integration      │
└──────────────────┴──────────────────┴──────────────────┴─────────────────────────┘
```

### Developer 1: Media ML & Forensics Engine (AI / Vision Lead)
* **Primary Focus:** Deepfake visual models, keyframe extraction, audio detection, and perceptual hashing.
* **Core Responsibilities:**
  1. Build Python inference pipeline using pre-trained Hugging Face vision models (`ViT` / `MobileNet`).
  2. Implement `OpenCV` video keyframe extractor (scene-change sampling).
  3. Integrate `imagehash` (pHash) generation for incoming media and compare against SQLite database (Hamming distance $\le 5$).
  4. Extract metadata (EXIF) and run audio classification pipeline (`Wav2Vec2`) if audio is present.
  5. Compute frame-level visual anomaly scores and return structured JSON forensic reports.

### Developer 2: Network Graph & Dissemination Engine (Graph / Data Lead)
* **Primary Focus:** NetworkX backend, synthetic botnet data generation, community clustering, and timeline propagation.
* **Core Responsibilities:**
  1. Build a synthetic social media data generator (`seed_network.py`) creating 300+ nodes and 1 clear coordinated botnet ring.
  2. Implement `NetworkX` graph engine: map nodes (accounts) and temporal co-sharing edges ($\le 120\text{s}$).
  3. Run Louvain Community Detection algorithm to isolate coordinated clusters.
  4. Implement Centrality and Degree calculations to flag **Seed Node ("Patient Zero")**, **Amplifiers**, and **Target Nodes**.
  5. Build dynamic network payload endpoints for the frontend visualization engine.

### Developer 3: Text, Claims, URL & Backend Core (Backend Lead)
* **Primary Focus:** FastAPI setup, SQLite schema, text NLP processing, claim extraction, and LLM countermeasure studio.
* **Core Responsibilities:**
  1. Initialize FastAPI application, SQLite schema, WebSockets connection manager, and CORS settings.
  2. Build Text Analysis Pipeline: claim extraction, sensationalism score calculation, and scam pattern recognition.
  3. Build URL Safety Inspector: shortener expansion, domain age/reputation check logic, and phishing flag rules.
  4. Integrate Gemini/OpenAI API prompt templates to auto-draft Fact-Check Cards, Counter-Narrative Posts, and Regulatory Takedown packets.
  5. Build the Multi-Signal Fusion engine (combining Dev 1, Dev 2, and Dev 3 outputs into a unified risk rating).

### Developer 4: Frontend UI & Interactive Dashboard (UX / Integration Lead)
* **Primary Focus:** React dashboard interface, interactive graph component, timeline scrubbers, and live presentation state.
* **Core Responsibilities:**
  1. Build React + Tailwind dashboard layout (Case List, Media Upload Zone, Detailed Audit Drawer).
  2. Integrate `react-force-graph-2d` for interactive 2D visualization of the network graph generated by Dev 2.
  3. Build the Temporal Propagation Slider component allowing scrubbing through content spread over time.
  4. Build the Diagnostic Evidence Panel displaying model confidence bars, uncertainty bands, and pHash provenance matches.
  5. Wire UI components to FastAPI WebSocket endpoints and prepare local `replay_mode` demo toggle.

---

## 6. 20-HOUR STEP-BY-STEP EXECUTION PLAN

```
[Hours 00-02] ──> Schema Locking, API Contracts & Pre-download Models
[Hours 02-08] ──> Core Functional Module Build (Parallel Track Execution)
[Hours 08-14] ──> Feature Integration & Cross-Module Pipeline Coupling
[Hours 14-18] ──> System Integration, UI Polishing & Replay Fallback Mode
[Hours 18-20] ──> Feature Freeze, QA Benchmarking, Pitch & Demo Rehearsals
```

### Phase 1: Foundation & Data Contracts (Hours 0–2)
* **Hour 0.0 - 0.5 (All):** Lock API payload structure (`Pydantic` models). Create Git repository and establish branch strategy.
* **Hour 0.5 - 2.0 (Dev 1):** Pre-download Hugging Face model weights (`dima806/deepfake_vs_real_image_detection` & `Wav2Vec2`) locally to bypass venue Wi-Fi limits.
* **Hour 0.5 - 2.0 (Dev 2):** Define SQLite schema for `accounts`, `posts`, `media_hashes`, and `edges`. Write basic NetworkX setup script.
* **Hour 0.5 - 2.0 (Dev 3):** Setup FastAPI skeleton, install dependencies, and configure base routing structure.
* **Hour 0.5 - 2.0 (Dev 4):** Scaffold React + Vite frontend, configure Tailwind CSS, and build component file layout.

### Phase 2: Core Module Development (Hours 2–8)
* **Hours 2–5 (Dev 1):** Complete Image/Video inference script and keyframe extraction wrapper. Test on sample deepfake/real assets.
* **Hours 2–5 (Dev 2):** Build `seed_network.py` dataset generator. Implement Louvain community algorithm and role tagging logic in NetworkX.
* **Hours 2–5 (Dev 3):** Implement text claim extraction logic, scam detection rule-base, and SQLite database CRUD endpoints.
* **Hours 2–5 (Dev 4):** Implement main React layout: File Upload dropzone, Investigation History list, and Status Overview cards.
* **Hours 5–8 (Dev 1):** Implement `imagehash` (pHash) calculation and Hamming distance lookup against SQLite database.
* **Hours 5–8 (Dev 2):** Build dynamic time-series frame slice logic to feed propagation timeline data to the backend API.
* **Hours 5–8 (Dev 3):** Build Gemini/OpenAI prompt pipeline for Fact-Check Card generation and Countermeasure drafting.
* **Hours 5–8 (Dev 4):** Integrate `react-force-graph-2d` canvas component into the React dashboard and style custom node colors by role.

### Phase 3: Integration & System Fusion (Hours 8–14)
* **Hours 8–11 (Dev 1 & Dev 3):** Connect Media Forensics output and Text Engine output to Dev 3's Multi-Signal Fusion Engine. Implement uncertainty band and disagreement logic.
* **Hours 8–11 (Dev 2 & Dev 4):** Connect NetworkX API endpoints to React Frontend. Verify node selection updates account detail drawer.
* **Hours 11–14 (Dev 3 & Dev 4):** Implement WebSockets connection to stream analysis logs in real time to the React operational console.
* **Hours 11–14 (Dev 1 & Dev 2):** Build video frame-by-frame analysis UI data binder and pHash historical match alert mechanism.

### Phase 4: Refinement, Replay Mode & Testing (Hours 14–18)
* **Hours 14–16 (All):** End-to-end integration test: Upload sample asset $\rightarrow$ trigger ML pipelines $\rightarrow$ query DB $\rightarrow$ map graph $\rightarrow$ view dashboard.
* **Hours 16–17 (Dev 3 & Dev 4):** Build `replay_stream.py` local fallback engine so the demo can run entirely offline without active internet/API calls during judging.
* **Hours 17–18 (All):** Complete feature freeze. Fix visual UI glitches, polish graphs, and verify error state handling ("Inconclusive" outputs).

### Phase 5: Demo Prep & Pitch Scripting (Hours 18–20)
* **Hours 18–19 (All):** Record backup video demonstration of TruthTrace AI operating smoothly.
* **Hours 19–20 (All):** Rehearse 3-minute pitch presentation and live system walkthrough 3 times.

---

## 7. AI PROMPTING & UTILITY INSTRUCTIONS (FOR CLAUDE & GEMINI PRO)

When passing tasks to your 2× Claude Pro and 2× Gemini Pro assistants during the hackathon, use the following role assignments:

* **Claude Pro #1 (Dev 1 Support - Vision & Forensics):** Focus on PyTorch models, OpenCV frame processing pipelines, Hugging Face transformers, and `imagehash` optimization scripts.
* **Claude Pro #2 (Dev 2 Support - Graph & NetworkX):** Focus on NetworkX graph math, Louvain algorithm optimization, network graph dataset seeding, and spatio-temporal co-sharing algorithms.
* **Gemini Pro #1 (Dev 3 Support - FastAPI, Backend & LLM Prompts):** Focus on FastAPI endpoints, SQLite query structures, prompt engineering for countermeasure generation, and JSON response schema validation.
* **Gemini Pro #2 (Dev 4 Support - React, Tailwind & ForceGraph):** Focus on React TypeScript components, Tailwind styling, `react-force-graph` event listeners, state management, and real-time UI updates.

---

## 8. DEMONSTRATION & PITCH STORYBOARD (3 MINUTES)

1. **The Core Ingestion (0:00 – 0:45):** Upload a re-compressed video/image asset to TruthTrace AI. Show real-time extraction of metadata, visual deepfake probability, and pHash historical matching in the Evidence Drawer. Highlight the system's honest uncertainty score when dealing with compression loss.
2. **Context & Historical Misattribution (0:45 – 1:15):** Show an example of an authentic photo paired with a false caption. Demonstrate how pHash provenance matches the image to an older event, exposing media recycling without relying solely on AI deepfake scores.
3. **The Disinformation Network & Patient Zero (1:15 – 2:15):** Switch to the Dissemination Network tab. Show the `react-force-graph` visualization. Scrub the timeline slider forward to reveal how a cluster of 30+ coordinated accounts amplified the post within seconds. Click the red node to highlight **"Patient Zero"**.
4. **Actionable Countermeasures (2:15 – 3:00):** Click **"Generate Action Packet"**. Show auto-generated Fact-Check Cards and ready-to-broadcast counter-narrative responses, closing the full threat-to-mitigation operational loop.

---

## 9. REUSABLE REPOSITORY AUDIT (2026-11-05)

The projects below are reference candidates, not dependencies. A repository counts as integrated only if TrustFeed imports, vendors, runs, or explicitly adapts its code. Merely listing a link here does not mean it is used.

| Repository | Intended contribution | Current TrustFeed use |
|---|---|---|
| [Harken](https://github.com/VladUZH/harken) | Multi-platform monitoring and ingestion | **Not integrated.** TrustFeed has its own limited public-search adapters for Mastodon, Lemmy, Hacker News, and Bluesky. |
| [LockStep](https://github.com/Vriti29/LockStep) | Coordinated-disinformation relationships and campaign clustering | **Not integrated.** TrustFeed's network analysis is implemented in `backend/network` with NetworkX. |
| [DeepTrace](https://github.com/obstinix/deeptrace) | Media deepfake detection | **Not integrated.** TrustFeed has its own `backend/media` pipeline and uses a Hugging Face image-classification model. |
| [OpenMagpie](https://github.com/obris-dev/openmagpie) | Social-media monitoring and ingestion | **Not integrated.** It is an alternative reference to Harken, not an additional service in this application. |
| [Nonescape](https://github.com/e3ntity/nonescape) | AI-generated image detection | **Not integrated.** No Nonescape model or code is installed or called. |
| [OSoMe Coordination Detection](https://github.com/osome-iu/coordination-detection) | Research coordination-detection methods | **Not integrated.** No OSoMe code or algorithms are imported. |
| [Multi-agent Fake News Detection](https://github.com/Aakashthakre-tech/multi-agent-fake-news-detection) | Multi-agent fake-news analysis | **Not integrated.** |
| [MultiModal-DeepFake](https://github.com/rshaojimmy/MultiModal-DeepFake) | Multimodal deepfake detection | **Not integrated.** TrustFeed does not currently analyze audio or lip-sync. |
| [OpenCV](https://github.com/opencv/opencv) | Image/video processing library | **Library used, repository not vendored.** The project installs `opencv-python-headless` and uses OpenCV for video frame/keyframe processing. |
| [DeepfakeBench](https://github.com/SCLBD/DeepfakeBench) | Deepfake detector benchmarking framework | **Not integrated.** TrustFeed has its own benchmark scripts and records; it does not run DeepfakeBench. |

**Current implementation summary:** TrustFeed is a Python/FastAPI service and React/TypeScript dashboard. It accepts text, links, images, and videos; runs rule-based text/link checks and an image detector with metadata, keyframe, and perceptual-hash analysis; optionally searches public sources and platform posts when the user opts in; and presents evidence, limitations, network/timeline views, history, replay, and rule-based action drafts. Unknown results remain unknown, and replay data is labelled synthetic.

**Current limits:** the image detector performs poorly at its current thresholds; coordination accuracy on real campaigns is not measured; platform monitoring is limited public search rather than complete feeds; OCR, audio, and lip-sync are not implemented; and action packets are rule-based templates, not generated counter-narratives. Check the root `README.md` for the latest measured status before a demo.
