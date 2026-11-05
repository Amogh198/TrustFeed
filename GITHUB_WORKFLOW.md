# GitHub Workflow — TrustFeed AI

## Repository source of truth

- Canonical repository: https://github.com/Amogh198/TrustFeed (owner: Amogh198; default branch observed: `main`).
- All four developers work against this one repository.
- Use `agent-status/` for live status, PRs to present work for integration, optional Issues for cross-lane requests, and `CLAUDE.md` plus the other root Markdown files as shared instructions.

## Before starting a task

1. Follow the mandatory protocol in `CLAUDE.md`.
2. Confirm from the board that no other lane is changing the same paths.
3. In the correct independent clone, fetch `origin/main`, fast-forward local `main`, and create a descriptively named branch from it.
4. Never switch between Claude accounts in one clone or let both accounts push the same branch.

## During work

- Use conventional commits, e.g. `feat: add coordination timeline payload`.
- Commit and push each milestone after validating it yourself, and before ending a session. See "Self-validation" in `AGENT_COORDINATION.md`. A pushed feature branch counts as shared progress, while local-only work doesn't.
- `main` shows little activity until final integration. Check the feature branches, or run `python tools/agent_sync.py`, to see real progress.
- Update your status file at task start, meaningful decision, blocker, and milestone. Use the handoff format in `CLAUDE.md` in PRs.
- If another branch changes a dependency or shared schema, sync with it and coordinate through its PR. Keep working on whatever it doesn't affect.

## Pull requests

1. Keep PRs available for visibility, coordination and integration. Document changed paths, verification results, risks, and integration notes. Link an Issue if one exists.
2. Don't wait on the PR. Keep working on your branch.
3. Teammates may comment when useful. Comments are optional and never block development.

## Final integration

Branches stay independent until then, and `python tools/compat_check.py` checks compatibility without merging. The coordinator (T3) controls merging to `main` in the sequence set out in `AGENT_COORDINATION.md`. After a merge, agents sync from `origin/main` when convenient.

## Repository settings

As observed on 2026-11-05. Only the repository admin can change these, and agents must not bypass them:

- The `Protect Main` ruleset applies to `main` only, with no bypass actors. It blocks force pushes and deletion and requires a pull request. It requires no approvals or resolved threads.
- Feature branches are unprotected, so development isn't affected.
- No CI workflows exist yet, so `check`, tests and lint run locally.
- Each agent authenticates with its own human's `gh auth login`. Never share tokens, and never paste cookies, PATs or API keys into chat or commits.
