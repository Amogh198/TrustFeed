# CLAUDE.md — TruthTrace AI Shared Agent Instructions

Applies to every coding agent in this repository, whichever AI tool operates the lane.

Build TruthTrace AI for LAKSHYA 2026: a hackathon MVP that ingests sample text and media, analyzes claims/media, maps a synthetic coordination campaign, and presents evidence with uncertainty. Prioritize a working, explainable offline demo over attempting every blueprint feature.

## Mandatory protocol

**At the start of every session:**

1. Read `AGENT_COORDINATION.md`: problem, architecture, ownership and rules.
2. Read your own `agent-status/<you>.md`. If you don't know which lane you are, match your `gh` login against the table in `AGENT_COORDINATION.md`. Set `PROTOCOL: adopted <date>` when you first follow this.
3. Run `python tools/agent_sync.py` to see the agent board. Open another agent's full record only if your work depends on it: `python tools/agent_sync.py show <agent>`.

**Before implementing a feature:**

4. Inspect the relevant recent commits, branches and PRs. Other agents' unmerged work is on their branches, not `main`.
5. Check ownership. Edit only paths your lane owns.
6. Check `API_CONTRACTS.md` and the other contracts listed in `AGENT_COORDINATION.md` before integrating.

**While working:**

7. Update your own status file after meaningful milestones. Never edit another agent's.
8. When architecture, responsibilities or integration status change, update `AGENT_COORDINATION.md`. When a contract changes, follow the notification rules there.
9. Tell affected lanes about integration dependencies through GitHub PRs, Issues or repository files. Private chats are not visible to other agents.

**Before pushing or opening a PR:**

10. Fetch, re-read the board, merge the latest `origin/main`, and run `python tools/agent_sync.py check <you>`.

## Working without humans

Make routine technical decisions yourself and don't ask humans what to do next. Ask only in the four cases listed in `AGENT_COORDINATION.md`. Never invent an assignment or take over another lane's work.

## Non-negotiable rules

1. Work within your lane in `TASK_BOARD.md`. Issues are optional, not a prerequisite.
2. Each feature gets its own descriptively named branch from latest `origin/main`, such as `feat/network-coordination`. Never push to `main` or share a branch or clone between agents.
3. Never overwrite another lane's changes to resolve a conflict.
4. Shared contracts belong to the integration lane. Propose changes in a PR or Issue and wait for agreement before making breaking changes.
5. Open one PR per feature. Include changed paths, acceptance criteria, commands and results used to verify, contract changes, known limits and dependencies. Do not claim verification you did not run.
6. Never put API keys, passwords, cookies, access tokens, private user data or real social account credentials in code, issues, logs or commits. Use `.env.example` with dummy values and keep `.env` ignored.
7. Keep scope hackathon-sized. Prefer deterministic synthetic fixtures and replay mode. Do not make live social API access a critical path. Report model output as a signal, not proof; return `Inconclusive` when evidence is insufficient.

## AI author/reviewer pairing

- `akshay_claude` / Claude Account A: hard media forensics task(s).
- `bhuvan_claude` / Claude Account B: hard network coordination task(s).
- Gemini lane 1: backend/API/text/integration.
- Gemini lane 2: frontend/dashboard.
- A different AI lane reviews each PR. A session must not approve its own work. Claude A reviews Claude B changes and vice versa; Gemini lanes cross-review when practical. Review only the work assigned to you; see `AGENT_COORDINATION.md`.
- A written AI review is useful evidence but is not a GitHub approval. Do not merge until the repository has an authenticated AI review integration and all required CI checks pass. If that automation is not installed, mark the PR blocked instead of bypassing protection.

## Handoff format

Use this in PR descriptions and in AI-to-AI handoffs on GitHub:

- Status: Ready / Doing / In Review / Blocked / Done
- Task and branch:
- Changed paths:
- Contract or dependency changes:
- Verification run and result:
- Next action / blocker:
- Reviewer lane:

## Completion means

Acceptance criteria are met, verification results are recorded, a different AI lane has reviewed it, the PR is merged through the protected workflow, and your status file is updated. Sync your clone from updated `main` before continuing.
