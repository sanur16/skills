---
name: self-improve
description: >
  Audit the user's recent work to find repeated manual workflows worth packaging as
  skills, subagents, hooks, or scheduled jobs — then create the high-confidence ones.
  Use whenever the user says "/self-improve", asks "what could I automate?", "make me
  more efficient", "audit my workflows", "find repetitive work", "find patterns in my
  recent work", wants to capture recent learnings into reusable tooling, or expresses
  frustration with repeating the same multi-step task. Also use proactively when you
  notice the user walking through a procedure they've clearly done before.
---

# /self-improve — Find and package repeated workflows

This skill audits the user's recent work, identifies workflows worth packaging, and creates the high-confidence ones as skills, subagents, hooks, or scheduled jobs.

The user is asking you to do introspection on their behalf. Don't expect them to hand you the list — your job is to find the patterns, sort the good ones from the noise, and act only on what the evidence supports.

---

## Evidence sources

Use these sources, roughly in priority order. Run searches in parallel where independent.

### 1. Claude Code session transcripts
- Look in `~/.claude/projects/` — each project has its own directory with session files (often JSONL) containing full conversation history, plus a `memory/` subdirectory.
- Default window: last 30 days, or all available history if shorter. Bias toward the most recent sessions; older ones are less likely to reflect current habits.
- Skim summaries first when present. Don't try to read every transcript end-to-end.
- Look for: tasks the user repeatedly asks for; multi-step processes they walked you through more than once; corrections they had to give multiple times; patterns the user described as annoying or tedious.

### 2. CLAUDE.md memory files
- Global: `~/.claude/CLAUDE.md` and entries under `~/.claude/projects/*/memory/`.
- Per-project: `CLAUDE.md` (and sometimes `.claude/CLAUDE.md`) in each active repo.
- Look for: feedback memories (recurring corrections), project memories (deadlines, ongoing initiatives), conventions repeated across multiple projects.

### 3. Shell history and git
- Shell history: `~/.zsh_history` or `~/.bash_history` — grep for repeated command sequences.
- Git activity across active repos: `git log --all --since="30 days ago" --pretty='%h %s' --author="$(git config user.email)"`. Look for repeated commit subjects (e.g. "bump version", "regenerate fixtures", "update screenshots", "fix lint").
- `git reflog` for context on local-only work that didn't land in commits.
- Treat these as **discovery signals only** — confirm important details in the relevant source system or repo before acting on them.

### 4. Existing skills, agents, commands, hooks, schedules, MCPs
Before recommending anything, check what already exists so you don't duplicate or fight existing tooling:
- `~/.claude/skills/` and plugin-bundled skills (visible in the available-skills system reminder).
- `~/.claude/agents/` and per-project `.claude/agents/`.
- `~/.claude/commands/` and per-project `.claude/commands/`.
- `~/.claude/settings.json` (hooks, permissions, env).
- `~/.claude/scheduled-tasks/` or any scheduled-task skill the user has installed (for cron-style routines).
- Configured MCP servers (listed in the system reminder).

A new asset is only justified if it's clearly distinct from — or a deliberate extension of — what's already there.

---

## Criteria for packaging

Only act on a candidate when it:
- **Occurred at least twice**, or is clearly likely to recur and costly to repeat.
- Has **stable inputs**, a **repeatable procedure**, and a **clear output or stopping condition**.
- Would **materially improve** speed, quality, consistency, or reliability.
- Is **not already adequately covered** by an existing skill, agent, command, hook, or MCP.

If any of these is weak, the candidate goes on the **needs more evidence** list — not the create list.

---

## Choose the smallest appropriate form

For each viable candidate, pick the smallest form that fits the work:

