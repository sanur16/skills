---
name: pr
description: "Run the complete pull-request lifecycle: inspect the active repository, review and simplify every commit, create or update a draft PR, run whole-branch adversarial review, automatically fix accepted findings, execute repository-aware validation, merge with an allowed strategy, delete the branch, and verify established delivery. Use when the user says /pr, asks to create, publish, land, merge, or complete a pull request, or requests the full PR workflow."
---

# PR

Own the full lifecycle and auto-merge when every gate passes. Use `$code-review`
as the only review child; it invokes `$code-simplify` itself. Do not wait for or
depend on Gemini, Claude, Codex, CodeRabbit, or GitHub Actions review bots.

Child skills may be hidden from the agent's skill list. Load them by path:
`$code-review` is [`../code-review/SKILL.md`](../code-review/SKILL.md) and
`$code-simplify` is [`../code-simplify/SKILL.md`](../code-simplify/SKILL.md).

## 1. Resolve scope and repository

Read applicable repository instructions. Inspect status, current branch,
remotes, default branch, existing PR, and the original request. Preserve
unrelated user changes.

If uncommitted work is in scope:

1. Stage only the intended files.
2. Invoke `$code-review` in `staged` mode.
3. Restage only accepted in-scope hunks and repeat until the exact index tree is
   clean. Never use whole-file staging when that file also has unrelated
   unstaged edits; let `code-review` stop on that mixed-file boundary.
4. Commit the reviewed tree with an intentional message.

If on the default branch, create a short-lived `codex/` branch before the first
commit. Never commit directly to the default branch.

## 2. Open or update a draft PR

Push the branch and find an existing open PR. Otherwise create a draft PR with:

- a concise title and summary;
- important implementation decisions;
- a generated test plan containing the commands and behaviours to verify;
- screenshots for changed user interfaces when practical.

Use the repository's actual PR base, not an assumed `main` branch.

## 3. Review the whole branch

Fetch the base and invoke `$code-review` in `branch` mode against that exact ref.
Automatically fix every verified in-scope finding. Each fix commit must itself
pass staged `$code-review`, then be pushed. Repeat branch review until clean or
until `code-review` reports a decision or non-converging scope boundary.

Fetch human reviews, inline comments, issue comments, and unresolved threads.
Verify and automatically fix credible in-scope human findings. Reply briefly
with the resolution and resolve the thread only after the fix is pushed and
validated. Never treat an AI-review bot as a required signal.

## 4. Run repository-aware proof

Use the repository profile returned by `$code-review`:

- run selected safe lint, type, unit, integration, build, and packaging checks;
- run relevant `safe_expensive` checks for affected UI, container, or service
  surfaces;
- exercise changed user-visible behaviour headlessly where feasible;
- attach desktop and mobile evidence for material UI changes;
- synthesize missing test-plan items from the diff.

Fix failures introduced by the branch automatically and repeat review and proof
on the new head. Do not hide or waive a failing check merely to merge.

## 5. Exact-head merge gate

Immediately before merging:

1. Record the locally reviewed and tested `HEAD`.
2. Confirm the PR head matches it.
3. Mark a clean draft ready with `gh pr ready`, then confirm it is not draft.
4. Confirm no unresolved human-requested change remains.
5. Confirm every required local proof passed on this head.
6. Inspect any existing deterministic GitHub checks. Diagnose failures, but do
   not require deprecated AI checks. Do not let a known GitHub billing failure
   invalidate equivalent successful local proof unless repository rules require
   that check.

Resolve the repository's allowed merge methods and any explicit instructions.
Prefer squash when allowed; otherwise use the documented allowed method. Bind
the merge operation to the reviewed SHA and delete the remote branch:

```bash
gh pr merge <number> <strategy-flag> --delete-branch --match-head-commit <reviewed-sha>
```

This is active auto-merge by the skill, not GitHub's `--auto` queue. If any gate
is uncertain, do not merge.

## 6. Delivery and verification

Capture the resulting merge commit SHA. After merge, update the local default
branch and remove the short-lived local branch when safe. Re-run repository
discovery in `commit` mode on that merge SHA so delivery decisions retain the
actual changed-file evidence.

Follow an established delivery contract only when repository evidence shows it:

- provider Git integration: observe the deployment and wait for completion;
- documented post-merge wrapper affecting changed files: run it when `/pr`
  authorises that repository's normal CD lifecycle;
- scheduled, release, database, or production operation without a proven
  contract: report it and do not invent a mutation.

For Windmill, use only the documented repository wrapper and only when Windmill
files changed. Never run raw `wmill sync` from an inferred directory.

Verify the deployed version or health endpoint when discoverable. If delivery
fails, diagnose and fix an in-scope code/configuration cause through a new
reviewed hotfix PR. Escalate provider outages, billing, missing credentials, and
ambiguous production decisions.

## 7. Closeout

Report the PR and merge URLs, reviewed/tested commit, automatic fixes, validation
proof, deployment result, and any true follow-up. Do not post review chatter when
a compact audit summary is sufficient.
