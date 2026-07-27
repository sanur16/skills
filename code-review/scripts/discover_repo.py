#!/usr/bin/env python3
"""Discover repository-specific review and delivery capabilities without mutation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SKIP_DIRS = {
    ".git", ".next", ".turbo", ".venv", "build", "coverage", "dist",
    "node_modules", "target", "vendor",
}
MUTATION_RE = re.compile(
    r"(?:\bnpm\s+audit\s+fix\b|\b(?:deploy|publish|release|migrate|seed)\b|"
    r"\bsync\s+push\b|\bwmill\b|\bwrangler\s+deploy\b|\brailway\s+up\b|"
    r"\bfly(?:ctl)?\s+deploy\b|\bnetlify\s+deploy\b|\bgit\s+(?:commit|push)\b|"
    r"\bgit\s+(?:clean|reset|restore|checkout|switch|merge|rebase|cherry-pick)\b|"
    r"\b(?:npm|pnpm|yarn|bun)\s+(?:install|add|remove|update|upgrade)\b|"
    r"\b(?:terraform|tofu)\s+(?:apply|destroy|import|state\s+(?:mv|rm))\b|"
    r"\bkubectl\s+(?:apply|create|delete|edit|patch|replace|rollout|scale|set)\b|"
    r"\bgh\s+pr\s+(?:create|close|edit|merge|reopen)\b|"
    r"\bdocker\s+(?:compose\s+(?:down|kill|push|rm|stop)|system\s+prune|(?:container|image|volume)\s+rm)\b|"
    r"\bdocker\s+(?:(?:build|buildx\s+build)|compose\s+build)\b[^\n]*--push\b|"
    r"\b(?:eslint|prettier|ruff)\b[^\n]*(?:--fix|--write|--output-file)\b|\bruff\s+format\b|"
    r"\b(?:vitest|jest)\b[^\n]*(?:--update(?:snapshot)?|-u)(?:\s|=|$)|"
    r"\b(?:vitest|jest)\b[^\n]*--output(?:-?f|F)ile(?:\s|=)|"
    r"\bplaywright\b[^\n]*--update-snapshots(?:\s|=|$)|\bcargo\s+fix\b|\bgofmt\b[^\n]*\s-w\b|"
    r"\bcurl\b[^\n]*(?:(?:-X|--request)\s*(?:POST|PUT|PATCH|DELETE)\b|"
    r"(?:--data(?:-[a-z]+)?|-d|-F|--form|--upload-file|-T)(?:\s|=)))", re.I,
)
CONTEXT_RE = re.compile(
    r"(?:\b(?:live|production|prod|remote)\b|\b(?:login|auth)\b|"
    r"\bzcli\b|\b(?:invoice-security|performance)\b)", re.I,
)
PLACEHOLDER_RE = re.compile(
    r"^\s*echo\s+['\"]?(?:error:\s*)?no tests? (?:specified|configured)['\"]?\s*"
    r"&&\s*exit\s+1\s*$", re.I,
)
EXPENSIVE_RE = re.compile(
    r"(?:\bplaywright\b|\be2e\b|\bdocker\s+build\b|\bxcodebuild\b|"
    r"\b(?:supabase\s+(?:start|test)|docker\s+compose)\b)", re.I,
)
SAFE_VALIDATOR_SEGMENT_RE = re.compile(
    r"^(?:(?:[A-Za-z_][A-Za-z0-9_]*=[^\s]+|env|cross-env)\s+)*(?:"
    r"(?:npm|pnpm|yarn|bun)\s+run\s+[\w:.-]+|"
    r"(?:eslint|tsc|vitest|jest|mocha|playwright|pyright)\b|"
    r"prettier\b[^\n]*--check\b|next\s+(?:build|lint)\b|"
    r"(?:vite|webpack|rollup|tsup)\s+build\b|"
    r"node\s+--test\b|python3?\s+-m\s+(?:pytest|unittest|ruff|mypy)\b|"
    r"(?:pytest|ruff|mypy)\b|go\s+(?:test|build|vet)\b|"
    r"cargo\s+(?:test|check|clippy|build)\b|swift\s+(?:test|build)\b|"
    r"\./node_modules/\.bin/prisma\s+validate\b|"
    r"\./node_modules/\.bin/supabase\s+db\s+lint\b|"
    r"\./node_modules/\.bin/wrangler\s+deploy\b[^\n]*--dry-run(?:\s|$)|"
    r"docker\s+(?:build|compose)\b|cd\s+[^\s]+|true\b)", re.I,
)


def git(root: Path, *args: str, allow_failure: bool = False) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], text=True, errors="surrogateescape",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode and not allow_failure:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def git_bytes(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.decode(errors="replace").strip() or f"git {' '.join(args)} failed"
        )
    return result.stdout


@dataclass(frozen=True)
class RepoView:
    """Read repository evidence from the exact working, index, or commit tree."""

    root: Path
    source: str
    files: frozenset[str]
    symlinks: frozenset[str]
    ref: str | None = None

    @classmethod
    def create(cls, root: Path, mode: str, commit: str) -> RepoView:
        if mode == "local":
            files: set[str] = set()
            symlinks: set[str] = set()
            for current, dirs, names in os.walk(root):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for name in names:
                    candidate = Path(current) / name
                    relative = candidate.relative_to(root).as_posix()
                    if candidate.is_symlink():
                        try:
                            candidate.resolve(strict=True).relative_to(root)
                        except (OSError, ValueError):
                            symlinks.add(relative)
                            continue
                    files.add(relative)
            return cls(root, "working-tree", frozenset(files), frozenset(symlinks))

        if mode == "staged":
            output = git(root, "ls-files", "--stage", "-z")
            source = "index"
            ref = None
        else:
            ref = git(root, "rev-parse", "--verify", f"{commit if mode == 'commit' else 'HEAD'}^{{commit}}").strip()
            output = git(root, "ls-tree", "-r", "-z", ref)
            source = f"commit:{ref}"

        files = set()
        symlinks = set()
        for record in split_z(output):
            metadata, separator, path = record.partition("\t")
            if not separator:
                continue
            mode_bits = metadata.split(" ", 1)[0]
            files.add(path)
            if mode_bits == "120000":
                symlinks.add(path)
        return cls(root, source, frozenset(files), frozenset(symlinks), ref)

    @property
    def directories(self) -> frozenset[str]:
        result = {"."}
        for filename in self.files:
            parent = Path(filename).parent
            while parent != Path("."):
                result.add(parent.as_posix())
                parent = parent.parent
        return frozenset(result)

    def is_file(self, path: Path) -> bool:
        relative = rel(self.root, path)
        return self._resolve_file(relative) is not None

    def is_dir(self, path: Path) -> bool:
        return rel(self.root, path) in self.directories

    def read_text(self, path: Path) -> str:
        relative = rel(self.root, path)
        resolved = self._resolve_file(relative)
        if resolved is None:
            raise OSError(f"{relative} is unavailable in {self.source}")
        if self.source == "working-tree":
            return path.read_text(encoding="utf-8", errors="replace")
        spec = f":{resolved}" if self.source == "index" else f"{self.ref}:{resolved}"
        return git_bytes(self.root, "show", spec).decode("utf-8", errors="replace")

    def _read_link(self, relative: str) -> str:
        spec = f":{relative}" if self.source == "index" else f"{self.ref}:{relative}"
        return git_bytes(self.root, "show", spec).decode("utf-8", errors="surrogateescape")

    def _resolve_file(self, relative: str, seen: frozenset[str] = frozenset()) -> str | None:
        """Resolve an in-repository symlink using only the selected evidence tree."""
        if relative not in self.files:
            return None
        if relative not in self.symlinks:
            return relative
        if self.source == "working-tree" or relative in seen:
            return None
        target = self._read_link(relative)
        if not target or target.startswith("/"):
            return None
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative), target))
        if resolved == ".." or resolved.startswith("../"):
            return None
        return self._resolve_file(resolved, seen | {relative})


def git_root(start: Path) -> Path:
    return Path(git(start, "rev-parse", "--show-toplevel").strip()).resolve()


def split_z(output: str) -> list[str]:
    return [item for item in output.split("\0") if item]


def default_base(root: Path) -> str | None:
    symbolic = git(
        root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD",
        allow_failure=True,
    ).strip()
    if symbolic:
        return symbolic
    for candidate in ("origin/main", "origin/master", "main", "master"):
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", candidate],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if result.returncode == 0:
            return candidate
    return None


def changed_files(
    root: Path, mode: str, base: str | None, commit: str,
) -> tuple[list[str], str | None]:
    diff_args = ("--name-only", "-z", "--no-renames", "--diff-filter=ACDMRTUXB")
    if mode == "staged":
        return sorted(split_z(git(root, "diff", "--cached", *diff_args))), base
    if mode == "local":
        paths = set(split_z(git(root, "diff", "--cached", *diff_args)))
        paths.update(split_z(git(root, "diff", *diff_args)))
        paths.update(split_z(git(root, "ls-files", "--others", "--exclude-standard", "-z")))
        return sorted(paths), base
    if mode == "commit":
        commit_id = git(root, "rev-parse", "--verify", f"{commit}^{{commit}}").strip()
        header = git(root, "cat-file", "-p", commit_id).split("\n\n", 1)[0]
        parents = [line.split(" ", 1)[1] for line in header.splitlines() if line.startswith("parent ")]
        if not parents:
            output = git(
                root, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z",
                commit_id,
            )
        else:
            parent = parents[0]
            available = subprocess.run(
                ["git", "-C", str(root), "cat-file", "-e", f"{parent}^{{commit}}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            if available.returncode:
                raise RuntimeError(
                    f"Parent of {commit_id} is unavailable; fetch enough history before commit discovery"
                )
            output = git(root, "diff", *diff_args, parent, commit_id)
        return sorted(split_z(output)), base
    if mode == "branch":
        selected_base = base or default_base(root)
        if not selected_base:
            raise RuntimeError("Unable to determine branch base; pass --base explicitly")
        return sorted(split_z(git(root, "diff", *diff_args, f"{selected_base}...HEAD"))), selected_base
    raise ValueError(f"Unsupported mode: {mode}")


def worktree_divergence(root: Path, mode: str, ref: str | None) -> list[str]:
    """Return disk paths that differ from the frozen evidence tree."""
    if mode == "local":
        return []
    diff_args = ("--name-only", "-z", "--no-renames", "--diff-filter=ACDMRTUXB")
    if mode == "staged":
        paths = set(split_z(git(root, "diff", *diff_args)))
    else:
        if not ref:
            raise RuntimeError(f"Missing evidence ref for {mode} mode")
        paths = set(split_z(git(root, "diff", *diff_args, ref)))
    paths.update(split_z(git(root, "ls-files", "--others", "--exclude-standard", "-z")))
    return sorted(paths)


def walk_files(view: RepoView, names: set[str]) -> Iterable[Path]:
    for filename in sorted(view.files):
        path = Path(filename)
        if path.name in names and view.is_file(view.root / path):
            yield view.root / path


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def path_applies(unit: Path, changed: list[str], root: Path) -> bool:
    if not changed:
        return False
    if unit == root:
        return True
    unit_path = rel(root, unit).rstrip("/")
    return any(item == unit_path or item.startswith(f"{unit_path}/") for item in changed)


def instruction_files(view: RepoView, changed: list[str]) -> list[str]:
    root = view.root
    directories = {root}
    for item in changed:
        candidate = (root / item).parent
        while candidate == root or root in candidate.parents:
            directories.add(candidate)
            if candidate == root:
                break
            candidate = candidate.parent
    found: list[Path] = []
    for directory in sorted(directories, key=lambda item: (len(item.parts), str(item))):
        agents, claude = directory / "AGENTS.md", directory / "CLAUDE.md"
        if view.is_file(agents):
            found.append(agents)
        elif view.is_file(claude):
            found.append(claude)
    return [rel(root, item) for item in dict.fromkeys(found)]


def package_manager(directory: Path, view: RepoView) -> str:
    root = view.root
    current = directory
    while current == root or root in current.parents:
        for lock, manager in (
            ("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
            ("bun.lock", "bun"), ("bun.lockb", "bun"),
            ("package-lock.json", "npm"),
        ):
            if view.is_file(current / lock):
                return manager
        if current == root:
            break
        current = current.parent
    return "npm"


def command_for(manager: str, script: str) -> str:
    if manager == "yarn":
        return f"yarn run {script}"
    if manager == "bun":
        return f"bun run {script}"
    return f"{manager} run {script}"


def expanded_script_commands(scripts: dict[str, Any], name: str) -> list[str]:
    """Expand lifecycle hooks and local package-script indirection for safety checks."""
    expanded: list[str] = []
    seen: set[str] = set()
    run_re = re.compile(r"\b(?:npm|pnpm|yarn|bun)\s+run\s+([\w:.-]+)")

    def visit(script: str) -> None:
        if script in seen:
            return
        seen.add(script)
        for candidate in (f"pre{script}", script, f"post{script}"):
            command = scripts.get(candidate)
            if not isinstance(command, str):
                continue
            expanded.append(command)
            for match in run_re.finditer(command):
                referenced = match.group(1)
                if referenced in scripts:
                    visit(referenced)

    visit(name)
    return expanded


def classify_command(
    name: str, command: str, lifecycle: Iterable[str] = (),
) -> tuple[str, str]:
    command_bundle = (command, *lifecycle)
    combined = " && ".join(command_bundle)
    if any(PLACEHOLDER_RE.match(item) for item in command_bundle):
        return "unavailable", "placeholder or explicitly missing command"
    if re.search(r"\b(?:npm|pnpm|yarn|bun)\s+run\s+[\w:.-]+\b[^\n]*--if-present\b", combined):
        return "contextual", "optional package script can succeed without running validation"
    if re.search(r"(?:`|\$\(|<\(|>\(|(?<!&)&(?!&)|\|\||;|\n|(?<!\|)\|(?!\|)|>>?|<(?!=))", combined):
        return "contextual", "shell control, substitution, or redirection requires manual inspection"
    pieces = [piece.strip() for item in command_bundle for piece in item.split("&&") if piece.strip()]
    package_run_re = re.compile(
        r"^(?:(?:[A-Za-z_][A-Za-z0-9_]*=[^\s]+|env|cross-env)\s+)*"
        r"(?:npm|pnpm|yarn|bun)\s+run\s+[\w:.-]+(?P<arguments>\s+.+)?$",
        re.I,
    )
    if any(
        (match := package_run_re.match(piece)) and match.group("arguments")
        for piece in pieces
    ):
        return "contextual", "package-script arguments require inspection after forwarding"
    mutation_subject = re.sub(
        r"\bwrangler\s+deploy\b[^\n;&|]*--dry-run(?:\s|$)",
        "wrangler dry-run validation ", combined, flags=re.I,
    )
    if MUTATION_RE.search(mutation_subject):
        return "mutation", "command or lifecycle performs an external or repository mutation"
    if CONTEXT_RE.search(name) or CONTEXT_RE.search(combined):
        return "contextual", "command appears to use authentication, live services, or production-like data"
    if not pieces or not all(SAFE_VALIDATOR_SEGMENT_RE.match(piece) for piece in pieces):
        return "contextual", "command is not a recognised local validator; inspect it before use"
    if EXPENSIVE_RE.search(name) or EXPENSIVE_RE.search(combined):
        return "safe_expensive", "local validation with material runtime or service setup cost"
    return "safe", "ordinary local verification"


def add_command(
    commands: list[dict[str, Any]], *, category: str, cwd: str,
    command: str, source: str, name: str | None = None,
    lifecycle: Iterable[str] = (),
) -> None:
    safety, reason = classify_command(name or category, command, lifecycle)
    item = {
        "category": category, "cwd": cwd or ".", "command": command,
        "source": source, "safety": safety, "reason": reason,
        "selected": safety == "safe",
    }
    if item not in commands:
        commands.append(item)


def javascript_units(
    view: RepoView, changed: list[str], commands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    root = view.root
    units: list[dict[str, Any]] = []
    manifests = [
        path for path in walk_files(view, {"package.json"})
        if path_applies(path.parent, changed, root)
    ]
    for manifest in manifests:
        try:
            data = json.loads(view.read_text(manifest))
        except (OSError, json.JSONDecodeError) as error:
            units.append({"path": rel(root, manifest), "ecosystem": "javascript", "error": str(error)})
            continue
        if not isinstance(data, dict):
            units.append({
                "path": rel(root, manifest), "ecosystem": "javascript",
                "error": "package.json must contain a JSON object",
            })
            continue
        raw_scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        scripts = {
            key: value for key, value in raw_scripts.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        manager = package_manager(manifest.parent, view)
        cwd = rel(root, manifest.parent) if manifest.parent != root else "."
        unit = {
            "path": rel(root, manifest), "ecosystem": "javascript",
            "package_manager": manager, "script_names": sorted(scripts),
        }
        if len(scripts) != len(raw_scripts):
            unit["warning"] = "ignored non-string package script entries"
        units.append(unit)
        preferred = {
            "lint": ("lint",),
            "typecheck": ("typecheck", "type-check", "check:types"),
            "test": ("test:unit", "test"),
            "build": ("build",),
        }
        for category, names in preferred.items():
            for script in names:
                if script not in scripts:
                    continue
                lifecycle = expanded_script_commands(scripts, script)
                add_command(
                    commands, category=category, cwd=cwd,
                    command=command_for(manager, script),
                    source=f"{rel(root, manifest)}#scripts.{script}",
                    name=script, lifecycle=lifecycle,
                )
    return units


def python_units(
    view: RepoView, changed: list[str], commands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    root = view.root
    units: list[dict[str, Any]] = []
    candidates = set(walk_files(view, {"pyproject.toml", "requirements.txt", "requirements-dev.txt"}))
    directories = sorted({path.parent for path in candidates if path_applies(path.parent, changed, root)})
    for directory in directories:
        files = sorted(path.name for path in candidates if path.parent == directory)
        cwd = rel(root, directory) if directory != root else "."
        text = "\n".join(
            view.read_text(directory / name) for name in files
        )
        has_tests = view.is_dir(directory / "tests")
        units.append({"path": cwd, "ecosystem": "python", "manifests": files})
        if "ruff" in text.lower():
            add_command(commands, category="lint", cwd=cwd, command="python3 -m ruff check .", source=",".join(files))
        if has_tests and "pytest" in text.lower():
            add_command(commands, category="test", cwd=cwd, command="python3 -m pytest -q", source=",".join(files))
        elif has_tests:
            add_command(
                commands, category="test", cwd=cwd,
                command="PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m unittest discover -s tests",
                source="tests/",
            )
    return units


def other_units(
    view: RepoView, changed: list[str], commands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    root = view.root
    units: list[dict[str, Any]] = []
    for manifest in walk_files(view, {"go.mod", "Cargo.toml", "Package.swift", "manifest.json"}):
        if not path_applies(manifest.parent, changed, root):
            continue
        cwd = rel(root, manifest.parent) if manifest.parent != root else "."
        source = rel(root, manifest)
        if manifest.name == "go.mod":
            units.append({"path": source, "ecosystem": "go"})
            add_command(commands, category="test", cwd=cwd, command="go test ./...", source=source)
            add_command(commands, category="build", cwd=cwd, command="go build ./...", source=source)
        elif manifest.name == "Cargo.toml":
            units.append({"path": source, "ecosystem": "rust"})
            add_command(commands, category="test", cwd=cwd, command="cargo test", source=source)
            add_command(commands, category="lint", cwd=cwd, command="cargo clippy --all-targets --all-features -- -D warnings", source=source)
        elif manifest.name == "Package.swift":
            units.append({"path": source, "ecosystem": "swift"})
            add_command(commands, category="test", cwd=cwd, command="swift test", source=source)
        else:
            try:
                manifest_data = json.loads(view.read_text(manifest))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(manifest_data, dict):
                continue
            if "location" not in manifest_data and "frameworkVersion" not in manifest_data:
                continue
            units.append({"path": source, "ecosystem": "zendesk"})
            add_command(commands, category="validate", cwd=cwd, command="zcli apps:validate", source=source, name="auth validate")
    return units


def capability(
    view: RepoView, changed: list[str], kind: str, evidence: Path, **extra: Any,
) -> dict[str, Any]:
    root = view.root
    evidence_rel = rel(root, evidence)
    scope = evidence if view.is_dir(evidence) else evidence.parent
    affected = path_applies(scope, changed, root) or evidence_rel in changed
    return {"kind": kind, "evidence": evidence_rel, "affected": affected, **extra}


def capabilities(
    view: RepoView, changed: list[str], commands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    root = view.root
    result: list[dict[str, Any]] = []
    names = {
        "netlify.toml": "netlify", "vercel.json": "vercel",
        "railway.json": "railway", "railway.toml": "railway", "fly.toml": "fly",
        "wrangler.toml": "cloudflare-workers", "wrangler.json": "cloudflare-workers",
        "wrangler.jsonc": "cloudflare-workers", "wmill.yaml": "windmill",
        "Dockerfile": "docker", "docker-compose.yml": "docker-compose",
        "compose.yml": "docker-compose", "playwright.config.ts": "playwright",
        "playwright.config.js": "playwright", "vitest.config.ts": "vitest",
        "jest.config.js": "jest", "drizzle.config.ts": "drizzle",
    }
    for path in walk_files(view, set(names)):
        kind = names[path.name]
        extra: dict[str, Any] = {}
        if kind == "windmill":
            wrapper = path.parent / "sync.sh"
            extra = {
                "canonical_wrapper": rel(root, wrapper) if view.is_file(wrapper) else None,
                "post_merge_command": f"./{rel(root, wrapper)} push" if view.is_file(wrapper) else None,
                "mutation": True,
            }
        item = capability(view, changed, kind, path, **extra)
        result.append(item)
        cwd = rel(root, path.parent) if path.parent != root else "."
        if kind == "cloudflare-workers" and item["affected"]:
            add_command(
                commands, category="infra-validate", cwd=cwd,
                command="./node_modules/.bin/wrangler deploy --dry-run", source=rel(root, path),
            )
        if kind == "docker" and item["affected"]:
            add_command(commands, category="container-build", cwd=cwd, command="docker build .", source=rel(root, path))
    database_dirs: set[tuple[Path, str]] = set()
    for config in walk_files(view, {"config.toml"}):
        if config.parent.name == "supabase":
            database_dirs.add((config.parent, "supabase"))
    for schema in walk_files(view, {"schema.prisma"}):
        database_dirs.add((schema.parent, "prisma"))
    for relative in view.directories:
        directory = root / relative
        if directory.name == "supabase" and view.is_dir(directory / "migrations"):
            database_dirs.add((directory, "supabase"))
    for directory, kind in sorted(database_dirs, key=lambda item: (str(item[0]), item[1])):
        item = capability(view, changed, kind, directory)
        result.append(item)
        if not item["affected"]:
            continue
        cwd = rel(root, directory.parent) if directory.parent != root else "."
        if kind == "prisma":
            add_command(
                commands, category="schema-validate", cwd=cwd,
                command="./node_modules/.bin/prisma validate", source=rel(root, directory),
            )
        elif view.is_file(directory / "config.toml"):
            add_command(
                commands, category="schema-validate", cwd=cwd,
                command="./node_modules/.bin/supabase db lint --level error", source=rel(root, directory),
            )
    return sorted(result, key=lambda item: (item["kind"], item["evidence"]))


def workflows(view: RepoView) -> list[dict[str, Any]]:
    root = view.root
    directory = root / ".github" / "workflows"
    if not view.is_dir(directory):
        return []
    result: list[dict[str, Any]] = []
    paths = [
        root / filename for filename in view.files
        if Path(filename).parent.as_posix() == ".github/workflows"
        and Path(filename).suffix in {".yml", ".yaml"}
        and filename not in view.symlinks
    ]
    for path in sorted(paths):
        lower = view.read_text(path).lower()
        semantic_lines = [line for line in lower.splitlines() if not line.lstrip().startswith("#")]
        semantic = "\n".join(semantic_lines)
        name_match = re.search(r"^name:\s*(.+)$", semantic, re.M)
        identity = f"{path.stem} {name_match.group(1) if name_match else ''}"
        if (
            "pull_request" in semantic
            and "review" in identity
            and re.search(r"(?:gemini|claude|openai|codex|coderabbit)", semantic)
        ):
            category = "ai_review"
        elif re.search(r"^\s*(?:schedule|cron):", semantic, re.M):
            category = "hosted_schedule"
        elif (
            re.search(
                r"^\s{2,8}[\w.-]*(?:deploy|publish|release|backup|watchdog|scrap|indexnow)[\w.-]*:\s*$",
                semantic, re.M,
            )
            or re.search(
                r"(?:netlify\s+deploy|wrangler\s+deploy|railway\s+up|fly(?:ctl)?\s+deploy|"
                r"npm\s+publish|gh\s+release\s+create|actions/deploy-pages|"
                r"cloudflare/pages-action|supabase\s+db\s+push|wmill\s+sync)",
                semantic,
            )
        ):
            category = "hosted_delivery"
        elif "pull_request" in semantic:
            category = "pr_validation"
        else:
            category = "other"
        result.append({"path": rel(root, path), "category": category})
    return result


def discover(
    start: Path, mode: str, base: str | None = None, commit: str = "HEAD",
) -> dict[str, Any]:
    root = git_root(start)
    effective_mode = mode
    if mode == "auto":
        staged, _ = changed_files(root, "staged", base, commit)
        if staged:
            effective_mode = "staged"
        else:
            local, _ = changed_files(root, "local", base, commit)
            effective_mode = "local" if local else "branch"
    changed, selected_base = changed_files(root, effective_mode, base, commit)
    view = RepoView.create(root, effective_mode, commit)
    commands: list[dict[str, Any]] = []
    units = javascript_units(view, changed, commands)
    units.extend(python_units(view, changed, commands))
    units.extend(other_units(view, changed, commands))
    caps = capabilities(view, changed, commands)
    divergence = worktree_divergence(root, effective_mode, view.ref)
    if divergence:
        for command_item in commands:
            command_item["selected"] = False
            command_item["execution_note"] = (
                "working tree differs from frozen evidence; isolate the target or inspect divergence before execution"
            )
    head = git(root, "rev-parse", "HEAD", allow_failure=True).strip() or None
    index_fingerprint = None
    if effective_mode == "staged":
        index_state = git_bytes(root, "ls-files", "--stage", "-z")
        index_fingerprint = hashlib.sha256(index_state).hexdigest()
    return {
        "schema_version": 3, "root": str(root), "mode": effective_mode,
        "requested_mode": mode, "evidence_source": view.source,
        "base": selected_base, "commit": view.ref if effective_mode == "commit" else None,
        "head": head, "index_fingerprint": index_fingerprint, "changed_files": changed,
        "worktree_divergence": divergence,
        "instructions": instruction_files(view, changed),
        "units": sorted(units, key=lambda item: (item["ecosystem"], item["path"])),
        "verification_commands": sorted(
            commands, key=lambda item: (item["cwd"], item["category"], item["command"]),
        ),
        "capabilities": caps, "workflows": workflows(view),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Path inside the Git repository")
    parser.add_argument("--mode", choices=("auto", "staged", "local", "branch", "commit"), default="auto")
    parser.add_argument("--base", help="Explicit branch/PR base ref")
    parser.add_argument("--commit", default="HEAD", help="Commit to inspect in commit mode")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    try:
        profile = discover(Path(args.root), args.mode, args.base, args.commit)
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps(profile, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
