# CLAUDE.md — TruthTrace AI Shared Agent Instructions

Read this file, `TASK_BOARD.md`, `API_CONTRACTS.md`, and `GITHUB_WORKFLOW.md` before starting or resuming work. These instructions apply to Claude, Gemini, and any coding agent working in this repository.

## Project

Build TruthTrace AI for LAKSHYA 2026: a hackathon MVP that ingests sample text and media, analyzes claims/media, maps a synthetic coordination campaign, and presents evidence with uncertainty. Follow `truthtrace_ai_master_context_execution_blueprint.md`, but prioritize a working, explainable offline demo over attempting every listed feature or cloning several large research repositories.

## Non-negotiable collaboration rules

1. Work only on the task described in a GitHub Issue. Confirm its owner, agent lane, acceptance criteria, and allowed paths before editing.
2. Each task gets its own branch from latest `origin/main`, named `feat/<issue>-<short-name>` (or `fix/`, `docs/`). Never push to `main` or share a branch/clone between AI accounts.
3. Before edits, fetch the latest `main` and read recent merged PRs/issues. Before PR, sync latest `main` deliberately and inspect overlap. Never overwrite another lane's changes to resolve a conflict.
4. Keep edits within the task's path ownership in `TASK_BOARD.md`. Shared contracts belong to the integration lane; propose changes in the issue and wait for agreement before changing them.
5. Open one PR per issue. Include changed paths, acceptance criteria mapping, commands/results used to verify, contract changes, known limits, and dependencies. Do not claim verification you did not run.
6. After each meaningful milestone, leave a status update in the linked GitHub Issue: `Doing`, `Done`, `Blocked`, or `Needs decision`; include branch, changed paths, next action, and blocker/decision if any. On PR creation and merge, update the issue. This is the shared memory between separate AI chats.
7. Never put API keys, passwords, cookies, access tokens, private user data, or real social account credentials in code, issues, logs, or commits. Use `.env.example` with dummy values and keep `.env` ignored.
8. Keep scope hackathon-sized. Prefer deterministic synthetic fixtures and replay mode. Do not make live social API access a critical path. Report model output as a signal, not proof; return `Inconclusive` when evidence is insufficient.

## AI author/reviewer pairing

- `akshay_claude` / Claude Account A: hard media forensics task(s).
- `bhuvan_claude` / Claude Account B: hard network coordination task(s).
- Gemini lane 1: backend/API/text/integration.
- Gemini lane 2: frontend/dashboard.
- A different AI lane reviews each PR. A session must not approve its own work. Claude A reviews Claude B changes and vice versa; Gemini lanes cross-review when practical. If a task needs a specific expert, request that AI lane in the Issue.
- A written AI review is useful evidence but is not a GitHub approval. Do not merge until the repository has an authenticated AI review integration and all required CI checks pass. If that automation is not installed, mark the PR blocked instead of bypassing protection.

## Required handoff format

Use this in every issue update or AI-to-AI handoff:

- Status: Doing / Done / Blocked / Needs decision
- Issue and branch:
- Changed paths:
- Contract or dependency changes:
- Verification run and result:
- Next action / blocker:
- Reviewer lane:

## Completion means

An issue is complete only when its acceptance criteria are met, verification results are recorded, a different AI lane has reviewed it, the PR is merged through the protected workflow, and the issue/status is updated. Sync all active clones from updated `main` before continuing.