- **Skill** (`~/.claude/skills/<name>/SKILL.md`) — a reusable workflow or playbook. Best when the user invokes a procedure (explicitly via `/name` or by description) and benefits from in-context instructions Claude follows. Default choice for most candidates.
- **Subagent** (`~/.claude/agents/<name>.md`) — a bounded specialist role for delegation in an isolated context. Best for investigation-heavy or context-heavy tasks where the main thread should stay clean and the agent returns a focused report.
- **Automation** — either:
  - a **hook** (in `~/.claude/settings.json`) for event-driven checks tied to tool/lifecycle events; or
  - a **scheduled job** (via a scheduling skill if available, or a cron / GitHub Actions invocation of `claude -p`) for recurring reports, reminders, or monitors.
- **Extend existing** — add to or refine an asset that's already there. Often better than creating a new one; resist the impulse to launch a new file when a 10-line edit to an existing skill would do.
- **Skip** — too one-off, ambiguous, sensitive, or poorly evidenced. Saying "no" is a valid result.

When in doubt: prefer extending over creating, prefer skills over agents, prefer human-invoked over automated.

---

## Workflow

### Step 1 — Gather evidence
Spawn parallel searches across the evidence sources above. You're sampling for patterns, not building an exhaustive index. A useful rule: if you've found a pattern three times, stop hunting for a fourth — move on.

### Step 2 — Produce the shortlist *first*
Before creating anything, surface a compact shortlist for the user. One entry per candidate:

```
### <workflow name>
- Evidence: <where you saw it + approximate dates>
- Frequency / confidence: <e.g. 4 times in past 2 weeks / high>
- Recommended form: skill | subagent | automation | extend <name> | skip
- Why: <one sentence on why this is or isn't worth packaging>
```

Group near-duplicates. Drop weak signals. The shortlist itself is the deliverable for the low/medium-confidence items — the user can always promote one later.

### Step 3 — Create only the high-confidence items
For each one you create:
- Keep it **narrow and practical**. A skill that does one thing well beats a kitchen-sink skill.
- Make it **source-aware**: name the actual files, commands, repos, or patterns it's responding to.
- Make it **easy to validate**: clear inputs, clear output, simple to test.
- Don't create speculative, overlapping, or overly broad assets.
- For skills, follow the format of existing entries under `~/.claude/skills/` (frontmatter with `name` and `description`, body in markdown).
- For subagents, follow `.claude/agents/` conventions in this repo / user dir.
- For hooks or scheduled jobs, prefer a purpose-built skill if one is installed (anything that manages `settings.json` or cron-style routines) over hand-editing config files.

### Step 4 — Report
Finish with three sections, in this order:

```
## Created or extended
- <item> — <path> — <one-line purpose>

## Deliberately skipped
- <workflow> — <reason>

## Needs more evidence before packaging
- <workflow> — <what would tip it over the line>
```

---

## Anti-patterns to avoid

- **Don't package things you imagine the user might want.** Stick to what the evidence supports. Hypothetical recurrence isn't evidence.
- **Don't create kitchen-sink skills.** "Helper for X" with five vaguely related sub-tasks is worse than nothing — it dilutes triggering and confuses future-you.
- **Don't auto-create automations that touch shared systems.** Cron jobs that hit prod, hooks that broadly block tool calls — surface these as proposals and let the user confirm before writing them.
- **Don't duplicate skills that already exist under a slightly different name.** If close variants of a workflow are already installed, extending one of them beats creating a near-duplicate alongside.
- **Don't include sensitive data in skill content.** Secrets, private message contents, PII — none of it belongs in a checked-in (or even local) skill file.
- **Don't over-instruct.** When in doubt, explain the *why* once and trust the model. Heavy `ALWAYS`/`NEVER` walls of text usually mean the skill needs reframing, not more rules.

---

## Communicating with the user

The user is asking for a verdict, not a buffet. After the shortlist, just make the high-confidence ones and report. If something is genuinely on the fence, name it specifically and ask one focused question — don't ask the user to re-evaluate the whole list. End-of-turn report should be skimmable in 30 seconds.
