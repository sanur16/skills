#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discover_repo import classify_command, discover


class RepositoryDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Test"], check=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self) -> None:
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, text=True,
            stdout=subprocess.PIPE,
        ).stdout

    def stage(self, path: str, content: str) -> dict:
        self.write(path, content)
        subprocess.run(["git", "-C", str(self.root), "add", path], check=True)
        return discover(self.root, "staged")

    def test_mutating_lifecycle_makes_build_unsafe(self) -> None:
        self.write("package-lock.json", "{}")
        self.write("package.json", json.dumps({
            "scripts": {"prebuild": "npm audit fix", "build": "next build", "lint": "eslint ."},
        }))
        self.write("app.js", "export const value = 1;\n")
        self.commit()
        profile = self.stage("app.js", "export const value = 2;\n")
        by_category = {item["category"]: item for item in profile["verification_commands"]}
        self.assertEqual(by_category["build"]["safety"], "mutation")
        self.assertEqual(by_category["lint"]["safety"], "safe")

    def test_nested_package_is_discovered_from_changed_path(self) -> None:
        self.write("package-lock.json", "{}")
        self.write("package.json", json.dumps({"scripts": {"lint": "eslint ."}}))
        self.write("apps/api/package.json", json.dumps({"scripts": {"test": "vitest run"}}))
        self.write("apps/api/src/index.ts", "export const value = 1;\n")
        self.commit()
        profile = self.stage("apps/api/src/index.ts", "export const value = 2;\n")
        paths = {unit["path"] for unit in profile["units"]}
        self.assertIn("package.json", paths)
        self.assertIn("apps/api/package.json", paths)

    def test_windmill_requires_affected_files_and_finds_wrapper(self) -> None:
        self.write("windmill/wmill.yaml", "defaultTs: bun\n")
        self.write("windmill/sync.sh", "#!/bin/sh\n")
        self.write("windmill/f/job.ts", "export {};\n")
        self.commit()
        profile = self.stage("windmill/f/job.ts", "export const changed = true;\n")
        windmill = next(item for item in profile["capabilities"] if item["kind"] == "windmill")
        self.assertTrue(windmill["affected"])
        self.assertEqual(windmill["canonical_wrapper"], "windmill/sync.sh")
        self.assertTrue(windmill["mutation"])

    def test_python_unittest_fallback(self) -> None:
        self.write("requirements.txt", "requests==2\n")
        self.write("tests/test_app.py", "import unittest\n")
        self.write("app.py", "VALUE = 1\n")
        self.commit()
        profile = self.stage("app.py", "VALUE = 2\n")
        commands = [item["command"] for item in profile["verification_commands"]]
        self.assertIn(
            "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m unittest discover -s tests",
            commands,
        )

    def test_placeholder_test_is_not_selected(self) -> None:
        self.write("package.json", json.dumps({
            "scripts": {"test": 'echo "Error: no test specified" && exit 1'},
        }))
        self.write("index.js", "module.exports = 1;\n")
        self.commit()
        profile = self.stage("index.js", "module.exports = 2;\n")
        test = next(item for item in profile["verification_commands"] if item["category"] == "test")
        self.assertEqual(test["safety"], "unavailable")
        self.assertFalse(test["selected"])

    def test_optional_missing_nested_script_is_not_selected(self) -> None:
        self.write("package-lock.json", "{}")
        self.write("package.json", json.dumps({"scripts": {
            "test": "npm run absent --if-present",
        }}))
        self.write("index.js", "module.exports = 1;\n")
        self.commit()
        profile = self.stage("index.js", "module.exports = 2;\n")
        test = next(item for item in profile["verification_commands"] if item["category"] == "test")
        self.assertEqual(test["safety"], "contextual")
        self.assertFalse(test["selected"])

    def test_forwarded_nested_script_mutation_flag_is_not_selected(self) -> None:
        self.write("package-lock.json", "{}")
        self.write("package.json", json.dumps({"scripts": {
            "test": "npm run unit -- --updateSnapshot",
            "unit": "jest",
        }}))
        self.write("index.js", "module.exports = 1;\n")
        self.commit()
        profile = self.stage("index.js", "module.exports = 2;\n")
        test = next(item for item in profile["verification_commands"] if item["category"] == "test")
        self.assertEqual(test["safety"], "contextual")
        self.assertFalse(test["selected"])

    def test_nested_agents_precedes_nested_claude(self) -> None:
        self.write("AGENTS.md", "root\n")
        self.write("apps/AGENTS.md", "nested\n")
        self.write("apps/CLAUDE.md", "fallback\n")
        self.write("apps/app.js", "module.exports = 1;\n")
        self.commit()
        profile = self.stage("apps/app.js", "module.exports = 2;\n")
        self.assertEqual(profile["instructions"], ["AGENTS.md", "apps/AGENTS.md"])

    def test_staged_internal_instruction_symlink_uses_index_target(self) -> None:
        self.write("docs/AGENTS.md", "frozen rules\n")
        self.write("app.js", "module.exports = 1;\n")
        os.symlink("docs/AGENTS.md", self.root / "AGENTS.md")
        self.commit()
        profile = self.stage("app.js", "module.exports = 2;\n")
        self.assertEqual(profile["instructions"], ["AGENTS.md"])
        self.assertEqual(profile["evidence_source"], "index")

    def test_chrome_manifest_is_not_treated_as_zendesk(self) -> None:
        self.write("extension/manifest.json", json.dumps({"manifest_version": 3, "name": "Extension"}))
        self.write("extension/app.js", "const value = 1;\n")
        self.commit()
        profile = self.stage("extension/app.js", "const value = 2;\n")
        self.assertFalse(any(unit["ecosystem"] == "zendesk" for unit in profile["units"]))

    def test_only_project_supabase_directory_is_detected(self) -> None:
        self.write("supabase/config.toml", "project_id = 'fixture'\n")
        self.write("lib/supabase/client.ts", "export {};\n")
        self.write("app.ts", "export const value = 1;\n")
        self.commit()
        profile = self.stage("app.ts", "export const value = 2;\n")
        evidence = [item["evidence"] for item in profile["capabilities"] if item["kind"] == "supabase"]
        self.assertEqual(evidence, ["supabase"])

    def test_deletions_are_included_in_every_diff_mode(self) -> None:
        self.write("nested/deleted.js", "export const value = 1;\n")
        self.commit()
        (self.root / "nested/deleted.js").unlink()
        self.assertEqual(discover(self.root, "local")["changed_files"], ["nested/deleted.js"])
        self.git("add", "-u")
        self.assertEqual(discover(self.root, "staged")["changed_files"], ["nested/deleted.js"])
        self.git("switch", "-c", "feature")
        self.git("commit", "-qm", "delete")
        self.assertEqual(
            discover(self.root, "branch", base="main")["changed_files"],
            ["nested/deleted.js"],
        )

    def test_staged_discovery_does_not_write_git_objects(self) -> None:
        self.write("package.json", json.dumps({"scripts": {"test": "node --test"}}))
        self.write("index.js", "export const value = 1;\n")
        self.commit()
        self.stage("index.js", "export const value = 2;\n")
        before = self.git("count-objects", "-v")
        status_before = self.git("status", "--porcelain=v1")
        profile = discover(self.root, "staged")
        self.assertEqual(self.git("count-objects", "-v"), before)
        self.assertEqual(self.git("status", "--porcelain=v1"), status_before)
        self.assertRegex(profile["index_fingerprint"], r"^[0-9a-f]{64}$")

    def test_commit_mode_uses_first_parent_for_merge(self) -> None:
        self.write("base", "base\n")
        self.commit()
        self.git("switch", "-c", "feature")
        self.write("feature", "feature\n")
        self.commit()
        self.git("switch", "main")
        self.write("main-only", "main\n")
        self.commit()
        self.git("merge", "--no-ff", "feature", "-m", "merge")
        self.assertEqual(discover(self.root, "commit")["changed_files"], ["feature"])

    def test_commit_mode_fails_when_shallow_parent_is_unavailable(self) -> None:
        self.write("first", "one\n")
        self.commit()
        self.write("second", "two\n")
        self.commit()
        with tempfile.TemporaryDirectory() as shallow_dir:
            shallow = Path(shallow_dir) / "clone"
            subprocess.run(
                ["git", "clone", "-q", "--depth", "1", f"file://{self.root}", str(shallow)],
                check=True,
            )
            with self.assertRaisesRegex(RuntimeError, "fetch enough history"):
                discover(shallow, "commit")

    def test_dangerous_or_unknown_commands_are_never_safe(self) -> None:
        commands = [
            "git clean -fdx && npm test",
            "git reset --hard HEAD && npm test",
            "npm install && npm test",
            "terraform apply -auto-approve",
            "kubectl apply -f deployment.yml",
            "gh pr merge 42 --squash",
            "curl --data @payload.json https://example.test",
            "curl -F file=@payload.json https://example.test",
            "aws s3 rm s3://bucket --recursive",
            "eslint . & rm -rf build",
            "docker compose down -v",
            "eslint . --fix",
            "docker buildx build --push .",
            "docker compose build --push",
            "ruff format .",
            "vitest run --update",
            "jest -u",
            "playwright test --update-snapshots",
            "npx prisma validate",
            "eslint . --output-file package.json",
            "vitest run --update=true",
            "jest --updateSnapshot=true",
            "jest --json --outputFile=package.json",
            "jest --json --outputFile package.json",
            "docker compose push",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertNotIn(classify_command("test", command)[0], {"safe", "safe_expensive"})

    def test_todo_filename_is_not_a_placeholder(self) -> None:
        self.assertEqual(classify_command("test", "vitest run todo.spec.ts")[0], "safe")
        self.assertEqual(classify_command("test", "pytest tests/test_todo.py")[0], "safe")

    def test_generated_node_tool_checks_require_local_binaries(self) -> None:
        self.write("prisma/schema.prisma", "generator client { provider = \"prisma-client-js\" }\n")
        self.commit()
        profile = self.stage(
            "prisma/schema.prisma",
            "generator client { provider = \"prisma-client-js\" }\nmodel User { id Int @id }\n",
        )
        command = next(item for item in profile["verification_commands"] if item["category"] == "schema-validate")
        self.assertEqual(command["command"], "./node_modules/.bin/prisma validate")
        self.assertEqual(command["safety"], "safe")

    def test_nested_package_script_inherits_contextual_zcli_command(self) -> None:
        self.write("package-lock.json", "{}")
        self.write("package.json", json.dumps({"scripts": {
            "build": "npm run validate && npm run package",
            "validate": "zcli apps:validate",
            "package": "zcli apps:package",
        }}))
        self.write("src/app.js", "export const value = 1;\n")
        self.commit()
        profile = self.stage("src/app.js", "export const value = 2;\n")
        build = next(item for item in profile["verification_commands"] if item["category"] == "build")
        self.assertEqual(build["safety"], "contextual")
        self.assertFalse(build["selected"])

    def test_yarn_run_expands_nested_scripts_and_rejects_builtins(self) -> None:
        self.write("yarn.lock", "")
        self.write("package.json", json.dumps({"scripts": {
            "test": "yarn run cleanup",
            "cleanup": "rm -rf /tmp/review-fixture",
        }}))
        self.write("app.js", "export const value = 1;\n")
        self.commit()
        profile = self.stage("app.js", "export const value = 2;\n")
        test = next(item for item in profile["verification_commands"] if item["category"] == "test")
        self.assertEqual(test["command"], "yarn run test")
        self.assertEqual(test["safety"], "contextual")
        self.assertFalse(test["selected"])
        self.assertEqual(classify_command("test", "yarn config set enableTelemetry 1")[0], "contextual")

    def test_failure_masking_shell_operators_are_contextual(self) -> None:
        for command in ("vitest run || true", "vitest run ; true", "vitest run | true"):
            with self.subTest(command=command):
                self.assertEqual(classify_command("test", command)[0], "contextual")

    def test_empty_change_set_has_no_affected_capabilities_or_commands(self) -> None:
        self.write("netlify.toml", "[build]\ncommand = 'npm run build'\n")
        self.write("supabase/config.toml", "project_id = 'fixture'\n")
        self.write("package.json", json.dumps({"scripts": {"test": "node --test"}}))
        self.commit()
        profile = discover(self.root, "local")
        self.assertFalse(any(item["affected"] for item in profile["capabilities"]))
        self.assertEqual(profile["verification_commands"], [])

    def test_database_directory_is_not_affected_by_unrelated_root_change(self) -> None:
        self.write("supabase/config.toml", "project_id = 'fixture'\n")
        self.write("app.js", "export const value = 1;\n")
        self.commit()
        profile = self.stage("app.js", "export const value = 2;\n")
        supabase = next(item for item in profile["capabilities"] if item["kind"] == "supabase")
        self.assertFalse(supabase["affected"])
        self.assertFalse(any(item["category"] == "schema-validate" for item in profile["verification_commands"]))

    def test_staged_evidence_ignores_unstaged_manifest_edits(self) -> None:
        self.write("package.json", json.dumps({"scripts": {"test": "node --test"}}))
        self.write("app.js", "export const value = 1;\n")
        self.commit()
        self.stage("app.js", "export const value = 2;\n")
        self.write("package.json", json.dumps({"scripts": {"test": "rm -rf /tmp/example"}}))
        profile = discover(self.root, "staged")
        test = next(item for item in profile["verification_commands"] if item["category"] == "test")
        self.assertEqual(profile["evidence_source"], "index")
        self.assertEqual(test["safety"], "safe")
        self.assertFalse(test["selected"])
        self.assertEqual(profile["worktree_divergence"], ["package.json"])

    def test_commit_evidence_ignores_working_tree_manifest_edits(self) -> None:
        self.write("package.json", json.dumps({"scripts": {"test": "node --test"}}))
        self.write("app.js", "export const value = 1;\n")
        self.commit()
        self.write("app.js", "export const value = 2;\n")
        self.commit()
        self.write("package.json", json.dumps({"scripts": {"test": "rm -rf /tmp/example"}}))
        profile = discover(self.root, "commit")
        test = next(item for item in profile["verification_commands"] if item["category"] == "test")
        self.assertTrue(profile["evidence_source"].startswith("commit:"))
        self.assertEqual(test["safety"], "safe")
        self.assertFalse(test["selected"])
        self.assertEqual(profile["worktree_divergence"], ["package.json"])

    def test_rename_includes_source_and_destination_scopes(self) -> None:
        self.write("AGENTS.md", "root\n")
        self.write("old/AGENTS.md", "old\n")
        self.write("old/file.js", "export const value = 1;\n")
        self.commit()
        (self.root / "new").mkdir()
        self.git("mv", "old/file.js", "new/file.js")
        profile = discover(self.root, "staged")
        self.assertEqual(profile["changed_files"], ["new/file.js", "old/file.js"])
        self.assertIn("old/AGENTS.md", profile["instructions"])

    def test_adversarial_manifests_do_not_crash_or_escape_root(self) -> None:
        self.write("package.json", "[]")
        self.write("app.js", "export const value = 1;\n")
        self.commit()
        profile = self.stage("app.js", "export const value = 2;\n")
        self.assertIn("must contain a JSON object", profile["units"][0]["error"])

        self.git("reset", "--hard", "HEAD")
        (self.root / "package.json").unlink()
        with tempfile.TemporaryDirectory() as external_dir:
            external = Path(external_dir) / "package.json"
            external.write_text(json.dumps({"scripts": {"test": "node --test"}}), encoding="utf-8")
            os.symlink(external, self.root / "package.json")
            self.git("add", "package.json")
            self.git("commit", "-qm", "external symlink")
            profile = self.stage("app.js", "export const value = 3;\n")
            self.assertFalse(any(unit["ecosystem"] == "javascript" for unit in profile["units"]))

    def test_non_string_package_script_is_ignored(self) -> None:
        self.write("package.json", json.dumps({"scripts": {"test": ["node", "--test"]}}))
        self.write("app.js", "export const value = 1;\n")
        self.commit()
        profile = self.stage("app.js", "export const value = 2;\n")
        self.assertEqual(profile["units"][0]["script_names"], [])
        self.assertIn("ignored", profile["units"][0]["warning"])

    def test_workflow_labels_and_flags_do_not_imply_delivery(self) -> None:
        self.write(".github/workflows/quote-database-tests.yml", """
name: Quote database tests
on: pull_request
jobs:
  tests:
    steps:
      - run: tool teardown --no-backup
""")
        self.write(".github/workflows/quality-report.yml", """
name: Quality report
on: pull_request
jobs:
  quality:
    steps:
      - name: Publish job summary
        run: echo report >> $GITHUB_STEP_SUMMARY
""")
        self.write(".github/workflows/convert-article.yml", """
name: Convert and merge reviewed article
on: workflow_dispatch
jobs:
  convert:
    steps:
      - uses: anthropics/claude-code-action@v1
""")
        self.write("app.js", "export const value = 1;\n")
        self.commit()
        profile = self.stage("app.js", "export const value = 2;\n")
        categories = {item["path"]: item["category"] for item in profile["workflows"]}
        self.assertEqual(categories[".github/workflows/quote-database-tests.yml"], "pr_validation")
        self.assertEqual(categories[".github/workflows/quality-report.yml"], "pr_validation")
        self.assertEqual(categories[".github/workflows/convert-article.yml"], "other")

    def test_supabase_migrations_are_detected_without_cli_config(self) -> None:
        self.write("supabase/migrations/001_initial_schema.sql", "select 1;\n")
        self.write("app.js", "export const value = 1;\n")
        self.commit()
        profile = self.stage(
            "supabase/migrations/001_initial_schema.sql",
            "select 2;\n",
        )
        supabase = next(item for item in profile["capabilities"] if item["kind"] == "supabase")
        self.assertTrue(supabase["affected"])
        self.assertFalse(any(item["category"] == "schema-validate" for item in profile["verification_commands"]))


if __name__ == "__main__":
    unittest.main()
