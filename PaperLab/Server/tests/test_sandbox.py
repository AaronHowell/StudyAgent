from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from integrations.sandbox.runner import SandboxRunner
from integrations.sandbox.task_manager import SandboxManager


class SandboxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.repo_root = Path(self.tempdir.name) / "repo"
        self.repo_root.mkdir(parents=True, exist_ok=True)
        (self.repo_root / "README.md").write_text("repo readme\n", encoding="utf-8")
        source_dir = self.repo_root / "example_project"
        source_dir.mkdir()
        (source_dir / "main.py").write_text("print('hello from repo')\n", encoding="utf-8")
        self.manager = SandboxManager(
            repo_root=self.repo_root,
            runs_root=self.repo_root / "data" / "runs",
        )
        self.runner = SandboxRunner(manager=self.manager)

    def test_create_run_task_builds_expected_layout(self) -> None:
        task = self.manager.create_run_task(
            title="Reproduce paper repo",
            objective="Create a local run workspace",
            source_path="example_project",
        )

        paths = self.manager.resolve_task_paths(task.task_id)
        self.assertTrue(paths.workspace.exists())
        self.assertTrue(paths.logs.exists())
        self.assertTrue(paths.outputs.exists())
        self.assertTrue(paths.metadata_file.exists())
        copied_file = paths.workspace / "example_project" / "main.py"
        self.assertTrue(copied_file.exists())

    def test_task_file_operations_stay_in_workspace(self) -> None:
        task = self.manager.create_run_task(title="Write task files", objective="Check workspace writes")

        written = self.manager.write_task_file(
            task.task_id,
            relative_path="notes/result.txt",
            content="sandboxed\n",
        )
        content = self.manager.read_task_file(task.task_id, relative_path="notes/result.txt")
        listing = self.manager.list_task_files(task.task_id, recursive=True)

        self.assertTrue(written.exists())
        self.assertEqual(content, "sandboxed\n")
        self.assertIn("notes/result.txt", listing)

        with self.assertRaises(ValueError):
            self.manager.write_task_file(task.task_id, relative_path="../escape.txt", content="nope")

    def test_run_task_command_allows_whitelisted_command(self) -> None:
        task = self.manager.create_run_task(title="Run python", objective="Execute one command")

        result = self.runner.run_task_command(
            task.task_id,
            command="python -c \"print('sandbox ok')\"",
            timeout_seconds=10,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("sandbox ok", result.stdout)
        self.assertTrue(Path(result.log_path).exists())

    def test_run_task_command_rejects_non_whitelisted_command(self) -> None:
        task = self.manager.create_run_task(title="Reject command", objective="Protect the sandbox")

        with self.assertRaises(ValueError):
            self.runner.run_task_command(task.task_id, command="powershell -Command Get-ChildItem")

    def test_finish_task_persists_status(self) -> None:
        task = self.manager.create_run_task(title="Finish", objective="Mark task done")

        updated = self.manager.finish_task(task.task_id, summary="done", status="finished")

        self.assertEqual(updated.status, "finished")
        reloaded = self.manager.load_metadata(task.task_id)
        self.assertEqual(reloaded.summary, "done")


if __name__ == "__main__":
    unittest.main()
