from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from datetime import timezone
import json
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from integrations.sandbox.models import RunTaskMetadata
from integrations.sandbox.models import RunTaskPaths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SandboxManager:
    """Manage task-scoped sandbox directories under Server/data/runs."""

    def __init__(self, *, repo_root: Path | None = None, runs_root: Path | None = None) -> None:
        server_root = Path(__file__).resolve().parents[3]
        self.repo_root = (repo_root or server_root).resolve()
        self.runs_root = (runs_root or self.repo_root / "data" / "runs").resolve()
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def create_run_task(
        self,
        *,
        title: str,
        objective: str,
        source_path: str | None = None,
        created_by: str = "workspace_worker",
    ) -> RunTaskMetadata:
        task_id = f"task_{uuid4().hex[:10]}"
        paths = self._paths_for(task_id)
        paths.workspace.mkdir(parents=True, exist_ok=False)
        paths.logs.mkdir(parents=True, exist_ok=False)
        paths.outputs.mkdir(parents=True, exist_ok=False)

        copied_source: str | None = None
        if source_path:
            source = self._resolve_repo_path(source_path)
            copied_target = paths.workspace / source.name
            if source.is_dir():
                shutil.copytree(source, copied_target)
            else:
                copied_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, copied_target)
            copied_source = str(source.relative_to(self.repo_root)).replace("\\", "/")

        now = _utc_now()
        metadata = RunTaskMetadata(
            task_id=task_id,
            title=title.strip() or task_id,
            objective=objective.strip() or title.strip() or task_id,
            status="created",
            created_by=created_by,
            created_at=now,
            updated_at=now,
            root_path=str(paths.task_root),
            workspace_path=str(paths.workspace),
            logs_path=str(paths.logs),
            outputs_path=str(paths.outputs),
            source_path=copied_source,
        )
        self._write_metadata(metadata)
        return metadata

    def load_metadata(self, task_id: str) -> RunTaskMetadata:
        paths = self._paths_for(task_id)
        if not paths.metadata_file.exists():
            raise FileNotFoundError(f"Sandbox task '{task_id}' does not exist.")
        payload = json.loads(paths.metadata_file.read_text(encoding="utf-8"))
        return RunTaskMetadata(**payload)

    def save_metadata(self, metadata: RunTaskMetadata) -> RunTaskMetadata:
        updated = replace(metadata, updated_at=_utc_now())
        self._write_metadata(updated)
        return updated

    def mark_running(self, task_id: str, *, command: str, exit_code: int | None) -> RunTaskMetadata:
        metadata = self.load_metadata(task_id)
        if metadata.status not in {"created", "running"}:
            raise ValueError(f"Sandbox task '{task_id}' is not active.")
        updated = replace(
            metadata,
            status="running",
            command_count=metadata.command_count + 1,
            last_command=command,
            last_exit_code=exit_code,
        )
        return self.save_metadata(updated)

    def finish_task(self, task_id: str, *, summary: str, status: str) -> RunTaskMetadata:
        normalized_status = status.strip().lower()
        if normalized_status not in {"finished", "failed", "expired"}:
            raise ValueError(f"Unsupported final task status '{status}'.")
        metadata = self.load_metadata(task_id)
        updated = replace(metadata, status=normalized_status, summary=summary.strip())
        return self.save_metadata(updated)

    def list_task_files(
        self,
        task_id: str,
        *,
        relative_path: str = ".",
        recursive: bool = False,
        limit: int = 200,
    ) -> list[str]:
        target = self._resolve_task_path(task_id, relative_path)
        iterator = sorted(target.rglob("*") if recursive else target.iterdir())
        entries: list[str] = []
        for child in iterator:
            entries.append(str(child.relative_to(self._paths_for(task_id).workspace)).replace("\\", "/"))
            if len(entries) >= max(limit, 1):
                break
        return entries

    def read_task_file(self, task_id: str, *, relative_path: str, max_chars: int = 12_000) -> str:
        target = self._resolve_task_path(task_id, relative_path)
        return target.read_text(encoding="utf-8")[: max(max_chars, 1)]

    def write_task_file(
        self,
        task_id: str,
        *,
        relative_path: str,
        content: str,
        overwrite: bool = True,
    ) -> Path:
        target = self._resolve_task_path(task_id, relative_path)
        if target.exists() and not overwrite:
            raise ValueError(f"Refusing to overwrite existing task file '{relative_path}'.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def list_repo(self, *, path: str = ".", recursive: bool = False, limit: int = 100) -> list[str]:
        target = self._resolve_repo_path(path)
        iterator = sorted(target.rglob("*") if recursive else target.iterdir())
        entries: list[str] = []
        for child in iterator:
            entries.append(str(child.relative_to(self.repo_root)).replace("\\", "/"))
            if len(entries) >= max(limit, 1):
                break
        return entries

    def read_repo_file(self, *, path: str, max_chars: int = 12_000) -> str:
        target = self._resolve_repo_path(path)
        return target.read_text(encoding="utf-8")[: max(max_chars, 1)]

    def search_repo(self, *, pattern: str, path: str = ".", limit: int = 30) -> str:
        search_root = self._resolve_repo_path(path)
        if not pattern.strip():
            raise ValueError("search_repo requires a non-empty pattern.")
        completed = subprocess.run(
            [
                "rg",
                "--line-number",
                "--no-heading",
                "--color",
                "never",
                "--max-count",
                str(max(limit, 1)),
                pattern,
                str(search_root),
            ],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stdout.strip() or completed.stderr.strip()

    def resolve_task_paths(self, task_id: str) -> RunTaskPaths:
        paths = self._paths_for(task_id)
        self.load_metadata(task_id)
        return paths

    def _resolve_repo_path(self, path_value: str) -> Path:
        candidate = (self.repo_root / (path_value or ".")).resolve()
        try:
            candidate.relative_to(self.repo_root)
        except ValueError as exc:
            raise ValueError(f"Path '{path_value}' escapes the repository root.") from exc
        if not candidate.exists():
            raise FileNotFoundError(candidate)
        return candidate

    def _resolve_task_path(self, task_id: str, relative_path: str) -> Path:
        workspace = self.resolve_task_paths(task_id).workspace
        candidate = (workspace / (relative_path or ".")).resolve()
        try:
            candidate.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"Path '{relative_path}' escapes the task workspace.") from exc
        return candidate

    def _paths_for(self, task_id: str) -> RunTaskPaths:
        task_root = self.runs_root / task_id
        return RunTaskPaths(
            task_root=task_root,
            workspace=task_root / "workspace",
            logs=task_root / "logs",
            outputs=task_root / "outputs",
            metadata_file=task_root / "metadata.json",
        )

    def _write_metadata(self, metadata: RunTaskMetadata) -> None:
        paths = self._paths_for(metadata.task_id)
        paths.task_root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(metadata.to_dict(), indent=2, ensure_ascii=True)
        paths.metadata_file.write_text(payload + "\n", encoding="utf-8")
