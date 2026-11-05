# CLAUDE.md — TruthTrace AI Shared Agent Instructions

Applies to every coding agent in this repository, whichever AI tool operates the lane.

Build TruthTrace AI for LAKSHYA 2026: a hackathon MVP that ingests sample text and media, analyzes claims/media, maps a synthetic coordination campaign, and presents evidence with uncertainty. Prioritize a working, explainable offline demo over attempting every blueprint feature.

## Mandatory protocol

**At the start of every session:**

1. Read `AGENT_COORDINATION.md`: problem, architecture, ownership and rules.
2. Read your own `agent-status/<you>.md`. If you don't know which lane you are, match your `gh` login against the table in `AGENT_COORDINATION.md`. Set `PROTOCOL: adopted <date>` when you first follow this.
3. Read the agent board, which a session-start hook adds to your context. If it isn't there, run `python tools/agent_sync.py`. Open another agent's full record only if your work depends on it: `python tools/agent_sync.py show <agent>`.

**Before implementing a feature:**

4. Inspect the relevant recent commits, branches and PRs. Other agents' unmerged work is on their branches, not `main`.
5. Check ownership. Edit only paths your lane owns.
6. Check `API_CONTRACTS.md` and the other contracts listed in `AGENT_COORDINATION.md` before integrating.

**While working:**

7. Update your own status file after meaningful milestones. Never edit another agent's.
8. When architecture, responsibilities or integration status change, update `AGENT_COORDINATION.md`. When a contract changes, follow the notification rules there.
9. Tell affected lanes about integration dependencies through GitHub PRs, Issues or repository files. Private chats are not visible to other agents.

**Before reporting a milestone:**

10. Validate your own work using the self-validation steps in `AGENT_COORDINATION.md`, including `python tools/compat_check.py`, and fix what they find.
11. Fetch, re-read the board, and run `python tools/agent_sync.py check <you>`. Then commit and push to your own branch.

## Working without humans

Make routine technical decisions yourself and don't ask humans what to do next. Ask only in the four cases listed in `AGENT_COORDINATION.md`. Never invent an assignment or take over another lane's work.

**Never wait for a review or approval.** No agent's work depends on another agent or person approving it. Keep building on your branch.

**Strategy:** independent development, continuous GitHub updates, self-validation, continuous compatibility checks, no mandatory reviews, delayed merging and controlled final integration. Details are in `AGENT_COORDINATION.md`.

## Non-negotiable rules

1. Work within your lane in `TASK_BOARD.md`. Issues are optional, not a prerequisite.
2. Each feature gets its own descriptively named branch from latest `origin/main`, such as `feat/network-coordination`. Never push to `main` or share a branch or clone between agents.
3. Never overwrite another lane's changes to resolve a conflict.
4. Shared contracts belong to the integration lane. Announce changes in a PR or Issue with migration steps, and keep existing consumers working where practical.
5. Record the commands you ran and their results when you report a milestone. Do not claim verification you did not run.
6. Never put API keys, passwords, cookies, access tokens, private user data or real social account credentials in code, issues, logs or commits. Use `.env.example` with dummy values and keep `.env` ignored.
7. Keep scope hackathon-sized. Prefer deterministic synthetic fixtures and replay mode. Do not make live social API access a critical path. Report model output as a signal, not proof; return `Inconclusive` when evidence is insufficient.
8. Never bypass repository protection. Merging to `main` is part of controlled final integration; see `AGENT_COORDINATION.md`.
9. Commit and push every completed milestone to your own branch, and before ending a session. Work that exists only on your machine doesn't count as shared progress.

## Lanes

- `akshay_claude` / Claude Account A: hard media forensics task(s).
- `bhuvan_claude` / Claude Account B: hard network coordination task(s).
- Gemini lane 1: backend/API/text/integration.
- Gemini lane 2: frontend/dashboard.

## Handoff format

Use this in PR descriptions and in AI-to-AI handoffs on GitHub:

- Status: Ready / Doing / Validated / Blocked / Done
- Task and branch:
- Changed paths:
- Contract or dependency changes:
- Verification run and result:
- Next action / blocker:

## Completion means

A milestone is complete when its requirements are met, your own validation passes, results are recorded, the work is pushed to your branch, and your status file is updated. It reaches `main` during final integration.
