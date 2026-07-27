# Repository discovery rules

Use the helper to discover evidence. Do not turn detection into authorisation.
Its `evidence_source` identifies the exact tree used for manifests,
instructions, workflows, and capabilities. Do not replace indexed or committed
evidence with a different working-tree version.

`worktree_divergence` lists disk paths that differ from that source. The helper
disables automatic commands when the list is non-empty because a package runner
would otherwise execute different code or scripts. Isolate the frozen target or
inspect the divergence before choosing a command manually.

## Command classes

- `safe`: read-only or ordinary local validation.
- `safe_expensive`: local validation that may build images, start disposable
  services, or run browser suites.
- `contextual`: may use live services, authentication, or production-like data;
  inspect documentation and obtain the caller's existing authority before use.
- `mutation`: deploys, publishes, migrates, seeds, syncs, commits, pushes, or
  changes an external system. Never run during code review.
- `unavailable`: placeholder or explicitly missing validation.

Unknown validators fail closed as `contextual`. Shell control, substitution,
redirection, write flags, and destructive tool subcommands are never selected
automatically even when the command begins with a familiar linter or test tool.

Package lifecycle scripts count. A harmless-looking `build` is not safe when
`prebuild` runs `npm audit fix`, a migration, a deployment, or another mutation.

## Capability evidence

Configuration proves that a capability exists; it does not prove that it is the
active deployment path. Require supporting repository instructions, existing
workflow behaviour, or provider linkage before treating a capability as CD.

Operational commands are eligible only when all are true:

1. The requested lifecycle phase authorises the mutation.
2. Changed files affect that capability.
3. Repository documentation identifies the canonical command or wrapper.
4. Required authentication is already available.
5. The command's target environment is resolved and reported.

For Windmill, prefer a repository wrapper such as `windmill/sync.sh`. Never run
raw `wmill sync` merely because `wmill.yaml` exists.

## Ambiguity

When signals disagree, prefer explicit instructions over inferred scripts. If a
safe command cannot be established, report a validation gap. Do not invent a
command or substitute a production operation for local proof.
