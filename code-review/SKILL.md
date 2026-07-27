---
name: code-review
description: "Run a repository-aware, adversarial review of staged, local, commit, or branch changes; discover safe validation commands, invoke code-simplify first, automatically fix credible in-scope findings, and repeat until clean. Use when explicitly requested for code review, before Codex creates a commit, or as the review child of $pr."
---

# Code Review

Review the exact change that is about to be committed or merged. Do not commit,
push, open a PR, deploy, or merge; the caller owns those actions.

## 1. Select and freeze the target

Choose one mode:

- `staged`: the index, immediately before a commit.
- `local`: staged, unstaged, and untracked work explicitly in scope.
- `commit`: one existing commit.
- `branch`: merge-base through `HEAD`, using the actual PR base when available.

Run the bundled discovery helper from the repository root:

```bash
python3 <skill-dir>/scripts/discover_repo.py --mode <mode> [--base <ref>] [--commit <ref>] --pretty
```

Read every applicable instruction file from the helper's `evidence_source`:
the index for staged mode, the named commit for commit/branch mode, and disk for
local mode. Inspect the full changed files and their immediate callers,
dependencies, schemas, and tests from that same source. Record the original
request, intended behaviour, changed files, non-test diff size, and target
commit/tree as the scope baseline.

For staged review, never silently include unstaged files. For branch review,
fetch the base first when needed and pass it explicitly. Regenerate the target
whenever edits occur.

Before permitting edits in staged mode, intersect `git diff --cached --name-only`
with `git diff --name-only`. If any file has both staged and unstaged changes,
invoke `$code-simplify` read-only and do not auto-edit that file. Stop before a
required fix rather than staging, overwriting, stashing, or otherwise disturbing
the user's unrelated unstaged hunks.

## 2. Guard the bundle

Run `git diff --check` against the selected target. Inspect added lines and new
files for credential material. Never reproduce a suspected secret in output.
If a credible secret is present, stop before sending the bundle to a reviewer
and report only its file, line, and credential type.

Do not omit semantic files merely because they are generated: lockfiles,
migrations, schemas, policies, manifests, generated clients, and deployment
configuration remain reviewable.

## 3. Invoke the simplification child

Explicitly invoke `$code-simplify` on the selected changed code. It may edit the
working tree unless step 1 set a read-only boundary, and it must preserve
behaviour and scope. Review its edits, reject unnecessary churn, and regenerate
discovery and the frozen target afterward.

Skip simplification for prose-only internal notes, lockfile-only changes, and
pure generated output. Still inspect those changes directly.

## 4. Run repository-aware validation

Use discovery output as evidence, not blind authority:

- Run selected commands marked `safe` first, cheapest to most expensive.
- Run `safe_expensive` commands when the changed surface warrants them.
- Never automatically run `contextual` or `mutation` commands during review.
- When `worktree_divergence` is non-empty, do not execute frozen-target
  commands through the divergent live checkout. Use a disposable target
  snapshot when practical, or inspect and report the validation boundary.
- Do not install dependencies unless they are missing and installation is a
  normal, non-destructive prerequisite for the selected check.
- If a command is ambiguous, inspect its manifest, lifecycle scripts, workflow,
  and repository documentation before deciding.
- Prefer focused tests for the changed package, then the repository's credible
  full verification command.

Treat failures introduced by the change as findings and fix them. Distinguish
pre-existing failures with a baseline or focused comparison when practical.

See [repository-discovery.md](references/repository-discovery.md) when discovery
reports ambiguous commands or operational capabilities.

## 5. Run one fresh adversarial review

Launch one fresh subagent with no prior conclusions. Give it:

- the original request and acceptance criteria;
- applicable repository instructions;
- the exact frozen patch or commit range;
- full relevant changed files and adjacent contracts;
- the repository profile;
- validation results.

Make the reviewer read-only. Ask it to find only credible issues introduced by
the change that materially affect correctness, security, data integrity,
reliability, performance, maintainability, or required tests. It must provide
file/line evidence and the smallest appropriate fix. It must not edit, commit,
push, deploy, create issues, or invoke another reviewer.

Use one reviewer by default. Add another only when the user requests a panel or
the change crosses a genuinely high-risk boundary such as authentication,
payments, destructive migrations, or production infrastructure.

## 6. Verify and fix automatically

Treat reviewer output as advisory. Verify every candidate against the real code,
types, documentation, history, and runtime contract. Reject speculative edge
cases, pre-existing problems, stylistic preferences, and broad rewrites.

Classify accepted findings:

- `in-scope`: introduced by this change and repairable without changing its
  contract. Fix automatically.
- `follow-up`: real but pre-existing or outside the owner boundary. Report it;
  do not expand this change or create an issue unless the caller authorises it.
- `decision`: requires a new public contract, migration strategy, secret,
  production mutation, or product choice. Stop and escalate.

After each accepted fix, rerun affected validation and review the newly frozen
target. Stop when there are no accepted actionable findings. After two repair
cycles without convergence, pause and reclassify the remaining findings instead
of continuing an uncontrolled rewrite. Stop sooner if files or non-test LOC grow
beyond twice the baseline without a clearly necessary in-scope fix.

## 7. Return proof

Return:

- mode and exact reviewed commit/tree;
- changed scope;
- simplifications applied;
- validation commands and results;
- findings accepted, fixed, rejected, or escalated;
- final clean result, or the precise blocker.

Do not run an extra review solely to obtain nicer wording. A clean final pass on
the exact target is sufficient.
