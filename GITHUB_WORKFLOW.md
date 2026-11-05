# GitHub Workflow — TrustFeed AI

## Repository source of truth

- Canonical repository: https://github.com/Amogh198/TrustFeed (owner: Amogh198; default branch observed: `main`).
- All four developers work against this one repository. Confirm all three invitations are accepted and access works.
- Use `agent-status/` for live status, PRs for proposed changes and independent AI review, optional Issues for cross-lane requests, and `CLAUDE.md` plus the other root Markdown files as shared instructions.

## Before starting a task

1. Follow the mandatory protocol in `CLAUDE.md`.
2. Confirm from the board that no other lane is changing the same paths.
3. In the correct independent clone, fetch `origin/main`, fast-forward local `main`, and create a descriptively named branch from it.
4. Never switch between Claude accounts in one clone or let both accounts push the same branch.

## During work

- Keep each PR to one feature. Use conventional commits, e.g. `feat: add coordination timeline payload`.
- Update your status file at task start, meaningful decision, blocker, PR open, and merge. Use the handoff format in `CLAUDE.md` in PRs.
- If another PR changes a dependency/shared schema, pause affected work, sync latest `main`, and coordinate through that PR before editing.

## Pull request flow

1. Before PR, fetch latest `origin/main`; reconcile changes deliberately, inspect the full changed-file list, and run `python tools/agent_sync.py check <you>`.
2. Open a PR to `main`, document changed paths, acceptance criteria, verification results, risks, and integration notes. Link an Issue if one exists.
3. A different AI lane reviews. The author does not review/approve its own PR. Review checks the diff, contract compatibility, scope, security/secrets, and actual verification evidence.
4. Merge only when authenticated AI approval and required CI checks pass. Turn on GitHub auto-merge only after the rules below are active and tested.
5. After merge, update the Issue and both active clones sync from the new `origin/main` before continuing.

## Required repository settings before coding

Set GitHub Rulesets or branch protection on `main`:

- Require a pull request; block direct pushes, force pushes, and branch deletion.
- Require one approval from an authenticated, non-author AI reviewer; dismiss stale approvals after new commits; require resolved conversations.
- Require relevant CI checks (at minimum backend import/test/lint and frontend install/build/lint once scripts exist).
- Disable administrator bypass if available; otherwise owner agrees not to bypass.
- Enable auto-merge only after required reviews/checks and merge strategy are verified.

## Important AI authentication gap

Claude Pro and Gemini Pro subscriptions are not themselves GitHub bot identities or GitHub Actions secrets. Before claiming the workflow is fully automated, install/configure an AI reviewer that can read PRs and submit an authenticated review, and configure required CI. Use a GitHub App or supported Action and store credentials only in repository/org secrets. Never paste cookies, PATs, or API keys into chat or commit them. A text review comment is not the same as a GitHub approval. If no authenticated reviewer is configured, keep the PR blocked rather than silently bypass rules.

## Setup status

As observed on 2026-11-05:

- A repository ruleset protects `main`: pull request required, one approval, stale approvals dismissed, resolved threads required, force pushes and deletion blocked.
- No CI workflows exist yet, and no authenticated AI reviewer is installed. See the open decision in `AGENT_COORDINATION.md`.
- Each agent authenticates with its own human's `gh auth login`. Never share tokens.
