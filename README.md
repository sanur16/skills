# skills

A public collection of [Claude Code](https://claude.com/claude-code) skills I use.

Each subdirectory is a self-contained skill with a `SKILL.md` at its root.

## Installing a skill

Clone the repo and symlink (or copy) the skill into your user-level skills directory:

```bash
git clone https://github.com/sanur16/skills.git
ln -s "$(pwd)/skills/self-improve" ~/.claude/skills/self-improve
```

Skills are auto-discovered the next time Claude Code starts.

## Skills in this repo

| Skill | What it does |
|---|---|
| [self-improve](./self-improve/) | Audits your recent Claude Code work, finds repeated workflows, and packages the high-confidence ones as skills, subagents, hooks, or scheduled jobs. |

## Contributing

These are my personal skills — feel free to fork and adapt. If something here is useful or broken, open an issue.
